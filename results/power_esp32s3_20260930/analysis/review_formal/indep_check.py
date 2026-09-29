"""Independent re-analysis of the ESP32-S3 formal sessions (review_formal).
Own code throughout; only ppk2_session.Converter is imported (current formula),
and it is itself cross-checked against a from-scratch Nordic formula.
Read-only on the recorder; writes indep_<label>.json next to this script."""
import hashlib
import json
import sys
import zlib
from pathlib import Path

import numpy as np

REPO = Path('/home/thc1006/dev/SpikeIDS-MCU')
BASE = REPO / 'results/power_esp32s3_20260930'
REC = BASE / 'ppk_esp10'
FORMAL = BASE / 'formal_20260930'
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / 'tools/ppk2_energy'))
from ppk2_session import Converter  # noqa: E402

FS = 100_000
V = 5.0
G = 5_000                       # 50 ms guard
MASK = 150_000                  # ON + 1.5 s
TEL_MAGIC = 0x54314D45
EXPECT = dict(bench=3467897573)  # cross-checked against the pipeline below; FNV of outputs is in-telemetry

meta = json.loads((REC / 'session.json').read_text())['metadata']
conv = Converter(meta, V, 'metadata-exact')
M = {k: float(v) for k, v in meta.items() if k[:1] in 'RGOSIU' and k[-1].isdigit()}


def own_ua(w):
    """From-scratch Nordic formula (pc-nrfconnect-ppk getAdcResult), uA."""
    adc = (w & 0x3FFF).astype(np.float64) * 4
    r = ((w >> 14) & 7).astype(np.int64)
    out = np.empty(len(w))
    for k in range(5):
        m = r == k
        if not m.any():
            continue
        x = (adc[m] - M[f'O{k}']) * ((1.8 / 163840) / M[f'R{k}'])
        out[m] = M[f'UG{k}'] * (x * (M[f'GS{k}'] * x + M[f'GI{k}']) + (M[f'S{k}'] * V + M[f'I{k}']))
    out[r > 4] = np.nan
    return out * 1e6


events = [json.loads(l) for l in (REC / 'events.jsonl').read_text().splitlines() if l.strip()]


def ci(x):
    x = np.asarray(x, float)
    n = len(x)
    m = float(x.mean())
    if n < 2:
        return dict(n=n, mean=m)
    from math import sqrt
    tq = {1: 12.706204736174698, 2: 4.302652729911275, 19: 2.093024054408263, 29: 2.045229642132703,
          9: 2.2621571627409915}[n - 1]
    sd = float(x.std(ddof=1))
    h = tq * sd / sqrt(n)
    return dict(n=n, mean=m, sd=sd, ci95=[m - h, m + h], cv=sd / m if m else None)


def crc32_words(ws):
    return zlib.crc32(np.asarray(ws, dtype='<u4').tobytes()) & 0xFFFFFFFF


def fnv(h, data):
    for b in data:
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h


def runs_of(b):
    d = np.diff(np.concatenate(([0], b.astype(np.int8), [0])))
    return np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]


