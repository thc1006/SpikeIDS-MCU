"""Offline energy analysis of SM07M captures (never opens hardware).

Inputs: a PPK2 session segment (raw u32 frames), the session metadata, and the
firmware window table read back afterwards. D0 (Arduino D12 / PH8) HIGH runs
are matched one-to-one, in order, with the firmware's marker-HIGH windows.
Every LOW gap between two HIGH windows is the firmware's DWT busy-wait loop.

Scope: board 5 V input downstream of JP2 (whole board minus ST-LINK), NOT the
SoC core or NPU. Definitions (V is an ASSUMED constant; 5V_STLK not measured):
  gross per inference        = V * sum(I dt over BENCH) / N
  incremental per inference  = (P_BENCH - P_IDLE) * T_BENCH / N
  vs-overhead per inference  = (P_BENCH - P_OVERHEAD) * T_BENCH / N  (sensitivity)
P_IDLE averages the trimmed busy-wait gaps just before and after the window,
so "incremental" is over a CPU spin, a lower bound on marginal cost vs sleep.
Confidence intervals here are REPEATABILITY only; instrument/voltage accuracy
is a separate Type-B budget (systematic_budget()).
"""
import json
import math
from pathlib import Path
import struct

import numpy as np
from scipy import stats

FS = 100_000.0
KIND = {1: 'IDLE', 2: 'BENCH', 3: 'OVERHEAD', 4: 'PULSE'}
R5 = 4                       # PPK2 top range (code 4; 50 mA .. 1 A)
MAX_UA = 1_000_000.0         # PPK2 Ampere-meter continuous rating: 1 A
DWT_AGREE_TOL = 0.005        # sum-based vs mean-power x DWT-time energy must agree within 0.5 %


def load_words(path):
    raw = Path(path).read_bytes()
    if len(raw) % 4:
        raise ValueError('Partial PPK2 frame in segment')
    return np.frombuffer(raw, dtype='<u4')


def counter_gaps(words):
    c = (words >> 18) & 63
    return np.nonzero(c[1:] != (c[:-1] + 1) % 64)[0] + 1


def high_runs(d0, glitch=3):
    """Half-open [start, stop) sample ranges where D0 is HIGH. LOW gaps and
    HIGH runs of <= `glitch` samples (30 us) are edge chatter; real windows
    and pulses here are >= 10 ms."""
    d = np.concatenate(([0], d0.astype(np.int8), [0]))
    edges = np.diff(d)
    runs = list(zip(np.nonzero(edges == 1)[0].tolist(), np.nonzero(edges == -1)[0].tolist()))
    merged = []
    for a, b in runs:
        if merged and a - merged[-1][1] <= glitch:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return [(a, b) for a, b in merged if b - a > glitch]


def fnv1a_bytes(data, h=2166136261):
    for b in data:
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h


def expected_checksums(outputs_words, inputs_words, n_rows, bench_reps, overhead_reps):
    """Checksums the firmware must report: BENCH over output words of rows
    0..n-1 (repeated), OVERHEAD over the first five input words (I/O alias)."""
    bench = b''.join(struct.pack('<5I', *outputs_words[r]) for r in range(n_rows)) * bench_reps
    over = b''.join(struct.pack('<5I', *inputs_words[r][:5]) for r in range(n_rows)) * overhead_reps
    return fnv1a_bytes(bench), fnv1a_bytes(over)


def ci95(values):
    v = np.asarray([x for x in values if x is not None], dtype=np.float64)
    if len(v) == 0:
        return dict(n=0, mean=None, sd=None, ci95=None, cv=None)
    m = float(v.mean())
    if len(v) < 2:
        return dict(n=1, mean=m, sd=None, ci95=None, cv=None)
    sd = float(v.std(ddof=1))
    half = float(stats.t.ppf(0.975, len(v) - 1) * sd / math.sqrt(len(v)))
    return dict(n=int(len(v)), mean=m, sd=sd, ci95=[m - half, m + half], cv=sd / abs(m) if m else None)


