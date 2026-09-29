"""Independent re-computation for diag_esp_02_01 (reviewer's own code; does not
import rm01_decode / analyze_schedule / run_sessions / ppk2_session)."""
import hashlib
import json
from pathlib import Path

import numpy as np

R = Path('/home/thc1006/dev/SpikeIDS-MCU/results/power_esp32s3_20260930')
REC = R / 'ppk_esp9'
LABEL = 'diag_esp_02_01'
FS = 100_000
G = 5_000  # 50 ms guard
V = 5.0
out = {}

ev = [json.loads(l) for l in open(REC / 'events.jsonl')]
st = next(e for e in ev if e['kind'] == 'segment_start' and e['label'] == LABEL)
sp = next(e for e in ev if e['kind'] == 'segment_stop' and e['label'] == LABEL)
on = [e for e in ev if e.get('name') == 'output_on' and st['sample_index'] <= e['sample_index'] <= sp['sample_index']]
off = [e for e in ev if e.get('name') == 'output_off' and e['sample_index'] >= st['sample_index']]
seg = REC / sp['path']

h = hashlib.sha256()
with open(seg, 'rb') as f:
    while True:
        b = f.read(1 << 24)
        if not b:
            break
        h.update(b)
out['sha256'] = h.hexdigest()
out['sha256_match_stop_event'] = h.hexdigest() == sp['sha256']

w = np.fromfile(seg, dtype='<u4')
out['frames'] = int(len(w))
out['frames_event'] = sp['frames']
out['frames_from_indices'] = sp['sample_index'] - st['sample_index']
out['n_output_on_in_segment'] = len(on)
ON = on[0]['sample_index'] - st['sample_index']
MASK = ON + int(1.5 * FS)
out['on_offset'] = ON
out['mask_end'] = MASK
out['output_off_after_stop_samples'] = off[0]['sample_index'] - sp['sample_index'] if off else None

# ---- own Nordic conversion from session.json metadata ----
meta = json.load(open(REC / 'session.json'))['metadata']
co = {p: np.array([float(meta[f'{p}{i}']) for i in range(5)]) for p in ('R', 'GS', 'GI', 'O', 'S', 'I', 'UG')}
rng = ((w >> 14) & 7).astype(np.int64)
out['range_code_gt4'] = int((rng > 4).sum())
out['bit17_set'] = int(((w >> 17) & 1).sum())
I = np.empty(len(w))  # mA
CH = 1 << 22
for s in range(0, len(w), CH):
    r = rng[s:s + CH]
    adc = (w[s:s + CH] & 0x3FFF).astype(np.float64) * 4.0
    x = (adc - co['O'][r]) * (1.8 / 163840) / co['R'][r]
    I[s:s + CH] = co['UG'][r] * (x * (co['GS'][r] * x + co['GI'][r]) + co['S'][r] * V + co['I'][r]) * 1e3
rng8 = rng.astype(np.int8)
del rng
hist = np.bincount(rng8, minlength=5).tolist()
out['range_hist'] = hist
nz3 = np.nonzero(rng8 < 4)[0]
nz3_after_on = nz3[nz3 >= ON]
out['non_R4_after_on'] = int(len(nz3_after_on))
if len(nz3_after_on):
    out['non_R4_after_on_first_last_s_after_on'] = [(int(nz3_after_on[0]) - ON) / FS, (int(nz3_after_on[-1]) - ON) / FS]
    out['non_R4_after_mask'] = int((nz3_after_on >= MASK).sum())
rail = np.nonzero((w & 0x3FFF) == 0x3FFF)[0]
out['adc_rail_frames_s_after_on'] = [(int(i) - ON) / FS for i in rail[:10]]
c = (w >> 18) & 63
gaps = np.nonzero(c[1:] != (c[:-1] + 1) % 64)[0] + 1
out['counter_gaps'] = int(len(gaps))

lb = (w >> 24).astype(np.uint8)
del w, c
d0 = (lb & 1).astype(bool)
upper = lb >> 1
out['pre_on_logic_bytes'] = np.unique(lb[:ON]).tolist()
pw = np.nonzero(upper[ON:] == 0)[0]
out['first_powered_s_after_on'] = float(pw[0] / FS) if len(pw) else None
out['unpowered_frames_after_mask'] = int((upper[MASK:] != 0).sum())
out['unpowered_frames_on_to_mask'] = int((upper[ON:MASK] != 0).sum())
# D0 between ON and mask (power-on artifact)
dm = d0[ON:MASK]
out['d0_high_frames_on_to_mask'] = int(dm.sum())
if dm.any():
    k = np.nonzero(dm)[0]
    out['d0_high_on_to_mask_first_last_ms'] = [k[0] / 100, k[-1] / 100]