def analyse(idx):
    label = f'esp_session_{idx:02d}'
    st = next(e for e in events if e['kind'] == 'segment_start' and e['label'] == label)
    sp = next(e for e in events if e['kind'] == 'segment_stop' and e['label'] == label)
    on = next(e for e in events if e['kind'] == 'command' and e['name'] == 'output_on'
              and e['sample_index'] >= st['sample_index'])
    off_after = next(e for e in events if e['kind'] == 'command' and e['name'] == 'output_off'
                     and e['sample_index'] >= sp['sample_index'])
    res = dict(label=label)
    path = REC / sp['path']
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 24), b''):
            h.update(chunk)
    res['sha256'] = h.hexdigest()
    res['sha256_matches_segment_stop'] = res['sha256'] == sp['sha256']
    w = np.fromfile(path, dtype='<u4')
    res['frames'] = int(len(w))
    res['frames_match'] = len(w) == sp['frames'] == sp['sample_index'] - st['sample_index']
    on_rel = on['sample_index'] - st['sample_index']
    res['on_rel_samples'] = int(on_rel)
    res['segment_start_to_on_s'] = on_rel / FS
    logic = (w >> 24).astype(np.uint8)
    d0 = (logic & 1).astype(bool)
    powered = (logic & 0xFE) == 0
    rng = ((w >> 14) & 7).astype(np.uint8)
    ctr = ((w >> 18) & 63).astype(np.int16)
    # --- pre-ON state inside the segment
    pre = logic[:on_rel]
    res['pre_on_logic_values'] = sorted(set(np.unique(pre).tolist()))
    ua_pre = conv.ua(w[:on_rel])[0]
    res['pre_on_mean_uA'] = float(ua_pre.mean())
    res['pre_on_max_uA'] = float(ua_pre.max())
    # --- counter gaps
    gp = np.nonzero(ctr[1:] != (ctr[:-1] + 1) % 64)[0] + 1
    res['counter_gaps'] = [dict(sample=int(i), after_on_ms=(int(i) - on_rel) / FS * 1e3,
                                jump=int((ctr[i] - ctr[i - 1]) % 64)) for i in gp]
    # --- power-on D0 artifact and logic power-up in the masked region
    after_on_low = np.nonzero(~d0[on_rel:])[0]
    res['d0_first_low_after_on_ms'] = float(after_on_low[0] / FS * 1e3) if len(after_on_low) else None
    pw = np.nonzero(powered[on_rel:])[0]
    res['logic_first_powered_after_on_ms'] = float(pw[0] / FS * 1e3) if len(pw) else None
    m0 = on_rel + MASK
    r0, f0 = runs_of(d0[on_rel:m0])
    res['masked_region_d0_runs'] = [((int(a)) / FS * 1e3, (int(b)) / FS * 1e3) for a, b in zip(r0, f0)]
    res['masked_region_powered_after_first_fraction'] = float(powered[on_rel + (pw[0] if len(pw) else 0):m0].mean())
    res['d0_at_mask'] = bool(d0[m0])
    # --- D0 runs after the mask
    dm = d0.copy()
    dm[:m0] = False
    ra, rb = runs_of(dm)
    widths = rb - ra
    gaps_low = ra[1:] - rb[:-1]
    res['d0_runs_after_mask'] = int(len(ra))
    res['glitch_runs_le3'] = int((widths <= 3).sum())
    res['glitch_lowgaps_le3'] = int((gaps_low <= 3).sum())
    res['logic_powered_after_mask_fraction'] = float(powered[m0:].mean())
    res['logic_powered_fraction_incl_mask'] = float(powered.mean())
    # --- telemetry
    sync = np.nonzero((widths >= 29_000) & (widths <= 31_000))[0]
    res['sync_candidates'] = sync.tolist()
    k0 = int(sync[0])
    bw = widths[k0 + 1:k0 + 1 + 64]
    bits = (bw > 50).astype(np.uint64)
    head = [int(sum(int(bits[32 * j + b]) << b for b in range(32))) for j in range(2)]
    assert head[0] == TEL_MAGIC, hex(head[0])
    count = head[1]
    nbits = (count + 3) * 32
    bw = widths[k0 + 1:k0 + 1 + nbits]
    assert len(bw) == nbits
    zero, one = bw[bw <= 50], bw[bw > 50]
    res['tel_bit_width_samples'] = dict(zero=[int(zero.min()), int(zero.max())], one=[int(one.min()), int(one.max())])
    per = ra[k0 + 2:k0 + 1 + nbits] - ra[k0 + 1:k0 + nbits]
    res['tel_bit_period_samples'] = [int(per.min()), int(per.max())]
    B = (bw > 50).astype(np.uint64).reshape(-1, 32)
    words = (B << np.arange(32, dtype=np.uint64)).sum(axis=1).astype(np.uint64).tolist()
    words = [int(x) for x in words]
    res['tel_words'] = len(words)
    res['tel_crc_ok'] = crc32_words(words[:count + 2]) == words[count + 2]
    hd = words[2:2 + 64]
    names = ('magic version struct_bytes stage error error_detail system_core_clock psram_enabled pq_env chip_info '
             'timer_ctrl schedules_done parity_mismatched_words parity_first_bad_row parity_outputs_fnv parity_rows '
             'cyc_lo cyc_hi cyc_min cyc_max cal_bench_cycles cal_overhead_cycles n_rows bench_reps overhead_reps cycles '
             'idle_cycles pulse_cycles pulse_count wiring_cycles wiring_pulses sham_cycles sham_pulses gap_cycles '
             'n_schedules windows_used').split()
    H = dict(zip(names, hd))
    H['multiplier'] = hd[36:44]
    for i, n in enumerate('telemetry_words settle_cycles timer_id cal_checksum'.split()):
        H[n] = hd[44 + i]
    H['model_sha_prefix'] = f'{hd[48]:08x}{hd[49]:08x}'
    H['vectors_sha_prefix'] = f'{hd[50]:08x}{hd[51]:08x}'
    for i, n in enumerate('apb_hz xtal_hz cpu_hz_clk reset_reason marker_gpio tick_hz core_id flash_bytes '
                          'idf_version cpu_per_conf sysclk_conf reserved_fc'.split()):
        H[n] = hd[52 + i]
    H['error'] = H['error'] - (1 << 32) if H['error'] >= 1 << 31 else H['error']
    res['header'] = {k: (hex(v) if k in ('magic', 'parity_outputs_fnv', 'timer_id', 'cpu_per_conf', 'sysclk_conf')
                         else v) for k, v in H.items()}
    cpc, scc = H['cpu_per_conf'], H['sysclk_conf']
    gates = dict(
        magic_EM01=H['magic'] == 0x31304D45, version_1=H['version'] == 1,
        stage_TELEMETRY=H['stage'] == 7, error_0=H['error'] == 0, pq_env_1=H['pq_env'] == 1,
        timer_CCNT=H['timer_id'] == 0x544E4343,
        parity=H['parity_rows'] == 1024 and H['parity_mismatched_words'] == 0 and H['parity_outputs_fnv'] == 0xccc5eb8b,
        schedules_5=H['schedules_done'] == 5 and H['n_schedules'] == 5,
        apb80=H['apb_hz'] == 80_000_000, xtal40=H['xtal_hz'] == 40_000_000, cpu240=H['cpu_hz_clk'] == 240_000_000,
        marker_gpio5=H['marker_gpio'] == 5, flash16MiB=H['flash_bytes'] == 16 * 1024 * 1024,
        cpuperiod_sel2=(cpc & 3) == 2, pll_freq_sel1=((cpc >> 2) & 1) == 1, soc_clk_sel1=((scc >> 10) & 3) == 1,
        reset_POWERON=H['reset_reason'] == 1, core0=H['core_id'] == 0,
        model_prefix=H['model_sha_prefix'] == '22dc7979340c34af', vectors_prefix=H['vectors_sha_prefix'] == 'cb5b3415cdbfb8a2',
        tel_words_consistent=count == 64 + 5 * H['windows_used'] == H['telemetry_words'],
    )
    res['boot_gates'] = gates
    nw = H['windows_used']
    W = []
    for i in range(nw):
        a = words[2 + 64 + 5 * i:2 + 64 + 5 * i + 5]
        W.append(dict(kind=a[0] & 0xFF, marker_high=(a[0] >> 8) & 0xFF, phase=a[0] >> 16, start_cycle=a[1],
                      end_cycle=a[2], iterations=a[3], checksum=a[4]))
    high = [x for x in W if x['marker_high']]
    res['fw_windows'] = nw
    res['fw_high_windows'] = len(high)
    res['pre_telemetry_runs'] = k0
    res['runs_eq_high_windows'] = k0 == len(high)
    # DONE run
    kd = k0 + 1 + nbits
    res['runs_after_frame'] = int(len(ra) - kd)
    res['done_run_s'] = float((rb[kd] - ra[kd]) / FS) if kd < len(ra) else None
    res['done_run_reaches_segment_end'] = bool(kd < len(ra) and rb[kd] == len(w))
    res['done_powered_fraction'] = float(powered[ra[kd]:rb[kd]].mean()) if kd < len(ra) else None
    # pipeline comparison of the window table
    A = json.loads((FORMAL / f'{label}_analysis.json').read_text())
    pw_tab = [{k: x[k] for k in ('kind', 'marker_high', 'phase', 'start_cycle', 'end_cycle', 'iterations', 'checksum')}
              for x in A['windows']]
    res['window_table_equals_pipeline'] = pw_tab == W
    res['unpowered_before_equals_mask'] = A['unpowered_before'] == m0
    # one-to-one run/window mapping: durations against cycles
    f_est = []
    resid = []
    for j, x in enumerate(high):
        cyc = (x['end_cycle'] - x['start_cycle']) & 0xFFFFFFFF
        dur = (rb[j] - ra[j]) / FS
        if x['kind'] in (2, 3):
            f_est.append(cyc / dur)
    fmed = float(np.median(f_est))
    for j, x in enumerate(high):
        cyc = (x['end_cycle'] - x['start_cycle']) & 0xFFFFFFFF
        resid.append(float((rb[j] - ra[j]) - cyc / fmed * FS))
    res['run_vs_cycles_residual_samples_maxabs'] = float(np.max(np.abs(resid)))
    res['cpu_hz_median'] = fmed
    # pipeline per-phase windows vs my runs (absolute samples)
    phase_names = {0: 'wiring', 1: 'sham', 2: 'schedule_00_repeat1', 3: 'schedule_01_repeat1',
                   4: 'schedule_02_repeat1', 5: 'schedule_03_dose2', 6: 'schedule_04_dose4'}
    mism = 0
    compared = 0
    for ph in range(2, 7):
        P = A['phases'][phase_names[ph]]
        js = [j for j, x in enumerate(high) if x['phase'] == ph]
        for k, j in enumerate(js):
            pwn = P['windows'][k]
            compared += 1
            if (P['slice'][0] + pwn['start_sample'], P['slice'][0] + pwn['stop_sample']) != (int(ra[j]), int(rb[j])):
                mism += 1
    res['pipeline_run_edges_compared'] = compared
    res['pipeline_run_edges_mismatched'] = mism
    wj = [j for j, x in enumerate(high) if x['phase'] == 0]
    res['wiring_widths_s'] = [float((rb[j] - ra[j]) / FS) for j in wj]
    res['wiring_widths_equal_pipeline'] = np.allclose(res['wiring_widths_s'], A['phases']['wiring']['widths_s'], rtol=0, atol=1e-12)
    # slice-level checks: logic powered, counter gaps, ranges
    phase_span = {}
    for ph in range(0, 7):
        js = [j for j, x in enumerate(high) if x['phase'] == ph]
        phase_span[ph] = (int(ra[js[0]]) - 100_000, int(rb[js[-1]]) + 300_000)
    res['analysed_extent_after_on_s'] = [(phase_span[0][0] - on_rel) / FS, (phase_span[6][1] - on_rel) / FS]
    res['counter_gaps_inside_analysed_extent'] = int(sum(phase_span[0][0] <= g['sample'] < phase_span[6][1]
                                                         for g in res['counter_gaps']))
    res['unpowered_frames_in_analysed_extent'] = int((~powered[phase_span[0][0]:phase_span[6][1]]).sum())
    for pn in A['phases'].values():
        a_, b_ = pn['slice']
        assert powered[a_:b_].all(), 'logic unpowered in pipeline slice'
    res['all_pipeline_slices_powered'] = True
    res['range_hist_analysed_extent'] = np.bincount(rng[phase_span[0][0]:phase_span[6][1]], minlength=8).tolist()
    # ---- energy per BENCH window
    sched = {}
    own_vs_conv = 0.0
    for ph in range(2, 7):
        js = [j for j, x in enumerate(high) if x['phase'] == ph]
        rows = []
        for jj, j in enumerate(js):
            x = high[j]
            if x['kind'] != 2:
                continue
            a, b = int(ra[j]), int(rb[j])
            u = conv.ua(w[a:b])[0]
            if ph == 2 and not own_vs_conv:
                own_vs_conv = float(np.max(np.abs(own_ua(w[a:b]) - u) / np.abs(u)))
            e = V * u.sum() * 1e-6 / FS
            # neighbours: previous and next D0 run (any kind)
            ib = (int(rb[j - 1]) + G, a - G)
            ia = (b + G, int(ra[j + 1]) - G)
            pib = V * conv.ua(w[ib[0]:ib[1]])[0].mean() * 1e-6
            pia = V * conv.ua(w[ia[0]:ia[1]])[0].mean() * 1e-6
            dur = (b - a) / FS
            pwin = e / dur
            rows.append(dict(j=j, a=a, b=b, iterations=x['iterations'], checksum=x['checksum'],
                             gross=e / x['iterations'], t_inf=dur / x['iterations'], p_bench=pwin,
                             incr=(pwin - (pib + pia) / 2) * dur / x['iterations'],
                             ranges=np.bincount(rng[a:b], minlength=5)[:5].tolist(),
                             range_switches=int((np.diff(rng[a:b]) != 0).sum()),
                             idle_ranges_ok=bool((rng[ib[0]:ib[1]] == 4).all() and (rng[ia[0]:ia[1]] == 4).all()),
                             powered=bool(powered[a:b].all()), max_uA=float(u.max()),
                             cycles=(x['end_cycle'] - x['start_cycle']) & 0xFFFFFFFF))
        sched[ph] = rows
    res['own_formula_vs_Converter_max_rel'] = own_vs_conv
    pipe = {ph: A['phases'][phase_names[ph]]['bench'] for ph in range(2, 7)}
    maxrel = 0.0
    maxrel_inc = 0.0
    for ph in range(2, 7):
        for r_, p_ in zip(sched[ph], pipe[ph]):
            maxrel = max(maxrel, abs(r_['gross'] / p_['gross_J_per_iter'] - 1))
            maxrel_inc = max(maxrel_inc, abs(r_['incr'] / p_['incremental_J_per_iter'] - 1))
        assert len(sched[ph]) == len(pipe[ph])
    res['bench_gross_max_rel_diff_vs_pipeline'] = maxrel
    res['bench_incr_max_rel_diff_vs_pipeline'] = maxrel_inc
    rep = [sched[ph] for ph in (2, 3, 4)]
    res['bench_checks'] = dict(
        n_repeat_windows=sum(len(r) for r in rep),
        iterations=sorted(set(r['iterations'] for rr in rep for r in rr)),
        checksum_ok=all(r['checksum'] == EXPECT['bench'] for rr in rep for r in rr),
        all_R4=all(r['ranges'][4] == r['b'] - r['a'] for rr in rep for r in rr),
        switches=sum(r['range_switches'] for rr in rep for r in rr),
        idle_R4=all(r['idle_ranges_ok'] for rr in rep for r in rr),
        powered=all(r['powered'] for rr in rep for r in rr),
        max_mA=max(r['max_uA'] for rr in rep for r in rr) / 1000,
        dose_iterations=[sorted(set(r['iterations'] for r in sched[ph])) for ph in (5, 6)],
        dose_checksums=[sorted(set(r['checksum'] for r in sched[ph])) for ph in (5, 6)],
        dose_all_R4=all(r['ranges'][4] == r['b'] - r['a'] for ph in (5, 6) for r in sched[ph]))
    per_sched = [float(np.mean([r['gross'] for r in rr])) for rr in rep]
    res['per_schedule_gross_mJ'] = [x * 1e3 for x in per_sched]
    res['headline_gross_J'] = float(np.mean(per_sched))
    res['headline_ci_between_schedules'] = ci(per_sched)
    res['incremental_J'] = float(np.mean([np.mean([r['incr'] for r in rr]) for rr in rep]))
    res['t_inf_s'] = float(np.mean([r['t_inf'] for rr in rep for r in rr]))
    res['p_bench_W'] = float(np.mean([r['p_bench'] for rr in rep for r in rr]))
    res['per_window_gross_mJ'] = [[r['gross'] * 1e3 for r in rr] for rr in rep]
    res['dose_window_gross_per_inf_mJ'] = {ph: [r['gross'] * 1e3 for r in sched[ph]] for ph in (5, 6)}
    # OLS gross window energy vs N over all 50 windows (descriptive)
    N = np.array([r['iterations'] for ph in range(2, 7) for r in sched[ph]], float)
    E = np.array([r['gross'] * r['iterations'] for ph in range(2, 7) for r in sched[ph]])
    X = np.vstack([N, np.ones_like(N)]).T
    beta = np.linalg.lstsq(X, E, rcond=None)[0]
    res['ols_slope_mJ'] = float(beta[0] * 1e3)
    res['ols_intercept_mJ'] = float(beta[1] * 1e3)
    # ---- sham (registered estimator, own code)
    sj = [j for j, x in enumerate(high) if x['phase'] == 1]
    width = int(np.median([rb[j] - ra[j] for j in sj]))

    def mI(a, b):
        return float(conv.ua(w[a:b])[0].mean()) / 1000

    dI = []
    for k, j in enumerate(sj):
        hi = mI(ra[j] + G, rb[j] - G)
        lows = []
        if k > 0:
            lows.append(mI(rb[sj[k - 1]] + G, ra[j] - G))
        end = ra[sj[k + 1]] if k + 1 < len(sj) else rb[j] + width
        lows.append(mI(rb[j] + G, end - G))
        dI.append(hi - float(np.mean(lows)))
    res['sham_dI_mA'] = ci(dI)
    res['sham_dI_max_abs_diff_vs_pipeline'] = float(np.max(np.abs(np.array(dI) - np.array(
        [x['dI_mA'] for x in A['phases']['sham']['windows']]))))
    res['sham_ranges'] = np.bincount(rng[int(ra[sj[0]]) - 190_000:int(rb[sj[-1]]) + 300_000], minlength=5)[:5].tolist()
    # ---- Amendment 3 C1-C3 (own implementation of the registered text)

    def span(x0, x1):
        x0, x1 = int(x0) + G, int(x1) - G
        return mI(x0, x1) if x1 - x0 > 20_000 else None

    c = dict(schedules={})
    idle_all, final_all = [], []
    for ph in range(2, 7):
        js = [j for j, x in enumerate(high) if x['phase'] == ph]
        pre3, body = js[:3], js[3:]
        assert [high[j]['kind'] for j in pre3] == [4, 4, 4]
        bj = [j for j in body if high[j]['kind'] == 2]
        oj = [j for j in body if high[j]['kind'] == 3]
        before = [span(rb[oj[i - 1]] if i else rb[pre3[-1]], ra[bj[i]]) for i in range(10)]
        after = [span(rb[bj[i]], ra[oj[i]]) for i in range(10)]
        final = span(rb[oj[9]], rb[oj[9]] + 100_000)
        d = float(np.mean(before) - np.mean(after))
        c['schedules'][ph] = dict(before=float(np.mean(before)), after=float(np.mean(after)), C1=d,
                                  C1_pass=abs(d) <= 0.25, final=final)
        idle_all += before + after
        final_all.append(final)
    c['C2'] = float(np.mean(final_all) - np.mean(idle_all))
    sl = [span(rb[sj[k]], ra[sj[k + 1]] if k + 1 < len(sj) else rb[sj[k]] + 100_000) for k in range(len(sj))]
    gb = span(ra[sj[0]] - 190_000, ra[sj[0]])
    ga = span(rb[sj[-1]] + 105_000, rb[sj[-1]] + 295_000)
    c['C3'] = [float(np.mean(sl) - gb), float(np.mean(sl) - ga)]
    c['PASS'] = all(v['C1_pass'] for v in c['schedules'].values()) and abs(c['C2']) <= 0.5 and all(
        abs(x) <= 0.5 for x in c['C3'])
    L = json.loads((FORMAL / f'{label}_lowspan.json').read_text())
    c['max_abs_diff_vs_pipeline_mA'] = float(max(
        [abs(c['schedules'][ph]['C1'] - list(L['schedules'].values())[ph - 2]['C1_diff_mA']) for ph in range(2, 7)]
        + [abs(c['C2'] - L['C2_final_minus_idle_mA'])] + [abs(a - b) for a, b in zip(c['C3'], L['C3_diffs_mA'])]))
    # time-resolved idle current (warm-up trajectory): every IDLE span mean vs time after ON
    traj = []
    for ph in range(2, 7):
        js = [j for j, x in enumerate(high) if x['phase'] == ph]
        for j in js[3:]:
            if high[j]['kind'] == 2:
                traj.append(((ra[j] - on_rel) / FS, span(rb[j - 1], ra[j])))
    res['idle_before_bench_traj'] = [(float(t), v) for t, v in traj]
    res['lowspan'] = c
    res['off_event_after_segment_s'] = (off_after['sample_index'] - sp['sample_index']) / FS
    res['pipeline_headline'] = json.loads((FORMAL / f'{label}_summary.json').read_text())[
        'headline_gross_J_per_inference_between_schedules']['mean']
    res['headline_rel_diff_vs_pipeline'] = res['headline_gross_J'] / res['pipeline_headline'] - 1
    del w
    return res


