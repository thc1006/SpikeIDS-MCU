"""Reviewer: IDLE spans that follow the SAME preceding activity (an OVERHEAD window) but run
different inlined wait-loop copies: L8a (IDLE after OVERHEAD, loop 0x42006aa1) vs L9 (final
IDLE after the 10th OVERHEAD, loop 0x42006cba); plus L8b (IDLE after BENCH, loop 0x42006b81).
Marker LOW in all three. Self-contained helpers copied from indep_phase_levels.py."""
import json, sys
import numpy as np
src = open('indep_phase_levels.py').read().split('# loop alignment per phase')[0]
exec(src)
out = {}
for name, rec, lab, ref in (('diag', 'ppk_esp2', 'diag_esp_01', None), ('attrib', 'ppk_esp2', 'attrib_nod0_01', 'diag')):
    w, C, on = load(rec, lab)
    if ref is None:
        runs = d0_runs(w, on); on_d = on; shift = 0; base_runs = runs
    else:
        shift = (on - on_d) - 30; runs = base_runs
    m = lambda a, b: float(mA(w[a + shift:b + shift], C).mean())
    a_, b_, f_ = [], [], []
    for j in range(5):
        sch = runs[25 + 23 * j:25 + 23 * (j + 1)]
        for c in range(10):
            b_.append(m(sch[3 + 2 * c][1] + G, sch[4 + 2 * c][0] - G))          # after BENCH  (0x42006b81)
            if c < 9:
                a_.append(m(sch[4 + 2 * c][1] + G, sch[5 + 2 * c][0] - G))      # after OVERHEAD (0x42006aa1)
        f_.append(m(sch[22][1] + G, sch[22][1] + FS - G))                        # after 10th OVERHEAD (0x42006cba)
    out[name] = {'L8a IDLE after OVERHEAD (0x42006aa1)': [round(float(np.mean(a_)), 3), round(float(np.std(a_, ddof=1)), 3), len(a_)],
                 'L8b IDLE after BENCH (0x42006b81)': [round(float(np.mean(b_)), 3), round(float(np.std(b_, ddof=1)), 3), len(b_)],
                 'L9 final IDLE after OVERHEAD (0x42006cba)': [round(float(np.mean(f_)), 3), round(float(np.std(f_, ddof=1)), 3), len(f_)]}
json.dump(out, open('indep_idle_split.json', 'w'), indent=1); print(json.dumps(out, indent=1))
