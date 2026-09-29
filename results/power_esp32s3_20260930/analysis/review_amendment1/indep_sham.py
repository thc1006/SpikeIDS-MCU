"""Independent re-computation (reviewer, 2026-09-30) of the Amendment 1 sham /
attribution numbers from the raw PPK2 frames. Does NOT import any repository
analysis code: own Nordic conversion, own D0 run finder, own alignment
(cross-correlation, not the parity-end step fit). Read-only on all inputs.
"""
import json
import sys
import numpy as np
from scipy import stats

R = '/home/thc1006/dev/SpikeIDS-MCU/results/power_esp32s3_20260930/ppk_esp2'
FS = 100_000
G = 5000  # 50 ms guard (registered guard_s = 0.05)

sess = json.load(open(f'{R}/session.json'))
md = sess['metadata']
C = {k: np.array([float(md[f'{k}{i}']) for i in range(5)]) for k in ('R', 'GS', 'GI', 'O', 'S', 'I', 'UG')}
V = 5.0
ev = [json.loads(x) for x in open(f'{R}/events.jsonl') if x.strip()]


def mA(w):
    """Nordic PPK2 formula (pc-nrfconnect-ppk / IRNAS ppk2-api), written here from scratch."""
    w = np.asarray(w, dtype=np.uint32)
    adc = (w & 0x3FFF).astype(np.float64) * 4.0
    r = ((w >> 14) & 7).astype(np.int64)
    if (r > 4).any():
        raise ValueError('invalid range code')
    x = (adc - C['O'][r]) * ((1.8 / 163840.0) / C['R'][r])
    amps = C['UG'][r] * (x * (C['GS'][r] * x + C['GI'][r]) + (C['S'][r] * V + C['I'][r]))
    return amps * 1e3


def seg_info(label):
    st = [e for e in ev if e['kind'] == 'segment_start' and e['label'] == label][-1]
    sp = [e for e in ev if e['kind'] == 'segment_stop' and e['label'] == label][-1]
    on = [e for e in ev if e.get('name') == 'output_on' and st['sample_index'] <= e['sample_index'] <= sp['sample_index']][0]
    w = np.memmap(f"{R}/{st['path']}", dtype='<u4', mode='r')
    return w, on['sample_index'] - st['sample_index']


def runs_of(b, glitch=3):
    d = np.diff(np.concatenate(([0], b.astype(np.int8), [0])))
    ups, dns = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
    out = []
    for a, e in zip(ups.tolist(), dns.tolist()):
        if out and a - out[-1][1] <= glitch:
            out[-1] = (out[-1][0], e)
        else:
            out.append((a, e))
    return [(a, e) for a, e in out if e - a > glitch]


def span_mean(w, a, b):
    return float(mA(w[a:b]).mean())


def ci_t(v):
    v = np.asarray(v, float)
    h = stats.t.ppf(0.975, len(v) - 1) * v.std(ddof=1) / np.sqrt(len(v))
    return v.mean(), h


def ms_trace(w, start, n_ms):
    out = np.empty(n_ms)
    step = 100_000  # 1 s chunks
    for k in range(0, n_ms, 1000):
        a = start + k * 100
        m = min(1000, n_ms - k)
        out[k:k + m] = mA(w[a:a + m * 100]).reshape(m, 100).mean(axis=1)
    return out


res = {}
wd, on_d = seg_info('diag_esp_01')
wn, on_n = seg_info('attrib_nod0_01')
bits_d = (np.asarray(wd) >> 24).astype(np.uint8)
pw_d = (bits_d & 0xFE) == 0
d0 = ((bits_d & 1) == 1) & pw_d
mask = on_d + int(1.5 * FS)
d0[:mask] = False
runs = runs_of(d0)
res['diag_runs_total'] = len(runs)
wid = [(b - a) / FS for a, b in runs[:25]]
res['wiring_widths_s'] = wid[:5]
res['sham_widths_s_minmax'] = [min(wid[5:25]), max(wid[5:25])]
res['first_wiring_rise_after_on_s'] = (runs[0][0] - on_d) / FS

# ---- boot: logic power-up, D0 while GPIO4 undriven --------------------------------
pw_idx = np.nonzero(pw_d[on_d:on_d + 300_000])[0]
p0 = on_d + int(pw_idx[0])
hi_boot = np.nonzero(((bits_d[p0:runs[0][0]] & 1) == 1) & pw_d[p0:runs[0][0]])[0]
res['diag_logic_powered_after_on_ms'] = (p0 - on_d) / 100
res['diag_d0_high_samples_between_logic_powerup_and_first_wiring'] = int(len(hi_boot))
res['diag_d0_high_boot_first_last_ms_after_on'] = ([(p0 + int(hi_boot[0]) - on_d) / 100, (p0 + int(hi_boot[-1]) - on_d) / 100]
                                                   if len(hi_boot) else None)