def ols(x, y):
    """y = a + b x with 95% CIs (t, n-2 df)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    if n < 3 or np.ptp(x) == 0:
        return None
    xm, ym = x.mean(), y.mean()
    sxx = float(((x - xm) ** 2).sum())
    b = float(((x - xm) * (y - ym)).sum() / sxx)
    a = float(ym - b * xm)
    resid = y - (a + b * x)
    s2 = float((resid ** 2).sum() / (n - 2))
    t = float(stats.t.ppf(0.975, n - 2))
    se_b, se_a = math.sqrt(s2 / sxx), math.sqrt(s2 * (1 / n + xm ** 2 / sxx))
    return dict(n=n, slope=b, slope_ci95=[b - t * se_b, b + t * se_b], intercept=a,
                intercept_ci95=[a - t * se_a, a + t * se_a],
                intercept_ci_contains_zero=bool(a - t * se_a <= 0 <= a + t * se_a))


def lag1(values):
    v = np.asarray([x for x in values if x is not None], float)
    if len(v) < 4 or v.std() == 0:
        return None
    return float(np.corrcoef(v[:-1], v[1:])[0, 1])


def code_mA(coef):
    """Current per ADC code in range R5 for this unit (first-order)."""
    return 4 * 1.8 / 163840 / coef['R'][R5] * coef['GI'][R5] * 1000


def systematic_budget(i_mA, volts_assumed=5.0, v_lo=4.4, v_hi=5.25, s4_A_per_V=None, gain=0.20,
                      nordic_vdd=4.0):
    """Type-B bounds on TRUE/ESTIMATED (not CIs), for the measured mean current i_mA.

    Gross: E_est = V_a * Q_est and Q_est - Q_true = S4 * (V_a - V_true) * T, so
    E_true/E_est = (V_true/V_a) * (1 - S4 (V_a - V_true) / I). Incremental (same V
    both windows): S-term cancels, E_true/E_est = V_true/V_a. PPK2 accuracy 'better than
    +/-20 %' (Nordic listing; +/-15 % not confirmed). Nordic's app applies S at the metadata VDD instead."""
    def gross_ratio(v):
        s_term = (s4_A_per_V or 0.0) * (volts_assumed - v) * 1000 / i_mA
        return (v / volts_assumed) * (1 - s_term)
    g_lo, g_hi = gross_ratio(v_lo) - 1, gross_ratio(v_hi) - 1
    i_lo, i_hi = v_lo / volts_assumed - 1, v_hi / volts_assumed - 1
    rss = lambda a: (gain ** 2 + a ** 2) ** 0.5
    worst = lambda lo, hi: [(1 - gain) * (1 + lo) - 1, (1 + gain) * (1 + hi) - 1]   # factors multiply
    return dict(kind='Type-B on true/estimated: RSS (labelled) and multiplicative worst-case bounds',
                gross_worst_case_bounds=worst(g_lo, g_hi), incremental_worst_case_bounds=worst(i_lo, i_hi),
                ppk2_gain_rel=gain, vin_band_V=[v_lo, v_hi], mean_current_mA=i_mA,
                gross_vin_rel=[g_lo, g_hi], incremental_vin_rel=[i_lo, i_hi],
                gross_rel_bounds=[-rss(g_lo), rss(g_hi)],          # RSS combination, not a bound
                incremental_rel_bounds=[-rss(i_lo), rss(i_hi)],    # RSS combination, not a bound
                nordic_app_convention_rel=(-(s4_A_per_V or 0) * (volts_assumed - nordic_vdd) * 1000 / i_mA),
                note='Same-setup ratios cancel gain and VIN; absolute values do not.')


def _span_stats(ua, r, a, b, volts, per_code_mA=None):
    seg = ua[a:b]
    q = float(seg.sum()) * 1e-6 / FS
    t = (b - a) / FS
    out = dict(samples=int(b - a), duration_s=t, charge_C=q, energy_J=q * volts,
               mean_power_W=q * volts / t if t else None,
               mean_current_mA=float(seg.mean()) / 1000 if len(seg) else None,
               sd_current_mA=float(seg.std()) / 1000 if len(seg) > 1 else None,
               non_r5_samples=int((r[a:b] != R5).sum()), over_1A_samples=int((seg > MAX_UA).sum()))
    if per_code_mA and out['sd_current_mA'] is not None:
        out['sd_current_codes'] = out['sd_current_mA'] / per_code_mA
    return out


def analyze_pulses(words, ua_fn, expected_count, expected_width_s, tol=0.25):
    d0 = ((words >> 24) & 1).astype(bool)
    runs = high_runs(d0)
    widths = [(b - a) / FS for a, b in runs]
    ok_count = len(runs) == expected_count
    ok_width = all(abs(w - expected_width_s) <= tol * expected_width_s for w in widths)
    starts_low = bool(len(d0)) and not d0[0]
    ends_low = bool(len(d0)) and not d0[-1]
    return dict(passed=bool(ok_count and ok_width and starts_low and ends_low), runs=len(runs),
                widths_s=widths, expected_count=expected_count, expected_width_s=expected_width_s,
                d0_low_at_segment_start=starts_low, d0_low_at_segment_end=ends_low,
                d0_high_fraction=float(d0.mean()) if len(d0) else None,
                counter_gaps=int(len(counter_gaps(words))))


def analyze_sham(words, ua_fn, table, volts, guard_s=0.05, per_code_mA=None, max_marker_mA=0.5,
                 reader_gaps=()):
    """Null control: HIGH and LOW are the same busy-wait; only the marker
    differs. dP estimates the method floor + the marker pin's own load."""
    problems = []
    if reader_gaps:
        problems.append(f'{len(reader_gaps)} host reader gap(s) inside the sham capture')
    if len(counter_gaps(words)):
        problems.append('PPK2 counter discontinuities in sham capture')
    ua = ua_fn(words)
    if not np.isfinite(ua).all():
        return dict(valid=False, problems=problems + ['Invalid range code'])
    r = (words >> 14) & 7
    d0 = ((words >> 24) & 1).astype(bool)
    if len(d0) and (d0[0] or d0[-1]):
        problems.append('D0 HIGH at sham segment start or end')
    runs = high_runs(d0)
    fw = [w for w in table if w['marker_high']]
    if len(runs) != len(fw) or len(runs) < 3:
        return dict(valid=False, problems=problems + [f'Sham HIGH runs {len(runs)} != firmware {len(fw)}'])
    g = int(round(guard_s * FS))
    width = int(np.median([b - a for a, b in runs]))
    rows = []
    for k, (a, b) in enumerate(runs):
        hi = _span_stats(ua, r, a + g, b - g, volts, per_code_mA)
        lows = []
        if k > 0:
            lows.append(_span_stats(ua, r, runs[k - 1][1] + g, a - g, volts, per_code_mA))
        lo_end = runs[k + 1][0] if k + 1 < len(runs) else min(len(ua), b + width)
        lows.append(_span_stats(ua, r, b + g, lo_end - g, volts, per_code_mA))
        for s in [hi] + lows:
            if s['non_r5_samples'] or s['over_1A_samples']:
                problems.append(f'Sham window {k}: non-R5 or >1 A samples')
        p_lo = sum(s['mean_power_W'] for s in lows) / len(lows)
        i_lo = sum(s['mean_current_mA'] for s in lows) / len(lows)
        rows.append(dict(window=k, dP_W=hi['mean_power_W'] - p_lo, dI_mA=hi['mean_current_mA'] - i_lo))
    di = ci95([x['dI_mA'] for x in rows])
    dp = ci95([x['dP_W'] for x in rows])
    marker_ok = di['mean'] is not None and abs(di['mean']) < max_marker_mA
    if not marker_ok:
        problems.append(f"Marker-level current difference {di['mean']:.3f} mA exceeds {max_marker_mA} mA")
    return dict(valid=not problems, problems=problems, windows=rows, null_dP_W=dp, null_dI_mA=di,
                null_dI_codes=(di['mean'] / per_code_mA) if (per_code_mA and di['mean'] is not None) else None,
                marker_load_check_passed=bool(marker_ok), max_marker_mA=max_marker_mA)


