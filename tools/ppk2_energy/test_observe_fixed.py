"""Synthetic only: fake clocks, serial/USB and signals; real bytes/files/JSON.

Never enumerates devices or opens a physical port. This is not a timing,
electrical safety or calibrated-current simulation.
"""
import contextlib
import io
import json
from pathlib import Path
import signal
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import observe_fixed as o


def word(counter, adc=16383, range_=4):
    return struct.pack('<I', adc | (range_ << 14) | ((counter % 64) << 18))


class Clock:
    def __init__(self): self.now = 0.
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


class Port:
    timeout = .02
    pending = 0

    def __init__(self, clock, fault=None):
        self.clock, self.fault = clock, fault
        self.writes, self.returned, self.read_timeouts = [], [], []
        self.started = self.stopped = False
        self.counter = self.reads = 0
        self.drain = []
        self.metadata_tail = b'\n'
        self.on_write_delay = 0.
        self.final_off_write_delay = 0.

    @property
    def in_waiting(self): return self.pending
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def fileno(self): return 123

    def write(self, data):
        self.writes.append(data)
        if data == b'\x06': self.started = True
        if data == b'\x07': self.stopped = True
        if data == b'\x0c\x01': self.clock.now += self.on_write_delay
        if data == b'\x0c\x00' and self.writes.count(data) == 2:
            self.clock.now += self.final_off_write_delay
        if self.fault == 'short_on' and data == b'\x0c\x01': return 1
        if self.fault == 'on_error' and data == b'\x0c\x01': raise OSError('ON error')
        if self.fault == 'off_error' and data == b'\x0c\x00' and self.writes.count(data) == 2:
            raise OSError('OFF error')
        if self.fault == 'stop_error' and data == b'\x07': raise OSError('STOP error')
        if self.fault == 'short_stop' and data == b'\x07': return 0
        return len(data)

    def read(self, count):
        self.read_timeouts.append(self.timeout)
        self.clock.now += self.timeout
        if not self.started: return self.metadata_tail
        if self.stopped:
            if self.fault == 'endless_drain':
                chunk = word(self.counter)
                self.counter += 1
            else:
                chunk = self.drain.pop(0) if self.drain else b''
                if isinstance(chunk, BaseException): raise chunk
            self.returned.append(chunk)
            return chunk
        self.reads += 1
        if self.reads == 2:
            if self.fault == 'read_error': raise OSError('read error')
            if self.fault == 'signal': o.interrupted(signal.SIGTERM, None)
        if self.fault == 'silence': return b''
        if self.fault in ('partial', 'complete_in_drain'):
            self.clock.now += 3.
            chunk = word(0)
            if self.fault == 'partial': chunk += b'\xff'
            else:
                self.drain = [chunk[2:], b'']
                chunk = chunk[:2]
        else:
            if self.fault == 'counter_gap' and self.reads == 2: self.counter += 1
            chunk = word(self.counter, range_=7 if self.fault == 'invalid_range' and self.reads == 2 else 4)
            self.counter += 1
        self.returned.append(chunk)
        return chunk


class Probe:
    serial_number = o.ST_SERIAL
    is_open = False

    def __init__(self, port):
        self.port, self.observed_writes, self.replies = port, [], []
    def open(self): self.is_open = True
    def close(self): self.is_open = False
    def transfer(self, command, readSize):
        assert command == [0xf7] and readSize == 8
        self.observed_writes.append(list(self.port.writes))
        reply = self.replies.pop(0) if self.replies else struct.pack('<II', 0, 0)
        if isinstance(reply, BaseException): raise reply
        return reply


