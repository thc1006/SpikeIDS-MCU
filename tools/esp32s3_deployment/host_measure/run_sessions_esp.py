"""Drive N autonomous EM01 power-on sessions on an ESP32-S3 N16R8 board.

Same session procedure, DONE rule, decoder and analysis as the FPB-RA4E1 driver
(tools/ra4e1_deployment/host_measure/run_sessions.py, imported here and not
modified): the platform is recognised from the EM01 telemetry magic. What
differs is the preflight:
  * the recorder runs in Source Meter mode at 5000 mV with --absent-guard
    including 'vid:303a,vid:1a86' (native USB-Serial/JTAG and CH343P): output ON
    is refused, and switched OFF, while either USB port of the board is connected;
  * no ESP32-S3 USB device (Espressif 303a, or a CH34x/CP210x/FTDI bridge) may
    be on the bus: the board is powered only from the PPK2 via its 5V pin;
  * the board holds a verified EM01 build (esp_ops.py flash record: rc 0, 3 regions
    'Hash of data verified', pinned hashes of the build and of the retained copies,
    MAC equal to --mac);
  * (ESP Amendment 2, review M2/M3) the recorder is fresh and has read the logic port
    unpowered (0xFF) in every bin: a board powered from its native USB cannot be seen by
    the USB guard (EM01 disables that port) but would power the logic port through 3V3;
    between sessions the latched logic byte must not change while the output is OFF;
    a dead recorder (stale status, failed command) ends the run as an instrument fault.
Never flashes, resets or changes the PPK2 mode/voltage.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / 'tools/ra4e1_deployment/host_measure'))
sys.path.insert(0, str(HERE))
import esp_ops  # noqa: E402
import run_sessions as rs  # noqa: E402

USB_VENDORS_FORBIDDEN = {'303a', '1a86', '10c4', '0403'}     # Espressif, WCH, Silicon Labs, FTDI
GUARD_TOKENS_REQUIRED = {'vid:303a', 'vid:1a86'}             # native USB-Serial/JTAG + CH343P
BUILD_MARKER_GPIO = {'build_02': 4, 'build_03': 5, 'build_04': 5}   # ESP Amendments 1-2
GUARD_MA = 300.0              # registered recorder guard (mean over 100 ms)
STATUS_STALE_S = 5.0          # the recorder rewrites status.json every 0.5 s
OFF_GAP_SKIP_S = 1.0          # rail decay right after OFF, excluded from the latch check
MASK_S = 1.5    # EM01 boot (ROM + 2nd-stage bootloader + app) precedes marker_init; RM01 settle keeps
                # the marker LOW for 2 s after it, so frames before ON + 1.5 s carry no marker (review minor)


def usb_vendors_present(root=Path('/sys/bus/usb/devices')):
    """Fail closed: unreadable sysfs counts as 'present'."""
    try:
        found = set()
        for d in root.iterdir():
            f = d / 'idVendor'
            if f.is_file():
                found.add(f.read_text().strip())
        return found & USB_VENDORS_FORBIDDEN
    except OSError:
        return {'sysfs-unreadable'}


def safe_command(rec, text, log):
    """A recorder that has exited leaves a FIFO without a reader (ENXIO); its own
    fail-safe has already switched the output OFF, so record and continue."""
    try:
        rec.command(text)
        return True
    except OSError as exc:
        log(dict(event='command_failed', command=text, error=f'{type(exc).__name__}: {exc}'))
        return False


def status_age_s(st):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(st['utc'])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return float('inf')


def logic_states(rec, a, b):
    """Distinct (bits_or, bits_and) states of the 10 ms bins with a <= sample_start < b."""
    rows = [r for r in rec.summary_rows(a) if int(r['sample_start']) < b]
    return sorted({(int(r['bits_or']), int(r['bits_and'])) for r in rows}), len(rows)


def wait_done_esp(rec, start_sample, t_on, timeout_s, log):
    """rs.wait_done (same DONE rule) plus instrument-fault detection (review M3)."""
    need = int(rs.DONE_HIGH_S * 100)
    last_print = 0
    while time.monotonic() - t_on < timeout_s:
        time.sleep(2.0)
        try:
            st = rec.status()
        except Exception as exc:
            return dict(done=False, instrument_fault=True, reason=f'recorder status unreadable: {exc}')
        if status_age_s(st) > STATUS_STALE_S:
            return dict(done=False, instrument_fault=True, reason=f"recorder status stale ({st.get('utc')})")
        if st['guard_tripped']:
            return dict(done=False, reason=f'current guard tripped: {st}')
        if not st['output_on']:
            usb = st.get('usb_guard_present_while_on')
            return dict(done=False, instrument_fault=not usb,
                        reason=('USB guard switched the output OFF' if usb else 'output OFF without a guard') + f': {st}')
        rows = rec.summary_rows(start_sample)
        run, rises = rs.done_state(rows)
        elapsed = len(rows) / 100.0
        if time.monotonic() - last_print > 30:
            log(dict(t=round(time.monotonic() - t_on, 1), captured_s=elapsed,
                     mean_mA_1s=(st['mean_uA_last_1s'] or 0) / 1000, d0_high_run_s=run / 100, d0_rises=rises))
            last_print = time.monotonic()
        if elapsed >= rs.DONE_MIN_ELAPSED_S and run >= need:
            if rises >= rs.DONE_MIN_RISES:
                return dict(done=True, captured_s=elapsed, done_high_s=run / 100, d0_rises=rises)
            return dict(done=False, reason=f'D0 HIGH {run / 100:.1f} s but only {rises} marker rises: stuck HIGH?')
    return dict(done=False, reason='timeout')


def preflight(rec, flash_record, build, mac):
    s = rec.session()
    running = [v for k, v in s['source_sha256'].items() if k.endswith('ppk2_session.py')]
    rs.require(running == [rs.sha(rs.PPK / 'ppk2_session.py')], 'recorder is not the current ppk2_session.py')
    rs.require(s.get('source_mv') == rs.SOURCE_MV and s['metadata'].get('mode') == '2'
               and s['metadata'].get('VDD') == str(rs.SOURCE_MV), 'recorder not in Source mode at 5000 mV')
    tokens = {t.strip().lower() for t in (s.get('absent_guard_serial') or '').split(',') if t.strip()}
    rs.require(GUARD_TOKENS_REQUIRED <= tokens,
               f"recorder --absent-guard must include {sorted(GUARD_TOKENS_REQUIRED)} (has {sorted(tokens)})")
    rs.require(abs(float(s.get('guard_mA', -1.0)) - GUARD_MA) < 1e-9,
               f"recorder guard {s.get('guard_mA')} mA, registered {GUARD_MA} mA")
    rs.require(build in BUILD_MARKER_GPIO, f'no registered marker GPIO for {build}')
    st = rec.status()
    rs.require(not st['output_on'] and not st['guard_tripped'], f'recorder output/guard state {st}')
    rs.require(status_age_s(st) < STATUS_STALE_S, f"recorder status stale ({st.get('utc')}): recorder not running")
    rs.require(st['recording'] is None, f"recorder already recording {st['recording']}")
    present = usb_vendors_present()
    rs.require(not present, f'ESP/USB-bridge device on the bus ({sorted(present)}): unplug the board USB first')
    txt = (flash_record / 'flash.console.txt').read_text()
    fj = json.loads((flash_record / 'flash.json').read_text())
    frec = json.loads((flash_record / 'flash_record.json').read_text())
    pins = esp_ops.BUILDS[build]
    d = esp_ops.FW / build / 'build'
    rs.require(fj['returncode'] == 0 and txt.count('Hash of data verified') == 3
               and str(d / 'em01.bin') in fj['argv'] and frec['build'] == build and frec['pins'] == pins
               and all(rs.sha(d / n) == h for n, h in pins.items())
               and all(rs.sha(flash_record / 'firmware' / Path(n).name) == h for n, h in pins.items()),
               f'no verified {build} flash record')
    rs.require((frec.get('mac') or '').lower() == mac.lower(), f"flash record MAC {frec.get('mac')} != board {mac}")
    rows = rec.summary_rows(0)
    rs.require(len(rows) >= 300, 'recorder has < 3 s of bins: wait before the unpowered-board check')
    bad = sum(1 for r in rows if int(r['bits_or']) != 255 or int(r['bits_and']) != 255)
    rs.require(bad == 0, f'logic port powered in {bad}/{len(rows)} bins with the output OFF: the board has '
                         'another supply (native USB?) or the recorder is not fresh')
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ppk-session', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--flash-record', type=Path, required=True, help='esp_ops.py flash --out DIR')
    ap.add_argument('--mac', required=True, help='board MAC from esp_ops identify (e.g. e8:f6:0a:8b:40:80)')
    ap.add_argument('--build', default=esp_ops.DEFAULT_BUILD, choices=sorted(esp_ops.BUILDS))
    ap.add_argument('--sessions', type=int, default=3)
    ap.add_argument('--off-s', type=float, default=10.0)
    ap.add_argument('--timeout-s', type=float, default=900.0)
    ap.add_argument('--label', default='esp_session')
    a = ap.parse_args(argv)
    rs.require(a.out.is_absolute() and not os.path.lexists(a.out), 'fresh absolute --out required')
    rec = rs.Recorder(a.ppk_session)
    sess_meta = preflight(rec, a.flash_record, a.build, a.mac)
    a.out.mkdir(parents=True)
    logf = (a.out / 'driver_log.jsonl').open('a')

    def log(obj):
        obj = dict(utc=rs.utc(), **obj)
        logf.write(json.dumps(obj) + '\n'); logf.flush()
        print(json.dumps(obj), flush=True)
    log(dict(event='preflight_ok', recorder=str(a.ppk_session), driver_sha256=rs.sha(Path(__file__)),
             shared_driver_sha256=rs.sha(Path(rs.__file__)), decoder_sha256=rs.sha(Path(rs.rd.__file__)),
             analysis_sha256=rs.sha(rs.PPK / 'analyze_schedule.py'), build=a.build))
    results = []
    prev_off = None
    for k in range(a.sessions):
        label = f'{a.label}_{k + 1:02d}'
        present = usb_vendors_present()
        rs.require(not present, f'ESP/USB-bridge device appeared: {sorted(present)}')
        n_ev = len(rec.events())
        if not safe_command(rec, f'start {label}', log):
            log(dict(event='abort', session=label, reason='recorder gone', instrument_fault=True))
            break
        time.sleep(1.0)
        safe_command(rec, 'on', log)
        time.sleep(1.5)
        new = rec.events()[n_ev:]
        start_ev = next((e for e in new if e['kind'] == 'segment_start'), None)
        on_ev = next((e for e in new if e['kind'] == 'command' and e.get('name') == 'output_on'), None)
        if not (start_ev and on_ev):
            safe_command(rec, 'off', log); safe_command(rec, 'stop', log)
            log(dict(event='abort', session=label, reason='segment/ON not confirmed', new_events=new))
            break
        log(dict(event='powered', session=label, segment_sample=start_ev['sample_index']))
        gap = None
        if prev_off is not None:
            gap = logic_states(rec, prev_off + int(OFF_GAP_SKIP_S * 100_000), on_ev['sample_index'])
            log(dict(event='off_gap_logic', session=label, states=gap[0], bins=gap[1]))
        t_on = time.monotonic()
        done = dict(done=False, reason='driver exception')
        try:
            done = wait_done_esp(rec, start_ev['sample_index'], t_on, a.timeout_s, log)
            time.sleep(1.0)
        finally:
            alive = safe_command(rec, 'stop', log)
            time.sleep(1.0)
            alive = safe_command(rec, 'off', log) and alive
        if not alive:
            done = dict(done, done=False, instrument_fault=True, reason='recorder gone: ' + done.get('reason', ''))
        log(dict(event='session_end', session=label, **done))
        time.sleep(1.0)
        evs = rec.events()
        offs = [e for e in evs[n_ev:] if e['kind'] == 'command' and e.get('name') == 'output_off']
        prev_off = offs[-1]['sample_index'] if offs else None
        stops = [e for e in evs[n_ev:] if e['kind'] == 'segment_stop' and e.get('label') == label]
        if not stops:
            log(dict(event='abort', session=label, reason='no segment_stop event'))
            break
        stop_ev = stops[-1]
        seg = dict(path=start_ev['path'], label=label, frames=stop_ev.get('frames'), sha256=stop_ev.get('sha256'))
        guard_hits = [e for e in evs[n_ev:] if e['kind'] == 'usb_guard_present_while_on']
        conv = None
        if done['done']:
            try:
                res, conv = rs.analyze(rec, seg, sess_meta, start_ev, stop_ev, on_ev, mask_s=MASK_S)
            except Exception as exc:
                res = dict(problems=[f'analysis error: {type(exc).__name__}: {exc}'], phases={}, header=None)
        else:
            res = dict(problems=['session did not reach DONE: ' + done.get('reason', '?')], phases={}, header=None)
        if guard_hits:
            res['problems'].append('ESP board USB appeared while the output was ON')
        if gap is not None and (len(gap[0]) != 1 or gap[1] < 100):
            res['problems'].append(f'logic byte changed (or < 1 s observed) while the output was OFF before this '
                                   f'session: {gap[0]} in {gap[1]} bins -> board powered from another source?')
        wiring = (res.get('phases') or {}).get('wiring') or {}
        if wiring.get('counter_gaps'):
            res['problems'].append(f"PPK2 counter discontinuity in the wiring phase ({wiring['counter_gaps']})")
        if res.get('header') and res['header'].get('platform') != 'esp32s3':
            res['problems'].append(f"telemetry platform is {res['header'].get('platform')}, not esp32s3")
        if res.get('header') and res['header']['clock_snapshot'].get('marker_gpio') != BUILD_MARKER_GPIO[a.build]:
            res['problems'].append(f"marker GPIO {res['header']['clock_snapshot'].get('marker_gpio')} is not "
                                   f"{BUILD_MARKER_GPIO[a.build]} of {a.build}")
        res.update(label=label, segment=seg, done=done, start_event=start_ev, stop_event=stop_ev, off_gap_logic=gap)
        (a.out / f'{label}_analysis.json').write_text(json.dumps(res, indent=1, default=str) + '\n')
        summ = rs.session_summary(res, conv) if res.get('header') else dict(eligible=False, problems=res['problems'])
        if res.get('header'):
            summ['reset_reason'] = res['header']['clock_snapshot'].get('reset_reason')
        (a.out / f'{label}_summary.json').write_text(json.dumps(summ, indent=1, default=str) + '\n')
        summ['instrument_fault'] = bool(done.get('instrument_fault'))
        results.append(dict(label=label, **summ))
        if not alive:
            log(dict(event='abort', session=label, reason='recorder gone; remaining sessions not run', instrument_fault=True))
        log(dict(event='analyzed', session=label, eligible=summ['eligible'], instrument_fault=summ['instrument_fault'],
                 problems=summ['problems'][:5],
                 gross=(summ.get('headline_gross_J_per_inference_between_schedules') or {}).get('mean')))
        if not alive:
            break
        if k + 1 < a.sessions:
            time.sleep(a.off_s)
    elig = [r for r in results if r['eligible']]
    agg = dict(sessions=len(results), eligible=len(elig),
               instrument_faults=[r['label'] for r in results if r.get('instrument_fault')],
               gross_J_per_inference_between_sessions=rs.az.ci95(
                   [r['headline_gross_J_per_inference_between_schedules']['mean'] for r in elig]),
               incremental_J_per_inference_between_sessions=rs.az.ci95(
                   [r['incremental_over_spin_J_per_inference_between_schedules']['mean'] for r in elig
                    if r['incremental_over_spin_J_per_inference_between_schedules']['mean'] is not None]),
               time_s_per_inference_between_sessions=rs.az.ci95([r['time_s_per_inference_windows']['mean'] for r in elig]),
               board_power_W_between_sessions=rs.az.ci95([r['board_power_W_bench']['mean'] for r in elig]),
               scope=rs.rd.PLATFORMS[0x31304D45]['scope'])
    (a.out / 'ESP_SESSIONS_AGGREGATE.json').write_text(json.dumps(agg, indent=1) + '\n')
    log(dict(event='aggregate', **{k: v for k, v in agg.items() if k != 'scope'}))
    return 0 if len(elig) == a.sessions else 2


if __name__ == '__main__':
    sys.exit(main())
