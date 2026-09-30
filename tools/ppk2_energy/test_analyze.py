"""Author tests: entirely synthetic inputs, no USB, no research results."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

import analyze as a


def metadata():
    return {f"{k}{i}": str(v) for k, v in
            {"R": 1., "GS": 0., "GI": 1., "O": 0., "S": 0., "I": 0., "UG": 1.}.items()
            for i in range(5)}


def frames(highs, adc=1024, channel=0):
    return b"".join(struct.pack("<I", adc | ((i % 64) << 18) | (int(h) << (24 + channel)))
                    for i, h in enumerate(highs))


def run(data, **kw):
    defaults = dict(channel=0, baseline=(0, 3), min_samples=2,
                    inferences=2, expected_windows=1, energy_voltage_v=5.)
    defaults.update(kw)
    return a.analyze_stream(io.BytesIO(data), a.Decoder(metadata(), 5., "metadata-exact", "none"), **defaults)


class ConversionTests(unittest.TestCase):
    def test_known_current_scaling(self):
        d = a.Decoder(metadata(), 5., "metadata-exact", "none")
        self.assertAlmostEqual(d.current_ua(1024, 0), 45000.)

    def test_all_ranges_and_voltage_term(self):
        m = metadata()
        for i in range(5):
            m[f"R{i}"] = str(i + 1)
            m[f"S{i}"] = "0.001"
        d = a.Decoder(m, 4., "metadata-exact", "none")
        for i in range(5):
            self.assertAlmostEqual(d.current_ua(1024, i), 45000. / (i + 1) + 4000.)

    def test_zero_policy_is_explicit(self):
        x = a.Decoder(metadata(), 5., "metadata-exact", "none")
        g = a.Decoder(metadata(), 5., "nordic-gui-4.4.1", "none")
        self.assertEqual(x.coef["GS"], [0.] * 5)
        self.assertEqual(g.coef["GS"], [1.] * 5)
        self.assertEqual(len(g.substitutions), 5)
        self.assertNotEqual(x.current_ua(1024, 0), g.current_ua(1024, 0))

    def test_invalid_metadata(self):
        for key, value in (("R0", 0), ("R0", -1), ("UG1", 0), ("GS3", "nan"), ("I4", True)):
            m = metadata(); m[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                a.Decoder(m, 5., "metadata-exact", "none")
        m = metadata(); del m["S2"]
        with self.assertRaises(ValueError): a.Decoder(m, 5., "metadata-exact", "none")
        m = metadata(); m["r0"] = "1"
        with self.assertRaises(ValueError): a.Decoder(m, 5., "metadata-exact", "none")

    def test_negative_is_retained(self):
        m = metadata(); m["O0"] = "20"
        self.assertLess(a.Decoder(m, 5., "metadata-exact", "none").current_ua(0, 0), 0)

    def test_type_and_boundary_checks(self):
        d = a.Decoder(metadata(), 5., "metadata-exact", "none")
        for adc, r in ((True, 0), (0., 0), (16384, 0), (-1, 0), (1, 5), (1, -1)):
            with self.subTest(adc=adc, r=r), self.assertRaises(ValueError): d.current_ua(adc, r)
        for v in (True, float("nan"), float("inf"), 5.25, .79):
            with self.subTest(v=v), self.assertRaises(ValueError): a.voltage(v)

    def test_constant_range_filter_does_not_smooth_output(self):
        d = a.Decoder(metadata(), 5., "metadata-exact", "nordic-4.4.1")
        self.assertEqual([d.current_ua(n, 4) for n in (0, 1024, 0)], [0., 45000., 0.])


class WindowTests(unittest.TestCase):
    def test_rectangular_integration_and_batch_divisor(self):
        report = run(frames([0] * 3 + [1] * 100 + [0] * 3))
        w = report["windows"][0]
        self.assertTrue(report["window_checks_passed"])
        self.assertAlmostEqual(w["duration_s"], .001)
        self.assertAlmostEqual(w["charge_estimate_uC"], 45.)
        self.assertAlmostEqual(w["energy_estimate_uJ"], 225.)
        self.assertAlmostEqual(w["gross_uJ_per_declared_inference"], 112.5)
        self.assertAlmostEqual(w["incremental_energy_estimate_uJ"], 0.)

    def test_unknown_energy_voltage_yields_charge_only(self):
        w = run(frames([0]*3 + [1]*3 + [0]), energy_voltage_v=None)["windows"][0]
        self.assertIsNone(w["energy_estimate_uJ"])
        self.assertIsNone(w["gross_uJ_per_declared_inference"])
        self.assertGreater(w["charge_estimate_uC"], 0)

    def test_channel_seven_and_counter_wrap(self):
        r = run(frames([0]*3 + [1]*100 + [0], channel=7), channel=7)
        self.assertTrue(r["window_checks_passed"])

    def test_no_gpio_and_truncated_windows_fail(self):
        for highs, baseline in (([0]*100, (0, 3)), ([1]*100+[0]*3, (100, 103)),
                                ([0]*3+[1]*100, (0, 3))):
            with self.subTest(highs=highs[:5]):
                self.assertFalse(run(frames(highs), baseline=baseline)["window_checks_passed"])

    def test_short_window_not_assigned_energy(self):
        r = run(frames([0]*3+[1]+[0]), min_samples=2)
        self.assertFalse(r["window_checks_passed"])
        self.assertIsNone(r["windows"][0]["energy_estimate_uJ"])

    def test_baseline_overlap_or_bounds_rejected(self):
        data = frames([0]*3 + [1]*3 + [0])
        for b in ((2, 4), (0, 99), (0, 0), (True, 2)):
            with self.subTest(b=b), self.assertRaises(ValueError): run(data, baseline=b)

    def test_malformed_stream(self):
        good = frames([0]*3 + [1]*3 + [0])
        broken = good[:4] + good[8:]
        for data in (b"", good + b"\x00", broken, struct.pack("<I", 7 << 14)):
            with self.subTest(size=len(data)), self.assertRaises(ValueError): run(data)

    def test_possible_clipping_fails(self):
        self.assertFalse(run(frames([0]*3+[1]*3+[0], adc=16383))["window_checks_passed"])


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.capture = self.root / "input"; self.capture.mkdir()
        self.raw = frames([0]*3 + [1]*100 + [0]*3)
        (self.capture / "samples.u32le").write_bytes(self.raw)
        self.report = {"schema": "ppk2-transport-diagnostic-v1", "transport_check_passed": True,
                       "metadata_fields": metadata(), "device": {"serial": "synthetic"},
                       "raw_metadata": "\n".join(f"{k}: {v}" for k, v in metadata().items()) + "\nEND\n",
                       "analysis": {"sha256": hashlib.sha256(self.raw).hexdigest(),
                                    "samples": len(self.raw)//4, "raw_bytes": len(self.raw)}}
        self.save_report()

    def tearDown(self): self.temp.cleanup()

    def save_report(self):
        (self.capture / "report.json").write_text(json.dumps(self.report))

    def cli(self, name="output", extra=()):
        argv = ["--capture", str(self.capture), "--output", str(self.root/name),
                "--capture-report-sha256", hashlib.sha256((self.capture/"report.json").read_bytes()).hexdigest(),
                "--correction-voltage-v", "5", "--correction-voltage-basis", "synthetic",
                "--coefficient-policy", "metadata-exact", "--spike-filter", "none", "--channel", "0",
                "--inferences-per-window", "10", "--expected-windows", "1", "--baseline", "0", "3"]
        with contextlib.redirect_stdout(io.StringIO()): code = a.main(argv + list(extra))
        return code, json.loads((self.root/name/"analysis.json").read_text())

    def test_success_is_not_research_acceptance(self):
        code, r = self.cli()
        self.assertEqual(code, 0)
        self.assertFalse(r["research_measurement_accepted"])
        self.assertFalse(r["metadata_vdd_used_as_voltage"])

    def test_hash_mismatch_retained(self):
        self.report["analysis"]["sha256"] = "0"*64; self.save_report()
        code, r = self.cli()
        self.assertEqual(code, 1)
        self.assertFalse(r["analysis_completed"])
        self.assertIn("identity", r["error"])

    def test_no_output_reuse(self):
        self.cli()
        with self.assertRaises(FileExistsError): self.cli()

    def test_unpassed_capture_rejected(self):
        self.report["transport_check_passed"] = "true"; self.save_report()
        self.assertEqual(self.cli()[0], 1)


if __name__ == "__main__": unittest.main()
