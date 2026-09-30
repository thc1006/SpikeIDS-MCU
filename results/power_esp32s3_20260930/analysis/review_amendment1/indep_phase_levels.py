"""Reviewer: current level of every busy-wait phase of diag_esp_01 / attrib_nod0_01
(build_02) and wiringcheck_esp_01 (build_03), tagged with marker state and with the
alignment of the inlined wait loop that runs it (from the build_02 = build_03
disassembly). Discriminates 'marker-state load' from 'loop-alignment' explanations.
Self-contained; read-only."""
import json
import sys
import numpy as np

BASE = '/home/thc1006/dev/SpikeIDS-MCU/results/power_esp32s3_20260930'
FS = 100_000
G = 5000


def load(rec, label):
    ev = [json.loads(x) for x in open(f'{BASE}/{rec}/events.jsonl') if x.strip()]
    md = json.load(open(f'{BASE}/{rec}/session.json'))['metadata']
    C = {k: np.array([float(md[f'{k}{i}']) for i in range(5)]) for k in ('R', 'GS', 'GI', 'O', 'S', 'I', 'UG')}
    st = [e for e in ev if e['kind'] == 'segment_start' and e['label'] == label][-1]
    sp = [e for e in ev if e['kind'] == 'segment_stop' and e['label'] == label][-1]
    on = [e for e in ev if e.get('name') == 'output_on' and st['sample_index'] <= e['sample_index'] <= sp['sample_index']][0]
    return np.memmap(f"{BASE}/{rec}/{st['path']}", dtype='<u4', mode='r'), C, on['sample_index'] - st['sample_index']


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


def d0_runs(w, on):
    bits = (np.asarray(w) >> 24).astype(np.uint8)
    d0 = ((bits & 1) == 1) & ((bits & 0xFE) == 0)
    d0[:on + int(1.5 * FS)] = False
    return runs_of(d0)


# loop alignment per phase (build_02 == build_03 disassembly; 32-byte ICache line)
LOOP = {'L2 parity->wiring gap': ('0x42006766', 'no-32B-cross'), 'L3/L5 pulses LOW span': ('0x420061fd', 'CROSSES'),
        'L4 wiring->sham gap': ('0x4200679e', 'CROSSES'), 'L6 sham->cal gap': ('0x420067d6', 'CROSSES'),
        'L7 cal/idle->schedule gap': ('0x42006a32', 'no-32B-cross'), 'L8 IDLE windows': ('0x42006aa1/0x42006b81', 'no-32B-cross'),
        'L9 final IDLE': ('0x42006cba', 'CROSSES'), 'L10 pre-telemetry gap': ('0x42006d3c', 'CROSSES'),
        'L11 post-sync LOW 100ms': ('0x42006dc0', 'no-32B-cross'),
        'H1/H2 pulses HIGH span': ('0x420061d4', 'no-32B-cross'), 'H4 telemetry sync HIGH 300ms': ('0x42006d7e', 'CROSSES')}


