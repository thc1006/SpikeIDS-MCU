"""Regression: re-analyze the 3 RA4E1 formal sessions with the CURRENT (platform-
generalized) decoder and compare every numeric leaf with the saved formal analysis
(decoded by decoder 94ab0ec4 before the generalization)."""
import json
import math
import sys
from pathlib import Path

REPO = Path('/home/thc1006/dev/SpikeIDS-MCU')
sys.path.insert(0, str(REPO / 'tools/ra4e1_deployment/host_measure'))
import run_sessions as rs  # noqa: E402

F = REPO / 'results/power_ra4e1_20260929/formal_20260930'
rec = rs.Recorder(REPO / 'results/power_ra4e1_20260929/ppk_main7')
ev = rec.events()
print('decoder now', rs.sha(Path(rs.rd.__file__))[:8], '| formal decoder 94ab0ec4')


def walk(a, b, path, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            if k not in a or k not in b:
                out['key_only_in'].append((path + '/' + str(k), 'saved' if k in a else 'new'))
            else:
                walk(a[k], b[k], path + '/' + str(k), out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out['len'].append((path, len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f'{path}[{i}]', out)
    elif isinstance(a, bool) or isinstance(b, bool) or a is None or b is None or isinstance(a, str) or isinstance(b, str):
        if a != b and not (isinstance(a, str) and isinstance(b, str) and a == b):
            out['value'].append((path, a, b))
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a != b:
            if math.isnan(a) and math.isnan(b):
                return
            rel = abs(a - b) / max(abs(a), abs(b), 1e-300)
            out['num'].append((path, rel))
    else:
        if a != b:
            out['value'].append((path, a, b))


for k in (1, 2, 3):
    label = f'ra_session_{k:02d}'
    saved = json.loads((F / f'{label}_analysis.json').read_text())
    st, sp, seg = saved['start_event'], saved['stop_event'], saved['segment']
    on = [e for e in ev if e.get('name') == 'output_on' and st['sample_index'] <= e['sample_index'] <= sp['sample_index']][0]
    res, conv = rs.analyze(rec, seg, rec.session(), st, sp, on, mask_s=0.5)
    new = json.loads(json.dumps(res, default=str))
    saved_cmp = {kk: vv for kk, vv in saved.items() if kk not in ('label', 'segment', 'done', 'start_event', 'stop_event')}
    out = dict(key_only_in=[], len=[], value=[], num=[])
    walk(saved_cmp, new, '', out)
    mx = max((r for _, r in out['num']), default=0.0)
    summ_new = rs.session_summary(res, conv)
    summ_old = json.loads((F / f'{label}_summary.json').read_text())
    print(f"{label}: eligible old/new {summ_old['eligible']}/{summ_new['eligible']} | gross old "
          f"{summ_old['headline_gross_J_per_inference_between_schedules']['mean']!r} new "
          f"{summ_new['headline_gross_J_per_inference_between_schedules']['mean']!r}")
    print(f"   numeric leaves differing: {len(out['num'])}, max rel {mx:.3e}; value diffs {out['value'][:5]}; "
          f"len diffs {out['len'][:5]}; keys only in {out['key_only_in'][:8]}")
