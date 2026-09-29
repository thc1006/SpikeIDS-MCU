"""Recompute the wiringcheck_esp_01 (ppk_esp8, GPIO5, build_03) sham windows with
several estimators, to check Amendment 2's '-0.526 and -0.648 mA'. Read-only."""
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path('/home/thc1006/dev/SpikeIDS-MCU')
sys.path.insert(0, str(REPO / 'tools/ppk2_energy'))
import analyze_schedule as az  # noqa: E402
import ppk2_session  # noqa: E402

D = REPO / 'results/power_esp32s3_20260930/ppk_esp8'
meta = json.loads((D / 'session.json').read_text())
ev = [json.loads(x) for x in (D / 'events.jsonl').read_text().splitlines() if x.strip()]
st = next(e for e in ev if e['kind'] == 'segment_start')
on = next(e for e in ev if e['kind'] == 'command' and e.get('name') == 'output_on')
w = az.load_words(D / st['path'])
conv = ppk2_session.Converter(meta['metadata'], 5.0)
ma = conv.ua(w)[0] / 1000.0
d0 = ((w >> 24) & 1).astype(bool)
mask = on['sample_index'] - st['sample_index'] + int(1.5 * 100_000)
d0[:mask] = False
runs = az.high_runs(d0)
wid = [(b - a) / 1e5 for a, b in runs]
g = 5000
m = lambda a, b: float(ma[a:b].mean())
sh = [r for r, x in zip(runs, wid) if 0.9 < x < 1.1]
wi = [r for r, x in zip(runs, wid) if 0.05 < x < 0.15]
(a0, b0), (a1, b1) = sh[:2]
hi0, hi1 = m(a0 + g, b0 - g), m(a1 + g, b1 - g)
lo_before0 = m(wi[-1][1] + g, a0 - g)            # the wiring->sham gap (not in the registered sham slice)
lo_after0 = m(b0 + g, a1 - g)
end = min(len(ma), b1 + (b1 - a1))
lo_after1 = m(b1 + g, end - g)
out = dict(runs=len(runs), widths_s=[round(x, 4) for x in wid], samples_after_last_run=len(ma) - b1,
           review1_W0_hi0_minus_mean_gapbefore_after0=hi0 - (lo_before0 + lo_after0) / 2,
           review1_W1_hi1_minus_after0=hi1 - lo_after0,
           registered_style_W0_hi0_minus_after0=hi0 - lo_after0,
           registered_style_W1_hi1_minus_mean_after0_after1=hi1 - (lo_after0 + lo_after1) / 2,
           W1_hi1_minus_after1=hi1 - lo_after1,
           levels_mA=dict(lo_before0=lo_before0, hi0=hi0, lo_after0=lo_after0, hi1=hi1, lo_after1=lo_after1,
                          lo_after1_span_s=(end - g - b1 - g) / 1e5))
print(json.dumps(out, indent=1))
