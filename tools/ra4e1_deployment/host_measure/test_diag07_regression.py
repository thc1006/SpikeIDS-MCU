"""Real-hardware regression on the diag_07 capture (skipped when the raw file is absent).

Review 2026-09-30 B1: after output OFF the PPK2 keeps its last logic byte, so a
formal segment opened before ON starts with a stale D0-HIGH run (0x01). With the
pre-ON frames masked as unpowered, the analysis must reproduce diag_07 exactly."""
import json
from pathlib import Path
import sys
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / 'tools/ppk2_energy'))
import ppk2_session  # noqa: E402
import rm01_decode as rd  # noqa: E402

R = REPO / 'results/power_ra4e1_20260929/ppk_main7'
SEG = R / 'seg_000_diag_07.u32le'


@unittest.skipUnless(SEG.exists(), 'diag_07 raw capture not present')
class Diag07Regression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ev = [json.loads(l) for l in (R / 'events.jsonl').read_text().splitlines()]
        start = next(e for e in ev if e['kind'] == 'segment_start' and e['label'] == 'diag_07')
        on = next(e for e in ev if e.get('name') == 'output_on' and e['sample_index'] >= start['sample_index'])
        cls.on_offset = on['sample_index'] - start['sample_index']
        conv = ppk2_session.Converter(json.loads((R / 'session.json').read_text())['metadata'], 5.0)
        cls.ua = staticmethod(lambda w: conv.ua(w)[0])
        z = np.load(REPO / 'results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq/validation_vectors.npz')
        cls.ins = [tuple(r) for r in np.ascontiguousarray(z['x'], '<f4').view('<u4')]
        cls.outs = [tuple(r) for r in np.ascontiguousarray(z['reference_logits'], '<f4').view('<u4')]
        w = np.fromfile(SEG, dtype='<u4').copy()
        # emulate the latched byte: logic 0x01 (D0 HIGH, D1..D7 LOW) until 20 ms after ON
        stale = cls.on_offset + 2_000
        w[:stale] = (w[:stale] & np.uint32(0x00FFFFFF)) | np.uint32(0x01 << 24)
        cls.words = w

    def test_stale_prefix_breaks_unmasked_analysis(self):
        res = rd.analyze_capture(self.words, self.ua, 5.0, self.ins, self.outs, top_range_only=False)
        self.assertTrue(res['problems'])
        self.assertFalse(rd.eligible(res))

    def test_masked_analysis_reproduces_diag07(self):
        res = rd.analyze_capture(self.words, self.ua, 5.0, self.ins, self.outs, top_range_only=False,
                                 unpowered_before=self.on_offset + 50_000)
        self.assertEqual(res['problems'], [])
        self.assertEqual(res['phase_problems'], [])
        self.assertTrue(rd.eligible(res))
        g = [res['phases'][f'schedule_0{k}_repeat1']['summary']['bench_gross_J_per_inference']['mean'] for k in range(3)]
        self.assertAlmostEqual(sum(g) / 3 * 1e3, 3.4764, places=3)
        self.assertAlmostEqual(res['phases']['sham']['null_dI_mA']['mean'], -0.1369, places=3)

    def test_eligibility_rule(self):
        res = rd.analyze_capture(self.words, self.ua, 5.0, self.ins, self.outs, top_range_only=False,
                                 unpowered_before=self.on_offset + 50_000)
        res['phases']['schedule_04_dose4']['valid'] = False          # dose: reported only
        self.assertTrue(rd.eligible(res))
        res['phases']['schedule_01_repeat1']['valid'] = False
        self.assertTrue(rd.eligible(res))                              # 2 repeats still valid
        res['phases']['schedule_02_repeat1']['valid'] = False
        self.assertFalse(rd.eligible(res))
        res['phases']['schedule_01_repeat1']['valid'] = True
        res['phases']['schedule_02_repeat1']['valid'] = True
        res['phases']['sham']['valid'] = False
        self.assertFalse(rd.eligible(res))


if __name__ == '__main__':
    unittest.main()
