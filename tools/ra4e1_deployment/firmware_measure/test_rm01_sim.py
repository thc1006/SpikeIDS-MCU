"""End-to-end host simulation of RM01: the real rm01.c (with a timing shim),
the real portable_qdq.c + model.c + embedded vectors, a synthetic PPK2 stream
built from the simulated marker/activity trace, then the real decoder and the
SM07M analysis. Also checks the fail-closed path on a corrupted inference."""
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'host_measure'))
import build  # noqa: E402
import rm01_decode as rd  # noqa: E402

PQ = REPO / 'tools/board_deployment/portable_qdq'
MODEL_C = REPO / 'results/portable_qdq_native_20260925_01/model_sources/model.c'
FLAGS = ['-std=c11', '-O2', '-fno-fast-math', '-ffp-contract=off', '-fexcess-precision=standard',
         '-Wall', '-Wextra', '-Werror']
BASE_UA, INFER_EXTRA_UA = 25_000.0, 5_000.0     # synthetic board current: 25 mA + 5 mA while inferring


def ua_fn(words):
    return (words & 0x3FFF).astype(np.float64) * 10.0


def compile_sim(tmp):
    text, _ = build.vectors_c(build.BUNDLE / 'validation_vectors.npz')
    (tmp / 'rm_vectors.c').write_text(text)
    inc = ['-I', str(HERE / 'sim'), '-I', str(HERE), '-I', str(PQ)]
    objs = []
    for src, extra in ((HERE / 'rm01.c', ['-Dpq_infer=sim_pq_infer']), (HERE / 'sim/sim_main.c', []),
                       (PQ / 'portable_qdq.c', []), (MODEL_C, ['-Wno-error']), (tmp / 'rm_vectors.c', [])):
        obj = tmp / (src.stem + '.o')
        subprocess.run(['cc', *FLAGS, *extra, *inc, '-c', str(src), '-o', str(obj)], check=True)
        objs.append(str(obj))
    exe = tmp / 'rm01_sim'
    subprocess.run(['cc', *objs, '-lm', '-o', str(exe)], check=True)
    return exe


def run_sim(exe, tmp, corrupt=None):
    env = dict(os.environ)
    if corrupt is not None:
        env['SIM_CORRUPT_CALL'] = str(corrupt)
    tr, blk = tmp / f'trace_{corrupt}.txt', tmp / f'block_{corrupt}.bin'
    subprocess.run([str(exe), str(tr), str(blk)], check=True, env=env, timeout=600)
    t = np.loadtxt(tr, dtype=np.int64)
    return t, blk.read_bytes()


