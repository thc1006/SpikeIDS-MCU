"""Two-stage summary over power-cycled SM07M sessions (offline).

Each session (one power-on) contributes the mean of its valid repeat-schedule
means. The between-session t-interval is the headline once >= 3 sessions
exist; window-level intervals stay labelled as within-session repeatability.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_schedule as az  # noqa: E402

KEYS = ('headline_gross_J_per_inference_between_schedules',
        'incremental_over_spin_J_per_inference_between_schedules')


def session_means(run_dir):
    d = Path(run_dir)
    if (d / 'FAILED.json').exists() or not (d / 'MEASURE_RESULT.json').exists():
        return None, None                      # a run that failed any gate is never pooled
    final = json.loads((d / 'MEASURE_RESULT.json').read_text())
    eligible = final.get('session_eligible')
    if eligible is None:        # run_04 predates the flag: recompute from its saved files (Amendment 3)
        s0 = json.loads((d / 'MEASUREMENT_SUMMARY.json').read_text())
        wiring = json.loads((d / 'WIRING.json').read_text())
        eligible = bool(s0['sham_null']['valid'] and wiring['passed'] and s0['valid_repeat_schedules'] >= 2)
    if not eligible:
        return None, None
    s = json.loads((d / 'MEASUREMENT_SUMMARY.json').read_text())
    return {k: (s.get(k) or {}).get('mean') for k in KEYS}, s


def aggregate(run_dirs):
    rows = []
    for d in run_dirs:
        means, s = session_means(d)
        if s is None:
            rows.append(dict(run=str(d), excluded='FAILED.json present, MEASURE_RESULT missing, or invalid capture'))
            continue
        rows.append(dict(run=str(d), valid_repeat_schedules=s['valid_repeat_schedules'], **means,
                         sham_valid=s['sham_null']['valid']))
    usable = [r for r in rows if 'excluded' not in r and r['valid_repeat_schedules'] >= 2 and r['sham_valid']]
    out = dict(sessions=rows, usable_sessions=len(usable),
               gross_J_per_inference_between_sessions=az.ci95([r[KEYS[0]] for r in usable]),
               incremental_over_spin_J_per_inference_between_sessions=az.ci95([r[KEYS[1]] for r in usable]),
               note='Between-session t-interval over session means; needs >= 3 power-cycled sessions.')
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('runs', nargs='+', type=Path)
    a = ap.parse_args(argv)
    print(json.dumps(aggregate(a.runs), indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