def runs_of(x, off=0):
    d = np.diff(np.concatenate(([0], x.astype(np.int8), [0])))
    return [(int(a) + off, int(b) + off) for a, b in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0])]


raw = runs_of(d0[MASK:], MASK)
out['raw_d0_runs_after_mask'] = len(raw)
out['recorder_d0_rising_whole_segment'] = sp['d0_rising']
out['raw_d0_rises_whole_segment'] = int(np.sum(np.diff(d0.astype(np.int8)) == 1)) + int(d0[0])
out['short_runs_le3'] = sum(1 for a, b in raw if b - a <= 3)
out['short_lows_le3'] = sum(1 for i in range(1, len(raw)) if raw[i][0] - raw[i - 1][1] <= 3)
runs = raw
A = json.load(open(R / 'diag_esp_02_run' / f'{LABEL}_analysis.json'))
W = A['windows']
fwh = [x for x in W if x['marker_high']]
out['fw_high_windows'] = len(fwh)
out['sync_run_width_s'] = (runs[len(fwh)][1] - runs[len(fwh)][0]) / FS
tel = runs[len(fwh) + 1:-1]
out['telemetry_bit_runs'] = len(tel)
out['telemetry_bits_expected'] = A['header']['telemetry_words'] * 32 + 3 * 32  # magic + count + CRC words
out['done_run_s'] = (runs[-1][1] - runs[-1][0]) / FS
out['done_run_reaches_end'] = runs[-1][1] == len(d0)
out['segment_end_d0'] = bool(d0[-1])

# map runs <-> firmware HIGH windows; width check with CCOUNT at 240 MHz nominal
fr = []
for (a, b), x in zip(runs[:len(fwh)], fwh):
    cyc = (x['end_cycle'] - x['start_cycle']) & 0xFFFFFFFF
    fr.append(dict(a=a, b=b, kind=x['kind'], phase=x['phase'], it=x['iterations'], cyc=cyc, ck=x['checksum']))
mis = [abs((f['b'] - f['a']) / FS - f['cyc'] / 240e6) for f in fr]
out['max_run_vs_ccount_width_mismatch_ms'] = max(mis) * 1e3

# wiring
wir = [f for f in fr if f['phase'] == 0]
out['wiring_widths_s'] = [(f['b'] - f['a']) / FS for f in wir]
# sham
sh = [f for f in fr if f['phase'] == 1]
H = [I[f['a'] + G:f['b'] - G].mean() for f in sh]
L = []
for k, f in enumerate(sh):
    e = sh[k + 1]['a'] if k + 1 < len(sh) else f['b'] + FS
    L.append(I[f['b'] + G:e - G].mean())
H, L = np.array(H), np.array(L)
dA = np.array([H[0] - L[0]] + [H[k] - (L[k - 1] + L[k]) / 2 for k in range(1, 20)])
dC = np.array([H[k] - (L[k - 1] + L[k]) / 2 for k in range(1, 20)])


def tci(x):
    x = np.asarray(x)
    from scipy import stats
    m, s = x.mean(), x.std(ddof=1)
    t = stats.t.ppf(0.975, len(x) - 1)
    return dict(n=len(x), mean=float(m), sd=float(s), ci95=[float(m - t * s / np.sqrt(len(x))), float(m + t * s / np.sqrt(len(x)))])


out['sham_A_pipeline_like'] = tci(dA)
out['sham_C_interior_two_sided'] = tci(dC)
# OLS on 40 half-span means: marker + quadratic time trend
tc = []
for k, f in enumerate(sh):
    tc.append((f['a'] + f['b']) / 2 / FS)
    e = sh[k + 1]['a'] if k + 1 < len(sh) else f['b'] + FS
    tc.append((f['b'] + e) / 2 / FS)
y = np.ravel(np.column_stack([H, L]))
t = np.array(tc) - np.mean(tc)
X = np.column_stack([np.ones(40), t, t ** 2, np.tile([1.0, 0.0], 20)])
beta, res, *_ = np.linalg.lstsq(X, y, rcond=None)
sig2 = float(((y - X @ beta) ** 2).sum() / (40 - 4))
se = float(np.sqrt(sig2 * np.linalg.inv(X.T @ X)[3, 3]))
out['sham_B_ols_quadtrend'] = dict(dI=float(beta[3]), se=se, ci95=[float(beta[3] - 2.028 * se), float(beta[3] + 2.028 * se)])
pipe_sham = [x['dI_mA'] for x in A['phases']['sham']['windows']]
out['sham_per_window_max_absdiff_vs_pipeline_mA'] = float(np.max(np.abs(dA - np.array(pipe_sham))))
out['sham_pipeline_mean'] = A['phases']['sham']['null_dI_mA']['mean']

