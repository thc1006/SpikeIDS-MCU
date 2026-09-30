"""Fixed 3 s AM raw acquisition, NOT electrical protection or board acceptance.

Only GetMetadata, output OFF/ON, sampling START/STOP and ST-LINK GET_TARGET_VOLTAGE
are used. No current/ADC/Vref threshold terminates the acquisition. Before/after
ST-LINK observations are deliberately outside sampling: this pinned pyOCD's
transfer(timeout=...) does not forward that timeout to its USB read.

The 3 s host deadline starts at the ON write ATTEMPT, not its return. A serial
write/OS scheduling delay can still overrun it; this is not a precise electrical
ON interval. Independent OFF/STOP attempts and the external timeout remain needed.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import struct
import sys
import termios
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
INFO = Path('/home/thc1006/.local/opt/ppk2-headless/ppk2_info.py')
USB = REPO / '.venv/lib/python3.13/site-packages/pyocd/probe/stlink/usb.py'
PINNED = {INFO: 'e35b4697f974c74c04ed97965a9df1d9f18ea19a046d3982f0ec59e625f41b13',
          USB: 'f668f479e8de8929c2af4ffe861f8aca4e9a9d02ac063178beafe46cb296c33f'}
PPK_SERIAL = 'F4728E9B55E0'
ST_SERIAL = '004000183234510E37333934'
DURATION = 3.0
WATCHDOG = 6.0
READ_TIMEOUT = .02
SILENCE_TIMEOUT = .5  # transport liveness policy, not a current/voltage limit
DRAIN_SECONDS = .5
BYTE_CAP = 2_000_000  # bounded host storage, not a hardware current limiter
PROTOCOL_COMMIT = '4cbb4c41c420ddb8125638fffc6d72f6b21c5aaa'
# At this Nordic commit serialDevice.sendCommand sends a worker message;
# worker/serialDevice.js issues separate port.write calls. abstractDevice and
# deviceActions specify no minimum START/ON or OFF/STOP interval or device ACK.
# The installed metadata helper likewise supplies no command-spacing contract.
# Separate host writes are preserved, NOT claimed distinct USB transactions.
# No new arbitrary delay is inserted before ON or between urgent OFF and STOP.


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_pins():
    pins = {str(p): digest(p) for p in PINNED}
    if any(pins[str(p)] != sha for p, sha in PINNED.items()):
        raise RuntimeError('Pinned metadata/USB source changed; no hardware access')
    pins[str(Path(__file__).resolve())] = digest(__file__)
    return pins


def load_hardware():
    """Called only after CLI opt-in and source commitments; never at import."""
    import serial
    from pyocd.probe.stlink.usb import STLinkUSBInterface
    if Path(sys.modules[STLinkUSBInterface.__module__].__file__).resolve() != USB:
        raise RuntimeError('Wrong pyOCD USB implementation')
    spec = importlib.util.spec_from_file_location('_fixed_observation_ppk_info', INFO)
    info = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(info)
    return serial.Serial, info.devices, info.query_metadata, STLinkUSBInterface


def error_text(exc):
    return f'{type(exc).__name__}: {exc}'


def command(port, value, state, name):
    row = dict(name=name, hex=value.hex(), at_monotonic=time.monotonic(),
               write_attempted=True, write_completed=False)
    state['commands'].append(row)
    if name == 'output_on':
        state['on_write_attempt_at_monotonic'] = row['at_monotonic']
        state['sampling_deadline_at_monotonic'] = row['at_monotonic'] + DURATION
    try:
        row['bytes_written'] = port.write(value)
        row['write_returned_at_monotonic'] = time.monotonic()
        if type(row['bytes_written']) is not int or row['bytes_written'] != len(value):
            raise OSError('Incomplete ' + name + ' write')
        row['write_completed'] = True
        if name == 'output_on':
            state['on_write_completed_at_monotonic'] = row['write_returned_at_monotonic']
    except BaseException as exc:
        row['error'] = error_text(exc)
        raise
    finally:
        row['write_finished_at_monotonic'] = time.monotonic()
        row['host_write_duration_seconds'] = row['write_finished_at_monotonic'] - row['at_monotonic']


def reference(probe, state, phase):
    row = dict(phase=phase, at_monotonic=time.monotonic(),
               command_hex='f7', is_vin_measurement=False,
               is_board_power_or_boot_verdict=False)
    state['references'].append(row)
    try:
        raw = bytes(probe.transfer([0xf7], readSize=8))
        row['raw_hex'] = raw.hex()
        if len(raw) != 8:
            raise ValueError('Incomplete target-reference reply')
        denominator, numerator = struct.unpack('<II', raw)
        row['denominator'], row['numerator'] = denominator, numerator
        # Zero denominator is retained as an unavailable observation, not an
        # electrical failure; transport length/I/O errors still fail acquisition.
        row['estimate_available'] = denominator != 0
        row['estimated_target_reference_v'] = 2 * numerator * 1.2 / denominator if denominator else None
    except BaseException as exc:
        row['error'] = error_text(exc)
        raise


class Frames:
    """Transport integrity only. Saturation and digital bits remain observations."""
    def __init__(self):
        self.tail = b''
        self.previous = None
        self.rows = 0
        self.saturated = 0
        self.ranges = [0] * 5

    def feed(self, chunk):
        data = self.tail + chunk
        end = len(data) // 4 * 4
        self.tail = data[end:]
        for (word,) in struct.iter_unpack('<I', data[:end]):
            adc, r, counter = word & 16383, (word >> 14) & 7, (word >> 18) & 63
            if r > 4:
                raise ValueError(f'Invalid range {r} at row {self.rows}')
            if self.previous is not None and counter != (self.previous + 1) % 64:
                raise ValueError(f'Counter discontinuity at row {self.rows}')
            self.previous = counter
            self.rows += 1
            self.saturated += adc == 16383
            self.ranges[r] += 1


def interrupted(signum, frame):
    raise InterruptedError(f'Signal {signum}; acquisition interrupted')


def observe(port, probe, sink, metadata, state):
    """One OFF -> START -> ON attempt, finally OFF then STOP independently.

    The caller supplies fresh metadata from the same exclusive port. Raw is
    stored before checking structure. Drain is attempted even after cleanup
    write failure; an empty read cannot upgrade failed cleanup to success.
    """
    if metadata.get('mode') != '1':
        raise ValueError('Fresh exact Ampere mode not verified; refusing commands')
    if port.in_waiting:
        raise RuntimeError('Unexpected pending bytes before acquisition')
    state.update(commands=[], references=[], cleanup_errors=[], acquisition_completed=False,
                 raw_bytes_written=0, raw_bytes_received=0, sampling_loop_completed=False)
    frames = Frames()
    failure = None
    parsing_valid = True

    def save(chunk):
        nonlocal parsing_valid
        state['raw_bytes_received'] += len(chunk)
        written = sink.write(chunk)
        if type(written) is not int or not 0 <= written <= len(chunk):
            raise OSError('Invalid raw write count')
        state['raw_bytes_written'] += written
        if written != len(chunk):
            raise OSError('Short raw write; available file bytes retained')
        if state['raw_bytes_written'] > BYTE_CAP:
            raise RuntimeError('Raw storage cap exceeded; offending bytes retained')
        if parsing_valid:
            try:
                frames.feed(chunk)
            except BaseException:
                parsing_valid = False
                raise

    signal.setitimer(signal.ITIMER_REAL, WATCHDOG)
    try:
        command(port, b'\x0c\x00', state, 'initial_output_off')
        time.sleep(.05)
        reference(probe, state, 'before_start_output_off')
        if port.in_waiting:
            raise RuntimeError('Unexpected pending bytes before START')
        command(port, b'\x06', state, 'sampling_start')
        command(port, b'\x0c\x01', state, 'output_on')
        deadline = state['sampling_deadline_at_monotonic']
        if time.monotonic() >= deadline:
            raise TimeoutError('ON write consumed the host observation deadline; no extension')
        last_data = time.monotonic()
        while (remaining := deadline - time.monotonic()) > 0:
            port.timeout = min(READ_TIMEOUT, remaining)
            chunk = port.read(4096)
            if chunk:
                last_data = time.monotonic()
                save(chunk)
            if time.monotonic() - last_data > SILENCE_TIMEOUT:
                raise TimeoutError('No recent raw samples; transport liveness failure')
        state['sampling_loop_completed'] = True
    except BaseException as exc:
        failure = exc
        state['acquisition_error'] = error_text(exc)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        cleanup_at = time.monotonic()
        attempt = state.get('on_write_attempt_at_monotonic')
        completed = state.get('on_write_completed_at_monotonic')
        deadline = state.get('sampling_deadline_at_monotonic')
        state['before_cleanup'] = dict(at_monotonic=cleanup_at,
            elapsed_since_on_write_attempt_s=None if attempt is None else cleanup_at - attempt,
            elapsed_since_on_write_completed_s=None if completed is None else cleanup_at - completed,
            host_deadline_overrun_s=None if deadline is None else max(0., cleanup_at - deadline),
            raw_bytes_written=state['raw_bytes_written'],
            raw_bytes_received=state['raw_bytes_received'],
            raw_whole_rows=state['raw_bytes_written'] // 4,
            structure_checked_rows=frames.rows, bytes_processed=frames.rows * 4,
            parsing_valid_so_far=parsing_valid)
        for name, value in (('final_output_off', b'\x0c\x00'), ('sampling_stop', b'\x07')):
            try:
                command(port, value, state, name)
            except BaseException as exc:
                state['cleanup_errors'].append(name + ': ' + error_text(exc))
                failure = failure or exc
        off = next(row for row in state['commands'] if row['name'] == 'final_output_off')
        stop = next(row for row in state['commands'] if row['name'] == 'sampling_stop')
        start = next((row for row in state['commands'] if row['name'] == 'sampling_start'), None)
        state['host_intervals'] = dict(
            on_attempt_to_off_attempt_s=None if attempt is None else off['at_monotonic'] - attempt,
            on_completed_to_off_attempt_s=None if completed is None else off['at_monotonic'] - completed,
            off_attempt_to_stop_attempt_s=stop['at_monotonic'] - off['at_monotonic'],
            off_finished_to_stop_attempt_s=stop['at_monotonic'] - off['write_finished_at_monotonic'],
            start_finished_to_on_attempt_s=None if start is None or attempt is None else attempt - start['write_finished_at_monotonic'],
            electrical_duration_measured=False)
        # No current conversion/threshold, retry ON, serial buffer reset or data
        # discard. A finite empty-read drain is not proof all device FIFO bytes
        # have arrived, and mod64 cannot detect losses in multiples of 64 samples.
        drain_start = time.monotonic()
        drain = state['post_stop_drain'] = dict(bytes=0, empty_read_observed=False)
        try:
            while (remaining := DRAIN_SECONDS - (time.monotonic() - drain_start)) > 0:
                port.timeout = min(READ_TIMEOUT, remaining)
                chunk = port.read(16384)
                if not chunk:
                    drain['empty_read_observed'] = True
                    break
                drain['bytes'] += len(chunk)
                save(chunk)
            if not drain['empty_read_observed']:
                raise TimeoutError('No empty read before stopped-stream drain deadline')
        except BaseException as exc:
            drain['error'] = error_text(exc)
            failure = failure or exc
        finally:
            drain['elapsed_seconds'] = time.monotonic() - drain_start
            port.timeout = READ_TIMEOUT
        try:
            reference(probe, state, 'after_cleanup_not_during_on')
        except BaseException as exc:
            failure = failure or exc
    state.update(structure_checked_rows=frames.rows, bytes_processed=frames.rows * 4,
                 raw_whole_rows=state['raw_bytes_written'] // 4,
                 eof_remainder_bytes=state['raw_bytes_written'] % 4,
                 saturated_adc_observations=frames.saturated, range_histogram=frames.ranges)
    if not state['raw_bytes_written'] or state['eof_remainder_bytes']:
        failure = failure or ValueError('Empty capture or partial final frame; raw retained')
    if failure:
        raise failure
    state['acquisition_completed'] = True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute-fixed-am-observation', action='store_true', required=True)
    args = parser.parse_args(argv)
    out = args.output
    if not out.is_absolute() or out != out.resolve() or os.path.lexists(out):
        raise ValueError('Use a canonical fresh absolute output directory')
    pins = source_pins()
    out.mkdir(mode=0o700)
    identity = (out.stat().st_dev, out.stat().st_ino)
    state = dict(schema='ppk2-fixed-am-observation-v1', utc=datetime.now(timezone.utc).isoformat(),
        duration_policy_seconds=DURATION, whole_acquisition_watchdog_seconds=WATCHDOG,
        duration_is_engineering_choice_not_electrical_spec=True,
        duration_origin='host_output_on_write_attempt',
        protocol_reference_commit=PROTOCOL_COMMIT,
        commands_are_separate_host_writes=True,
        distinct_usb_transactions_verified=False, command_acknowledgements_observed=False,
        required_start_on_or_off_stop_spacing_established=False,
        source_pins_before=pins, commands=[], references=[], acquisition_completed=False,
        research_measurement_accepted=False, board_powered_verified=False, board_boot_verified=False,
        board_accepted=False, electrical_safety_verified=False, input_voltage_measured=False,
        electrical_output_off_verified=False, firmware_changed=False, voltage_or_mode_changed=False,
        current_based_hardware_limiter=False, during_on_reference_observed=False,
        current_or_energy_computed=False, external_timeout_required=True,
        serial_open_completed=False, metadata_query_attempted=False,
        metadata_query_completed=False, output_on_write_attempted=False,
        output_on_write_completed=False,
        limits=['OFF write completion is not physical OFF verification.',
                'Host crash/USB failure can prevent cleanup; external timeout is required.',
                'Finite drain and modulo-64 counters cannot prove lossless physical sampling.',
                'No during-ON Vref; after-OFF Vref cannot establish board boot failure.',
                'Only this script and the named metadata/USB helpers are source-pinned, not the entire runtime.',
                'Write attempts/returns are host events, not device ACKs or electrical switching times.',
                'Write blocking or OS scheduling can overrun the 3 s host deadline; no hard electrical bound is established.',
                '3 s host interval is not calibrated sample time, operating rating or safety limit.'])
    original_handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM)}
    error = None
    probe = None
    try:
        for s in original_handlers:
            signal.signal(s, interrupted)
        Serial, devices, query_metadata, Probe = load_hardware()
        matches = [p for p in devices() if p['serial'] == PPK_SERIAL]
        probes = [p for p in Probe.get_all_connected_devices() if p.serial_number == ST_SERIAL]
        if len(matches) != 1 or len(probes) != 1:
            raise RuntimeError('Fixed PPK2/ST-LINK pair not uniquely present')
        state.update(ppk=matches[0], stlink_serial=ST_SERIAL)
        probe = probes[0]
        probe.open()  # USB endpoint only, no SWD/debug-mode entry, reset or flash.
        with Serial(matches[0]['port'], baudrate=115200, timeout=READ_TIMEOUT,
                    write_timeout=.3, exclusive=True) as port:
            state['serial_open_completed'] = True
            fcntl.ioctl(port.fileno(), termios.TIOCEXCL)
            state['metadata_query_attempted'] = True
            metadata_raw, metadata = query_metadata(port)
            state.update(raw_metadata=metadata_raw.decode('ascii'), metadata_fields=metadata,
                         metadata_query_completed=True)
            tail = port.read(256)
            state['metadata_tail_hex'] = tail.hex()
            if any(b not in b'\r\n\t ' for b in tail) or port.in_waiting:
                raise RuntimeError('Unexpected metadata tail/pending data')
            with (out / 'samples.u32le').open('xb') as sink:
                try:
                    observe(port, probe, sink, metadata, state)
                finally:
                    sink.flush()
                    os.fsync(sink.fileno())
    except BaseException as exc:
        error = exc
        state['error'] = error_text(exc)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        on = next((row for row in state['commands'] if row['name'] == 'output_on'), {})
        state['output_on_write_attempted'] = on.get('write_attempted', False)
        state['output_on_write_completed'] = on.get('write_completed', False)
        if probe is not None and probe.is_open:
            try:
                probe.close()
            except BaseException as exc:
                state['probe_close_error'] = error_text(exc)
                error = error or exc
        try:
            state['source_pins_after'] = {p: digest(p) for p in pins}
            if state['source_pins_after'] != pins:
                raise RuntimeError('Source changed during observation')
            if out.resolve() != out or (out.stat().st_dev, out.stat().st_ino) != identity:
                raise RuntimeError('Owned output directory changed')
            raw = out / 'samples.u32le'
            if raw.exists():
                state.update(raw_sha256=digest(raw), raw_size_bytes=raw.stat().st_size)
        except BaseException as exc:
            state['publication_error'] = error_text(exc)
            error = error or exc
        if error:
            state['acquisition_completed'] = False
        for s, handler in original_handlers.items():
            signal.signal(s, handler)
        # Publication is refused if root identity changed; no writes into a
        # replacement root. This is a bounded filesystem check, not atomic IO.
        if out.resolve() != out or (out.stat().st_dev, out.stat().st_ino) != identity:
            raise RuntimeError('Owned output directory changed; refusing report write')
        rendered = (json.dumps(state, indent=2, allow_nan=False) + '\n').encode()
        with (out / 'report.json').open('xb') as report:
            report.write(rendered)
            report.flush()
            os.fsync(report.fileno())
        print(json.dumps(dict(acquisition_completed=state['acquisition_completed'],
                              report=str(out / 'report.json'), report_sha256=digest(out / 'report.json'))))
    return 1 if error else 0


if __name__ == '__main__':
    sys.exit(main())
