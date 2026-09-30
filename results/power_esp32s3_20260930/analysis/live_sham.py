"""Early (non-registered) sham check on a segment that is still being recorded
(exit 10 = ABORT, 0 = CONTINUE, 1 = WAIT, 3 = NO-DECISION):
D0 runs after output-ON + 1.5 s, first 5 = wiring, next 20 = sham; per-pulse
dI = mean(HIGH) - mean(neighbouring LOWs), 50 ms guard at every edge. The
registered gate is decided later by the full pipeline; this only allows an
early abort when the marker pin is clearly loaded."""
import json
import sys
import numpy as np

sys.path.insert(0, '/home/thc1006/dev/SpikeIDS-MCU/tools/ra4e1_deployment/host_measure')
sys.path.insert(0, '/home/thc1006/dev/SpikeIDS-MCU/tools/ppk2_energy')
import rm01_decode as rd  # noqa: E402
import analyze_schedule as az  # noqa: E402
import ppk2_session  # noqa: E402

R, label = sys.argv[1], sys.argv[2]
ev = [json.loads(x) for x in open(f'{R}/events.jsonl') if x.strip()]
st = [e for e in ev if e['kind'] == 'segment_start' and e['label'] == label][-1]
on = [e for e in ev if e.get('name') == 'output_on' and e['sample_index'] >= st['sample_index']][0]
conv = ppk2_session.Converter(json.load(open(f'{R}/session.json'))['metadata'], 5.0)
raw = open(f"{R}/{st['path']}", 'rb').read()
w = np.frombuffer(raw[: len(raw) // 4 * 4], dtype='<u4')
d0, powered = rd.logic_d0(w)
d0 = d0.copy()
d0[: on['sample_index'] - st['sample_index'] + 150_000] = False
runs = az.high_runs(d0)
I = conv.ua(w)[0] / 1000.0
wid = [round((b - a) / 1e5, 4) for a, b in runs[:25]]
print(f'captured {len(w) / 1e5:.1f} s; D0 runs {len(runs)}; wiring widths {wid[:5]}; sham widths {sorted(set(wid[5:25]))}')
if len(runs) < 26:
    print('VERDICT: WAIT (not enough runs yet)'); sys.exit(1)
wid_s = [(b - a) / 1e5 for a, b in runs[:25]]
if not (all(0.09 <= x <= 0.11 for x in wid_s[:5]) and all(0.98 <= x <= 1.02 for x in wid_s[5:25])):
    print('VERDICT: NO-DECISION (D0 run widths are not 5 wiring + 20 sham pulses; leave it to the pipeline)')
    sys.exit(3)
G = 5000
sham = runs[5:25]
dI = []
for j, (a, b) in enumerate(sham):
    nxt = runs[5 + j + 1][0]
    prv = runs[5 + j - 1][1]
    lo = 0.5 * (I[prv + G: a - G].mean() + I[b + G: nxt - G].mean())
    dI.append(I[a + G: b - G].mean() - lo)
dI = np.array(dI)
T975 = {19: 2.093}.get(len(dI) - 1, 2.093)            # Student t, 19 dof (review A2 minor 6)
ci = T975 * dI.std(ddof=1) / np.sqrt(len(dI))
m = float(dI.mean())
if not np.isfinite(m) or not np.isfinite(ci):
    print('VERDICT: NO-DECISION (non-finite estimate)'); sys.exit(3)
# Early abort only when the whole early CI lies beyond the gate: the registered decision
# is the pipeline's; this estimator reads ~0.03 mA more negative (review minor).
abort = abs(m) - ci > 0.5
print(f'EARLY SHAM dI = {m:+.4f} mA (95% CI {m - ci:+.4f} .. {m + ci:+.4f}, n={len(dI)}); '
      f'VERDICT: {"ABORT (clearly beyond the 0.5 mA gate)" if abort else "CONTINUE (pipeline decides)"}')
print('per-pulse:', np.round(dI, 3).tolist())
print(f'current: {I[on["sample_index"] - st["sample_index"] + 150_000:].mean():.3f} mA mean after ON+1.5 s')
sys.exit(10 if abort else 0)