def analyze_schedule(words, ua_fn, table, params, volts, guard_s=0.05, expected=None, per_code_mA=None,
                     reader_gaps=()):
    """table: firmware window records (dicts with kind/start_cycle/end_cycle/
    iterations/checksum/marker_high) in execution order. reader_gaps: host
    reader stalls (> READER_GAP_S) inside this segment; any gap invalidates it
    because a stall can drop counter-invisible multiples of 64 samples."""
    problems = []
    if reader_gaps:
        problems.append(f'{len(reader_gaps)} host reader gap(s) inside the capture (possible silent sample loss)')
    gaps = counter_gaps(words)
    if len(gaps):
        problems.append(f'{len(gaps)} PPK2 counter discontinuities; timing/energy invalid')
    ua = ua_fn(words)
    if not np.isfinite(ua).all():
        problems.append('Invalid range code in capture; no energy computed')
        return dict(valid=False, problems=problems, samples=int(len(words)))
    r = (words >> 14) & 7
    d0 = ((words >> 24) & 1).astype(bool)
    if len(d0) and d0[0]:
        problems.append('D0 HIGH at segment start: capture began inside a window')
    if len(d0) and d0[-1]:
        problems.append('D0 HIGH at segment end: capture stopped inside a window')
    runs = high_runs(d0)
    fw_high = [w for w in table if w['marker_high']]
    if len(runs) != len(fw_high):
        problems.append(f'D0 HIGH runs {len(runs)} != firmware HIGH windows {len(fw_high)}')
        return dict(valid=False, problems=problems, runs=len(runs), firmware_high=len(fw_high))
    kinds = [KIND[w['kind']] for w in fw_high]
    want = ['PULSE'] * params['pulse_count'] + ['BENCH', 'OVERHEAD'] * params['cycles']
    if kinds != want:
        problems.append('Firmware HIGH window order is not preamble + (BENCH, OVERHEAD) x cycles')
        return dict(valid=False, problems=problems)
    guard = int(round(guard_s * FS))

    def span(a, b):
        s = _span_stats(ua, r, a, b, volts, per_code_mA)
        if s['non_r5_samples']:
            problems.append(f'Span [{a},{b}) left range R5 ({s["non_r5_samples"]} samples)')
        if s['over_1A_samples']:
            problems.append(f'Span [{a},{b}) exceeds 1 A (PPK2 rating)')
        return s

    windows, clocks = [], []
    for k, ((a, b), fw) in enumerate(zip(runs, fw_high)):
        rec = span(a, b)
        cycles = (fw['end_cycle'] - fw['start_cycle']) & 0xFFFFFFFF
        rec.update(index=k, kind=KIND[fw['kind']], start_sample=a, stop_sample=b,
                   dwt_cycles=cycles, iterations=fw['iterations'], checksum=fw['checksum'],
                   cpu_hz_estimate=cycles / rec['duration_s'] if rec['duration_s'] else None)
        windows.append(rec)
        if rec['kind'] in ('BENCH', 'OVERHEAD'):
            clocks.append(rec['cpu_hz_estimate'])
    f_med = float(np.median(clocks)) if clocks else None
    for kind in ('BENCH', 'OVERHEAD'):   # descriptive only: HSI RC wander is ~0.1 % between windows
        ws = [w for w in windows if w['kind'] == kind]
        if ws:
            f_kind = float(np.median([w['cpu_hz_estimate'] for w in ws]))
            for w in ws:
                w['sample_residual'] = w['samples'] - w['dwt_cycles'] / f_kind * FS
    idle_len = int(round(params['idle_cycles'] / f_med * FS)) if f_med else 0

    def idle_after(k):
        a = runs[k][1] + guard
        b = (runs[k + 1][0] if k + 1 < len(runs) else runs[k][1] + idle_len) - guard
        if b - a < int(0.2 * FS):
            problems.append(f'Idle gap after HIGH {k} shorter than 0.2 s after guards')
            return None
        return span(a, b)

    idles = {k: idle_after(k) for k in range(params['pulse_count'] - 1, len(runs))}
    bench_rows, over_rows = [], []
    for k, rec in enumerate(windows):
        if rec['kind'] not in ('BENCH', 'OVERHEAD'):
            continue
        before, after = idles.get(k - 1), idles.get(k)
        if not (before and after):
            problems.append(f'Window {k}: two-sided idle baseline unavailable')
            continue
        p_idle = (before['mean_power_W'] + after['mean_power_W']) / 2
        i_idle = (before['mean_current_mA'] + after['mean_current_mA']) / 2
        n = rec['iterations']
        row = dict(window=k, iterations=n, duration_s=rec['duration_s'],
                   p_window_W=rec['mean_power_W'], p_idle_W=p_idle,
                   p_idle_before_W=before['mean_power_W'], p_idle_after_W=after['mean_power_W'],
                   dP_W=rec['mean_power_W'] - p_idle, dI_mA=rec['mean_current_mA'] - i_idle,
                   gross_J_per_iter=rec['energy_J'] / n,
                   gross_dwt_J_per_iter=rec['mean_power_W'] * (rec['dwt_cycles'] / f_med) / n if f_med else None,
                   incremental_J_per_iter=(rec['mean_power_W'] - p_idle) * rec['duration_s'] / n,
                   incremental_J_window=(rec['mean_power_W'] - p_idle) * rec['duration_s'],
                   charge_C_per_iter=rec['charge_C'] / n,
                   time_s_per_iter_ppk2=rec['duration_s'] / n,
                   dwt_cycles_per_iter=rec['dwt_cycles'] / n, checksum=rec['checksum'])
        if per_code_mA:
            row['dI_codes'] = row['dI_mA'] / per_code_mA
        (bench_rows if rec['kind'] == 'BENCH' else over_rows).append(row)
    for b in bench_rows:                      # BENCH k is followed by OVERHEAD k+1
        o = next((x for x in over_rows if x['window'] == b['window'] + 1), None)
        if o:
            b['vs_overhead_J_per_iter'] = (b['p_window_W'] - o['p_window_W']) * b['duration_s'] / b['iterations']
    bench_ck = {x['checksum'] for x in bench_rows}
    over_ck = {x['checksum'] for x in over_rows}
    if len(bench_ck) > 1 or len(over_ck) > 1:
        problems.append('Checksums differ between repeated windows (nondeterministic outputs)')
    if expected:
        if bench_ck and bench_ck != {expected['bench']}:
            problems.append('BENCH checksum != expected from bitwise-verified parity outputs')
        if over_ck and over_ck != {expected['overhead']}:
            problems.append('OVERHEAD checksum != expected input-copy checksum')
    for x in bench_rows:
        if x['gross_dwt_J_per_iter'] and abs(x['gross_J_per_iter'] / x['gross_dwt_J_per_iter'] - 1) > DWT_AGREE_TOL:
            problems.append(f"Window {x['window']}: sum-based and DWT-time energy differ by "
                            f"{x['gross_J_per_iter'] / x['gross_dwt_J_per_iter'] - 1:+.2%}")
    inc_series = [x['incremental_J_per_iter'] for x in bench_rows]
    summary = dict(
        bench_incremental_J_per_inference=ci95(inc_series),
        bench_gross_J_per_inference=ci95([x['gross_J_per_iter'] for x in bench_rows]),
        bench_gross_dwt_J_per_inference=ci95([x['gross_dwt_J_per_iter'] for x in bench_rows]),
        bench_vs_overhead_J_per_inference=ci95([x.get('vs_overhead_J_per_iter') for x in bench_rows]),
        bench_charge_C_per_inference=ci95([x['charge_C_per_iter'] for x in bench_rows]),
        bench_time_s_per_inference=ci95([x['time_s_per_iter_ppk2'] for x in bench_rows]),
        bench_dP_W=ci95([x['dP_W'] for x in bench_rows]),
        bench_dI_mA=ci95([x['dI_mA'] for x in bench_rows]),
        bench_dI_codes=ci95([x.get('dI_codes') for x in bench_rows]),
        overhead_dP_W=ci95([x['dP_W'] for x in over_rows]),
        overhead_incremental_J_per_iteration=ci95([x['incremental_J_per_iter'] for x in over_rows]),
        idle_power_W=ci95([x['p_idle_W'] for x in bench_rows]),
        bench_power_W=ci95([x['p_window_W'] for x in bench_rows]),
        cpu_hz_estimate=ci95(clocks),
        diagnostics=dict(
            lag1_autocorrelation_incremental=lag1(inc_series),
            trend_incremental_per_cycle=ols(list(range(len(inc_series))), inc_series),
            carryover_idle_after_minus_before_W=ci95([x['p_idle_after_W'] - x['p_idle_before_W'] for x in bench_rows]),
            bench_sample_residuals=[w.get('sample_residual') for w in windows if w['kind'] == 'BENCH'],
            per_cycle_incremental_J=inc_series))
    return dict(valid=not problems, problems=problems, assumed_volts=volts, guard_s=guard_s,
                scope='board 5V input downstream of JP2 (whole board minus ST-LINK), not core/NPU',
                repeatability_only=True, windows=windows, bench=bench_rows, overhead=over_rows,
                summary=summary, counter_gaps=int(len(gaps)), samples=int(len(words)))


def main(argv=None):
    import argparse
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ppk2_session
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--segment', type=Path, required=True)
    ap.add_argument('--session-json', type=Path, required=True)
    ap.add_argument('--table-json', type=Path, required=True, help='{"params":..,"windows":[..],"expected":..}')
    ap.add_argument('--volts', type=float, default=5.0)
    a = ap.parse_args(argv)
    meta = json.loads(a.session_json.read_text())['metadata']
    conv = ppk2_session.Converter(meta, a.volts)
    t = json.loads(a.table_json.read_text())
    res = analyze_schedule(load_words(a.segment), lambda w: conv.ua(w)[0], t['windows'], t['params'],
                           a.volts, expected=t.get('expected'), per_code_mA=code_mA(conv.c))
    print(json.dumps(res, indent=1))
    return 0 if res['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
