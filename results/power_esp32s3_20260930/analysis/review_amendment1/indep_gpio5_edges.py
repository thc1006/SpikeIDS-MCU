"""Reviewer (NON-REGISTERED, forecast only): marker-edge current steps at the
first sham edges, compared across
  diag_esp_01       build_02, marker GPIO4, D0 on GPIO4 (ribbon)
  attrib_nod0_01    build_02, marker GPIO4, D0 detached
  wiringcheck_esp_01 build_03, marker GPIO5, D0 on GPIO5 (jumpers)
Local step = mean[edge+50 ms, edge+450 ms] - mean[edge-450 ms, edge-50 ms]
(drift-robust; sign: current after minus before). Rising marker edge first.
Edge times come from each capture's own D0 (diag, wiring check) or from the
diag edges + parity-end offset (attrib, -0.3 ms)."""
import json
import sys
import numpy as np

BASE = '/home/thc1006/dev/SpikeIDS-MCU/results/power_esp32s3_20260930'
FS = 100_000


def load(rec, label):
    ev = [json.loads(x) for x in open(f'{BASE}/{rec}/events.jsonl') if x.strip()]
    md = json.load(open(f'{BASE}/{rec}/session.json'))['metadata']
    C = {k: np.array([float(md[f'{k}{i}']) for i in range(5)]) for k in ('R', 'GS', 'GI', 'O', 'S', 'I', 'UG')}
    st = [e for e in ev if e['kind'] == 'segment_start' and e['label'] == label][-1]
    sp = [e for e in ev if e['kind'] == 'segment_stop' and e['label'] == label][-1]
    on = [e for e in ev if e.get('name') == 'output_on' and st['sample_index'] <= e['sample_index'] <= sp['sample_index']][0]
    w = np.memmap(f"{BASE}/{rec}/{st['path']}", dtype='<u4', mode='r')
    return w, C, on['sample_index'] - st['sample_index']


def mA(w, C):
    w = np.asarray(w, dtype=np.uint32)
    adc = (w & 0x3FFF).astype(np.float64) * 4.0
    r = ((w >> 14) & 7).astype(np.int64)
    x = (adc - C['O'][r]) * ((1.8 / 163840.0) / C['R'][r])
    return C['UG'][r] * (x * (C['GS'][r] * x + C['GI'][r]) + (C['S'][r] * 5.0 + C['I'][r])) * 1e3


def runs_of(b, glitch=3):
    d = np.diff(np.concatenate(([0], b.astype(np.int8), [0])))
    out = []
    for a, e in zip(np.nonzero(d == 1)[0].tolist(), np.nonzero(d == -1)[0].tolist()):
        if out and a - out[-1][1] <= glitch:
            out[-1] = (out[-1][0], e)
        else:
            out.append((a, e))
    return [(a, e) for a, e in out if e - a > glitch]


def d0_runs(w, on, upto):
    bits = (np.asarray(w[:upto]) >> 24).astype(np.uint8)
    d0 = ((bits & 1) == 1) & ((bits & 0xFE) == 0)
    d0[:on + int(1.5 * FS)] = False
    return runs_of(d0)


def step(w, C, e):
    return float(mA(w[e + 5000:e + 45000], C).mean() - mA(w[e - 45000:e - 5000], C).mean())


out = {}
wd, Cd, ond = load('ppk_esp2', 'diag_esp_01')
rd = d0_runs(wd, ond, ond + 80 * FS)
wn, Cn, onn = load('ppk_esp2', 'attrib_nod0_01')
ww, Cw, onw = load('ppk_esp8', 'wiringcheck_esp_01')
rw = d0_runs(ww, onw, len(ww))
sh_d = rd[5:25]
sh_w = [r for r in rw[5:]]
edges_d = [x for a, b in sh_d for x in (a, b)]
edges_w = [x for a, b in sh_w for x in (a, b) if x + 45000 <= len(ww)]
shift = (onn - ond) - 30
out['edge_times_after_on_s'] = dict(diag=[round((e - ond) / FS, 4) for e in edges_d[:6]],
                                    wiring=[round((e - onw) / FS, 4) for e in edges_w])
out['diag_GPIO4_D0on_steps_mA'] = [round(step(wd, Cd, e), 3) for e in edges_d]
out['attrib_GPIO4_D0off_steps_mA'] = [round(step(wn, Cn, e + shift), 3) for e in edges_d]
out['wiring_GPIO5_D0on_steps_mA'] = [round(step(ww, Cw, e), 3) for e in edges_w]
k = len(edges_w)
for nm in ('diag_GPIO4_D0on_steps_mA', 'attrib_GPIO4_D0off_steps_mA'):
    v = np.array(out[nm])
    out[nm + '_summary'] = dict(first_k_edges=k, rise_mean_first=float(v[:k:2].mean()), fall_mean_first=float(v[1:k:2].mean()),
                                rise_mean_all=float(v[0::2].mean()), fall_mean_all=float(v[1::2].mean()),
                                rise_sd_all=float(v[0::2].std(ddof=1)), fall_sd_all=float(v[1::2].std(ddof=1)))
v = np.array(out['wiring_GPIO5_D0on_steps_mA'])
out['wiring_GPIO5_summary'] = dict(edges=k, rise_mean=float(v[0::2].mean()), fall_mean=float(v[1::2].mean()))
# wiring pulses (0.1 s): local step with 10 ms guard / 40 ms spans, all three captures
def wstep(w, C, a, b):
    hi = mA(w[a + 1000:b - 1000], C).mean()
    lo = 0.5 * (mA(w[a - 9000:a - 1000], C).mean() + mA(w[b + 1000:b + 9000], C).mean())
    return round(float(hi - lo), 3)
out['wiring_pulse_dI_mA'] = dict(diag=[wstep(wd, Cd, a, b) for a, b in rd[:5]],
                                 attrib=[wstep(wn, Cn, a + shift, b + shift) for a, b in rd[:5]],
                                 wiringcheck_gpio5=[wstep(ww, Cw, a, b) for a, b in rw[:5]])
json.dump(out, open(sys.argv[1], 'w'), indent=1)
print(json.dumps(out, indent=1))