# C3
gap_b = I[sh[0]['a'] - 2 * FS + G:sh[0]['a'] - G].mean()
gap_a = I[sh[-1]['b'] + FS + G:sh[-1]['b'] + 3 * FS - G].mean()
out['C3'] = dict(sham_low=float(L.mean()), gap_before=float(gap_b), gap_after=float(gap_a),
                 diffs=[float(L.mean() - gap_b), float(L.mean() - gap_a)])

# schedules
pipe_bench = {}
for name, ph in A['phases'].items():
    if name.startswith('schedule'):
        pipe_bench[int(name.split('_')[1])] = ph
sched = {}
idle_all, final_all = [], []
for s in range(5):
    ph = 2 + s
    fs_ = [f for f in fr if f['phase'] == ph]
    pre, rest = fs_[:3], fs_[3:]
    bench, over = rest[0::2], rest[1::2]
    assert all(f['kind'] == 2 for f in bench) and all(f['kind'] == 3 for f in over) and len(bench) == 10
    E = [V * I[f['a']:f['b']].sum() * 1e-3 / FS / f['it'] for f in bench]
    P = [V * I[f['a']:f['b']].mean() * 1e-3 for f in bench]
    tpi = [(f['b'] - f['a']) / FS / f['it'] for f in bench]
    tpi_cc = [f['cyc'] / 240e6 / f['it'] for f in bench]
    clk = [f['cyc'] / ((f['b'] - f['a']) / FS) for f in bench + over]
    before = [I[(over[i - 1]['b'] if i else pre[2]['b']) + G:bench[i]['a'] - G].mean() for i in range(10)]
    after = [I[bench[i]['b'] + G:over[i]['a'] - G].mean() for i in range(10)]
    final = I[over[9]['b'] + G:over[9]['b'] + FS - G].mean()
    rng_ok = all(np.all(rng8[x0:x1] == 4) for x0, x1 in
                 [(f['a'], f['b']) for f in bench] + [(bench[i]['b'], over[i]['a']) for i in range(10)]
                 + [((over[i - 1]['b'] if i else pre[2]['b']), bench[i]['a']) for i in range(10)])
    pb = pipe_bench[s]['bench']
    rel = [E[i] / pb[i]['gross_J_per_iter'] - 1 for i in range(10)]
    it_ok = all(bench[i]['it'] == pb[i]['iterations'] for i in range(10))
    cks = sorted({f['ck'] for f in bench}), sorted({f['ck'] for f in over})
    sched[s] = dict(kind=pipe_bench[s]['kind'], iterations=bench[0]['it'], gross_mJ_mean=float(np.mean(E)) * 1e3,
                    gross_mJ_sd=float(np.std(E, ddof=1)) * 1e3,
                    gross_rel_diff_vs_pipeline_max=float(np.max(np.abs(rel))), iterations_match=it_ok,
                    bench_power_W=float(np.mean(P)), time_ms=float(np.mean(tpi)) * 1e3, time_cc_ms=float(np.mean(tpi_cc)) * 1e3,
                    cpu_MHz=float(np.mean(clk)) / 1e6, cpu_MHz_min=float(np.min(clk)) / 1e6, cpu_MHz_max=float(np.max(clk)) / 1e6,
                    idle_before=float(np.mean(before)), idle_after=float(np.mean(after)),
                    C1=float(np.mean(before) - np.mean(after)), final_idle=float(final),
                    bench_minus_idle_mA=float(np.mean([I[f['a']:f['b']].mean() for f in bench]) - np.mean(before + after)),
                    all_R4_no_switch=bool(rng_ok), checksums_unique=[len(cks[0]), len(cks[1])],
                    bench_ck=cks[0], first_gross=float(E[0]) * 1e3, last_gross=float(E[-1]) * 1e3)
    idle_all += before + after
    final_all.append(final)
out['schedules'] = sched
out['C2'] = float(np.mean(final_all) - np.mean(idle_all))
rep = [sched[s]['gross_mJ_mean'] for s in range(3)]
out['headline_gross_mJ'] = dict(mean=float(np.mean(rep)), sd=float(np.std(rep, ddof=1)), cv=float(np.std(rep, ddof=1) / np.mean(rep)))
# 1-s mean current profile at a few landmarks
out['I_mean_whole_after_mask_mA'] = float(I[MASK:runs[len(fwh)][0]].mean())
print(json.dumps(out, indent=1, default=float))
Path(__file__).with_name('indep_check_out.json').write_text(json.dumps(out, indent=1, default=float) + '\n')
