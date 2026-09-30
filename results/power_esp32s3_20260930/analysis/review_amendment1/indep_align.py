"""Reviewer pass 2: alignment of attrib_nod0_01 onto diag_esp_01 at 0.1 ms resolution
(own step fit + own cross-correlation, lag window chosen to avoid the 24.85 ms
inference-period alias), then the sham estimates, paired D0-share, quadrature null,
absolute levels, BENCH-edge residuals and sham-edge step profiles. Self-contained
(re-implements conversion and run finding; no repository analysis imports)."""
import json
import sys
import numpy as np
from scipy import stats

R = '/home/thc1006/dev/SpikeIDS-MCU/results/power_esp32s3_20260930/ppk_esp2'
FS = 100_000
G = 5000
sess = json.load(open(f'{R}/session.json'))
md = sess['metadata']
C = {k: np.array([float(md[f'{k}{i}']) for i in range(5)]) for k in ('R', 'GS', 'GI', 'O', 'S', 'I', 'UG')}
ev = [json.loads(x) for x in open(f'{R}/events.jsonl') if x.strip()]


def mA(w):
    w = np.asarray(w, dtype=np.uint32)
    adc = (w & 0x3FFF).astype(np.float64) * 4.0
    r = ((w >> 14) & 7).astype(np.int64)
    x = (adc - C['O'][r]) * ((1.8 / 163840.0) / C['R'][r])
    return C['UG'][r] * (x * (C['GS'][r] * x + C['GI'][r]) + (C['S'][r] * 5.0 + C['I'][r])) * 1e3


def seg(label):
    st = [e for e in ev if e['kind'] == 'segment_start' and e['label'] == label][-1]
    sp = [e for e in ev if e['kind'] == 'segment_stop' and e['label'] == label][-1]
    on = [e for e in ev if e.get('name') == 'output_on' and st['sample_index'] <= e['sample_index'] <= sp['sample_index']][0]
    return np.memmap(f"{R}/{st['path']}", dtype='<u4', mode='r'), on['sample_index'] - st['sample_index']


def runs_of(b, glitch=3):
    d = np.diff(np.concatenate(([0], b.astype(np.int8), [0])))
    out = []
    for a, e in zip(np.nonzero(d == 1)[0].tolist(), np.nonzero(d == -1)[0].tolist()):
        if out and a - out[-1][1] <= glitch:
            out[-1] = (out[-1][0], e)
        else:
            out.append((a, e))
    return [(a, e) for a, e in out if e - a > glitch]


def bins(w, a, b, n=10):
    x = mA(w[a:b]); m = len(x) // n * n
    return x[:m].reshape(-1, n).mean(axis=1)


def step_fit(x):
    c = np.cumsum(np.r_[0, x]); c2 = np.cumsum(np.r_[0, x * x]); n = len(x); best = None
    for k in range(20, n - 20):
        a1, a2 = c[k], c[n] - c[k]
        s = c2[n] - a1 * a1 / k - a2 * a2 / (n - k)
        if best is None or s < best[0]:
            best = (s, k, a1 / k, a2 / (n - k))
    return best


def ci_t(v):
    v = np.asarray(v, float)
    h = stats.t.ppf(0.975, len(v) - 1) * v.std(ddof=1) / np.sqrt(len(v))
    return float(v.mean()), [float(v.mean() - h), float(v.mean() + h)]


wd, on_d = seg('diag_esp_01')
wn, on_n = seg('attrib_nod0_01')
bits = (np.asarray(wd) >> 24).astype(np.uint8)
d0 = ((bits & 1) == 1) & ((bits & 0xFE) == 0)
d0[:on_d + int(1.5 * FS)] = False
runs = runs_of(d0)
del bits, d0
res = {}
# ---- parity-end step, 0.1 ms bins, +-1 s around 27.6 s after ON ---------------------
c_d = on_d + 2_759_800
_, kd, m1d, m2d = step_fit(bins(wd, c_d - FS, c_d + FS))
t_d = c_d - FS + kd * 10                      # sample index in diag
c_n = on_n + (t_d - on_d)
_, kn, m1n, m2n = step_fit(bins(wn, c_n - FS, c_n + FS))
t_n = c_n - FS + kn * 10
off_step = (t_n - on_n) - (t_d - on_d)        # samples: attrib event time - diag event time (both from ON)
res['parity_end_step'] = dict(diag_after_on_s=(t_d - on_d) / FS, attrib_after_on_s=(t_n - on_n) / FS,
                              diag_levels_mA=[m1d, m2d], attrib_levels_mA=[m1n, m2n], offset_ms=off_step / 100)
# ---- xcorr at 0.1 ms, lags within +-10 ms (inference period 24.85 ms -> no alias) ----
xd = bins(wd, t_d - 50_000, t_d + 50_000); xs = xd - xd.mean()
best = None
for L in range(-100, 101):
    y = bins(wn, on_n + (t_d - on_d) - 50_000 + L * 10, on_n + (t_d - on_d) + 50_000 + L * 10); ys = y - y.mean()
    c = float((xs * ys).sum() / np.sqrt((xs * xs).sum() * (ys * ys).sum()))
    if best is None or c > best[1]:
        best = (L, c)
res['xcorr_parity_end_lag_0p1ms'] = dict(lag_ms=best[0] / 10, corr=best[1])
shift = (on_n - on_d) + off_step              # diag sample -> attrib sample
res['shift_used_ms_rel_on'] = off_step / 100

