from pathlib import Path
import struct
import sys
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_schedule as az  # noqa: E402

FS = 100_000
F_CPU = 64e6
UA_PER_COUNT = 100.0       # synthetic linear current map for tests


def synth(segments, counter0=0):
    """segments: list of (seconds, adc, d0). Returns uint32 frames."""
    parts = []
    for seconds, adc, d0 in segments:
        n = int(round(seconds * FS))
        parts.append(np.full(n, (adc & 0x3FFF) | (4 << 14) | ((d0 & 1) << 24), dtype=np.uint32))
    w = np.concatenate(parts)
    c = (np.arange(len(w), dtype=np.uint32) + counter0) % 64
    return w | (c << 18)


def ua_fn(words):
    return (words & 0x3FFF).astype(np.float64) * UA_PER_COUNT


def schedule(cycles=3, pulses=2, idle=0.5, bench=0.8, over=0.4, idle_adc=2000, bench_adc=2600,
             over_adc=2050, n_bench=8, n_over=1000):
    segs = [(0.3, idle_adc, 0)]                      # pre-schedule host time
    table, t = [], 0
    def fw(kind, dur, iters, high, ck=0):
        nonlocal t
        start = int(t * F_CPU) & 0xFFFFFFFF
        t += dur
        table.append(dict(kind=kind, start_cycle=start, end_cycle=int(t * F_CPU) & 0xFFFFFFFF,
                          iterations=iters, checksum=ck, marker_high=high))
    for _ in range(pulses):
        segs += [(0.02, idle_adc, 1), (0.02, idle_adc, 0)]
        fw(4, 0.02, 0, 1); t += 0.02
    for _ in range(cycles):
        segs += [(idle, idle_adc, 0), (bench, bench_adc, 1), (idle, idle_adc, 0), (over, over_adc, 1)]
        fw(1, idle, 0, 0); fw(2, bench, n_bench, 1, 111); fw(1, idle, 0, 0); fw(3, over, n_over, 1, 222)
    segs += [(idle, idle_adc, 0)]
    fw(1, idle, 0, 0)
    params = dict(pulse_count=pulses, cycles=cycles, idle_cycles=int(idle * F_CPU))
    return synth(segs), table, params


