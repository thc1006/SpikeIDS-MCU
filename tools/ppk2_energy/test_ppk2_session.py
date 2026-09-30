import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze  # noqa: E402
import ppk2_session as ps  # noqa: E402

META = {'R0': '997.9588', 'R1': '101.3213', 'R2': '10.2998', 'R3': '0.9688', 'R4': '0.0562',
        'GS0': '0.0000', 'GS1': '142.6852', 'GS2': '20.8866', 'GS3': '2.9386', 'GS4': '0.0834',
        'GI0': '1.0000', 'GI1': '0.9609', 'GI2': '0.9563', 'GI3': '0.9442', 'GI4': '0.9534',
        'O0': '130.4886', 'O1': '89.9935', 'O2': '77.4222', 'O3': '59.5241', 'O4': '104.6074',
        'S0': '0.000000001', 'S1': '0.000000179', 'S2': '0.000001771', 'S3': '0.000020370',
        'S4': '0.002760722', 'I0': '0.000000036', 'I1': '-0.000000243', 'I2': '0.000055379',
        'I3': '-0.000295807', 'I4': '-0.008772146', 'UG0': '1.00', 'UG1': '1.00', 'UG2': '1.00',
        'UG3': '1.00', 'UG4': '1.00'}


def frames(adcs, ranges, bits, counter0=0):
    out = b''
    for i, (a, r, b) in enumerate(zip(adcs, ranges, bits)):
        word = (a & 0x3FFF) | ((r & 7) << 14) | (((counter0 + i) % 64) << 18) | ((b & 255) << 24)
        out += struct.pack('<I', word)
    return out