# unpowered (0xFF) frames after the mask, before DONE
res['diag_unpowered_frames_after_mask'] = int((~pw_d[mask:]).sum())
del d0

# ---- registered-equivalent sham estimator on diag ----------------------------------
sham = runs[5:25]
width = int(np.median([b - a for a, b in sham]))


def sham_rows(w, sh, shift=0, guard=G, first_before=False):
    rows = []
    for k, (a, b) in enumerate(sh):
        a, b = a + shift, b + shift
        hi = span_mean(w, a + guard, b - guard)
        lows = []
        if k > 0:
            lows.append(span_mean(w, sh[k - 1][1] + shift + guard, a - guard))
        elif first_before:
            lows.append(span_mean(w, a - width + guard, a - guard))
        nxt = sh[k + 1][0] + shift if k + 1 < len(sh) else b + width
        lows.append(span_mean(w, b + guard, nxt - guard))
        rows.append(dict(hi=hi, lo=float(np.mean(lows)), dI=hi - float(np.mean(lows))))
    return rows


rd = sham_rows(wd, sham)
m, h = ci_t([r['dI'] for r in rd])
res['diag_sham_dI_registered_equiv'] = dict(mean=m, ci95=[m - h, m + h], n=len(rd))
reg = json.load(open(f'{R}/diag_esp_01_analysis.json'))['phases']['sham']['windows']
res['diag_sham_max_abs_diff_vs_pipeline_per_window_mA'] = float(max(abs(a['dI'] - b['dI_mA']) for a, b in zip(rd, reg)))

# ---- attribution: align by cross-correlation of 1 ms traces (from ON) --------------
n_ms = 120_000
td = ms_trace(wd, on_d, n_ms)
tn = ms_trace(wn, on_n, n_ms)


def xcorr_lag(x, y, lo, hi, maxlag=200):
    """lag L (ms) maximising corr(x[t], y[t+L]) over t in [lo, hi)."""
    xs = x[lo:hi] - x[lo:hi].mean()
    best = None
    for L in range(-maxlag, maxlag + 1):
        ys = y[lo + L:hi + L] - y[lo + L:hi + L].mean()
        c = float((xs * ys).sum() / np.sqrt((xs * xs).sum() * (ys * ys).sum()))
        if best is None or c > best[1]:
            best = (L, c)
    return best


# parity (constant load) ends ~2 s before the first wiring pulse: use 20..40 s after ON
lag_par = xcorr_lag(td, tn, 20_000, 40_000)
res['xcorr_lag_ms_parity_region'] = lag_par
# region containing sham + calibration + schedule-0 start (sham itself has no D0 in attrib, but
# the marker-load step is still present in attrib): 30..90 s after ON
lag_sh = xcorr_lag(td, tn, 30_000, 90_000)
res['xcorr_lag_ms_30_90s'] = lag_sh
# later region: schedules 90..119 s
lag_late = xcorr_lag(td, tn, 90_000, 119_000)
res['xcorr_lag_ms_90_119s'] = lag_late
L = lag_par[0]
shift_samples = (on_n - on_d) + L * 100   # diag sample index -> attrib sample index

rn = sham_rows(wn, [(a + shift_samples, b + shift_samples) for a, b in sham])
m2, h2 = ci_t([r['dI'] for r in rn])
res['attrib_sham_dI'] = dict(mean=m2, ci95=[m2 - h2, m2 + h2], n=len(rn), lag_ms=L)
diff = np.array([a['dI'] - b['dI'] for a, b in zip(rd, rn)])   # diag - attrib = D0-lead share
md_, hd_ = ci_t(diff)
res['paired_diag_minus_attrib_dI'] = dict(mean=md_, ci95=[md_ - hd_, md_ + hd_], n=len(diff))
# unpaired (Welch) for completeness
tt = stats.ttest_ind([r['dI'] for r in rd], [r['dI'] for r in rn], equal_var=False)
res['welch_p_diag_vs_attrib'] = float(tt.pvalue)
# robustness of the attrib estimate to the alignment lag
res['attrib_dI_vs_lag'] = {int(l): float(np.mean([r['dI'] for r in sham_rows(
    wn, [(a + (on_n - on_d) + l * 100, b + (on_n - on_d) + l * 100) for a, b in sham])]))
    for l in (L - 20, L - 5, L, L + 5, L + 20)}
