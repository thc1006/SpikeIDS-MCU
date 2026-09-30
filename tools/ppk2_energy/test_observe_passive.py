"""Offline fakes only; never open serial or USB."""
import io
import struct
import unittest
import observe_passive as p


class Port:
    in_waiting = 0
    timeout = .02

    def __init__(self, fault=None):
        self.t = 0.; self.writes = []; self.counter = 0
        self.stopped = False; self.fault = fault; self.saved = []

    def write(self, raw):
        self.writes.append(raw)
        if raw == b'\x06' and self.fault == 'delayed_start': self.t += 3.1
        if raw == b'\x06' and self.fault == 'short_start': return 0
        if raw == b'\x06' and self.fault == 'bool_start': return True
        if raw == b'\x07':
            self.stopped = True
            if self.fault == 'stop_error': raise OSError('stop failed')
        return len(raw)

    def read(self, size):
        self.t += self.timeout
        if self.stopped or self.fault == 'silence': return b''
        if self.counter == 1 and self.fault == 'read_error': raise OSError('read failed')
        r = 7 if self.fault == 'bad_range' else self.counter % 5
        c = (self.counter + (1 if self.fault == 'gap' and self.counter else 0)) % 64
        self.counter += 1
        raw = struct.pack('<I', 100 | r << 14 | c << 18)
        if self.fault == 'partial': self.t += 3.; raw += b'X'
        self.saved.append(raw)
        return raw


class PassiveTests(unittest.TestCase):
    def execute(self, fault=None, mode='1'):
        port = Port(fault); sink = io.BytesIO(); state = {}
        return port, sink, state, lambda: p.collect(port, sink, {'mode': mode}, state, now=lambda: port.t)

    def test_success_only_start_stop(self):
        port, sink, state, run = self.execute(); run()
        self.assertEqual(port.writes, [b'\x06', b'\x07'])
        self.assertTrue(state['acquisition_completed'])
        self.assertEqual(sink.getvalue(), b''.join(port.saved))
        self.assertTrue(all(n > 0 for n in state['range_histogram']))
        self.assertFalse(state['model_executed']); self.assertFalse(state['energy_measured'])

    def test_failures_retain_raw_and_stop(self):
        for fault in ('short_start', 'bool_start', 'delayed_start', 'silence',
                      'bad_range', 'gap', 'partial', 'read_error', 'stop_error'):
            with self.subTest(fault=fault):
                port, sink, state, run = self.execute(fault)
                with self.assertRaises(Exception): run()
                self.assertEqual(port.writes, [b'\x06', b'\x07'])
                self.assertEqual(sink.getvalue(), b''.join(port.saved))
                self.assertFalse(state['acquisition_completed'])
                self.assertFalse(state['output_switch_command_sent'])

    def test_wrong_mode_no_commands(self):
        for mode in ('0', '2', 1, None):
            port, sink, state, run = self.execute(mode=mode)
            with self.assertRaises(ValueError): run()
            self.assertEqual(port.writes, [])

    def test_pending_stream_not_interfered(self):
        port, sink, state, run = self.execute(); port.in_waiting = 4
        with self.assertRaises(ValueError): run()
        self.assertEqual(port.writes, [])


if __name__ == '__main__': unittest.main()