def synth_words(trace, lead_unpowered=0, active_range=3):
    """PPK2-like frames at 1000 cycles/sample: counter bits, D0 = marker,
    range 3 (active_range while inferring), ADC = current / 10 uA. The first
    `lead_unpowered` samples model the board still off: all 8 logic bits read 1
    (logic-port VCC absent) and zero current, as the real PPK2 reports."""
    n = int(trace[-1, 0] // 1000) + 1
    starts = np.minimum((trace[:, 0] + 999) // 1000, n)      # first sample at/after each change
    marker = np.zeros(n, np.uint32)
    act = np.zeros(n, np.uint32)
    for k in range(len(trace)):
        a, b = starts[k], (starts[k + 1] if k + 1 < len(trace) else n)
        marker[a:b] = trace[k, 1]
        act[a:b] = trace[k, 2]
    code = np.round((BASE_UA + INFER_EXTRA_UA * act) / 10.0).astype(np.uint32)
    rng = np.where(act == 1, active_range, 3).astype(np.uint32)
    bits = marker
    if lead_unpowered:
        code = np.concatenate((np.zeros(lead_unpowered, np.uint32), code))
        rng = np.concatenate((np.full(lead_unpowered, 3, np.uint32), rng))
        bits = np.concatenate((np.full(lead_unpowered, 0xFF, np.uint32), bits))
        n += lead_unpowered
    counter = (np.arange(n, dtype=np.uint32) % 64) << 18
    return code | (rng << 14) | counter | (bits << 24)


def ram_block(raw):
    words = struct.unpack(f'<{len(raw) // 4}I', raw)
    h = rd.parse_header(list(words[:rd.HEADER_WORDS]))
    wins = []
    for i in range(h['windows_used']):
        k, s, e, it, ck, mh, ph, _ = words[rd.HEADER_WORDS + 8 * i: rd.HEADER_WORDS + 8 * i + 8]
        wins.append(dict(index=i, kind=k, marker_high=mh, phase=ph, start_cycle=s, end_cycle=e,
                         iterations=it, checksum=ck))
    return h, wins


class Rm01SimTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls.tmpdir.name)
        cls.exe = compile_sim(cls.tmp)
        z = np.load(build.BUNDLE / 'validation_vectors.npz')
        cls.inputs = [tuple(r) for r in np.ascontiguousarray(z['x'], '<f4').view('<u4')]
        cls.outputs = [tuple(r) for r in np.ascontiguousarray(z['reference_logits'], '<f4').view('<u4')]

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_full_session_decodes_and_analyzes(self):
        trace, raw = run_sim(self.exe, self.tmp)
        words = synth_words(trace, lead_unpowered=150_000)     # 1.5 s before the board powers up
        res = rd.analyze_capture(words, ua_fn, 5.0, self.inputs, self.outputs)
        self.assertEqual(res['problems'], [])
        h, wins = ram_block(raw)
        tel = res['header']
        self.assertEqual(h['stage_name'], 'DONE')
        self.assertEqual(tel['stage_name'], 'TELEMETRY')
        for key in rd.FIELDS:
            if key != 'stage':
                self.assertEqual(tel[key], h[key], key)
        self.assertEqual(res['windows'], wins)
        self.assertTrue(rd.clock_ok(tel['clock_snapshot']))
        self.assertNotEqual(tel['cal_checksum'], 0)
        self.assertEqual(len(wins), 5 + 20 + 5 * 44)
        self.assertEqual(tel['parity_mismatched_words'], 0)
        self.assertGreaterEqual(res['telemetry']['done_high_s'], 0.4)
        phases = res['phases']
        self.assertEqual(list(phases), ['wiring', 'sham', 'schedule_00_repeat1', 'schedule_01_repeat1',
                                        'schedule_02_repeat1', 'schedule_03_dose2', 'schedule_04_dose4'])
        for label, r in phases.items():
            self.assertTrue(r['valid'], (label, r.get('problems')))
        self.assertAlmostEqual(phases['sham']['null_dI_mA']['mean'], 0.0, places=6)
        t_inf = 2_500_000 / 100e6
        for label, r in phases.items():
            if not label.startswith('schedule'):
                continue
            s = r['summary']
            self.assertAlmostEqual(s['cpu_hz_estimate']['mean'] / 100e6, 1.0, delta=1e-3)
            gross = s['bench_gross_J_per_inference']['mean']
            inc = s['bench_incremental_J_per_inference']['mean']
            self.assertAlmostEqual(gross / (5.0 * 0.030 * t_inf), 1.0, delta=0.005, msg=label)
            self.assertAlmostEqual(inc / (5.0 * 0.005 * t_inf), 1.0, delta=0.01, msg=label)
            self.assertEqual(len(r['bench']), 10)
            self.assertEqual(r['range_consistent_windows'], 10)
            self.assertEqual({x['iterations'] for x in r['bench']},
                             {r['params']['bench_reps'] * 16})

    def test_leading_unpowered_high_does_not_break_decoding(self):
        trace, _ = run_sim(self.exe, self.tmp)
        words = synth_words(trace, lead_unpowered=100_000)
        raw_d0 = ((words >> 24) & 1).astype(bool)
        self.assertTrue(raw_d0[0])                                 # the B1 artefact is present
        d0, powered = rd.logic_d0(words)
        self.assertFalse(d0[:100_000].any())
        self.assertFalse(powered[:100_000].any())

    def test_range_switch_during_inference_blocks_incremental_only(self):
        trace, _ = run_sim(self.exe, self.tmp)
        words = synth_words(trace, active_range=4)
        res = rd.analyze_capture(words, ua_fn, 5.0, self.inputs, self.outputs)
        self.assertEqual(res['problems'], [])
        r = res['phases']['schedule_00_repeat1']
        self.assertEqual(r['range_consistent_windows'], 0)
        self.assertIsNone(r['incremental_J_per_inference_range_consistent']['mean'])
        gross = r['summary']['bench_gross_J_per_inference']['mean']
        self.assertAlmostEqual(gross / (5.0 * 0.030 * 0.025), 1.0, delta=0.005)

    def test_decode_failure_is_reported_not_raised(self):
        trace, _ = run_sim(self.exe, self.tmp)
        words = synth_words(trace)
        words = words[: len(words) // 2]                           # capture ends before telemetry
        res = rd.analyze_capture(words, ua_fn, 5.0, self.inputs, self.outputs)
        self.assertIsNone(res['header'])
        self.assertTrue(res['problems'][0].startswith('telemetry decode failed'))

    def test_corrupted_inference_fails_closed(self):
        trace, raw = run_sim(self.exe, self.tmp, corrupt=7)
        words = synth_words(trace)
        res = rd.analyze_capture(words, ua_fn, 5.0, self.inputs, self.outputs)
        h = res['header']
        self.assertEqual(h['stage_name'], 'ERROR')
        self.assertEqual(h['error'], -203)
        self.assertEqual(h['parity_first_bad_row'], 7)
        self.assertEqual(h['parity_mismatched_words'], 1)
        self.assertEqual(h['windows_used'], 0)
        self.assertEqual(h['schedules_done'], 0)
        self.assertEqual(res['phases'], {})
        self.assertTrue(any('self-parity' in p for p in res['problems']))

    def test_bit_error_breaks_crc(self):
        trace, _ = run_sim(self.exe, self.tmp)
        words = synth_words(trace)
        d0 = ((words >> 24) & 1).astype(bool)
        _, _, tel, _ = rd.decode_telemetry(d0)
        runs = rd.az.high_runs(d0)
        a, b = runs[tel['sync_run_index'] + 1 + 32 * 10 + 3]      # a bit inside the header
        d0[a:b] = False
        d0[a:a + (75 if b - a < 50 else 25)] = True              # flip its width class
        with self.assertRaises(rd.DecodeError):
            rd.decode_telemetry(d0)


if __name__ == '__main__':
    unittest.main()
