"""Attribution of the diag_esp_01 sham artifact: the same EM01 sequence with the
PPK2 D0 lead detached from GPIO4. Marker edges are predicted from diag_esp_01
(aligned on the parity-end current step), and the sham HIGH/LOW current difference
is computed identically for both runs (plus a quadrature-shifted null)."""
import json
import os
import sys
import numpy as np

sys.path.insert(0, '/home/thc1006/dev/SpikeIDS-MCU/tools/ppk2_energy')
import ppk2_session  # noqa: E402

D = os.path.dirname(os.path.abspath(__file__))
REPO = '/home/thc1006/dev/SpikeIDS-MCU'
R = f'{REPO}/results/power_esp32s3_20260930/ppk_esp2'
label = sys.argv[1] if len(sys.argv) > 1 else 'attrib_nod0_01'
ref = json.load(open(f'{D}/diag_reference.json'))
sess = json.load(open(f'{R}/session.json'))
conv = ppk2_session.Converter(sess['metadata'], 5.0)
ev = [json.loads(x) for x in open(f'{R}/events.jsonl') if x.strip()]
st = [e for e in ev if e['kind'] == 'segment_start' and e['label'] == label][-1]
on = [e for e in ev if e.get('name') == 'output_on' and e['sample_index'] >= st['sample_index']][0]
raw = open(f"{R}/{st['path']}", 'rb').read()
w = np.frombuffer(raw[: len(raw) // 4 * 4], dtype='<u4')
on_off = on['sample_index'] - st['sample_index']
I = conv.ua(w)[0] / 1000.0
ms = I[on_off: on_off + (len(I) - on_off) // 100 * 100].reshape(-1, 100).mean(axis=1)   # 1 ms bins from ON
dg = np.load(f'{D}/diag_I_1ms.npy')


def step_fit(x, lo, hi, guard=5):
    c = np.cumsum(np.r_[0, x]); c2 = np.cumsum(np.r_[0, x * x]); best = None
    for k in range(lo + guard, hi - guard):
        a1, a2 = c[k] - c[lo], c[hi] - c[k]
        s = (c2[hi] - c2[lo]) - a1 * a1 / (k - lo) - a2 * a2 / (hi - k)
        if best is None or s < best[0]:
            best = (s, k, a1 / (k - lo), a2 / (hi - k))
    return best


pe = ref['parity_end_step_after_on'] // 100
_, k_new, m1n, m2n = step_fit(ms, pe - 1000, pe + 1000)
_, k_dg, m1d, m2d = step_fit(dg, pe - 1000, pe + 1000)
delta = k_new - k_dg          # ms
print(f'parity-end step: diag {k_dg / 1e3:.4f} s ({m1d:.3f}->{m2d:.3f} mA), no-D0 {k_new / 1e3:.4f} s '
      f'({m1n:.3f}->{m2n:.3f} mA); alignment offset {delta} ms')

runs = [(x // 100, y // 100) for x, y in ref['runs_after_on']]
sham = [runs[i] for i in ref['phase_runs']['sham']]
wiring = [runs[i] for i in ref['phase_runs']['wiring']]
G = 50   # ms excluded next to every edge


def sham_dI(x, runs_ms, shift=0, guard=G):
    out = []
    for j, (a, b) in enumerate(runs_ms):
        a, b = a + shift, b + shift
        nxt = runs_ms[j + 1][0] + shift if j + 1 < len(runs_ms) else b + (b - a)
        prv_end = runs_ms[j - 1][1] + shift if j > 0 else a - (b - a)
        hi = x[a + guard: b - guard].mean()
        lo_after = x[b + guard: nxt - guard].mean()
        lo_before = x[prv_end + guard: a - guard].mean()
        out.append(hi - 0.5 * (lo_after + lo_before))
    return np.array(out)


def summ(v):
    return f'mean {v.mean():+.4f} mA, sd {v.std(ddof=1):.4f}, 95% CI +-{1.96 * v.std(ddof=1) / np.sqrt(len(v)):.4f} (n={len(v)})'


if len(ms) < sham[-1][1] + delta + 1100:
    print(f'capture too short: {len(ms) / 1e3:.1f} s after ON'); sys.exit(1)
sham_new = [(a + delta, b + delta) for a, b in sham]
print('SHAM dI  diag (D0 on GPIO4):   ', summ(sham_dI(dg, sham)))
print('SHAM dI  no-D0 (D0 detached):  ', summ(sham_dI(ms, sham_new)))
print('null (500 ms shift) diag:      ', summ(sham_dI(dg, sham, shift=500, guard=100)))
print('null (500 ms shift) no-D0:     ', summ(sham_dI(ms, sham_new, shift=500, guard=100)))
# absolute levels (runs are separate power-ons: between-run offsets are possible)
hi_d = np.concatenate([dg[a + G: b - G] for a, b in sham]); lo_d = np.concatenate([dg[b + G: b + 1000 - G] for a, b in sham])
hi_n = np.concatenate([ms[a + G: b - G] for a, b in sham_new]); lo_n = np.concatenate([ms[b + G: b + 1000 - G] for a, b in sham_new])
print(f'levels diag: sham-HIGH {hi_d.mean():.3f}  sham-LOW {lo_d.mean():.3f} | no-D0: same slots {hi_n.mean():.3f} / {lo_n.mean():.3f} mA')
print(f'parity (last 10 s, marker LOW in diag): diag {dg[k_dg - 10000:k_dg - 50].mean():.3f}  no-D0 {ms[k_new - 10000:k_new - 50].mean():.3f} mA')
print(f'gap after parity (1.9 s, marker LOW in diag): diag {dg[k_dg + 50:k_dg + 1950].mean():.3f}  no-D0 {ms[k_new + 50:k_new + 1950].mean():.3f} mA')
wd = [dg[a + 10: b - 10].mean() - 0.5 * (dg[a - 90: a - 10].mean() + dg[b + 10: b + 90].mean()) for a, b in wiring]
wn = [ms[a + delta + 10: b + delta - 10].mean() - 0.5 * (ms[a + delta - 90: a + delta - 10].mean() + ms[b + delta + 10: b + delta + 90].mean()) for a, b in wiring]
print('wiring pulses dI (mA) diag:', np.round(wd, 3), '| no-D0:', np.round(wn, 3))
json.dump(dict(delta_ms=int(delta), k_new=int(k_new), k_diag=int(k_dg), on_offset=int(on_off)), open(f'{D}/{label}_align.json', 'w'))