def levels(w, C, runs, shift=0, full=True):
    m = lambda a, b: float(mA(w[a + shift:b + shift], C).mean())
    out = {}
    s = runs
    out['L4 wiring->sham gap'] = m(s[4][1] + 10_000 + G, s[5][0] - G)
    out['L3/L5 pulses LOW span'] = float(np.mean([m(s[k][1] + G, s[k + 1][0] - G) for k in range(5, 24)]))
    out['H1/H2 pulses HIGH span'] = float(np.mean([m(a + G, b - G) for a, b in s[5:25]]))
    out['wiring HIGH (0.1 s, 10 ms guard)'] = float(np.mean([m(a + 1000, b - 1000) for a, b in s[0:5]]))
    out['wiring LOW (0.1 s, 10 ms guard)'] = float(np.mean([m(b + 1000, b + 9000) for a, b in s[0:5]]))
    out['L2 parity->wiring gap'] = m(s[0][0] - 2 * FS + G + 20_000, s[0][0] - G)   # skip 200 ms after parity end
    if not full:
        return out
    e24 = s[24][1]
    out['L6 sham->cal gap'] = m(e24 + FS + G, e24 + 3 * FS - G)
    out['L7 cal/idle->schedule gap'] = float(np.mean([m(s[25 + 23 * j][0] - 2 * FS + G, s[25 + 23 * j][0] - G) for j in range(5)]))
    idle = []
    fin = []
    for j in range(5):
        sch = s[25 + 23 * j:25 + 23 * (j + 1)]
        idle.append(m(sch[2][1] + 2000 + G, sch[3][0] - G))                 # after preamble: 20 ms pulses-LOW + IDLE
        for c in range(10):
            b_end, o_start = sch[3 + 2 * c][1], sch[4 + 2 * c][0]
            idle.append(m(b_end + G, o_start - G))                           # IDLE after BENCH
            if c < 9:
                idle.append(m(sch[4 + 2 * c][1] + G, sch[5 + 2 * c][0] - G))  # IDLE after OVERHEAD
        fin.append(m(sch[22][1] + G, sch[22][1] + FS - G))                   # final IDLE
    out['L8 IDLE windows'] = float(np.mean(idle))
    out['L9 final IDLE'] = float(np.mean(fin))
    sy = s[140]
    out['L10 pre-telemetry gap'] = m(sy[0] - 2 * FS + G, sy[0] - G)
    out['H4 telemetry sync HIGH 300ms'] = m(sy[0] + G, sy[1] - G)
    out['L11 post-sync LOW 100ms'] = m(sy[1] + 1000, s[141][0] - 1000)
    # adjacent pairs (same marker state LOW, different loop alignment), per schedule
    out['pair L9(final IDLE, CROSSES) - L7(next gap, no-cross), schedules 0-3'] = [
        round(m(s[25 + 23 * j + 22][1] + G, s[25 + 23 * j + 22][1] + FS - G) - m(s[25 + 23 * (j + 1)][0] - 2 * FS + G, s[25 + 23 * (j + 1)][0] - G), 3)
        for j in range(4)]
    out['pair L6(CROSSES) - L7 first(no-cross)'] = round(m(e24 + FS + G, e24 + 3 * FS - G) - m(s[25][0] - 2 * FS + G, s[25][0] - G), 3)
    out['pair H4(sync HIGH, CROSSES) - L10(LOW, CROSSES)'] = round(out['H4 telemetry sync HIGH 300ms'] - out['L10 pre-telemetry gap'], 3)
    out['pair H4(sync HIGH) - L11(LOW, no-cross)'] = round(out['H4 telemetry sync HIGH 300ms'] - out['L11 post-sync LOW 100ms'], 3)
    return out


res = dict(loop_alignment=LOOP)
wd, Cd, ond = load('ppk_esp2', 'diag_esp_01')
rd = d0_runs(wd, ond)
res['diag_GPIO4_D0on'] = levels(wd, Cd, rd)
wn, Cn, onn = load('ppk_esp2', 'attrib_nod0_01')
res['attrib_GPIO4_D0off'] = levels(wn, Cn, rd, shift=(onn - ond) - 30)
ww, Cw, onw = load('ppk_esp8', 'wiringcheck_esp_01')
rw = d0_runs(ww, onw)
rw_pad = rw + [(len(ww) - FS, len(ww))] * 20    # only the first phases exist; pad for indexing
o = {}
m = lambda a, b: float(mA(ww[a:b], Cw).mean())
o['L2 parity->wiring gap'] = m(rw[0][0] - 2 * FS + G + 20_000, rw[0][0] - G)
o['L4 wiring->sham gap'] = m(rw[4][1] + 10_000 + G, rw[5][0] - G)
o['wiring HIGH (0.1 s, 10 ms guard)'] = float(np.mean([m(a + 1000, b - 1000) for a, b in rw[0:5]]))
o['wiring LOW (0.1 s, 10 ms guard)'] = float(np.mean([m(b + 1000, b + 9000) for a, b in rw[0:5]]))
o['H1/H2 pulses HIGH span (2 sham)'] = float(np.mean([m(a + G, b - G) for a, b in rw[5:7]]))
o['L3/L5 pulses LOW span (1 sham LOW)'] = m(rw[5][1] + G, rw[6][0] - G)
res['wiringcheck_GPIO5_D0on'] = o
json.dump(res, open(sys.argv[1], 'w'), indent=1)
print(json.dumps(res, indent=1))
