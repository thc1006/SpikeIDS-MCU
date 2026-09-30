"""Full-sequence comparison diag_esp_01 (D0 on GPIO4) vs attrib_nod0_01 (D0 detached).
The no-D0 run has no marker record, so every diag D0 HIGH run is mapped onto it
(offset from the parity-end step), with the residual alignment measured at BENCH
edges. Identical simple estimators are applied to both runs."""
import json
import os
import sys
import numpy as np

sys.path.insert(0, '/home/thc1006/dev/SpikeIDS-MCU/tools/ppk2_energy')
import ppk2_session  # noqa: E402

D = os.path.dirname(os.path.abspath(__file__))
R = '/home/thc1006/dev/SpikeIDS-MCU/results/power_esp32s3_20260930/ppk_esp2'
ref = json.load(open(f'{D}/diag_reference.json'))
al = json.load(open(f'{D}/attrib_nod0_01_align.json'))
sess = json.load(open(f'{R}/session.json'))
conv = ppk2_session.Converter(sess['metadata'], 5.0)
ev = [json.loads(x) for x in open(f'{R}/events.jsonl') if x.strip()]


def load(label):
    st = [e for e in ev if e['kind'] == 'segment_start' and e['label'] == label][-1]
    sp = [e for e in ev if e['kind'] == 'segment_stop' and e['label'] == label][-1]
    on = [e for e in ev if e.get('name') == 'output_on' and st['sample_index'] <= e['sample_index'] <= sp['sample_index']][0]
    w = np.fromfile(f"{R}/{st['path']}", dtype='<u4')
    off = on['sample_index'] - st['sample_index']
    return conv.ua(w)[0][off:] / 1000.0, w[off:]      # mA from ON, frames from ON


Id, wd = load('diag_esp_01')
In, wn = load('attrib_nod0_01')
delta = al['delta_ms'] * 100                            # samples
runs = [tuple(r) for r in ref['runs_after_on']]

# D0 during boot in the diag (frames from ON to the first marker drive): bit 24 = D0
bits = (wd[:200_000] >> 24) & 0xFF
pw = np.nonzero((bits & 0xFE) == 0)[0]
p0 = int(pw[0]) if len(pw) else None
hi = np.nonzero(bits[p0:] & 1)[0] if p0 is not None else []
print(f'diag boot: logic powered at {p0 / 100 if p0 is not None else None} ms after ON; D0 HIGH samples in the first 2 s after that: '
      f'{len(hi)} (first/last at {hi[0] / 100 if len(hi) else None} / {hi[-1] / 100 if len(hi) else None} ms)')


def edge_fit(x, s, half=3000):
    """Step location (samples) near s in 10-sample (0.1 ms) bins."""
    a = x[s - half: s + half]
    b = a[: len(a) // 10 * 10].reshape(-1, 10).mean(axis=1)
    c = np.cumsum(np.r_[0, b]); c2 = np.cumsum(np.r_[0, b * b]); n = len(b); best = None
    for k in range(20, n - 20):
        a1, a2 = c[k], c[n] - c[k]
        sse = c2[n] - a1 * a1 / k - a2 * a2 / (n - k)
        if best is None or sse < best[0]:
            best = (sse, k)
    return s - half + best[1] * 10


rows = []
for name, sc in ref['schedules'].items():
    s0, s1 = sc['slice_after_on']
    sr = [r for r in runs if s0 <= r[0] < s1]
    benches = sr[3::2][: len(sc['bench'])] if len(sr) >= 23 else []
    # schedule layout: 3 preamble pulses then 10 x [IDLE, BENCH(HIGH), IDLE, OVERHEAD(HIGH)]
    for j, ((a, b), meta) in enumerate(zip(benches, sc['bench'])):
        ra = edge_fit(In, a + delta); rb = edge_fit(In, b + delta)
        resid = ((ra - (a + delta)) / 100, (rb - (b + delta)) / 100)
        n_it = meta['iterations']
        g_d = 5.0 * Id[a:b].sum() * 1e-5 / 1e3 / n_it          # J per inference (mA*s -> A*s)
        g_n = 5.0 * In[a + delta:b + delta].sum() * 1e-5 / 1e3 / n_it
        idle_d = 0.5 * (Id[a - 90_000:a - 10_000].mean() + Id[b + 10_000:b + 90_000].mean())
        idle_n = 0.5 * (In[a + delta - 90_000:a + delta - 10_000].mean() + In[b + delta + 10_000:b + delta + 90_000].mean())
        rows.append(dict(sched=name, j=j, n=n_it, resid_ms=resid, gross_d=g_d, gross_n=g_n,
                         bench_d=Id[a:b].mean(), bench_n=In[a + delta:b + delta].mean(), idle_d=idle_d, idle_n=idle_n))

res = np.array([r['resid_ms'] for r in rows])
print(f'{len(rows)} BENCH windows mapped; alignment residual at edges: median {np.median(res):+.2f} ms, max |.| {np.abs(res).max():.2f} ms')
for name in ref['schedules']:
    rr = [r for r in rows if r['sched'] == name]
    gd = np.mean([r['gross_d'] for r in rr]); gn = np.mean([r['gross_n'] for r in rr])
    print(f"{name:22s} gross/inf diag {gd * 1e3:.4f} mJ | no-D0 {gn * 1e3:.4f} mJ ({(gn / gd - 1) * 100:+.2f} %) | "
          f"BENCH {np.mean([r['bench_d'] for r in rr]):.3f}/{np.mean([r['bench_n'] for r in rr]):.3f} mA | "
          f"IDLE {np.mean([r['idle_d'] for r in rr]):.3f}/{np.mean([r['idle_n'] for r in rr]):.3f} mA | "
          f"BENCH-IDLE {np.mean([r['bench_d'] - r['idle_d'] for r in rr]):+.3f}/{np.mean([r['bench_n'] - r['idle_n'] for r in rr]):+.3f} mA")
rep = [r for r in rows if 'repeat' in r['sched']]
d = np.array([r['bench_n'] - r['bench_d'] for r in rep])
print(f'repeat schedules: no-D0 minus diag BENCH current {d.mean():+.4f} mA (sd {d.std(ddof=1):.4f}, n={len(d)}); '
      f'IDLE {np.mean([r["idle_n"] - r["idle_d"] for r in rep]):+.4f} mA')