class ScheduleTest(unittest.TestCase):
    def test_exact_energy_and_clock(self):
        words, table, params = schedule()
        res = az.analyze_schedule(words, ua_fn, table, params, 5.0,
                                  expected=dict(bench=111, overhead=222))
        self.assertTrue(res['valid'], res['problems'])
        s = res['summary']
        inc = (0.260 - 0.200) * 5.0 * 0.8 / 8
        gross = 0.260 * 5.0 * 0.8 / 8
        self.assertAlmostEqual(s['bench_incremental_J_per_inference']['mean'], inc, places=9)
        self.assertAlmostEqual(s['bench_gross_J_per_inference']['mean'], gross, places=9)
        self.assertAlmostEqual(s['cpu_hz_estimate']['mean'], F_CPU, delta=F_CPU * 1e-6)
        self.assertAlmostEqual(s['overhead_incremental_J_per_iteration']['mean'],
                               (0.205 - 0.200) * 5.0 * 0.4 / 1000, places=12)
        self.assertEqual(len(res['bench']), 3)

    def test_idle_transients_inside_guard_are_excluded(self):
        words, table, params = schedule()
        ua_clean = ua_fn(words)
        d0 = ((words >> 24) & 1).astype(bool)
        runs = az.high_runs(d0)
        bumped = words.copy()
        for a, b in runs:                      # 20 ms elevated tail after each window
            bumped[b:b + 2000] = (bumped[b:b + 2000] & ~np.uint32(0x3FFF)) | np.uint32(2600)
        res = az.analyze_schedule(bumped, ua_fn, table, params, 5.0)
        self.assertTrue(res['valid'], res['problems'])
        self.assertAlmostEqual(res['summary']['idle_power_W']['mean'], 0.2 * 5.0, places=9)

    def test_missing_high_run_is_invalid(self):
        words, table, params = schedule()
        d0 = ((words >> 24) & 1).astype(bool)
        a, b = az.high_runs(d0)[3]
        cut = words.copy()
        cut[a:b] &= ~np.uint32(1 << 24)        # D0 wire dropped for one window
        res = az.analyze_schedule(cut, ua_fn, table, params, 5.0)
        self.assertFalse(res['valid'])

    def test_counter_gap_is_reported(self):
        words, table, params = schedule()
        broken = np.concatenate((words[:5000], words[5064 + 1:]))
        res = az.analyze_schedule(broken, ua_fn, table, params, 5.0)
        self.assertFalse(res['valid'])
        self.assertTrue(any('discontinuit' in p for p in res['problems']))

    def test_checksum_mismatch_is_invalid(self):
        words, table, params = schedule()
        res = az.analyze_schedule(words, ua_fn, table, params, 5.0, expected=dict(bench=1, overhead=222))
        self.assertFalse(res['valid'])

    def test_edge_chatter_is_debounced(self):
        words, table, params = schedule()
        d0 = ((words >> 24) & 1).astype(bool)
        a, b = az.high_runs(d0)[4]
        chat = words.copy()
        chat[a + 1] &= ~np.uint32(1 << 24)          # 1-sample dropout just after an edge
        chat[b + 1] |= np.uint32(1 << 24)           # 1-sample spike just after a falling edge
        res = az.analyze_schedule(chat, ua_fn, table, params, 5.0)
        self.assertTrue(res['valid'], res['problems'])

    def test_pulses(self):
        words = synth([(0.2, 2000, 0)] + [(0.1, 2000, 1), (0.1, 2000, 0)] * 5)
        res = az.analyze_pulses(words, ua_fn, 5, 0.1)
        self.assertTrue(res['passed'])
        floating = synth([(1.0, 2000, 1)])      # unconnected D0 reads HIGH
        self.assertFalse(az.analyze_pulses(floating, ua_fn, 5, 0.1)['passed'])

    def test_expected_checksums_match_firmware_fnv(self):
        outs = [[0x41300000 + i, 1, 2, 3, 4] for i in range(3)]
        ins = [[0x3F800000 + i] + [0] * 40 for i in range(3)]
        b, o = az.expected_checksums(outs, ins, 3, 2, 1)
        h = 2166136261
        for _ in range(2):
            for r in range(3):
                for w in outs[r]:
                    for k in range(4):
                        h = ((h ^ ((w >> (8 * k)) & 0xFF)) * 16777619) & 0xFFFFFFFF
        self.assertEqual(b, h)
        self.assertEqual(o, az.fnv1a_bytes(b''.join(struct.pack('<5I', *ins[r][:5]) for r in range(3))))



