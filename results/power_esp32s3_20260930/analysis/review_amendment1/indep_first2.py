"""Reviewer (NON-REGISTERED): identical estimator on the first two sham windows of all three
captures (the wiring check stops 36 s after ON, so only two sham windows exist there).
W0 = hi0 - mean(lo_gap_before, lo_after0); W1 = hi1 - lo_after0 (50 ms guards)."""

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


G = 5000
def first2(w, C, sh, prev_end):
    (a0, b0), (a1, b1) = sh[0], sh[1]
    m = lambda a, b: float(mA(w[a:b], C).mean())
    lo_gap, lo0 = m(prev_end + G, a0 - G), m(b0 + G, a1 - G)
    return [round(m(a0 + G, b0 - G) - 0.5 * (lo_gap + lo0), 3), round(m(a1 + G, b1 - G) - lo0, 3)]
wd, Cd, ond = load('ppk_esp2', 'diag_esp_01'); rd = d0_runs(wd, ond, ond + 80 * FS)
wn, Cn, onn = load('ppk_esp2', 'attrib_nod0_01'); sft = (onn - ond) - 30
ww, Cw, onw = load('ppk_esp8', 'wiringcheck_esp_01'); rw = d0_runs(ww, onw, len(ww))
out = dict(diag_gpio4=first2(wd, Cd, rd[5:7], rd[4][1]),
           attrib_gpio4_nod0=first2(wn, Cn, [(a + sft, b + sft) for a, b in rd[5:7]], rd[4][1] + sft),
           wiringcheck_gpio5=first2(ww, Cw, rw[5:7], rw[4][1]))
# the same two-window estimator slid over all 19 consecutive window pairs of diag and attrib
def slide(w, C, runs, s=0):
    vals = []
    for k in range(5, 24):
        vals.append(np.mean(first2(w, C, [(a + s, b + s) for a, b in runs[k:k + 2]], runs[k - 1][1] + s)))
    return np.round(vals, 3).tolist()
out['diag_pairwise_means'] = slide(wd, Cd, rd)
out['attrib_pairwise_means'] = slide(wn, Cn, rd, sft)
out['wiringcheck_pair_mean'] = float(np.mean(out['wiringcheck_gpio5']))
json.dump(out, open('indep_first2.json', 'w'), indent=1); print(json.dumps(out))
