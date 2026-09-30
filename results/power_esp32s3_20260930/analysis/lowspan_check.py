"""Code-placement check (ESP Amendment 3): marker-LOW busy-wait spans that ran
different machine code in build_02/03 must agree in build_04. Neighbour-based, so
slow thermal drift cancels:
  C1  per schedule: |mean(IDLE before BENCH) - mean(IDLE after BENCH)| <= 0.25 mA
  C2  pooled over schedules: |mean(final IDLE) - mean(all IDLE)| <= 0.5 mA
  C3  |mean(sham LOW halves) - mean(2 s gap before / after the sham)| <= 0.5 mA
usage: lowspan_check.py ANALYSIS_JSON RECORDER_DIR  ->  prints and writes <label>_lowspan.json"""
import json
import sys
from pathlib import Path
import numpy as np

REPO = Path('/home/thc1006/dev/SpikeIDS-MCU')
sys.path.insert(0, str(REPO / 'tools/ra4e1_deployment/host_measure'))
sys.path.insert(0, str(REPO / 'tools/ppk2_energy'))
import rm01_decode as rd  # noqa: E402
import analyze_schedule as az  # noqa: E402
import ppk2_session  # noqa: E402

C1_MA, C2_MA, C3_MA = 0.25, 0.5, 0.5
G = 5_000                                                   # 50 ms excluded next to every edge
a_path, rec_dir = Path(sys.argv[1]), Path(sys.argv[2])
a = json.loads(a_path.read_text())
seg = a['segment']
conv = ppk2_session.Converter(json.loads((rec_dir / 'session.json').read_text())['metadata'], 5.0)
w = np.fromfile(rec_dir / seg['path'], dtype='<u4')
I = conv.ua(w)[0] / 1000.0
d0, _ = rd.logic_d0(w)
d0 = d0.copy()
d0[:a['unpowered_before']] = False
runs = az.high_runs(d0)


def span(x0, x1):
    x0, x1 = int(x0) + G, int(x1) - G
    return float(I[x0:x1].mean()) if x1 - x0 > 20_000 else None


def runs_in(sl):
    return [(x, y) for x, y in runs if sl[0] <= x < sl[1]]


out = dict(label=seg['label'], thresholds_mA=dict(C1=C1_MA, C2=C2_MA, C3=C3_MA), schedules={})
idle_all, final_all = [], []
for name, ph in a['phases'].items():
    if not name.startswith('schedule'):
        continue
    r = runs_in(ph['slice'])[3:]                            # drop the 3 preamble pulses (20 ms)
    if len(r) < 20:
        out['schedules'][name] = dict(error=f'{len(r)} runs'); continue
    bench, over = r[0::2][:10], r[1::2][:10]
    before = [span(over[i - 1][1] if i else runs_in(ph['slice'])[2][1], bench[i][0]) for i in range(10)]
    after = [span(bench[i][1], over[i][0]) for i in range(10)]
    final = span(over[9][1], over[9][1] + 100_000)          # final IDLE = 1 s after the last OVERHEAD
    before = [x for x in before if x is not None]; after = [x for x in after if x is not None]
    d = float(np.mean(before) - np.mean(after))
    out['schedules'][name] = dict(idle_before_mA=float(np.mean(before)), idle_after_mA=float(np.mean(after)),
                                  C1_diff_mA=d, C1_pass=abs(d) <= C1_MA, final_idle_mA=final)
    idle_all += before + after
    if final is not None:
        final_all.append(final)
c2 = float(np.mean(final_all) - np.mean(idle_all)) if final_all else None
sham = runs_in(a['phases']['sham']['slice'])
sham_low = [span(sham[j][1], sham[j + 1][0] if j + 1 < len(sham) else sham[j][1] + 100_000) for j in range(len(sham))]
sham_low = [x for x in sham_low if x is not None]
gap_before = span(sham[0][0] - 190_000, sham[0][0])         # 2 s gap (+0.1 s wiring LOW) before the sham
gap_after = span(sham[-1][1] + 105_000, sham[-1][1] + 295_000)   # the 2 s gap after the last sham LOW half
c3 = [float(np.mean(sham_low) - g) for g in (gap_before, gap_after) if g is not None]
out.update(C2_final_minus_idle_mA=c2, C2_pass=(c2 is not None and abs(c2) <= C2_MA),
           sham_low_mA=float(np.mean(sham_low)), gap_before_mA=gap_before, gap_after_mA=gap_after,
           C3_diffs_mA=c3, C3_pass=bool(c3) and all(abs(x) <= C3_MA for x in c3))
out['C1_pass'] = all(v.get('C1_pass') for v in out['schedules'].values())
out['PASS'] = bool(out['C1_pass'] and out['C2_pass'] and out['C3_pass'])
(a_path.parent / f"{seg['label']}_lowspan.json").write_text(json.dumps(out, indent=1) + '\n')
for k, v in out['schedules'].items():
    print(f"{k:22s} C1 IDLE before {v.get('idle_before_mA', 0):.3f} after {v.get('idle_after_mA', 0):.3f} "
          f"diff {v.get('C1_diff_mA', float('nan')):+.3f} mA -> {'ok' if v.get('C1_pass') else 'FAIL'} | final IDLE {v.get('final_idle_mA')}")
print(f"C2 final IDLE - IDLE = {c2:+.3f} mA -> {'ok' if out['C2_pass'] else 'FAIL'}")
print(f"C3 sham LOW {out['sham_low_mA']:.3f} vs gaps {gap_before:.3f} / {gap_after:.3f} -> diffs {[round(x, 3) for x in c3]} "
      f"-> {'ok' if out['C3_pass'] else 'FAIL'}")
print('CODE-PLACEMENT CHECK:', 'PASS' if out['PASS'] else 'FAIL')
