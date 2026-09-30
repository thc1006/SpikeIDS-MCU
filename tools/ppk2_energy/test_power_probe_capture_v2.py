"""Six bounded independent controls; fake devices only, never physical I/O.

Drain and filesystem publication are real. Main orchestration substitutes the
already-reviewed pulse, metadata, serial/USB, signal and target-reference seams.
"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import power_probe_capture_v2 as v


def ready():
    return {"commands": [{"name": n, "write_completed": True}
                         for n in ("final_output_off", "sampling_stop")]}


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class Port:
    def __init__(self, chunks, clock=None):
        self.chunks = iter(chunks)
        self.timeout = .02
        self.reads = 0
        self.clock = clock

    def read(self, count):
        self.reads += 1
        if self.clock:
            self.clock.now += min(.001, self.timeout)
        value = next(self.chunks, b"")
        if isinstance(value, BaseException):
            raise value
        return value

    def write(self, value):
        raise AssertionError("Drain must never send hardware commands")


class DrainControls(unittest.TestCase):
    def test_fragments_are_preserved_and_no_control_writes(self):
        port, sink, state, clock = Port([b"abc", b"d", b""]), io.BytesIO(), ready(), Clock()
        v.drain_stopped(port, sink, state, clock=clock)
        self.assertEqual(sink.getvalue(), b"abcd")
        self.assertEqual(state["post_stop_drain"]["bytes"], 4)
        self.assertTrue(state["post_stop_drain"]["empty_read_observed"])
        self.assertEqual(port.timeout, .02)

    def test_uncompleted_off_or_stop_prevents_every_read(self):
        for missing in ("final_output_off", "sampling_stop"):
            state, port = ready(), Port([b"data"])
            for row in state["commands"]:
                if row["name"] == missing:
                    row["write_completed"] = False
            with self.subTest(missing=missing), self.assertRaises(RuntimeError):
                v.drain_stopped(port, io.BytesIO(), state, clock=Clock())
            self.assertEqual(port.reads, 0)

    def test_read_and_short_sink_failures_keep_available_bytes(self):
        sink, state = io.BytesIO(), ready()
        with self.assertRaises(OSError):
            v.drain_stopped(Port([b"data", OSError("read failed")]), sink, state, clock=Clock())
        self.assertEqual(sink.getvalue(), b"data")
        class ShortSink(io.BytesIO):
            def write(self, value):
                super().write(value[:2])
                return 2
        sink = ShortSink()
        with self.assertRaises(OSError):
            v.drain_stopped(Port([b"data"]), sink, ready(), clock=Clock())
        self.assertEqual(sink.getvalue(), b"da")

    def test_byte_limit_fails_without_control_command(self):
        state, sink, clock = ready(), io.BytesIO(), Clock()
        port = Port([b"a" * 16384] * 65, clock)
        with self.assertRaises(RuntimeError):
            v.drain_stopped(port, sink, state, clock=clock)
        self.assertEqual(len(sink.getvalue()), 1_048_576)
        self.assertEqual(state["post_stop_drain"]["bytes"], 1_048_576)
        self.assertEqual(port.timeout, .02)

    def test_deadline_limits_each_read_and_restores_timeout(self):
        clock = Clock()
        class SlowPort(Port):
            def read(self, count):
                clock.now += min(.49, self.timeout)
                return b"x"
        port = SlowPort([])
        port.timeout = 1.0
        with self.assertRaises(TimeoutError):
            v.drain_stopped(port, io.BytesIO(), ready(), clock=clock)
        self.assertLessEqual(clock.now, .50000001)
        self.assertEqual(port.timeout, 1.0)

    def test_main_preserves_pulse_failure_and_still_drains_and_reads_reference(self):
        class SerialPort(Port):
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def fileno(self): return 123
        class Probe:
            serial_number = v.original.ST_SERIAL
            is_open = False
            def open(self): self.is_open = True
            def close(self): self.is_open = False
        probe = Probe()
        fake_serial = types.ModuleType("serial")
        fake_info = types.ModuleType("ppk2_info")
        fake_info.devices = lambda: [{"serial": v.original.PPK_SERIAL, "port": "/fake"}]
        fake_info.query_metadata = lambda port: (b"mode: 1\nEND\n", {"mode": "1"})
        modules = {"serial": fake_serial, "ppk2_info": fake_info}
        for name in ("pyocd", "pyocd.probe", "pyocd.probe.stlink", "pyocd.probe.stlink.usb"):
            modules[name] = types.ModuleType(name)
            modules[name].__path__ = []
        modules["pyocd.probe.stlink.usb"].STLinkUSBInterface = types.SimpleNamespace(get_all_connected_devices=lambda: [probe])
        def failed_pulse(port, selected, raw, metadata, state):
            raw.write(b"head")
            state.update(ready(), cleanup_errors=[])
            raise RuntimeError("original cutoff retained")
        with tempfile.TemporaryDirectory(prefix="ppk2-v2-mock-") as temp:
            output = Path(temp) / "new-output"
            fake_serial.Serial = lambda *args, **kwargs: SerialPort([b"\n", b"tail", b""])
            with patch.dict(sys.modules, modules), patch.object(sys, "path", sys.path.copy()), \
                 patch.object(sys, "argv", ["test", "--output", str(output), "--execute-same-policy-power-test"]), \
                 patch.object(v.fcntl, "ioctl"), patch.object(v.signal, "signal"), patch.object(v.signal, "setitimer"), \
                 patch.object(v.original, "pulse", failed_pulse), \
                 patch.object(v.original, "reference", return_value={"estimated_v": .01, "is_vin_measurement": False}) as reference, \
                 contextlib.redirect_stdout(io.StringIO()):
                code = v.main()
            result = json.loads((output / "report.json").read_bytes())
            self.assertEqual(code, 1)
            self.assertIn("original cutoff retained", result["pulse_error"])
            self.assertEqual(result["error"], result["pulse_error"])
            self.assertEqual((output / "samples.u32le").read_bytes(), b"headtail")
            self.assertEqual(result["post_stop_drain"]["bytes"], 4)
            self.assertFalse(result["power_probe_completed"])
            self.assertFalse(result["research_measurement_accepted"])
            self.assertFalse(result["electrical_output_off_verified"])
            self.assertEqual(result["references"][-1]["phase"], "after")
            reference.assert_called_once()


if __name__ == "__main__":
    unittest.main()
