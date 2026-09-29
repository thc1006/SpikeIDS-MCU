"""Build the diag_esp_01 reference timeline used by sham_nod0.py / full_nod0.py:
every D0 HIGH run relative to output ON (after the 1.5 s mask), the parity-end
current step, the phase membership of the runs, and a 1 ms current trace from ON.
Outputs (derived, regenerable, not versioned): diag_reference.json, diag_I_1ms.npy."""
import json
import os
import sys
import numpy as np

REPO = '/home/thc1006/dev/SpikeIDS-MCU'
sys.path.insert(0, f'{REPO}/tools/ra4e1_deployment/host_measure')
sys.path.insert(0, f'{REPO}/tools/ppk2_energy')
import rm01_decode as rd  # noqa: E402
import analyze_schedule as az  # noqa: E402
import ppk2_session  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
R = f'{REPO}/results/power_esp32s3_20260930/ppk_esp2'
a = json.load(open(f'{R}/diag_esp_01_analysis.json'))
conv = ppk2_session.Converter(json.load(open(f'{R}/session.json'))['metadata'], 5.0)
ev = [json.loads(x) for x in open(f'{R}/events.jsonl') if x.strip()]
st = [e for e in ev if e['kind'] == 'segment_start' and e['label'] == 'diag_esp_01'][-1]
on = [e for e in ev if e.get('name') == 'output_on'][0]
on_off = on['sample_index'] - st['sample_index']
w = np.fromfile(f"{R}/seg_000_diag_esp_01.u32le", dtype='<u4')
d0, powered = rd.logic_d0(w)
d0[:a['unpowered_before']] = False
runs = az.high_runs(d0)
I = conv.ua(w)[0] / 1000.0
ms = I[: len(I) // 100 * 100].reshape(-1, 100).mean(axis=1)          # 1 ms bins, segment time
wr = runs[0][0]                                                       # first wiring rise


def step_fit(x, lo, hi, guard=5):
    c = np.cumsum(np.r_[0, x]); c2 = np.cumsum(np.r_[0, x * x]); best = None
    for k in range(lo + guard, hi - guard):
        a1, a2 = c[k] - c[lo], c[hi] - c[k]
        s = (c2[hi] - c2[lo]) - a1 * a1 / (k - lo) - a2 * a2 / (hi - k)
        if best is None or s < best[0]:
            best = (s, k, a1 / (k - lo), a2 / (hi - k))
    return best


guess = (wr - 200000) // 100                                          # parity ends one 2 s gap before wiring
_, k, m1, m2 = step_fit(ms, guess - 500, guess + 500)
print('parity-end step %.4f s after ON (%.3f -> %.3f mA); first wiring rise %.4f s after ON'
      % ((k * 100 - on_off) / 1e5, m1, m2, (wr - on_off) / 1e5))
ref = dict(on_offset=int(on_off), parity_end_step_after_on=int(k * 100 - on_off),
           runs_after_on=[[int(x - on_off), int(y - on_off)] for x, y in runs], n_runs=len(runs),
           telemetry_sync_after_on=int(a['telemetry']['sync_start_sample'] - on_off),
           sham_slice_after_on=[int(a['phases']['sham']['slice'][0] - on_off), int(a['phases']['sham']['slice'][1] - on_off)])
ref['phase_runs'] = {ph: [i for i, (x, y) in enumerate(runs) if a['phases'][ph]['slice'][0] <= x < a['phases'][ph]['slice'][1]]
                     for ph in ('wiring', 'sham')}
ref['schedules'] = {ph: dict(slice_after_on=[int(v['slice'][0] - on_off), int(v['slice'][1] - on_off)],
                             bench=[dict(window=b['window'], iterations=b['iterations'], duration_s=b['duration_s'],
                                         p_window_W=b['p_window_W'], p_idle_W=b['p_idle_W']) for b in v['bench']])
                    for ph, v in a['phases'].items() if ph.startswith('schedule')}
json.dump(ref, open(f'{OUT}/diag_reference.json', 'w'))
np.save(f'{OUT}/diag_I_1ms.npy', ms[on_off // 100:])                  # 1 ms bins from ON
print('saved', f'{OUT}/diag_reference.json', f'{OUT}/diag_I_1ms.npy')
