"""Reviewer: checks of the self-test (ppk_selftest_logic_01) and the wiring check
(ppk_esp8 / wiringcheck_esp_01) claims, from raw frames. Self-contained; read-only.
Also a NON-REGISTERED look at the marker-state current on GPIO5 in the wiring check
(forecast only; it must not change any registered decision)."""
import json
import sys
import numpy as np
from scipy import stats

BASE = '/home/thc1006/dev/SpikeIDS-MCU/results/power_esp32s3_20260930'
FS = 100_000


def load(rec, label):
    ev = [json.loads(x) for x in open(f'{BASE}/{rec}/events.jsonl') if x.strip()]
    md = json.load(open(f'{BASE}/{rec}/session.json'))['metadata']
    C = {k: np.array([float(md[f'{k}{i}']) for i in range(5)]) for k in ('R', 'GS', 'GI', 'O', 'S', 'I', 'UG')}
    st = [e for e in ev if e['kind'] == 'segment_start' and e['label'] == label][-1]
    sp = [e for e in ev if e['kind'] == 'segment_stop' and e['label'] == label][-1]
    on = [e for e in ev if e.get('name') == 'output_on' and st['sample_index'] <= e['sample_index'] <= sp['sample_index']][0]
    off = [e for e in ev if e.get('name') in ('output_off', 'final_output_off') and e['sample_index'] >= on['sample_index']]
    w = np.fromfile(f"{BASE}/{rec}/{st['path']}", dtype='<u4')
    return w, C, on['sample_index'] - st['sample_index'], (off[0]['sample_index'] - st['sample_index']) if off else None, ev, st, sp


def conv(w, C, volts):
    adc = (w & 0x3FFF).astype(np.float64) * 4.0
    r = ((w >> 14) & 7).astype(np.int64)
    x = (adc - C['O'][r]) * ((1.8 / 163840.0) / C['R'][r])
    return C['UG'][r] * (x * (C['GS'][r] * x + C['GI'][r]) + (C['S'][r] * volts + C['I'][r])) * 1e3   # mA


def runs_of(b, glitch=3):
    d = np.diff(np.concatenate(([0], b.astype(np.int8), [0])))
    out = []
    for a, e in zip(np.nonzero(d == 1)[0].tolist(), np.nonzero(d == -1)[0].tolist()):
        if out and a - out[-1][1] <= glitch:
            out[-1] = (out[-1][0], e)
        else:
            out.append((a, e))
    return [(a, e) for a, e in out if e - a > glitch]


res = {}
# ---------------- self-test ----------------
w, C, on, off, ev, st, sp = load('ppk_selftest_logic_01', 'logic_vcc_selftest_01')
I = conv(w, C, 3.3) * 1000.0      # uA
bits = (w >> 24) & 0xFF
pw = (bits & 0xFE) == 0
first_pw = int(np.nonzero(pw[on:])[0][0]) if pw[on:].any() else None
res['selftest'] = dict(
    frames=int(len(w)), on_offset=on, off_offset=off,
    logic_bytes_before_on=sorted(set(np.unique(bits[:on]).tolist())),
    first_powered_frame_after_on_ms=first_pw / 100 if first_pw is not None else None,
    powered_fraction_on_after_wake=float(pw[on + first_pw:off].mean()) if first_pw is not None else None,
    logic_bytes_on=np.unique(bits[on + (first_pw or 0):off]).tolist(),
    mean_uA_before_on=float(I[:on].mean()), mean_uA_on_after_20ms=float(I[on + 2000:off].mean()),
    mean_uA_on_last_4s=float(I[off - 400_000:off].mean()), mean_uA_after_off=float(I[off + 1000:].mean()),
    ranges_on=np.bincount(((w[on:off] >> 14) & 7).astype(int), minlength=5).tolist(),
    peak_uA_on=float(I[on:off].max()),
    counter_gaps=[int(i) for i in (np.nonzero(((w[1:] >> 18) & 63) != ((((w[:-1] >> 18) & 63) + 1) % 64))[0] + 1)],
)
# ---------------- wiring check ----------------
w, C, on, off, ev, st, sp = load('ppk_esp8', 'wiringcheck_esp_01')
I = conv(w, C, 5.0)
bits = (w >> 24) & 0xFF
pw = (bits & 0xFE) == 0
first_pw = int(np.nonzero(pw[on:])[0][0])
nb = (len(w) - on) // 1000
pw_bins = pw[on:on + nb * 1000].reshape(nb, 1000).all(axis=1)
d0 = ((bits & 1) == 1) & pw
d0[:on + int(1.5 * FS)] = False
runs = runs_of(d0)
mask = on + int(1.5 * FS)
one_s = [float(I[a:a + FS].mean()) for a in range(mask, runs[0][0] - FS, FS)]
res['wiringcheck'] = dict(
    frames=int(len(w)), on_offset=on, seconds_after_on=(len(w) - on) / FS,
    logic_bytes_before_on=np.unique(bits[:on]).tolist(),
    first_powered_frame_after_on_ms=first_pw / 100,
    powered_10ms_bins_after_on=f'{int(pw_bins.sum())}/{nb}',
    unpowered_frames_after_first_powered=int((~pw[on + first_pw:]).sum()),
    runs=len(runs), widths_s=[round((b - a) / FS, 5) for a, b in runs],
    first_rise_after_on_s=(runs[0][0] - on) / FS,
    one_s_mean_mA_before_wiring=[min(one_s), max(one_s)],
    non_R4_after_0p2s=int((((w[on + 20_000:] >> 14) & 7) != 4).sum()),
    counter_gaps=int((((w[1:] >> 18) & 63) != ((((w[:-1] >> 18) & 63) + 1) % 64)).sum()),
    last_logic_byte=int(bits[-1]),
)
# NON-REGISTERED marker-state estimate on GPIO5 (build_03): complete sham pulses only
sh = [r for r in runs[5:] if abs((r[1] - r[0]) / FS - 1.0) < 0.05]
G = 5000
rows = []
for k, (a, b) in enumerate(sh):
    hi = I[a + G:b - G].mean()
    lows = []
    prev_end = runs[runs.index((a, b)) - 1][1]
    lows.append(I[prev_end + G:a - G].mean())
    if b + FS <= len(w):
        lows.append(I[b + G:b + FS - G].mean())
    rows.append(dict(hi=float(hi), lo=float(np.mean(lows)), dI=float(hi - np.mean(lows)), n_lows=len(lows)))
res['gpio5_marker_state_nonregistered'] = rows
json.dump(res, open(sys.argv[1], 'w'), indent=1)
print(json.dumps(res, indent=1))
