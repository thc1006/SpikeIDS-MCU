"""Decode + analyze one EM01 PPK2-powered segment with the registered pipeline
(run_sessions.analyze with the ESP mask, session_summary, ESP platform gates)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, '/home/thc1006/dev/SpikeIDS-MCU/tools/ra4e1_deployment/host_measure')
sys.path.insert(0, '/home/thc1006/dev/SpikeIDS-MCU/tools/esp32s3_deployment/host_measure')
import run_sessions as rs  # noqa: E402
import run_sessions_esp as rse  # noqa: E402

R = Path(sys.argv[1]); label = sys.argv[2]
rec = rs.Recorder(R)
ev = rec.events()
st = [e for e in ev if e['kind'] == 'segment_start' and e['label'] == label][-1]
sp = [e for e in ev if e['kind'] == 'segment_stop' and e['label'] == label][-1]
on = [e for e in ev if e.get('name') == 'output_on' and st['sample_index'] <= e['sample_index'] <= sp['sample_index']][0]
seg = dict(path=st['path'], label=label, frames=sp.get('frames'), sha256=sp.get('sha256'))
res, conv = rs.analyze(rec, seg, rec.session(), st, sp, on, mask_s=rse.MASK_S)
summ = rs.session_summary(res, conv) if res.get('header') else dict(eligible=False, problems=res['problems'])
(R / f'{label}_analysis.json').write_text(json.dumps(dict(res, segment=seg), indent=1, default=str))
(R / f'{label}_summary.json').write_text(json.dumps(summ, indent=1, default=str))
h = res.get('header') or {}
print('platform:', h.get('platform'), '| problems:', res['problems'][:6], '| phase_problems:', res.get('phase_problems', [])[:6])
print('header:', {k: h.get(k) for k in ('stage_name', 'error', 'pq_env', 'parity_mismatched_words', 'schedules_done',
                                         'bench_reps', 'overhead_reps', 'windows_used')}, 'fnv', hex(h.get('parity_outputs_fnv', 0)))
print('snapshot:', h.get('clock_snapshot'))
print('telemetry:', {k: (res.get('telemetry') or {}).get(k) for k in ('frame_words', 'done_high_s', 'extra_bits_after_frame')},
      '| logic_powered_fraction', res.get('logic_powered_fraction'), '| unpowered_before', res.get('unpowered_before'))
for k, v in res.get('phases', {}).items():
    s = v.get('summary', {})
    print(f"{k:24s} valid={v.get('valid')} problems={v.get('problems', [])[:2]}")
    if s:
        g = s['bench_gross_J_per_inference']; t = s['bench_time_s_per_inference']
        print(f"   gross {g['mean']*1e3:.4f} mJ/inf (cv {g['cv']:.2e}), t {t['mean']*1e3:.3f} ms, P_bench {s['bench_power_W']['mean']:.5f} W,"
              f" P_idle {s['idle_power_W']['mean']:.5f} W, inc {s['bench_incremental_J_per_inference']['mean']*1e3:.4f} mJ,"
              f" cpu {s['cpu_hz_estimate']['mean']/1e6:.5f} MHz, range-consistent {v.get('range_consistent_windows')}/{v.get('bench_windows')}")
if 'wiring' in res.get('phases', {}):
    w = res['phases']['wiring']; sh = res['phases']['sham']
    print('wiring widths', [round(x, 4) for x in w.get('widths_s', [])], '| sham dI mA', sh.get('null_dI_mA'))
print('SUMMARY eligible:', summ.get('eligible'), '| gross between schedules:', summ.get('headline_gross_J_per_inference_between_schedules'))
print('incremental (range-consistent):', summ.get('incremental_over_spin_J_per_inference_between_schedules'), '| dominant range', summ.get('dominant_range'))
print('timebase:', res.get('timebase_check'), '| ranges:', res.get('range_histogram_capture'), '| counter_gaps', res.get('counter_gaps'), '| reader_gaps', res.get('reader_gaps'))
