"""Independent small raw-transport controls; all hardware and time are fake."""
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import observe_fixed as o


def packed(counter, range_=4):
    return (16383 + range_ * 16384 + (counter % 64) * 262144).to_bytes(4, 'little')


class Sim:
    def __init__(self, delay=0., cleanup_failure=False, bad_frame=False):
        self.now, self.delay = 0., delay
        self.cleanup_failure, self.bad_frame = cleanup_failure, bad_frame
        self.writes, self.delivered, self.references = [], [], []
        self.timeout, self.in_waiting, self.count = .02, 0, 0
        self.stopped = False

    def monotonic(self): return self.now
    def sleep(self, duration): self.now += duration

    def write(self, payload):
        self.writes.append((payload, self.now))
        if payload == b'\x0c\x01': self.now += self.delay
        if payload == b'\x07': self.stopped = True
        if self.cleanup_failure and len(self.writes) >= 4:
            raise OSError('Independent simulated cleanup failure')
        return len(payload)

    def read(self, count):
        self.now += self.timeout
        if self.stopped: return b''
        data = packed(self.count, 7 if self.bad_frame else 4)
        self.count += 1
        self.delivered.append(data)
        return data

    def transfer(self, command, readSize):
        if command != [247] or readSize != 8:
            raise AssertionError('Unexpected USB command')
        self.references.append(len(self.writes))
        return bytes(8)


class IndependentControls(unittest.TestCase):
    def run_sim(self, sim, raw, state):
        with patch.object(o.time, 'monotonic', sim.monotonic), \
             patch.object(o.time, 'sleep', sim.sleep), \
             patch.object(o.signal, 'setitimer'):
            o.observe(sim, sim, raw, {'mode': '1'}, state)

    def test_frames_one_byte_chunks_counter_wrap_all_ranges(self):
        frames = o.Frames()
        for index in range(320):
            for byte in packed(index, index % 5):
                frames.feed(bytes([byte]))
        self.assertEqual(frames.rows, 320)
        self.assertEqual(frames.saturated, 320)
        self.assertEqual(frames.ranges, [64] * 5)
        self.assertEqual(frames.tail, b'')

    def test_counter_cannot_detect_a_whole_64_missing_samples(self):
        frames = o.Frames()
        frames.feed(packed(0) + packed(65))
        self.assertEqual(frames.rows, 2)  # documents a limitation, not losslessness

    def test_delayed_on_no_extra_window_no_reference_during_on(self):
        sim, raw, state = Sim(delay=.29), io.BytesIO(), {}
        self.run_sim(sim, raw, state)
        self.assertAlmostEqual(sim.writes[3][1] - sim.writes[2][1], 3.)
        self.assertEqual(sim.references, [1, 5])
        self.assertEqual(raw.getvalue(), b''.join(sim.delivered))
        self.assertTrue(state['acquisition_completed'])
        self.assertFalse(state['host_intervals']['electrical_duration_measured'])

    def test_late_on_no_new_window_immediate_cleanup_no_success(self):
        sim, raw, state = Sim(delay=3.01), io.BytesIO(), {}
        with self.assertRaises(TimeoutError): self.run_sim(sim, raw, state)
        self.assertEqual(sim.writes[3][1], sim.writes[2][1] + 3.01)
        self.assertFalse(state['acquisition_completed'])
        self.assertEqual(len(sim.delivered), 0)

    def test_both_cleanup_failures_still_attempted_and_retained(self):
        sim, raw, state = Sim(cleanup_failure=True), io.BytesIO(), {}
        with self.assertRaises(OSError): self.run_sim(sim, raw, state)
        self.assertEqual([entry[0] for entry in sim.writes[-2:]], [b'\x0c\x00', b'\x07'])
        self.assertEqual(len(state['cleanup_errors']), 2)
        self.assertFalse(state['acquisition_completed'])
        self.assertEqual(raw.getvalue(), b''.join(sim.delivered))

    def test_invalid_frame_preserved_no_retry_on(self):
        sim, raw, state = Sim(bad_frame=True), io.BytesIO(), {}
        with self.assertRaises(ValueError): self.run_sim(sim, raw, state)
        self.assertEqual(raw.getvalue(), packed(0, 7))
        self.assertEqual(sum(entry[0] == b'\x0c\x01' for entry in sim.writes), 1)
        self.assertFalse(state['acquisition_completed'])

    def test_bool_write_count_not_accepted_as_single_byte_success(self):
        class BadPort:
            def write(self, data): return True
        state = {'commands': []}
        with self.assertRaises(OSError): o.command(BadPort(), b'\x06', state, 'sampling_start')
        self.assertFalse(state['commands'][0]['write_completed'])
        self.assertIn('error', state['commands'][0])


if __name__ == '__main__': unittest.main()