if __name__ == '__main__':
    for i in [int(x) for x in sys.argv[1:]] or [1, 2, 3]:
        r = analyse(i)
        (OUT / f"indep_{r['label']}.json").write_text(json.dumps(r, indent=1, default=float) + '\n')
        print(json.dumps({k: r[k] for k in ('label', 'sha256_matches_segment_stop', 'frames_match', 'headline_gross_J',
                                            'pipeline_headline', 'headline_rel_diff_vs_pipeline',
                                            'bench_gross_max_rel_diff_vs_pipeline')}, default=float))


def expected_checksums():
    """FNV-1a of the embedded reference outputs: full 1024-row parity FNV and the
    BENCH checksum (rows 0..15, bench_reps 4/8/16), own implementation."""
    import re
    src = (REPO / 'tools/ra4e1_deployment/firmware_measure/build_03/rm_vectors.c').read_text()
    sha = re.search(r'rm_vectors_sha256\[65\]\s*=\s*"([0-9a-f]{64})"', src)
    body = src[src.index('rm_expected[5120]'):]
    body = body[body.index('{') + 1:body.index('}')]
    vals = [int(t, 0) for t in re.findall(r'0x[0-9a-fA-F]+|\d+', body)]
    assert len(vals) == 5120, len(vals)
    le = np.asarray(vals, dtype='<u4')
    par = fnv(2166136261, le.tobytes())
    out = dict(vectors_sha256=sha.group(1) if sha else None, parity_fnv=hex(par))
    for reps in (4, 8, 16):
        out[f'bench_reps{reps}'] = fnv(2166136261, np.tile(le[:80], reps).tobytes())
    return out
