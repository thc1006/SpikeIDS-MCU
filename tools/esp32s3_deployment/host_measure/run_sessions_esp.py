"""Drive N autonomous EM01 power-on sessions on an ESP32-S3 N16R8 board.

Same session procedure, DONE rule, decoder and analysis as the FPB-RA4E1 driver
(tools/ra4e1_deployment/host_measure/run_sessions.py, imported here and not
modified): the platform is recognised from the EM01 telemetry magic. What
differs is the preflight:
  * the recorder runs in Source Meter mode at 5000 mV with --absent-guard set
    to the board's USB serial (recorded by esp_ops.py identify);
  * no ESP32-S3 USB device (Espressif 303a, or a CH34x/CP210x/FTDI bridge) may
    be on the bus: the board is powered only from the PPK2 via its 5V pin;
  * the board holds a verified EM01 build (esp_ops.py flash record: 3 regions
    'Hash of data verified', pinned build hashes).
Never flashes, resets or changes the PPK2 mode/voltage.
"""
import argparse
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


def preflight(rec, guard_serial, flash_record, build):
    s = rec.session()
    running = [v for k, v in s['source_sha256'].items() if k.endswith('ppk2_session.py')]
    rs.require(running == [rs.sha(rs.PPK / 'ppk2_session.py')], 'recorder is not the current ppk2_session.py')
    rs.require(s.get('source_mv') == rs.SOURCE_MV and s['metadata'].get('mode') == '2'
               and s['metadata'].get('VDD') == str(rs.SOURCE_MV), 'recorder not in Source mode at 5000 mV')
    rs.require(s.get('absent_guard_serial') == guard_serial, 'recorder absent-guard is not the ESP board serial')
    st = rec.status()
    rs.require(not st['output_on'] and not st['guard_tripped'], f'recorder output/guard state {st}')
    rs.require(st['recording'] is None, f"recorder already recording {st['recording']}")
    present = usb_vendors_present()
    rs.require(not present, f'ESP/USB-bridge device on the bus ({sorted(present)}): unplug the board USB first')
    txt = (flash_record / 'flash.console.txt').read_text()
    argv = json.loads((flash_record / 'flash.json').read_text())['argv']
    pins = esp_ops.BUILDS[build]
    d = esp_ops.FW / build / 'build'
    rs.require(txt.count('Hash of data verified') == 3 and str(d / 'em01.bin') in argv
               and all(rs.sha(d / n) == h for n, h in pins.items()), f'no verified {build} flash record')
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ppk-session', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--guard-serial', required=True, help='ESP board USB iSerial (esp_ops identify)')
    ap.add_argument('--flash-record', type=Path, required=True)
    ap.add_argument('--build', default=esp_ops.DEFAULT_BUILD, choices=sorted(esp_ops.BUILDS))
    ap.add_argument('--sessions', type=int, default=3)
    ap.add_argument('--off-s', type=float, default=10.0)
    ap.add_argument('--timeout-s', type=float, default=900.0)
    ap.add_argument('--label', default='esp_session')
    a = ap.parse_args(argv)
    rs.require(a.out.is_absolute() and not os.path.lexists(a.out), 'fresh absolute --out required')
    rec = rs.Recorder(a.ppk_session)
    sess_meta = preflight(rec, a.guard_serial, a.flash_record, a.build)
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
    for k in range(a.sessions):
        label = f'{a.label}_{k + 1:02d}'
        present = usb_vendors_present()
        rs.require(not present, f'ESP/USB-bridge device appeared: {sorted(present)}')
        n_ev = len(rec.events())
        rec.command(f'start {label}')
        time.sleep(1.0)
        rec.command('on')
        time.sleep(1.5)
        new = rec.events()[n_ev:]
        start_ev = next((e for e in new if e['kind'] == 'segment_start'), None)
        on_ev = next((e for e in new if e['kind'] == 'command' and e.get('name') == 'output_on'), None)
        if not (start_ev and on_ev):
            rec.command('off'); rec.command('stop')
            log(dict(event='abort', session=label, reason='segment/ON not confirmed', new_events=new))
            break
        log(dict(event='powered', session=label, segment_sample=start_ev['sample_index']))
        t_on = time.monotonic()
        done = dict(done=False, reason='driver exception')
        try:
            done = rs.wait_done(rec, start_ev['sample_index'], t_on, a.timeout_s, log)
            time.sleep(1.0)
        finally:
            rec.command('stop')
            time.sleep(1.0)
            rec.command('off')
        log(dict(event='session_end', session=label, **done))
        time.sleep(1.0)
        evs = rec.events()
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
                res, conv = rs.analyze(rec, seg, sess_meta, start_ev, stop_ev, on_ev)
            except Exception as exc:
                res = dict(problems=[f'analysis error: {type(exc).__name__}: {exc}'], phases={}, header=None)
        else:
            res = dict(problems=['session did not reach DONE: ' + done.get('reason', '?')], phases={}, header=None)
        if guard_hits:
            res['problems'].append('ESP board USB appeared while the output was ON')
        if res.get('header') and res['header'].get('platform') != 'esp32s3':
            res['problems'].append(f"telemetry platform is {res['header'].get('platform')}, not esp32s3")
        res.update(label=label, segment=seg, done=done, start_event=start_ev, stop_event=stop_ev)
        (a.out / f'{label}_analysis.json').write_text(json.dumps(res, indent=1, default=str) + '\n')
        summ = rs.session_summary(res, conv) if res.get('header') else dict(eligible=False, problems=res['problems'])
        if res.get('header'):
            summ['reset_reason'] = res['header']['clock_snapshot'].get('reset_reason')
        (a.out / f'{label}_summary.json').write_text(json.dumps(summ, indent=1, default=str) + '\n')
        results.append(dict(label=label, **summ))
        log(dict(event='analyzed', session=label, eligible=summ['eligible'], problems=summ['problems'][:5],
                 gross=(summ.get('headline_gross_J_per_inference_between_schedules') or {}).get('mean')))
        if k + 1 < a.sessions:
            time.sleep(a.off_s)
    elig = [r for r in results if r['eligible']]
    agg = dict(sessions=len(results), eligible=len(elig),
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
