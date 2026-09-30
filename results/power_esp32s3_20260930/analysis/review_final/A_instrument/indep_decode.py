"""Reviewer A (instrument & conversion): independent PPK2 decoder.

Re-implements pc-nrfconnect-ppk src/device/serialDevice.ts (getAdcResult,
parseMeta `meta[k] || default`, spike filter alpha .18 / alpha5 .06 / 3
samples, currentVdd = regulator setpoint) from the Nordic source, WITHOUT
importing ppk2_session/analyze. ppk2_session.Converter is imported ONLY for
the comparison. Read-only on raw data. One segment at a time (memmap).
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path('/home/thc1006/dev/SpikeIDS-MCU')
RES = ROOT / 'results/power_esp32s3_20260930'
OUT = RES / 'analysis/review_final/A_instrument'
SEGS = ['seg_000_esp_session_01', 'seg_001_esp_session_02', 'seg_002_esp_session_03']
LABELS = ['esp_session_01', 'esp_session_02', 'esp_session_03']
FS = 100_000
V_SET = 5000  # mV, regulator setpoint -> Nordic currentVdd

sess = json.loads((RES / 'ppk_esp10/session.json').read_text())
meta = {}
for line in sess['raw_metadata'].splitlines():
    if ':' in line:
        k, v = line.split(':', 1)
        meta[k.strip().lower()] = float(v)
DEF = dict(r=[1031.64, 101.65, 10.15, 0.94, 0.043], gs=[1] * 5, gi=[1] * 5, o=[0] * 5,
           s=[0] * 5, i=[0] * 5, ug=[1] * 5)
ADC_MULT = 1.8 / 163840


def modifiers(gui):
    return {k: [((meta[f'{k}{j}'] or d[j]) if gui else meta[f'{k}{j}']) for j in range(5)]
            for k, d in DEF.items()}


def lut(m, vdd_mv):
    L = np.full((8, 16384), np.nan)
    adc = np.arange(16384) * 4.0                     # getMaskedValue(ADC) * 4
    for r in range(5):
        rwg = (adc - m['o'][r]) * (ADC_MULT / m['r'][r])
        L[r] = m['ug'][r] * (rwg * (m['gs'][r] * rwg + m['gi'][r])
                             + (m['s'][r] * (vdd_mv / 1000) + m['i'][r]))
    return L * 1e6                                   # uA


def nordic_filter(ua, r, alpha=.18, alpha5=.06, samples=3, pre=1000):
    """Exact sequential emulation, run only around range switches (EMA memory
    0.94**1000 ~ 1e-27, so starting 1000 samples early is exact to fp)."""
    out = ua.copy()
    sw = np.nonzero(r[1:] != r[:-1])[0] + 1
    regions = []
    for s in sw:
        a, b = max(0, s - pre), min(len(ua), s + samples + 2)
        if regions and a <= regions[-1][1]:
            regions[-1][1] = max(regions[-1][1], b)
        else:
            regions.append([a, b])
    for a, b in regions:
        roll = roll4 = None
        prev = int(r[a - 1]) if a else int(r[a])
        after = cons = 0
        for j in range(a, b):
            x, rg = float(ua[j]), int(r[j])
            p4, p = roll4, roll
            roll = x if roll is None else alpha * x + (1 - alpha) * roll
            roll4 = x if roll4 is None else alpha5 * x + (1 - alpha5) * roll4
            y = x
            if prev != rg or after > 0:
                if prev != rg:
                    cons, after = 0, samples
                else:
                    cons += 1
                if rg == 4:
                    if cons < 2 and p4 is not None:
                        roll4, roll = p4, p
                    y = roll4
                else:
                    y = roll
                after -= 1
            prev = rg
            out[j] = y
    return out, len(sw)


sys.path.insert(0, str(ROOT / 'tools/ppk2_energy'))
import ppk2_session  # noqa: E402  (comparison target only)

conv = ppk2_session.Converter(sess['metadata'], 5.0, policy='metadata-exact')
L_gui = lut(modifiers(True), V_SET)
L_exact = lut(modifiers(False), V_SET)

report = {'coefficients_gui': modifiers(True), 'coefficients_exact': modifiers(False), 'sessions': {}}
for seg, label in zip(SEGS, LABELS):
    w = np.memmap(RES / f'ppk_esp10/{seg}.u32le', dtype='<u4', mode='r')
    adc = (w & 0x3FFF).astype(np.int32)
    r = np.minimum((w >> 14) & 7, 5).astype(np.int8)
    ua = L_gui[r, adc]
    ua_exact = L_exact[r, adc]
    ua_conv = conv.ua(np.asarray(w))[0]
    ua_f, nsw = nordic_filter(ua, r)
    rep = {'samples': int(len(w)), 'range_switches': nsw, 'per_range': {}}
    for k in range(5):
        m = r == k
        n = int(m.sum())
        if n:
            a, c, f = ua[m].mean(), ua_conv[m].mean(), ua_f[m].mean()
            rep['per_range'][k] = dict(n=n, mean_uA_indep=a, mean_uA_conv=c, mean_uA_indep_filtered=f,
                                       rel_conv_vs_indep=(c - a) / a if a else None,
                                       max_abs_diff_uA_conv=float(np.abs(ua_conv[m] - ua[m]).max()),
                                       max_abs_diff_uA_exact_vs_conv=float(np.abs(ua_conv[m] - ua_exact[m]).max()))
    ana = json.loads((RES / f'formal_20260930/{label}_analysis.json').read_text())
    summ = json.loads((RES / f'formal_20260930/{label}_summary.json').read_text())
    d0 = ((w >> 24) & 1).astype(np.int8)
    win_rows, sched_gross = [], {}
    for pname, ph in ana['phases'].items():
        if 'windows' not in ph or not isinstance(ph.get('windows'), list) or 'slice' not in ph:
            continue
        off = ph['slice'][0]
        for win in ph['windows']:
            if 'start_sample' not in win:
                continue
            a, b = off + win['start_sample'], off + win['stop_sample']
            d0_ok = bool(d0[a:b].all()) and d0[a - 1] == 0 and d0[b] == 0
            s_i, s_c, s_f = float(ua[a:b].sum()), float(ua_conv[a:b].sum()), float(ua_f[a:b].sum())
            e_i = V_SET / 1000 * s_i * 1e-6 / FS
            row = dict(phase=pname, kind=win.get('kind'), a=int(a), b=int(b), d0_edges_ok=d0_ok,
                       energy_J_pipeline=win.get('energy_J'), energy_J_indep=e_i,
                       energy_J_conv=V_SET / 1000 * s_c * 1e-6 / FS, energy_J_indep_filtered=V_SET / 1000 * s_f * 1e-6 / FS,
                       mean_mA_indep=s_i / (b - a) / 1000, iterations=win.get('iterations'))
            win_rows.append(row)
            if win.get('kind') == 'BENCH':
                sched_gross.setdefault(pname, []).append(e_i / win['iterations'])
    bench = [x for x in win_rows if x['kind'] == 'BENCH']
    rel = np.array([(x['energy_J_indep'] - x['energy_J_pipeline']) / x['energy_J_pipeline'] for x in win_rows if x['energy_J_pipeline']])
    relf = np.array([(x['energy_J_indep_filtered'] - x['energy_J_indep']) / x['energy_J_indep'] for x in win_rows])
    reps = [np.mean(v) for k, v in sched_gross.items() if 'repeat' in k]
    headline = float(np.mean(reps))
    rep.update(windows=len(win_rows), bench_windows=len(bench), all_d0_edges_ok=all(x['d0_edges_ok'] for x in win_rows),
               max_abs_rel_window_energy_indep_vs_pipeline=float(np.abs(rel).max()),
               max_abs_rel_window_energy_filtered_vs_unfiltered=float(np.abs(relf).max()),
               schedule_gross_mJ={k: float(np.mean(v)) * 1e3 for k, v in sched_gross.items()},
               headline_mJ_indep=headline * 1e3,
               headline_mJ_pipeline=summ['headline_gross_J_per_inference_between_schedules']['mean'] * 1e3,
               headline_rel_diff=(headline - summ['headline_gross_J_per_inference_between_schedules']['mean'])
               / summ['headline_gross_J_per_inference_between_schedules']['mean'],
               bench_mean_mA_indep=float(np.mean([x['mean_mA_indep'] for x in bench])))
    # instrument events
    c = ((w >> 18) & 63).astype(np.int16)
    gaps = np.nonzero(c[1:] != (c[:-1] + 1) % 64)[0] + 1
    rep['counter_gaps'] = []
    for g in gaps[:10]:
        lo, hi = max(0, g - 2), min(len(w), g + 3)
        rep['counter_gaps'].append(dict(index=int(g), counters=c[lo:hi].tolist(), ranges=r[lo:hi].tolist(),
                                        adc=adc[lo:hi].tolist(), bits=((w[lo:hi] >> 24) & 255).tolist(),
                                        uA=[round(float(v), 1) for v in ua[lo:hi]]))
    on_idx = int(np.argmax(ua > 5000))           # first sample > 5 mA = output ON
    pk = on_idx + int(np.argmax(ua[on_idx:on_idx + 150_000]))
    rep['power_on'] = dict(first_gt_5mA=on_idx, peak_index=pk, peak_mA=float(ua[pk]) / 1000,
                           peak_ms_after_first=(pk - on_idx) / 100,
                           samples_gt_600mA=int((ua[on_idx:on_idx + 150_000] > 600_000).sum()),
                           samples_gt_1A=int((ua[on_idx:on_idx + 150_000] > 1_000_000).sum()),
                           adc_sat_indices=np.nonzero(adc == 16383)[0].tolist()[:10],
                           non_r4_after_mask=int((r[on_idx + 150_000:] != 4).sum()),
                           first_window_start=min(x['a'] for x in win_rows))
    report['sessions'][label] = rep
    print(label, json.dumps({k: v for k, v in rep.items() if k not in ('per_range',)}, default=float)[:1500])
    print(' per_range', json.dumps(rep['per_range'], default=float))
    del w, adc, r, ua, ua_exact, ua_conv, ua_f, d0, c
hl = [report['sessions'][s]['headline_mJ_indep'] for s in LABELS]
report['aggregate_mJ_indep'] = float(np.mean(hl))
print('aggregate', report['aggregate_mJ_indep'], hl)
(OUT / 'indep_decode.json').write_text(json.dumps(report, indent=1, default=float))
