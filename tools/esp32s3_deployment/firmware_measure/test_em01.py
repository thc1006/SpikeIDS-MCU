"""EM01 (ESP32-S3) offline tests: provenance of the derived source and an
end-to-end host simulation through the shared decoder and SM07M analysis."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / 'tools/ra4e1_deployment/host_measure'))
import derive_em01  # noqa: E402
import rm01_decode as rd  # noqa: E402

PQ = REPO / 'tools/board_deployment/portable_qdq'
MODEL_C = REPO / 'results/portable_qdq_native_20260925_01/model_sources/model.c'
NPZ = REPO / 'results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq/validation_vectors.npz'
FLAGS = ['-std=gnu11', '-O2', '-fno-fast-math', '-ffp-contract=off', '-fexcess-precision=standard',
         '-Wall', '-Wextra', '-Werror']
CYCLES_PER_SAMPLE = 2400                     # 240 MHz / 100 kS/s
BASE_UA, INFER_EXTRA_UA = 25_000.0, 5_000.0
T_INF = 1_200_000 / 240e6
MEASUREMENT_FUNCTIONS = ['wait_cycles', 'ms_cycles', 'fnv1a', 'crc32_word', 'fail', 'infer_row',
                         'overhead_row', 'window_begin', 'window_end', 'pulses', 'run_parity', 'calibrate',
                         'run_schedule', 'tel_word', 'telemetry', 'hex_prefix']


def function_text(src, name):
    m = re.search(r'^(static [^\n]*\b' + name + r'\(|void ' + name + r'\()', src, re.M)
    assert m, name
    i = src.index('{', m.start())
    depth = 0
    for j in range(i, len(src)):
        depth += {'{': 1, '}': -1}.get(src[j], 0)
        if depth == 0:
            return src[m.start():j + 1]
    raise AssertionError(name)


def ua_fn(words):
    return (words & 0x3FFF).astype(np.float64) * 10.0


def vectors_c(tmp):
    import importlib.util
    spec = importlib.util.spec_from_file_location('rm01_build', REPO / 'tools/ra4e1_deployment/firmware_measure/build.py')
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    text, _ = b.vectors_c(b.BUNDLE / 'validation_vectors.npz')
    (tmp / 'rm_vectors.c').write_text(text.replace('#include "rm01.h"', '#include "em01.h"', 1))


def compile_sim(tmp):
    vectors_c(tmp)
    inc = ['-I', str(HERE / 'sim'), '-I', str(HERE), '-I', str(PQ)]
    objs = []
    for src, extra in ((HERE / 'em01.c', ['-DEM01_HOST_SIM', '-Dpq_infer=sim_pq_infer']),
                       (HERE / 'sim/sim_main.c', ['-DEM01_HOST_SIM']), (PQ / 'portable_qdq.c', []),
                       (MODEL_C, ['-Wno-error']), (tmp / 'rm_vectors.c', [])):
        obj = tmp / (src.stem + '.o')
        subprocess.run(['cc', *FLAGS, *extra, *inc, '-c', str(src), '-o', str(obj)], check=True)
        objs.append(str(obj))
    exe = tmp / 'em01_sim'
    subprocess.run(['cc', *objs, '-lm', '-o', str(exe)], check=True)
    return exe


def run_sim(exe, tmp, corrupt=None):
    env = dict(os.environ)
    if corrupt is not None:
        env['SIM_CORRUPT_CALL'] = str(corrupt)
    tr, blk = tmp / f'trace_{corrupt}.txt', tmp / f'block_{corrupt}.bin'
    subprocess.run([str(exe), str(tr), str(blk)], check=True, env=env, timeout=900)
    return np.loadtxt(tr, dtype=np.int64), blk.read_bytes()


def synth_words(trace):
    n = int(trace[-1, 0] // CYCLES_PER_SAMPLE) + 1
    starts = np.minimum((trace[:, 0] + CYCLES_PER_SAMPLE - 1) // CYCLES_PER_SAMPLE, n)
    marker = np.zeros(n, np.uint32); act = np.zeros(n, np.uint32)
    for k in range(len(trace)):
        a, b = starts[k], (starts[k + 1] if k + 1 < len(trace) else n)
        marker[a:b] = trace[k, 1]; act[a:b] = trace[k, 2]
    code = np.round((BASE_UA + INFER_EXTRA_UA * act) / 10.0).astype(np.uint32)
    counter = (np.arange(n, dtype=np.uint32) % 64) << 18
    return code | (3 << 14) | counter | (marker << 24)


class Em01Provenance(unittest.TestCase):
    def test_em01_is_derived_from_rm01(self):
        self.assertEqual((HERE / 'em01.c').read_text(), derive_em01.derive(derive_em01.RM01.read_text()))

    def test_measurement_functions_identical(self):
        rm, em = derive_em01.RM01.read_text(), (HERE / 'em01.c').read_text()
        for name in MEASUREMENT_FUNCTIONS:
            self.assertEqual(function_text(em, name), function_text(rm, name), name)

    def test_header_layout_matches_rm01(self):
        rm_h = (REPO / 'tools/ra4e1_deployment/firmware_measure/rm01.h').read_text()
        em_h = (HERE / 'em01.h').read_text()
        for pat in (r'_Static_assert\(offsetof\(rm_result_t, parity_mismatched_words\) == 0x30',
                    r'_Static_assert\(offsetof\(rm_result_t, window\) == RM_HEADER_WORDS \* 4',
                    r'_Static_assert\(sizeof\(rm_result_t\) == 0x100 \+ 32 \* RM_MAX_WINDOWS'):
            self.assertTrue(re.search(pat, rm_h) and re.search(pat, em_h), pat)


class Em01Simulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls.tmpdir.name)
        cls.exe = compile_sim(cls.tmp)
        z = np.load(NPZ)
        cls.ins = [tuple(r) for r in np.ascontiguousarray(z['x'], '<f4').view('<u4')]
        cls.outs = [tuple(r) for r in np.ascontiguousarray(z['reference_logits'], '<f4').view('<u4')]

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_full_session(self):
        trace, raw = run_sim(self.exe, self.tmp)
        res = rd.analyze_capture(synth_words(trace), ua_fn, 5.0, self.ins, self.outs)
        h = res['header']
        self.assertEqual(res['problems'], [])
        self.assertEqual(res['phase_problems'], [])
        self.assertEqual(h['platform'], 'esp32s3')
        self.assertEqual(h['clock_snapshot']['cpu_hz_clk'], 240_000_000)
        self.assertEqual(h['windows_used'], 245)
        self.assertTrue(rd.eligible(res))
        for label, r in res['phases'].items():
            self.assertTrue(r['valid'], label)
            if label.startswith('schedule'):
                s = r['summary']
                self.assertAlmostEqual(s['cpu_hz_estimate']['mean'] / 240e6, 1.0, delta=1e-3)
                self.assertAlmostEqual(s['bench_gross_J_per_inference']['mean'] / (5.0 * 0.030 * T_INF), 1.0,
                                       delta=0.005, msg=label)
                self.assertAlmostEqual(s['bench_incremental_J_per_inference']['mean'] / (5.0 * 0.005 * T_INF),
                                       1.0, delta=0.01, msg=label)
                self.assertTrue('ESP32-S3' in r['scope'])

    def test_corrupted_inference_fails_closed(self):
        trace, _ = run_sim(self.exe, self.tmp, corrupt=11)
        res = rd.analyze_capture(synth_words(trace), ua_fn, 5.0, self.ins, self.outs)
        h = res['header']
        self.assertEqual((h['stage_name'], h['error'], h['parity_first_bad_row']), ('ERROR', -203, 11))
        self.assertFalse(rd.eligible(res))


if __name__ == '__main__':
    unittest.main()