class Harness(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.port = Port(self.clock)
        self.probe = Probe(self.port)
        self.raw, self.state = io.BytesIO(), {}
        for context in (patch.object(o.time, 'monotonic', self.clock.monotonic),
                        patch.object(o.time, 'sleep', self.clock.sleep),
                        patch.object(o.signal, 'setitimer')):
            context.start()
            self.addCleanup(context.stop)

    def invoke(self, metadata=None):
        return o.observe(self.port, self.probe, self.raw,
                         {'mode': '1'} if metadata is None else metadata, self.state)

    def cleaned(self):
        self.assertEqual(self.port.writes[-2:], [b'\x0c\x00', b'\x07'])


class AcquisitionTests(Harness):
    def test_fixed_duration_saturation_zero_reference_no_electrical_cutoff(self):
        self.invoke({'mode': '1', 'I4': '0.8', 'unneeded_calibration': 'not parsed'})
        self.assertTrue(self.state['acquisition_completed'])
        self.assertTrue(self.state['sampling_loop_completed'])
        self.assertGreaterEqual(self.state['before_cleanup']['elapsed_since_on_write_completed_s'], 3.)
        self.assertEqual(self.state['saturated_adc_observations'], self.state['raw_whole_rows'])
        self.assertGreater(self.state['raw_whole_rows'], 100)
        self.assertEqual(self.raw.getvalue(), b''.join(self.port.returned))
        self.assertEqual(self.port.writes, [b'\x0c\x00', b'\x06', b'\x0c\x01', b'\x0c\x00', b'\x07'])
        self.assertEqual(self.probe.observed_writes, [self.port.writes[:1], self.port.writes])
        self.assertEqual(self.state['host_intervals']['start_finished_to_on_attempt_s'], 0.)
        self.assertEqual(self.state['host_intervals']['off_finished_to_stop_attempt_s'], 0.)
        self.assertFalse(self.state['host_intervals']['electrical_duration_measured'])
        self.assertTrue(self.state['post_stop_drain']['empty_read_observed'])
        self.assertTrue(all(0 < timeout <= .02 for timeout in self.port.read_timeouts))

    def test_high_reference_is_observation_not_cutoff(self):
        self.probe.replies = [struct.pack('<II', 1, 99)] * 2
        self.invoke()
        self.assertTrue(self.state['acquisition_completed'])
        self.assertGreater(self.state['references'][0]['estimated_target_reference_v'], 100)

    def test_wrong_or_untyped_mode_has_no_commands(self):
        for mode in ('2', 1, True, None):
            with self.subTest(mode=mode), self.assertRaises(ValueError): self.invoke({'mode': mode})
        self.assertEqual(self.port.writes, [])

    def test_stale_pending_has_no_commands(self):
        self.port.pending = 4
        with self.assertRaises(RuntimeError): self.invoke()
        self.assertEqual(self.port.writes, [])

    def test_pending_after_before_reference_refuses_start_on(self):
        original = self.probe.transfer
        def transfer(*args, **kwargs):
            self.port.pending = 4
            return original(*args, **kwargs)
        self.probe.transfer = transfer
        with self.assertRaises(RuntimeError): self.invoke()
        self.cleaned()
        self.assertNotIn(b'\x06', self.port.writes)
        self.assertNotIn(b'\x0c\x01', self.port.writes)

    def test_short_on_still_off_stop_without_claiming_completed_on(self):
        self.port.fault = 'short_on'
        with self.assertRaises(OSError): self.invoke()
        self.cleaned()
        self.assertFalse(self.state['commands'][2]['write_completed'])
        self.assertTrue(self.state['commands'][2]['write_attempted'])
        self.assertIsNone(self.state['before_cleanup']['elapsed_since_on_write_completed_s'])

    def test_delayed_on_write_consumes_existing_three_second_budget(self):
        self.port.on_write_delay = .25
        self.invoke()
        on = next(row for row in self.state['commands'] if row['name'] == 'output_on')
        off = next(row for row in self.state['commands'] if row['name'] == 'final_output_off')
        self.assertAlmostEqual(off['at_monotonic'] - on['at_monotonic'], 3., places=7)
        self.assertLess(self.state['before_cleanup']['elapsed_since_on_write_completed_s'], 2.751)
        self.assertAlmostEqual(on['host_write_duration_seconds'], .25)
        self.assertAlmostEqual(self.state['sampling_deadline_at_monotonic'], on['at_monotonic'] + 3.)
        self.assertAlmostEqual(self.state['host_intervals']['on_attempt_to_off_attempt_s'], 3.)

    def test_on_write_beyond_deadline_does_not_start_new_sampling_window(self):
        self.port.on_write_delay = 3.1
        with self.assertRaises(TimeoutError): self.invoke()
        self.cleaned()
        self.assertEqual(self.port.reads, 0)
        self.assertFalse(self.state['sampling_loop_completed'])
        self.assertAlmostEqual(self.state['before_cleanup']['host_deadline_overrun_s'], .1)

    def test_delayed_short_on_has_attempt_origin_and_retains_drain(self):
        self.port.on_write_delay = .27
        self.port.fault = 'short_on'
        self.port.drain = [word(0), b'']
        with self.assertRaises(OSError): self.invoke()
        self.cleaned()
        on = self.state['commands'][2]
        self.assertFalse(on['write_completed'])
        self.assertAlmostEqual(on['host_write_duration_seconds'], .27)
        self.assertAlmostEqual(self.state['host_intervals']['on_attempt_to_off_attempt_s'], .27)
        self.assertIsNone(self.state['host_intervals']['on_completed_to_off_attempt_s'])
        self.assertEqual(self.raw.getvalue(), word(0))
        self.assertEqual(self.port.reads, 0)

    def test_delayed_on_error_records_elapsed_without_completed_write(self):
        self.port.on_write_delay = .15
        self.port.fault = 'on_error'
        with self.assertRaises(OSError): self.invoke()
        self.cleaned()
        on = self.state['commands'][2]
        self.assertNotIn('write_returned_at_monotonic', on)
        self.assertAlmostEqual(on['host_write_duration_seconds'], .15)
        self.assertAlmostEqual(self.state['before_cleanup']['elapsed_since_on_write_attempt_s'], .15)
        self.assertNotIn('on_write_completed_at_monotonic', self.state)

    def test_delayed_failed_off_still_stops_without_inserted_delay(self):
        self.port.final_off_write_delay = .12
        self.port.fault = 'off_error'
        with self.assertRaises(OSError): self.invoke()
        self.cleaned()
        self.assertAlmostEqual(self.state['host_intervals']['on_attempt_to_off_attempt_s'], 3.)
        self.assertAlmostEqual(self.state['host_intervals']['off_attempt_to_stop_attempt_s'], .12)
        self.assertEqual(self.state['host_intervals']['off_finished_to_stop_attempt_s'], 0.)

    def test_very_late_short_on_still_immediately_cleans_not_new_window(self):
        self.port.on_write_delay = 3.2
        self.port.fault = 'short_on'
        with self.assertRaises(OSError): self.invoke()
        self.cleaned()
        self.assertEqual(self.port.reads, 0)
        self.assertAlmostEqual(self.state['before_cleanup']['host_deadline_overrun_s'], .2)

    def test_on_error_still_off_stop(self):
        self.port.fault = 'on_error'
        with self.assertRaises(OSError): self.invoke()
        self.cleaned()

    def test_read_error_keeps_received_raw(self):
        self.port.fault = 'read_error'
        with self.assertRaises(OSError): self.invoke()
        self.cleaned()
        self.assertEqual(self.raw.getvalue(), word(0))

    def test_signal_keeps_received_raw_and_cleans(self):
        self.port.fault = 'signal'
        with self.assertRaises(InterruptedError): self.invoke()
        self.cleaned()
        self.assertEqual(self.raw.getvalue(), word(0))

    def test_off_failure_is_failure_even_when_drain_empty(self):
        self.port.fault = 'off_error'
        with self.assertRaises(OSError): self.invoke()
        self.cleaned()
        self.assertTrue(self.state['post_stop_drain']['empty_read_observed'])
        self.assertEqual(len(self.state['cleanup_errors']), 1)
        self.assertFalse(self.state['acquisition_completed'])

    def test_stop_failure_after_off_is_retained(self):
        self.port.fault = 'stop_error'
        with self.assertRaises(OSError): self.invoke()
        self.cleaned()
        self.assertIn('sampling_stop', self.state['cleanup_errors'][0])

    def test_short_stop_is_failure(self):
        self.port.fault = 'short_stop'
        with self.assertRaises(OSError): self.invoke()
        self.cleaned()

    def test_no_samples_is_liveness_failure_not_success(self):
        self.port.fault = 'silence'
        with self.assertRaises(TimeoutError): self.invoke()
        self.cleaned()
        self.assertEqual(self.raw.getvalue(), b'')

    def test_counter_gap_preserves_offending_chunk(self):
        self.port.fault = 'counter_gap'
        with self.assertRaises(ValueError): self.invoke()
        self.cleaned()
        self.assertEqual(self.raw.getvalue(), word(0) + word(2))
        self.assertEqual(self.state['structure_checked_rows'], 1)

    def test_invalid_range_preserves_offending_chunk(self):
        self.port.fault = 'invalid_range'
        with self.assertRaises(ValueError): self.invoke()
        self.cleaned()
        self.assertEqual(self.raw.getvalue(), word(0) + word(1, range_=7))

    def test_partial_final_frame_fails_without_deleting_raw(self):
        self.port.fault = 'partial'
        with self.assertRaises(ValueError): self.invoke()
        self.assertEqual(self.raw.getvalue(), word(0) + b'\xff')
        self.assertEqual(self.state['eof_remainder_bytes'], 1)

    def test_split_frame_can_complete_in_bounded_drain(self):
        self.port.fault = 'complete_in_drain'
        self.invoke()
        self.assertTrue(self.state['acquisition_completed'])
        self.assertEqual(self.raw.getvalue(), word(0))
        self.assertEqual(self.state['before_cleanup']['raw_bytes_written'], 2)
        self.assertEqual(self.state['post_stop_drain']['bytes'], 2)

    def test_drain_deadline_no_empty_read_is_failure(self):
        self.port.fault = 'endless_drain'
        with self.assertRaises(TimeoutError): self.invoke()
        self.assertLessEqual(self.state['post_stop_drain']['elapsed_seconds'], .500001)
        self.assertGreater(self.state['post_stop_drain']['bytes'], 0)

    def test_drain_read_error_retains_loop_raw(self):
        self.port.drain = [OSError('drain failure')]
        with self.assertRaises(OSError): self.invoke()
        self.assertGreater(len(self.raw.getvalue()), 0)
        self.assertIn('drain failure', self.state['post_stop_drain']['error'])

    def test_short_raw_write_is_recorded_and_cleanup_attempted(self):
        class Short(io.BytesIO):
            def write(self, data):
                super().write(data[:2])
                return 2
        self.raw = Short()
        with self.assertRaises(OSError): self.invoke()
        self.cleaned()
        self.assertEqual(len(self.raw.getvalue()), 2)
        self.assertEqual(self.state['raw_bytes_written'], 2)
        self.assertEqual(self.state['raw_bytes_received'], 4)

    def test_byte_cap_retains_offending_chunk(self):
        with patch.object(o, 'BYTE_CAP', 4), self.assertRaises(RuntimeError): self.invoke()
        self.cleaned()
        self.assertEqual(len(self.raw.getvalue()), 8)

    def test_before_reference_error_prevents_on_and_cleans(self):
        self.probe.replies = [OSError('reference transport')]
        with self.assertRaises(OSError): self.invoke()
        self.cleaned()
        self.assertNotIn(b'\x0c\x01', self.port.writes)

    def test_after_reference_short_read_keeps_full_raw_but_not_success(self):
        self.probe.replies = [struct.pack('<II', 0, 0), b'\x00']
        with self.assertRaises(ValueError): self.invoke()
        self.assertTrue(self.state['sampling_loop_completed'])
        self.assertGreater(len(self.raw.getvalue()), 400)
        self.assertFalse(self.state['acquisition_completed'])


class MainTests(Harness):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory(prefix='fixed-observation-synthetic-')
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'fresh'
        self.source = Path(self.temp.name) / 'source.txt'
        self.source.write_bytes(b'synthetic-source')
        self.sourcepins = {str(self.source): o.digest(self.source)}
        self.metadata = {'mode': '1'}
        self.query_error = self.open_error = None
        self.serial_options = None
        def serial(*args, **kwargs):
            self.serial_options = kwargs
            if self.open_error: raise self.open_error
            return self.port
        def query(port):
            if self.query_error: raise self.query_error
            return b'mode: 1\nEND\n', self.metadata
        self.loader = lambda: (serial,
            lambda: [{'serial': o.PPK_SERIAL, 'port': '/synthetic-no-device'}], query,
            types.SimpleNamespace(get_all_connected_devices=lambda: [self.probe]))
        for context in (patch.object(o, 'source_pins', lambda: self.sourcepins.copy()),
                        patch.object(o, 'load_hardware', lambda: self.loader()),
                        patch.object(o.fcntl, 'ioctl'), patch.object(o.signal, 'signal')):
            context.start()
            self.addCleanup(context.stop)

    def main(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = o.main(['--output', str(self.output), '--execute-fixed-am-observation'])
        return code, json.loads((self.output / 'report.json').read_bytes())

    def test_success_real_files_and_limits(self):
        code, report = self.main()
        self.assertEqual(code, 0)
        self.assertTrue(report['acquisition_completed'])
        for field in ('research_measurement_accepted', 'board_powered_verified', 'board_boot_verified',
                      'board_accepted', 'electrical_safety_verified', 'input_voltage_measured',
                      'electrical_output_off_verified', 'firmware_changed', 'voltage_or_mode_changed',
                      'current_based_hardware_limiter', 'during_on_reference_observed', 'current_or_energy_computed',
                      'distinct_usb_transactions_verified', 'command_acknowledgements_observed',
                      'required_start_on_or_off_stop_spacing_established'):
            self.assertIs(report[field], False)
        self.assertEqual(report['duration_origin'], 'host_output_on_write_attempt')
        self.assertEqual(report['source_pins_before'], report['source_pins_after'])
        self.assertEqual(report['raw_sha256'], o.digest(self.output / 'samples.u32le'))
        self.assertEqual(report['raw_size_bytes'], report['raw_bytes_written'])
        self.assertTrue(self.serial_options['exclusive'])
        self.assertEqual(self.serial_options['write_timeout'], .3)
        self.assertTrue(report['output_on_write_completed'])

    def test_open_failure_does_not_claim_on_or_metadata(self):
        self.open_error = OSError('cannot open')
        code, report = self.main()
        self.assertEqual(code, 1)
        self.assertFalse(report['serial_open_completed'])
        self.assertFalse(report['metadata_query_attempted'])
        self.assertFalse(report['output_on_write_attempted'])
        self.assertEqual(report['commands'], [])

    def test_metadata_failure_does_not_claim_on(self):
        self.query_error = ValueError('metadata invalid')
        code, report = self.main()
        self.assertEqual(code, 1)
        self.assertTrue(report['metadata_query_attempted'])
        self.assertFalse(report['metadata_query_completed'])
        self.assertFalse(report['output_on_write_attempted'])
        self.assertEqual(report['commands'], [])

    def test_wrong_mode_has_report_no_on(self):
        self.metadata = {'mode': '2'}
        code, report = self.main()
        self.assertEqual(code, 1)
        self.assertFalse(report['output_on_write_attempted'])
        self.assertEqual(report['raw_size_bytes'], 0)

    def test_nonwhitespace_metadata_tail_no_on(self):
        self.port.metadata_tail = b'\x00\x01'
        code, report = self.main()
        self.assertEqual(code, 1)
        self.assertEqual(report['metadata_tail_hex'], '0001')
        self.assertFalse(report['output_on_write_attempted'])

    def test_signal_main_retains_raw_and_failure_report(self):
        self.port.fault = 'signal'
        code, report = self.main()
        self.assertEqual(code, 1)
        self.assertEqual((self.output / 'samples.u32le').read_bytes(), word(0))
        self.assertFalse(report['acquisition_completed'])
        self.assertIn('InterruptedError', report['error'])
        self.cleaned()

    def test_short_on_main_distinguishes_attempt_and_completion(self):
        self.port.fault = 'short_on'
        code, report = self.main()
        self.assertEqual(code, 1)
        self.assertTrue(report['output_on_write_attempted'])
        self.assertFalse(report['output_on_write_completed'])
        self.cleaned()

    def test_off_failure_real_raw_is_retained(self):
        self.port.fault = 'off_error'
        code, report = self.main()
        self.assertEqual(code, 1)
        self.assertGreater(report['raw_size_bytes'], 400)
        self.assertFalse(report['acquisition_completed'])
        self.assertIn('OFF error', report['error'])

    def test_source_endpoint_change_is_failure(self):
        close = self.probe.close
        def changed():
            self.source.write_bytes(b'changed synthetic source')
            close()
        self.probe.close = changed
        code, report = self.main()
        self.assertEqual(code, 1)
        self.assertFalse(report['acquisition_completed'])
        self.assertIn('Source changed', report['publication_error'])

    def test_existing_output_never_loads_hardware(self):
        self.output.mkdir()
        with patch.object(o, 'load_hardware') as loader, self.assertRaises(ValueError): self.main()
        loader.assert_not_called()

    def test_missing_explicit_flag_never_loads_hardware(self):
        with patch.object(o, 'load_hardware') as loader, contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            o.main(['--output', str(self.output)])
        loader.assert_not_called()

    def test_existing_root_symlink_rejected(self):
        self.output.symlink_to(Path(self.temp.name), target_is_directory=True)
        with patch.object(o, 'load_hardware') as loader, self.assertRaises(ValueError): self.main()
        loader.assert_not_called()


if __name__ == '__main__':
    unittest.main()
