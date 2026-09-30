"""Independent pulse controls: real Decoder/byte IO, fake time/ports/Vref only.

No imports or calls to serial, pyOCD, USB enumeration, or actual hardware.
The fake stream is not a calibrated timing or physical power simulation.
"""
import io
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import power_probe as p


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Port:
    in_waiting = 0

    def __init__(self, clock, fault=None):
        self.clock, self.fault = clock, fault
        self.writes = []
        self.counter = 0

    def write(self, value):
        self.writes.append(value)
        if self.fault == "short_on" and value == b"\x0c\x01":
            return 1
        if self.fault == "off_failure" and value == b"\x0c\x00" and self.writes.count(value) == 2:
            raise OSError("synthetic final OFF failure")
        return len(value)

    def read(self, count):
        self.clock.now += .02
        if self.fault == "read_failure":
            raise OSError("synthetic read failure")
        if self.fault == "silence":
            return b""
        if self.fault == "counter_gap":
            return struct.pack("<II", 0, 2 << 18)
        data = struct.pack("<I", (self.counter % 64) << 18)
        self.counter += 1
        if self.fault == "partial_frame":
            # The first read advances beyond the full 3 s loop deadline but
            # returns one complete frame plus a final incomplete frame.
            self.clock.now += 3.0
            return data + b"\x00"
        return data


def metadata(current=.001):
    m = {f"{g}{n}": 1.0 if g in ("R", "UG") else 0.0
         for g in ("R", "GS", "GI", "O", "S", "I", "UG") for n in range(5)}
    m.update(mode="1", I0=current)
    return m


class PulseControls(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.port = Port(self.clock)
        self.raw, self.state = io.BytesIO(), {}
        self.enter = [patch.object(p.time, "monotonic", self.clock.monotonic),
                      patch.object(p.time, "sleep", self.clock.sleep),
                      patch.object(p.signal, "setitimer"),
                      patch.object(p, "reference", return_value={"estimated_v": 3.3,
                                   "is_vin_measurement": False, "raw_hex": "synthetic"})]
        for patcher in self.enter:
            patcher.start()
            self.addCleanup(patcher.stop)

    def invoke(self, m=None):
        return p.pulse(self.port, object(), self.raw, m or metadata(), self.state)

    def cleaned(self):
        self.assertEqual(self.port.writes[-2:], [b"\x0c\x00", b"\x07"])

    def test_success_real_decoder_preserves_bytes_and_off_before_stop(self):
        self.invoke()
        self.assertTrue(self.state["pulse_loop_completed"])
        self.assertEqual(self.state["cleanup_errors"], [])
        self.assertEqual(len(self.raw.getvalue()), self.state["samples"] * 4)
        self.assertAlmostEqual(self.state["maximum_uA"], 1000.)
        self.assertEqual(self.port.writes, [b"\x0c\x00", b"\x06", b"\x0c\x01", b"\x0c\x00", b"\x07"])

    def test_wrong_mode_never_sends_on_or_any_command(self):
        for mode in ("2", 1, None):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.invoke(dict(metadata(), mode=mode))
        self.assertEqual(self.port.writes, [])

    def test_partial_on_still_attempts_off_and_stop(self):
        self.port.fault = "short_on"
        with self.assertRaises(OSError):
            self.invoke()
        self.cleaned()
        self.assertFalse(next(x for x in self.state["commands"] if x["name"] == "output_on")["write_completed"])

    def test_read_failure_still_attempts_off_and_stop(self):
        self.port.fault = "read_failure"
        with self.assertRaises(OSError):
            self.invoke()
        self.cleaned()

    def test_missing_samples_times_out_and_attempts_off(self):
        self.port.fault = "silence"
        with self.assertRaises(TimeoutError):
            self.invoke()
        self.cleaned()
        self.assertLess(self.clock.now, 1.0)

    def test_raw_write_failure_still_attempts_off_and_stop(self):
        class BrokenSink:
            def write(self, value):
                raise OSError("synthetic sink failure")
        self.raw = BrokenSink()
        with self.assertRaises(OSError):
            self.invoke()
        self.cleaned()

    def test_unfiltered_current_cutoff_preserves_available_raw(self):
        with self.assertRaises(RuntimeError):
            self.invoke(metadata(.8))
        self.cleaned()
        self.assertGreater(self.state["maximum_uA"], 700_000)
        self.assertGreater(len(self.raw.getvalue()), 0)

    def test_counter_gap_preserves_received_bytes_and_cleans(self):
        self.port.fault = "counter_gap"
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.cleaned()
        self.assertEqual(len(self.raw.getvalue()), 8)

    def test_off_failure_does_not_skip_stop_or_disappear(self):
        self.port.fault = "off_failure"
        self.invoke()
        self.cleaned()
        self.assertEqual(len(self.state["cleanup_errors"]), 1)
        self.assertIn("final_output_off", self.state["cleanup_errors"][0])
        self.assertTrue(self.state["commands"][-1]["write_completed"])
        self.assertFalse(self.state["commands"][-2]["write_completed"])

    def test_partial_final_frame_is_not_a_completed_valid_probe(self):
        self.port.fault = "partial_frame"
        with self.assertRaises((RuntimeError, ValueError)):
            self.invoke()
        self.cleaned()
        self.assertEqual(self.state["unprocessed_trailing_bytes"], 1)
        self.assertEqual(len(self.raw.getvalue()), 5)


if __name__ == "__main__":
    unittest.main()