class FakePort:
    def __init__(self):
        self.writes = []

    def write(self, value):
        self.writes.append(bytes(value))
        return len(value)

    def flush(self):
        pass


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.conv = ps.Converter(META, 5.0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_vectorized_formula_matches_codex_decoder(self):
        rng = np.random.default_rng(1)
        adcs = rng.integers(0, 16383, 500)
        rs = rng.integers(0, 5, 500)
        words = np.frombuffer(frames(adcs, rs, [0] * 500), dtype='<u4')
        ua, _, bad = self.conv.ua(words)
        dec = analyze.Decoder(META, 5.0, 'metadata-exact', 'none')
        ref = [dec.current_ua(int(a), int(r)) for a, r in zip(adcs, rs)]
        self.assertFalse(bad.any())
        np.testing.assert_allclose(ua, ref, rtol=1e-12, atol=1e-9)

    def test_segment_edges_bins_and_discontinuity(self):
        port = FakePort()
        s = ps.Session(port, self.out, self.conv, 950.0)
        s.start_segment('t 1')
        bits = ([0] * 700 + [1] * 600 + [0] * 700) * 2
        n = len(bits)
        data = frames([2000] * n, [2] * n, bits)
        s.feed(data[:1001])            # unaligned split
        s.feed(data[1001:])
        s.stop_segment()
        seg = s.segments[0]
        self.assertEqual(seg['frames'], n)
        self.assertEqual(seg['d0_rising'], 2)
        self.assertEqual((self.out / seg['path']).read_bytes(), data)
        self.assertEqual(s.discontinuities, [])
        rows = (self.out / 'summary_10ms.csv').read_text().strip().splitlines()
        self.assertEqual(len(rows) - 1, n // ps.BIN)
        s.feed(frames([2000] * 10, [2] * 10, [0] * 10, counter0=5))
        self.assertEqual(len(s.discontinuities), 1)

    def test_guard_trips_only_when_output_on(self):
        port = FakePort()
        s = ps.Session(port, self.out, self.conv, 950.0)
        big = frames([16000] * ps.GUARD_WINDOW, [4] * ps.GUARD_WINDOW, [0] * ps.GUARD_WINDOW)
        s.feed(big)
        self.assertFalse(s.guard_tripped)       # output OFF: no command
        s.write_cmd(ps.CMD_ON, 'output_on')
        s.feed(frames([16000] * ps.GUARD_WINDOW, [4] * ps.GUARD_WINDOW, [0] * ps.GUARD_WINDOW,
                      counter0=ps.GUARD_WINDOW % 64))
        self.assertTrue(s.guard_tripped)
        self.assertEqual(port.writes[-1], ps.CMD_OFF)
        self.assertFalse(s.output_on)
        kinds = [json.loads(l)['kind'] for l in (self.out / 'events.jsonl').read_text().splitlines()]
        self.assertIn('guard_trip', kinds)

    def test_arm_fires_only_after_absence_hold(self):
        port = FakePort()
        s = ps.Session(port, self.out, self.conv, 950.0)
        t = {'now': 0.0}
        present = {'v': True}
        arm = ps.Arm('X', hold_s=2.0, present=lambda _: present['v'], clock=lambda: t['now'])
        for now in (0.0, 5.0):
            t['now'] = now
            arm.poll(s)
        self.assertFalse(arm.fired)            # never ON while ST-LINK present
        present['v'] = False
        t['now'] = 6.0; arm.poll(s)
        t['now'] = 7.5; arm.poll(s)
        self.assertFalse(arm.fired)            # hold not yet met
        present['v'] = True
        t['now'] = 7.9; arm.poll(s)            # brief absence resets
        present['v'] = False
        t['now'] = 8.0; arm.poll(s)
        t['now'] = 10.1; arm.poll(s)
        self.assertTrue(arm.fired)
        self.assertEqual(port.writes, [ps.CMD_ON])
        present['v'] = True
        t['now'] = 12.0; arm.poll(s)
        self.assertEqual(arm.returned_at, 12.0)
        self.assertEqual(port.writes, [ps.CMD_ON])  # fires once only

    def test_invalid_range_is_nan_not_crash(self):
        words = np.frombuffer(frames([100, 100], [5, 1], [0, 0]), dtype='<u4')
        ua, _, bad = self.conv.ua(words)
        self.assertTrue(np.isnan(ua[0]) and bad[0])
        self.assertTrue(np.isfinite(ua[1]))


class UnplugTest(unittest.TestCase):
    """Reproduces 2026-09-29 15:14: USB pulled mid-session; report must still be written."""
    def test_report_written_when_device_vanishes(self):
        import serial
        chunks = [b'', frames([2000] * 4096, [2] * 4096, [0] * 4096)]

        class Gone(serial.SerialException):
            pass

        class Port:
            def __init__(self, *a, **k):
                self.writes = []
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def fileno(self):
                return os.open('/dev/null', os.O_RDONLY)
            def write(self, v):
                if len(self.writes) >= 2:
                    raise OSError(5, 'Input/output error')
                self.writes.append(v)
                return len(v)
            def flush(self):
                pass
            def read(self, n):
                if chunks:
                    return chunks.pop(0)
                raise Gone('device reports readiness to read but returned no data')

        class Info:
            @staticmethod
            def devices():
                return [{'port': '/dev/null', 'serial': ps.PPK_SERIAL, 'vid': 1, 'pid': 2}]
            @staticmethod
            def query_metadata(port):
                return b'mode: 1\nEND\n', dict(META, mode='1')

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'sess'
            old = (serial.Serial, ps.load_info, ps.fcntl.ioctl)
            serial.Serial, ps.load_info = Port, (lambda: Info)
            ps.fcntl.ioctl = lambda *a: None
            try:
                rc = ps.main(['--out', str(out), '--record-initial', 'x'])
            finally:
                serial.Serial, ps.load_info, ps.fcntl.ioctl = old
            report = json.loads((out / 'session.json').read_text())
            self.assertEqual(rc, 1)
            self.assertIn('readiness to read', report['error'])
            self.assertEqual(report['segments'][0]['frames'], 4096)
            self.assertFalse(report['status']['output_on'])




class ReaderTest(unittest.TestCase):
    def test_gap_marker_in_stream_order(self):
        chunks = [b'a' * 8, b'', b'b' * 8, None, b'c' * 8]
        class Port:
            def read(self, n):
                c = chunks.pop(0) if chunks else b''
                if c is None:
                    time.sleep(0.15)             # host stall longer than READER_GAP_S
                    return b''
                return c
        r = ps.Reader(Port(), gap_s=0.1)
        r.start()
        time.sleep(0.4)
        r.stop_flag.set(); r.join(1)
        items = []
        while not r.q.empty():
            items.append(r.q.get()[:2])
        kinds = [k for k, _ in items]
        self.assertEqual(kinds, ['data', 'data', 'gap', 'data'])
        self.assertGreater(items[2][1], 0.1)

    def test_reader_error_is_forwarded(self):
        class Port:
            def read(self, n):
                raise OSError('gone')
        r = ps.Reader(Port())
        r.start(); r.join(1)
        self.assertEqual(r.q.get()[0], 'error')


if __name__ == '__main__':
    unittest.main()