# ---- BENCH-edge residuals (all 5 schedules) -------------------------------------------
# schedule runs: after 25 (wiring+sham) runs, each schedule = 3 preamble + 10 x (BENCH, OVERHEAD)
resid = []
k = 25
for s in range(5):
    sched = runs[k:k + 23]; k += 23
    for j in range(10):
        a, b = sched[3 + 2 * j]
        for e in (a, b):
            x = bins(wn, e + shift - 3000, e + shift + 3000)   # +-30 ms at 0.1 ms
            _, kk, _, _ = step_fit(x)
            resid.append(((e + shift - 3000 + kk * 10) - (e + shift)) / 100)
resid = np.array(resid)
res['bench_edge_residual_ms'] = dict(n=len(resid), median=float(np.median(resid)), max_abs=float(np.abs(resid).max()),
                                     p90_abs=float(np.percentile(np.abs(resid), 90)),
                                     per_schedule_median=[float(np.median(resid[20 * i:20 * i + 20])) for i in range(5)])
sham = runs[5:25]
width = int(np.median([b - a for a, b in sham]))


def span(w, a, b):
    return float(mA(w[a:b]).mean())


def rows(w, sh, sft=0, guard=G):
    out = []
    for i, (a, b) in enumerate(sh):
        a, b = a + sft, b + sft
        hi = span(w, a + guard, b - guard)
        lows = [span(w, sh[i - 1][1] + sft + guard, a - guard)] if i else []
        nxt = sh[i + 1][0] + sft if i + 1 < len(sh) else b + width
        lows.append(span(w, b + guard, nxt - guard))
        out.append((hi, float(np.mean(lows))))
    return np.array(out)


rd = rows(wd, sham)
rn = rows(wn, [(a + shift, b + shift) for a, b in sham])
res['diag_dI'] = ci_t(rd[:, 0] - rd[:, 1])
res['attrib_dI'] = ci_t(rn[:, 0] - rn[:, 1])
res['paired_D0_share(diag-attrib)'] = ci_t((rd[:, 0] - rd[:, 1]) - (rn[:, 0] - rn[:, 1]))
res['welch_p'] = float(stats.ttest_ind(rd[:, 0] - rd[:, 1], rn[:, 0] - rn[:, 1], equal_var=False).pvalue)
res['levels'] = dict(diag_hi=float(rd[:, 0].mean()), diag_lo=float(rd[:, 1].mean()),
                     attrib_hi=float(rn[:, 0].mean()), attrib_lo=float(rn[:, 1].mean()),
                     offset_hi=float(rn[:, 0].mean() - rd[:, 0].mean()), offset_lo=float(rn[:, 1].mean() - rd[:, 1].mean()))
for nm, w, sh in (('diag', wd, sham), ('attrib', wn, [(a + shift, b + shift) for a, b in sham])):
    q = rows(w, sh, sft=50_000, guard=10_000)
    res[f'{nm}_quadrature_null'] = ci_t(q[:, 0] - q[:, 1])
# offsets in other phases (parity last 10 s; BENCH / OVERHEAD / IDLE of the repeat schedules)
res['offset_parity_last10s_mA'] = span(wn, t_n - 10 * FS, t_n - 5000) - span(wd, t_d - 10 * FS, t_d - 5000)
bo, oo, io = [], [], []
k = 25
for s in range(3):
    sched = runs[k:k + 23]; k += 23
    for j in range(10):
        (a, b), (c, e) = sched[3 + 2 * j], sched[4 + 2 * j]
        bo.append(span(wn, a + shift + G, b + shift - G) - span(wd, a + G, b - G))
        oo.append(span(wn, c + shift + G, e + shift - G) - span(wd, c + G, e - G))
        io.append(span(wn, b + shift + G, c + shift - G) - span(wd, b + G, c - G))
res['offset_repeat_BENCH_mA'] = ci_t(bo); res['offset_repeat_OVERHEAD_mA'] = ci_t(oo); res['offset_repeat_IDLE_mA'] = ci_t(io)


# ---- sham-edge step profile, 10 us resolution ---------------------------------------
def prof(w, edges):
    acc = np.zeros(1200)
    for e in edges:
        acc += mA(w[e - 200:e + 1000])
    acc /= len(edges)
    base = acc[:180].mean()
    top = float(np.mean([span(w, e + 1000, e + 5000) for e in edges]))
    f = (acc - base) / (top - base)
    q = lambda a, b: round(float(f[200 + a:200 + b].mean()), 3)
    return dict(step_mA=round(top - base, 4), frac={'-0.2..0': q(-20, 0), '0..0.02ms': q(0, 2), '0.02..0.05': q(2, 5),
                                                  '0.05..0.1': q(5, 10), '0.1..0.2': q(10, 20), '0.2..0.3': q(20, 30),
                                                  '0.3..0.5': q(30, 50), '0.5..1': q(50, 100), '1..2': q(100, 200),
                                                  '2..5': q(200, 500), '5..8': q(500, 800), '8..10': q(800, 1000)})


rises = [a for a, b in sham]; falls = [b for a, b in sham]
res['profile_diag_rise'] = prof(wd, rises); res['profile_diag_fall'] = prof(wd, falls)
res['profile_attrib_rise'] = prof(wn, [e + shift for e in rises]); res['profile_attrib_fall'] = prof(wn, [e + shift for e in falls])
# same profile on the 100 BENCH edges of diag (marker + load change)
json.dump(res, open(sys.argv[1], 'w'), indent=1)
print(json.dumps(res, indent=1))
