"""Read-only checks of run_sessions_esp.py's instrument/board-state gates on recorded
captures (ESP Amendments 2-3). Never commands a recorder."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / 'tools/ra4e1_deployment/host_measure'))
sys.path.insert(0, str(HERE))
import run_sessions as rs  # noqa: E402
import run_sessions_esp as rse  # noqa: E402

E = REPO / 'results/power_esp32s3_20260930'


@unittest.skipUnless((E / 'ppk_esp2/summary_10ms.csv').exists(), 'recorded captures not present')
class EspGates(unittest.TestCase):
    def test_used_recorder_refused(self):
        rec = rs.Recorder(E / 'ppk_esp2')          # logic port was powered during diag_esp_01
        with self.assertRaises(SystemExit):
            rse.preflight(rec, E / 'flash_em01_build02', 'build_02', 'e8:f6:0a:8b:40:80')

    def test_unregistered_build_refused(self):
        with self.assertRaises(SystemExit):
            rse.preflight(rs.Recorder(E / 'ppk_esp2'), E / 'flash_em01_build02', 'build_99', 'e8:f6:0a:8b:40:80')

    def test_pre_on_and_off_gap_states(self):
        rec = rs.Recorder(E / 'ppk_esp2')
        ev = rec.events()
        ons = [e['sample_index'] for e in ev if e.get('name') == 'output_on']
        off = [e['sample_index'] for e in ev if e.get('name') == 'output_off' and e['sample_index'] > 0][0]
        self.assertEqual(rse.logic_states(rec, 0, ons[0] - 1000)[0], [(255, 255)])
        self.assertEqual(rse.logic_states(rec, off + 100_000, ons[1] - 1000)[0], [(1, 1)])   # latched after DONE

    def test_status_age(self):
        self.assertEqual(rse.status_age_s({'utc': 'garbage'}), float('inf'))
        self.assertEqual(rse.status_age_s({}), float('inf'))
        self.assertGreater(rse.status_age_s({'utc': '2026-09-29T00:00:00+00:00'}), 3600)

    def test_build_markers(self):
        self.assertEqual(rse.BUILD_MARKER_GPIO['build_04'], 5)
        self.assertEqual(rse.esp_ops.DEFAULT_BUILD, 'build_04')


if __name__ == '__main__':
    unittest.main()