# quadrature null (500 ms shift, 100 ms guard) on both
for name, w, sh in (('diag', wd, sham), ('attrib', wn, [(a + shift_samples, b + shift_samples) for a, b in sham])):
    rr = sham_rows(w, sh, shift=50_000, guard=10_000)
    mq, hq = ci_t([r['dI'] for r in rr])
    res[f'{name}_quadrature_null'] = dict(mean=mq, ci95=[mq - hq, mq + hq])
# levels
res['levels_mA'] = dict(diag_hi=float(np.mean([r['hi'] for r in rd])), diag_lo=float(np.mean([r['lo'] for r in rd])),
                        attrib_hi=float(np.mean([r['hi'] for r in rn])), attrib_lo=float(np.mean([r['lo'] for r in rn])))

# ---- step profile at the 40 sham edges (10 us resolution), diag and attrib -------
def edge_profile(w, edges, sign, pre=2000, post=5000):
    """Average current around the edges; step fraction in bins relative to the edge.
    base = [-20, -1] ms, top = [+5 ms, +50 ms] (read separately)."""
    acc = np.zeros(pre + post)
    for e in edges:
        acc += sign * mA(w[e - pre:e + post])
    acc /= len(edges)
    top = float(np.mean([sign * span_mean(w, e + 500, e + 5000) for e in edges]))
    base = acc[:pre - 100].mean()
    frac = lambda a, b: float((acc[pre + a:pre + b].mean() - base) / (top - base))
    bins = {'-1..-0.1ms': frac(-100, -10), '-0.1..0ms': frac(-10, 0), '0..0.05ms': frac(0, 5),
            '0.05..0.1ms': frac(5, 10), '0.1..0.2ms': frac(10, 20), '0.2..0.5ms': frac(20, 50),
            '0.5..1ms': frac(50, 100), '1..5ms': frac(100, 500), '5..50ms': frac(500, 5000)}
    return dict(step_mA=float(top - base), frac=bins)


rises = [a for a, b in sham]; falls = [b for a, b in sham]
res['edge_profile_diag_rise(dI_hi-lo)'] = edge_profile(wd, rises, 1)
res['edge_profile_diag_fall(dI_lo-hi)'] = edge_profile(wd, falls, 1)
res['edge_profile_attrib_rise'] = edge_profile(wn, [e + shift_samples for e in rises], 1)
res['edge_profile_attrib_fall'] = edge_profile(wn, [e + shift_samples for e in falls], 1)

# ---- ranges / ADC rail / current band in diag ---------------------------------------
def chunked_idx(w, pred, start=0, step=5_000_000):
    out = []
    for a in range(start, len(w), step):
        x = np.asarray(w[a:a + step])
        out.append(np.nonzero(pred(x))[0] + a)
    return np.concatenate(out) if out else np.zeros(0, int)


non4 = chunked_idx(wd, lambda x: ((x >> 14) & 7) != 4, start=on_d) - on_d
res['diag_non_R4_frames_after_on'] = int(len(non4))
res['diag_non_R4_first_last_after_on_s'] = [float(non4[0] / FS), float(non4[-1] / FS)] if len(non4) else None
res['diag_non_R4_frames_after_0p2s'] = int((non4 > 20_000).sum())
res['diag_non_R4_frames_after_mask'] = int((non4 > int(1.5 * FS)).sum())
rail = chunked_idx(wd, lambda x: (x & 0x3FFF) == 16383)
res['diag_adc_upper_rail_frames[idx,ms_after_on,range]'] = [[int(i), (int(i) - on_d) / 100.0, int((wd[i] >> 14) & 7)] for i in rail]
railn = chunked_idx(wn, lambda x: (x & 0x3FFF) == 16383)
res['attrib_adc_upper_rail_frames[idx,ms_after_on,range]'] = [[int(i), (int(i) - on_n) / 100.0, int((wn[i] >> 14) & 7)] for i in railn]
non4n = chunked_idx(wn, lambda x: ((x >> 14) & 7) != 4, start=on_n) - on_n
res['attrib_non_R4_frames_after_on'] = int(len(non4n))
res['attrib_non_R4_first_last_after_on_s'] = [float(non4n[0] / FS), float(non4n[-1] / FS)] if len(non4n) else None
# 1 s means from ON+1.5 s to the first telemetry sync (use runs[140])
t_end = runs[140][0] if len(runs) > 140 else len(wd)
secs = [(span_mean(wd, a, a + FS)) for a in range(mask, t_end - FS, FS)]
res['diag_1s_mean_mA_min_max'] = [float(min(secs)), float(max(secs))]
json.dump(res, open(sys.argv[1] if len(sys.argv) > 1 else '/dev/stdout', 'w'), indent=1, default=float)
print(json.dumps(res, indent=1, default=float))
