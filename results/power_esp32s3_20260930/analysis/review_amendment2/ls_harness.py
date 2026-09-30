"""Reviewer harness for analysis/live_sham.py (read-only on the recordings).
Truncated copies go to /tmp/ls_trunc_*; nothing in the repo is modified.
1) live-streaming truncations of ppk_esp2/diag_esp_01;
2) synthetic shifts of the marker-HIGH current (patched Converter.ua) to
   probe the abort rule on both signs, compared with the registered span
   definition (analyze_schedule.analyze_sham: k=0 after-LOW only, last k
   after-LOW of one median width, t-CI);
3) timing of the calibration inside the j=19 LOW span."""
import io
import json
import os
import shutil
import subprocess
import sys
import contextlib
import numpy as np
from scipy import stats

REPO = '/home/thc1006/dev/SpikeIDS-MCU'
LS = f'{REPO}/results/power_esp32s3_20260930/analysis/live_sham.py'
PY = f'{REPO}/.venv/bin/python'
R = f'{REPO}/results/power_esp32s3_20260930/ppk_esp2'
LABEL = 'diag_esp_01'
sys.path.insert(0, f'{REPO}/tools/ra4e1_deployment/host_measure')
sys.path.insert(0, f'{REPO}/tools/ppk2_energy')
import rm01_decode as rd  # noqa: E402
import analyze_schedule as az  # noqa: E402
import ppk2_session  # noqa: E402

ev = [json.loads(x) for x in open(f'{R}/events.jsonl') if x.strip()]
st = [e for e in ev if e['kind'] == 'segment_start' and e['label'] == LABEL][-1]
on = [e for e in ev if e.get('name') == 'output_on' and e['sample_index'] >= st['sample_index']][0]
on0 = on['sample_index'] - st['sample_index']
seg = f"{R}/{st['path']}"
w_full = np.fromfile(seg, dtype='<u4')
d0, _ = rd.logic_d0(w_full)
d0 = d0.copy(); d0[: on0 + 150_000] = False
runs = az.high_runs(d0)
out = dict(on_sample=on0, run24=runs[24], run25=runs[25], run26=runs[26],
           run25_after_on_s=(runs[25][0] - on0) / 1e5, run24_end_after_on_s=(runs[24][1] - on0) / 1e5)


def make_trunc(name, n_samples):
    d = f'/tmp/ls_trunc_{name}'
    os.makedirs(d, exist_ok=True)
    for f in ('events.jsonl', 'session.json'):
        shutil.copyfile(f'{R}/{f}', f'{d}/{f}')
    with open(seg, 'rb') as src, open(f"{d}/{st['path']}", 'wb') as dst:
        dst.write(src.read(int(n_samples) * 4 + 2))  # +2: a partial trailing word
    return d


def run_ls(d):
    p = subprocess.run([PY, '-B', LS, d, LABEL], capture_output=True, text=True,
                       env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    return dict(exit=p.returncode, stdout=p.stdout.strip().splitlines()[:2], stderr=p.stderr.strip()[-300:])


cuts = {
    'mid_sham20': (runs[24][0] + runs[24][1]) // 2,
    'after_sham20': runs[24][1] + 50_000,
    'run25_plus2': runs[25][0] + 2,
    'run25_plus10': runs[25][0] + 10,
    'on_plus80s': on0 + 80 * 100_000,
}
out['truncations'] = {k: dict(cut_after_on_s=(v - on0) / 1e5, **run_ls(make_trunc(k, v))) for k, v in cuts.items()}

# Synthetic shifts on the ON+80 s copy: exec live_sham.py in-process with a patched Converter.ua.
d80 = '/tmp/ls_trunc_on_plus80s'
src = open(LS).read()
orig_ua = ppk2_session.Converter.ua


def exec_ls(delta_mA):
    def ua(self, words):
        u, r, bad = orig_ua(self, words)
        hi, _ = rd.logic_d0(words)
        return u + hi * (delta_mA * 1000.0), r, bad
    ppk2_session.Converter.ua = ua
    buf = io.StringIO(); code = 0
    sys.argv = ['live_sham.py', d80, LABEL]
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(src, LS, 'exec'), {'__name__': '__main__'})
    except SystemExit as e:
        code = e.code
    finally:
        ppk2_session.Converter.ua = orig_ua
    return code, buf.getvalue().strip().splitlines()[1] if len(buf.getvalue().splitlines()) > 1 else buf.getvalue()


# Registered span definition on the same runs (no synthetic shift).
w80 = np.fromfile(f"{d80}/{st['path']}", dtype='<u4')
conv = ppk2_session.Converter(json.load(open(f'{R}/session.json'))['metadata'], 5.0)
I = conv.ua(w80)[0] / 1000.0
sham = runs[5:25]
G = 5000
width = int(np.median([b - a for a, b in sham]))
reg, live = [], []
for k, (a, b) in enumerate(sham):
    lows = []
    if k > 0:
        lows.append(I[sham[k - 1][1] + G: a - G].mean())
    lo_end = sham[k + 1][0] if k + 1 < len(sham) else b + width
    lows.append(I[b + G: lo_end - G].mean())
    reg.append(I[a + G: b - G].mean() - np.mean(lows))
    nxt = runs[5 + k + 1][0]; prv = runs[5 + k - 1][1]
    live.append(I[a + G: b - G].mean() - 0.5 * (I[prv + G: a - G].mean() + I[b + G: nxt - G].mean()))
reg, live = np.array(reg), np.array(live)
sd_r = reg.std(ddof=1); hw_t = stats.t.ppf(0.975, 19) * sd_r / np.sqrt(20)
out['registered_def'] = dict(mean=reg.mean(), ci=[reg.mean() - hw_t, reg.mean() + hw_t])
out['live_def'] = dict(mean=live.mean(), hw_z=1.96 * live.std(ddof=1) / np.sqrt(20))
out['live_minus_reg_per_pulse'] = np.round(live - reg, 3).tolist()
# LOW span composition for j=19 (live): calibration current vs sham LOW
b19 = sham[19][1]; nxt = runs[25][0]
seg19 = I[b19 + G: nxt - G]
out['j19_live_low_span_s'] = len(seg19) / 1e5
out['j19_low_1s_to_2s_mean'] = float(I[b19 + G: b19 + 100_000 - G].mean())
out['j19_live_low_mean'] = float(seg19.mean())
out['j0_live_low_span_s'] = (sham[0][0] - G - (runs[4][1] + G)) / 1e5

# Synthetic: delta applied to marker-HIGH samples shifts both estimators by ~delta.
syn = {}
for target in (-0.45, -0.53, -0.56, -0.60, +0.45, +0.53, +0.60, -0.40):
    delta = target - live.mean()
    syn[f'{target:+.2f}'] = dict(delta=round(delta, 4), reg_mean=round(reg.mean() + delta, 4),
                                 reg_pass=bool(abs(reg.mean() + delta) < 0.5), live=exec_ls(delta))
out['synthetic'] = syn
json.dump(out, open(f'{REPO}/results/power_esp32s3_20260930/analysis/review_amendment2/ls_harness.json', 'w'),
          indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
print(json.dumps(out, indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o)))
