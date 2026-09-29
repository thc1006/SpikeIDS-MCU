"""Drive N autonomous RM01 power-on sessions on the FPB-RA4E1 and analyze them.

Preconditions (all checked; any failure refuses before power is applied):
  * a ppk2_session.py recorder is running in Source Meter mode at 5000 mV with
    --absent-guard <J-Link OB serial>, output OFF, guard not tripped, and it is
    the current ppk2_session.py (sha256);
  * the J-Link OB (J9) is NOT on the USB bus (J9 unplugged), so the board is
    powered only through CN2 by the PPK2 (the recorder also refuses ON otherwise);
  * the board holds RM01 build_03 (flash record with 'Verify successful').
Per session: start a raw segment, output ON (board boots RM01 from flash), wait
for DONE (D0 HIGH >= 12 s after >= 60 s; the longest HIGH window is ~5.6 s),
stop the segment, output OFF for --off-s, then decode + analyze offline. Never
flashes, resets over SWD, or changes the PPK2 mode/voltage.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PPK = REPO / 'tools/ppk2_energy'
sys.path.insert(0, str(PPK))
sys.path.insert(0, str(HERE))
import analyze_schedule as az  # noqa: E402
import ppk2_session  # noqa: E402
import rm01_decode as rd  # noqa: E402

JLINK_SERIAL = '000831033862'
SOURCE_MV = 5000
FLASH_RECORD = REPO / 'results/power_ra4e1_20260929/flash_rm01_build03'
BUILD_BIN = '19532b807902eb39510adfb85358a5f92d14abe5919156c03ed2ce531f89cb7f'   # build_03
VECTORS = REPO / 'results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq/validation_vectors.npz'
DONE_HIGH_S, DONE_MIN_ELAPSED_S = 12.0, 60.0
DONE_MIN_RISES = 100          # 140 firmware HIGH windows precede telemetry; >= 10 ms apart except preamble
# Type-B assumption for the unmeasured Source Meter output (no Nordic spec; one
# DevZone user measured 4.918 V at a 5000 mV setpoint = -1.6 %): band -3 % / +2 %.
VOUT_BAND_V = (4.85, 5.10)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def require(ok, msg):
    if not ok:
        raise SystemExit('REFUSED: ' + msg)


class Recorder:
    def __init__(self, d):
        self.d = d

    def session(self):
        return json.loads((self.d / 'session.json').read_text())

    def status(self):
        for _ in range(20):
            try:
                return json.loads((self.d / 'status.json').read_text())
            except (json.JSONDecodeError, FileNotFoundError):
                time.sleep(0.05)
        raise RuntimeError('status.json unreadable')

    def command(self, text):
        fd = os.open(self.d / 'control', os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, (text + '\n').encode())
        finally:
            os.close(fd)

    def events(self):
        out = []
        for x in (self.d / 'events.jsonl').read_text().splitlines():
            try:
                out.append(json.loads(x))
            except json.JSONDecodeError:      # a line still being written
                continue
        return out

    def summary_rows(self, from_sample):
        rows = []
        with open(self.d / 'summary_10ms.csv') as f:
            for r in csv.DictReader(f):
                try:
                    if int(r['sample_start']) >= from_sample:
                        int(r['bits_or']); int(r['bits_and']); float(r['mean_uA'])
                        rows.append(r)
                except (TypeError, ValueError):   # partial trailing row
                    continue
        return rows


def preflight(rec):
    s = rec.session()
    running = [v for k, v in s['source_sha256'].items() if k.endswith('ppk2_session.py')]
    require(running == [sha(PPK / 'ppk2_session.py')], 'recorder is not the current ppk2_session.py')
    require(s.get('source_mv') == SOURCE_MV and s['metadata'].get('mode') == '2'
            and s['metadata'].get('VDD') == str(SOURCE_MV), 'recorder not in Source mode at 5000 mV')
    require(s.get('absent_guard_serial') == JLINK_SERIAL, 'recorder has no J-Link absent-guard')
    st = rec.status()
    require(not st['output_on'] and not st['guard_tripped'], f'recorder output/guard state {st}')
    require(st['recording'] is None, f"recorder already recording {st['recording']}")
    require(not ppk2_session.usb_present(JLINK_SERIAL), 'J-Link OB present: unplug J9 first')
    txt = (FLASH_RECORD / 'flash.console.txt').read_text()
    cmd = (FLASH_RECORD / 'flash.jlink').read_text()
    require('Verify successful' in txt and 'firmware_measure/build_03/firmware.bin' in cmd
            and sha(REPO / 'tools/ra4e1_deployment/firmware_measure/build_03/firmware.bin') == BUILD_BIN,
            'no verified build_03 flash record')
    return s


def done_state(rows):
    """From 10 ms summary rows: (current D0-HIGH run in bins, D0 rises seen).
    A bin counts only if the logic port is powered (D1..D7 LOW in the whole
    bin): all-ones bins are the unpowered-port signature, not a marker."""
    run, rises, prev_low = 0, 0, False
    for r in rows:
        bor, band = int(r['bits_or']), int(r['bits_and'])
        if bor & 0xFE:                   # logic port unpowered / D1..D7 not LOW
            run, prev_low = 0, False
            continue
        if band & 1:
            run += 1
        else:
            run = 0
        if (bor & 1) and prev_low:
            rises += 1
        prev_low = not (bor & 1)         # a rise needs a bin with no HIGH at all before it
    return run, rises


def wait_done(rec, start_sample, t_on, timeout_s, log):
    """DONE = D0 HIGH (logic powered) >= DONE_HIGH_S after >= DONE_MIN_ELAPSED_S
    and after >= DONE_MIN_RISES marker rises (a stuck-HIGH D0 is not DONE)."""
    need = int(DONE_HIGH_S * 100)
    last_print = 0
    while time.monotonic() - t_on < timeout_s:
        time.sleep(2.0)
        st = rec.status()
        if not st['output_on'] or st['guard_tripped']:
            return dict(done=False, reason=f'output dropped / guard: {st}')
        rows = rec.summary_rows(start_sample)
        run, rises = done_state(rows)
        elapsed = len(rows) / 100.0
        if time.monotonic() - last_print > 30:
            log(dict(t=round(time.monotonic() - t_on, 1), captured_s=elapsed,
                     mean_mA_1s=(st['mean_uA_last_1s'] or 0) / 1000, d0_high_run_s=run / 100, d0_rises=rises))
            last_print = time.monotonic()
        if elapsed >= DONE_MIN_ELAPSED_S and run >= need:
            if rises >= DONE_MIN_RISES:
                return dict(done=True, captured_s=elapsed, done_high_s=run / 100, d0_rises=rises)
            return dict(done=False, reason=f'D0 HIGH {run / 100:.1f} s but only {rises} marker rises: stuck HIGH?')
    return dict(done=False, reason='timeout')


def analyze(rec, seg, sess_meta, start_ev, stop_ev, on_ev, mask_s=0.5):
    conv = ppk2_session.Converter(sess_meta['metadata'], SOURCE_MV / 1000.0)
    ua = lambda w: conv.ua(w)[0]
    words = az.load_words(rec.d / seg['path'])
    gaps = [(e['sample_index'] - start_ev['sample_index'], e['gap_s']) for e in rec.events()
            if e['kind'] == 'reader_gap' and start_ev['sample_index'] <= e['sample_index'] <= stop_ev['sample_index']]
    z = np.load(VECTORS)
    ins = [tuple(r) for r in np.ascontiguousarray(z['x'], '<f4').view('<u4')]
    outs = [tuple(r) for r in np.ascontiguousarray(z['reference_logits'], '<f4').view('<u4')]
    # Frames before output ON + 0.5 s are physically unpowered (J9 unplugged); the PPK2
    # latches its last logic byte while the board is off (Amendment 3, review B1).
    unpowered_before = max(0, on_ev['sample_index'] - start_ev['sample_index'] + int(mask_s * 100_000))
    res = rd.analyze_capture(words, ua, SOURCE_MV / 1000.0, ins, outs, reader_gaps=gaps, top_range_only=False,
                             unpowered_before=unpowered_before)
    r = (words >> 14) & 7
    res['range_histogram_capture'] = np.bincount(r[r <= 4], minlength=5)[:5].tolist()
    res['reader_gaps'] = gaps
    res['counter_gaps'] = int(len(az.counter_gaps(words)))
    host_s = stop_ev['host_monotonic'] - start_ev['host_monotonic']
    res['timebase_check'] = dict(frames=int(len(words)), host_s=host_s,
                                 ppk2_rate_vs_host=(len(words) / host_s) if host_s else None,
                                 note='descriptive: consumer backlog at segment edges also enters host_s')
    return res, conv


def session_summary(res, conv=None):
    ph = res.get('phases', {})
    reps = [v for k, v in ph.items() if k.startswith('schedule') and v.get('kind') == 'repeat' and v.get('valid')]
    doses = [v for k, v in ph.items() if k.startswith('schedule') and v.get('kind') == 'dose']
    sham = ph.get('sham', {})
    wiring = ph.get('wiring', {})
    g = [v['summary']['bench_gross_J_per_inference']['mean'] for v in reps]
    # Protocol: incremental only from range-consistent windows (same dominant range, no switch).
    inc = [v['incremental_J_per_inference_range_consistent']['mean'] for v in reps
           if (v.get('incremental_J_per_inference_range_consistent') or {}).get('mean') is not None]
    windows = [row for v in reps for row in v['bench']]
    valid_sched = [v for k, v in ph.items() if k.startswith('schedule') and v.get('valid')]
    gross_pts = [(row['iterations'], row['gross_J_per_iter'] * row['iterations']) for v in valid_sched for row in v['bench']]
    inc_pts = [(row['iterations'], row['incremental_J_window']) for v in valid_sched for row in v['bench']
               if row.get('range_consistent')]
    sham_dP = (sham.get('null_dP_W') or {}).get('mean')
    mean_mA = (sum(x['p_window_W'] for x in windows) / len(windows) / (SOURCE_MV / 1000) * 1000) if windows else None
    ranges = [row['range_dominant']['window'] for row in windows if row.get('range_dominant')]
    dom = max(set(ranges), key=ranges.count) if ranges else None
    budget = None
    if mean_mA and conv is not None and dom is not None:
        budget = az.systematic_budget(mean_mA, volts_assumed=SOURCE_MV / 1000, v_lo=VOUT_BAND_V[0],
                                      v_hi=VOUT_BAND_V[1], s4_A_per_V=float(conv.c['S'][dom]),
                                      gain=0.20, nordic_vdd=SOURCE_MV / 1000)
        budget['S_term_range'] = dom
        budget['vout_band_basis'] = ('assumption: Nordic gives no Source Meter accuracy; one DevZone user '
                                     'measured 4.918 V at 5000 mV (thread 125227)')
        budget['gain_basis'] = ('PPK2 UG v1.0.1 intro "better than +/-20 %"; Table 9 lists +/-10 % (R1-R4), '
                                '+/-15 % (R5) for average readout; the conservative 20 % is used')
    return dict(
        eligible=rd.eligible(res),
        problems=res['problems'], phase_problems=res.get('phase_problems', []),
        headline_gross_J_per_inference_between_schedules=az.ci95(g),
        incremental_over_spin_J_per_inference_between_schedules=az.ci95(inc),
        gross_J_per_inference_windows=az.ci95([x['gross_J_per_iter'] for x in windows]),
        time_s_per_inference_windows=az.ci95([x['time_s_per_iter_ppk2'] for x in windows]),
        board_power_W_bench=az.ci95([x['p_window_W'] for x in windows]),
        board_power_W_idle_spin=az.ci95([x['p_idle_W'] for x in windows]),
        cpu_hz_estimate=[v['summary']['cpu_hz_estimate'] for v in reps],
        sham_null_dI_mA=sham.get('null_dI_mA'),
        sham_null_dP_W=sham.get('null_dP_W'),
        incremental_sham_corrected_J_per_inference_windows=az.ci95(
            [x['incremental_J_per_iter'] - sham_dP * x['time_s_per_iter_ppk2'] for x in windows
             if x.get('range_consistent')]) if sham_dP is not None else None,
        incremental_range_consistent_windows=sum(1 for x in windows if x.get('range_consistent')),
        bench_windows=len(windows), dominant_range=dom,
        dose_valid=[d.get('valid') for d in doses],
        dose_response_gross_J_vs_N=az.ols([p_[0] for p_ in gross_pts], [p_[1] for p_ in gross_pts]),
        dose_response_incremental_J_vs_N=az.ols([p_[0] for p_ in inc_pts], [p_[1] for p_ in inc_pts]),
        systematic=budget,
        parity=dict(mismatched_words=res['header']['parity_mismatched_words'],
                    outputs_fnv=hex(res['header']['parity_outputs_fnv'])))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ppk-session', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--sessions', type=int, default=3)
    ap.add_argument('--off-s', type=float, default=10.0)
    ap.add_argument('--timeout-s', type=float, default=900.0)
    ap.add_argument('--label', default='ra_session')
    a = ap.parse_args(argv)
    require(a.out.is_absolute() and not os.path.lexists(a.out), 'fresh absolute --out required')
    rec = Recorder(a.ppk_session)
    sess_meta = preflight(rec)
    a.out.mkdir(parents=True)
    logf = (a.out / 'driver_log.jsonl').open('a')

    def log(obj):
        obj = dict(utc=utc(), **obj)
        logf.write(json.dumps(obj) + '\n'); logf.flush()
        print(json.dumps(obj), flush=True)
    log(dict(event='preflight_ok', recorder=str(a.ppk_session), driver_sha256=sha(Path(__file__)),
             decoder_sha256=sha(HERE / 'rm01_decode.py'), analysis_sha256=sha(PPK / 'analyze_schedule.py')))
    results = []
    for k in range(a.sessions):
        label = f'{a.label}_{k + 1:02d}'
        require(not ppk2_session.usb_present(JLINK_SERIAL), 'J-Link OB present: unplug J9')
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
            done = wait_done(rec, start_ev['sample_index'], t_on, a.timeout_s, log)
            time.sleep(1.0)
        finally:                                   # never leave the output ON or a segment open
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
                res, conv = analyze(rec, seg, sess_meta, start_ev, stop_ev, on_ev)
            except Exception as exc:            # record and continue with the next power-on
                res = dict(problems=[f'analysis error: {type(exc).__name__}: {exc}'], phases={}, header=None)
        else:
            res = dict(problems=['session did not reach DONE: ' + done.get('reason', '?')], phases={}, header=None)
        if guard_hits:
            res['problems'].append('J-Link OB appeared on USB while the output was ON')
        res.update(label=label, segment=seg, done=done, start_event=start_ev, stop_event=stop_ev)
        (a.out / f'{label}_analysis.json').write_text(json.dumps(res, indent=1, default=str) + '\n')
        summ = session_summary(res, conv) if res.get('header') else dict(eligible=False, problems=res['problems'])
        (a.out / f'{label}_summary.json').write_text(json.dumps(summ, indent=1, default=str) + '\n')
        results.append(dict(label=label, **summ))
        log(dict(event='analyzed', session=label, eligible=summ['eligible'], problems=summ['problems'][:5],
                 gross=(summ.get('headline_gross_J_per_inference_between_schedules') or {}).get('mean')))
        if k + 1 < a.sessions:
            time.sleep(a.off_s)
    elig = [r for r in results if r['eligible']]
    agg = dict(sessions=len(results), eligible=len(elig),
               gross_J_per_inference_between_sessions=az.ci95(
                   [r['headline_gross_J_per_inference_between_schedules']['mean'] for r in elig]),
               incremental_J_per_inference_between_sessions=az.ci95(
                   [r['incremental_over_spin_J_per_inference_between_schedules']['mean'] for r in elig
                    if r['incremental_over_spin_J_per_inference_between_schedules']['mean'] is not None]),
               time_s_per_inference_between_sessions=az.ci95(
                   [r['time_s_per_inference_windows']['mean'] for r in elig]),
               board_power_W_between_sessions=az.ci95([r['board_power_W_bench']['mean'] for r in elig]),
               scope='FPB-RA4E1 whole board at its main 5 V net (J2-5), PPK2 Source Meter 5.000 V setpoint (VOUT unmeasured), J9 unplugged')
    (a.out / 'RA_SESSIONS_AGGREGATE.json').write_text(json.dumps(agg, indent=1) + '\n')
    log(dict(event='aggregate', **{k: v for k, v in agg.items() if k != 'scope'}))
    return 0 if len(elig) == a.sessions else 2


if __name__ == '__main__':
    sys.exit(main())