class ReviewFixTest(unittest.TestCase):
    def test_last_overhead_has_two_sided_baseline(self):
        words, table, params = schedule()
        params = dict(params, idle_cycles=int(0.5 * F_CPU))
        res = az.analyze_schedule(words, ua_fn, table, params, 5.0)
        self.assertTrue(res['valid'], res['problems'])
        self.assertEqual(len(res['overhead']), 3)
        self.assertEqual(len(res['bench']), 3)
        self.assertAlmostEqual(res['bench'][0]['vs_overhead_J_per_iter'], (0.260 - 0.205) * 5 * 0.8 / 8, places=9)

    def test_range_change_and_overcurrent_are_flagged(self):
        words, table, params = schedule()
        params = dict(params, idle_cycles=int(0.5 * F_CPU))
        a, b = az.high_runs(((words >> 24) & 1).astype(bool))[3]
        w = words.copy()
        w[a + 100:a + 200] = (w[a + 100:a + 200] & ~np.uint32(7 << 14)) | np.uint32(3 << 14)
        self.assertTrue(any('left range R5' in p for p in az.analyze_schedule(w, ua_fn, table, params, 5.0)['problems']))
        big = words.copy()
        big[a + 10:a + 20] = (big[a + 10:a + 20] & ~np.uint32(0x3FFF)) | np.uint32(12000)  # 1.2 A
        self.assertTrue(any('exceeds 1 A' in p for p in az.analyze_schedule(big, ua_fn, table, params, 5.0)['problems']))

    def test_reader_gap_invalidates_and_residual_is_descriptive(self):
        words, table, params = schedule()
        a, b = az.high_runs(((words >> 24) & 1).astype(bool))[4]
        lossy = np.concatenate((words[:a + 1000], words[a + 1064:]))   # counters still mod-64 continuous
        self.assertEqual(len(az.counter_gaps(lossy)), 0)
        res = az.analyze_schedule(lossy, ua_fn, table, params, 5.0)
        self.assertTrue(res['valid'], res['problems'])          # residual alone no longer invalidates
        self.assertLess(min(res['summary']['diagnostics']['bench_sample_residuals']), -50)
        res = az.analyze_schedule(lossy, ua_fn, table, params, 5.0, reader_gaps=[(a + 1000, 0.3)])
        self.assertFalse(res['valid'])
        self.assertTrue(any('reader gap' in p for p in res['problems']))

    def test_sum_and_dwt_energy_agree(self):
        words, table, params = schedule()
        res = az.analyze_schedule(words, ua_fn, table, params, 5.0)
        s = res['summary']
        self.assertAlmostEqual(s['bench_gross_J_per_inference']['mean'] / s['bench_gross_dwt_J_per_inference']['mean'], 1, places=5)

    def test_edge_quantization_is_not_flagged(self):
        words, table, params = schedule()
        d0 = ((words >> 24) & 1).astype(bool)
        w = words.copy()
        for a, b in az.high_runs(d0)[2:]:          # shift every window edge by 2 samples
            w[a - 2:a] |= np.uint32(1 << 24)
            w[b - 2:b] &= ~np.uint32(1 << 24)
        res = az.analyze_schedule(w, ua_fn, table, params, 5.0)
        self.assertTrue(res['valid'], res['problems'])

    def test_sham_null_and_marker_load(self):
        segs = [(0.5, 2000, 0)]
        table = []
        for _ in range(6):
            segs += [(1.0, 2000, 1), (1.0, 2000, 0)]
            table.append(dict(kind=4, start_cycle=0, end_cycle=0, iterations=0, checksum=0, marker_high=1))
        ok = az.analyze_sham(synth(segs), ua_fn, table, 5.0)
        self.assertTrue(ok['valid'], ok['problems'])
        self.assertAlmostEqual(ok['null_dI_mA']['mean'], 0.0, places=9)
        loaded = [(0.5, 2000, 0)] + [(1.0, 2010, 1), (1.0, 2000, 0)] * 6   # +1 mA while marker HIGH
        bad = az.analyze_sham(synth(loaded), ua_fn, table, 5.0)
        self.assertFalse(bad['marker_load_check_passed'])
        self.assertAlmostEqual(bad['null_dI_mA']['mean'], 1.0, places=6)

    def test_ols_and_budget(self):
        fit = az.ols([16, 16, 32, 32, 64, 64], [1.6e-2, 1.61e-2, 3.2e-2, 3.21e-2, 6.4e-2, 6.39e-2])
        self.assertAlmostEqual(fit['slope'], 1e-3, delta=2e-5)
        self.assertTrue(fit['intercept_ci_contains_zero'])
        bud = az.systematic_budget(108.0, s4_A_per_V=0.002760722, gain=0.15)
        self.assertAlmostEqual(bud['incremental_rel_bounds'][0], -(0.15 ** 2 + 0.12 ** 2) ** 0.5, places=9)
        self.assertAlmostEqual(bud['incremental_rel_bounds'][1], (0.15 ** 2 + 0.05 ** 2) ** 0.5, places=9)
        self.assertAlmostEqual(bud['gross_vin_rel'][0], 0.88 * (1 - 0.002760722 * 0.6 * 1000 / 108) - 1, places=9)
        self.assertAlmostEqual(bud['nordic_app_convention_rel'], -0.002760722 * 1000 / 108, places=9)
        w = az.systematic_budget(108.0, gain=0.20)['incremental_worst_case_bounds']
        self.assertAlmostEqual(w[0], 0.8 * 0.88 - 1, places=9)
        self.assertAlmostEqual(w[1], 1.2 * 1.05 - 1, places=9)
        self.assertIsNotNone(bud['gross_rel_bounds'])


if __name__ == '__main__':
    unittest.main()
