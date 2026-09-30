"""Three-second raw AM observation; NEVER switches DUT output or changes voltage.

Diagnostic of the existing state, not trained-model power. Only metadata 0x19,
sampling START 0x06 and STOP 0x07 are permitted. No ST-LINK is opened. Reuses
the frozen frame parser and ordinary-file retention helper, not their runners.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import termios
import time

SELF = Path(__file__).resolve()
HERE = SELF.parent
REPO = HERE.parents[1]
PPK_SERIAL = 'F4728E9B55E0'
FIXED = HERE / 'observe_fixed.py'
VENDOR = REPO / 'tools/n6_deployment/prepare_vendor.py'
INFO = Path('/home/thc1006/.local/opt/ppk2-headless/ppk2_info.py')
HASHES = {
    FIXED: '7ed8fcd668f939665e638e55bb8c486ba727e90687ddf35e91a0b88acf030334',
    VENDOR: 'cd1bb490fa913d0ffde3c5c59ff8108134537228ded9ec130e5ac17939f7a94f',
    INFO: 'e35b4697f974c74c04ed97965a9df1d9f18ea19a046d3982f0ec59e625f41b13',
}
DURATION = 3.0
FLAGS = dict(output_switch_command_sent=False, voltage_or_mode_changed=False,
             target_accessed=False, model_executed=False, energy_measured=False,
             electrical_safety_verified=False, input_voltage_measured=False,
             research_measurement_accepted=False)


def load_fixed(path):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != HASHES[path]:
        raise RuntimeError('Fixed helper changed: ' + str(path))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_file_location('_passive_' + path.stem, path))
    exec(compile(raw, str(path), 'exec'), mod.__dict__)
    return mod


v = load_fixed(VENDOR)
frames_module = load_fixed(FIXED)


def collect(port, sink, metadata, state, *, now=time.monotonic):
    """One START/STOP attempt. Raw bytes survive parse or cleanup failures."""
    if metadata.get('mode') != '1' or port.in_waiting:
        raise ValueError('Need fresh Ampere mode and no pending serial data')
    state.update(commands=[], cleanup_errors=[], raw_bytes=0, sampling_completed=False,
                 acquisition_completed=False, **FLAGS)
    frames = frames_module.Frames()
    failure = None
    parsing = True

    def write(value):
        if value not in (b'\x06', b'\x07'):
            raise ValueError('Only sampling commands allowed')
        event = dict(hex=value.hex(), attempted_at=now(), completed=False)
        state['commands'].append(event)
        try:
            n = port.write(value)
            event['write_count'] = n
            if type(n) is not int or n != len(value):
                raise OSError('Short sampling command write')
            event['completed'] = True
        except BaseException as exc:
            event['error'] = str(exc)
            raise
        finally:
            event['returned_at'] = now()

    def save(raw):
        nonlocal parsing
        n = sink.write(raw)
        if type(n) is not int or n != len(raw):
            raise OSError('Short raw-file write; partial file retained')
        state['raw_bytes'] += n
        if state['raw_bytes'] > 2_000_000:
            raise ValueError('Raw storage cap exceeded')
        if parsing:
            try:
                frames.feed(raw)
            except BaseException:
                parsing = False
                raise

    started = now()
    state['start_attempt_at'] = started
    deadline = started + DURATION
    try:
        write(b'\x06')
        if now() >= deadline:
            raise TimeoutError('START consumed deadline; no extension')
        last_data = now()
        while (remaining := deadline - now()) > 0:
            port.timeout = min(.02, remaining)
            raw = port.read(4096)
            if raw:
                last_data = now()
                save(raw)
            if now() - last_data > .5:
                raise TimeoutError('Sample stream silent')
        state['sampling_completed'] = True
    except BaseException as exc:
        failure = exc
        state['sampling_error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        state['before_stop_at'] = now()
        try:
            write(b'\x07')
        except BaseException as exc:
            state['cleanup_errors'].append(type(exc).__name__ + ': ' + str(exc))
            failure = failure or exc
        drain_deadline = now() + .5
        state['drain_empty_read'] = False
        try:
            while (remaining := drain_deadline - now()) > 0:
                port.timeout = min(.02, remaining)
                raw = port.read(16384)
                if not raw:
                    state['drain_empty_read'] = True
                    break
                save(raw)
            if not state['drain_empty_read']:
                raise TimeoutError('Stopped-stream drain incomplete')
        except BaseException as exc:
            state['cleanup_errors'].append(type(exc).__name__ + ': ' + str(exc))
            failure = failure or exc
    state.update(structure_checked_rows=frames.rows, range_histogram=frames.ranges,
                 saturated_adc_observations=frames.saturated,
                 remainder_bytes=state['raw_bytes'] % 4,
                 host_elapsed_to_stop_s=state['before_stop_at'] - started)
    if not state['raw_bytes'] or state['remainder_bytes']:
        failure = failure or ValueError('Empty or partial raw frames')
    if failure:
        raise failure
    state['acquisition_completed'] = True


def interrupted(signum, frame):
    raise InterruptedError('Passive observation signal ' + str(signum))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--execute-passive-observation', action='store_true', required=True)
    args = p.parse_args(argv)
    pins = {str(path): v.snapshot(path) for path in (SELF, *HASHES)}
    for path, expected in HASHES.items():
        v.require(pins[str(path)]['sha256'] == expected, 'Changed helper')
    owner = v.Output(args.output)
    state = dict(schema=1, kind='passive_existing_state_raw_diagnostic',
                 timestamp_utc=datetime.now(timezone.utc).isoformat(),
                 duration_policy_seconds=DURATION, output_state='not queried or changed',
                 duration_is_not_electrical_time=True, physical_lossless_sampling_verified=False,
                 current_or_energy_computed=False, source_pins_before=pins,
                 acquisition_completed=False, commands=[], **FLAGS)
    error = None
    handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM)}
    try:
        owner.write('INTENT.json', v.encoded(state))
        for s in handlers:
            signal.signal(s, interrupted)
        info = load_fixed(INFO)
        matches = [d for d in info.devices() if d['serial'] == PPK_SERIAL]
        v.require(len(matches) == 1, 'Exact PPK2 serial not uniquely present')
        state['device'] = matches[0]
        with info.serial.Serial(matches[0]['port'], baudrate=115200, timeout=.02,
                                write_timeout=.3, exclusive=True) as port:
            fcntl.ioctl(port.fileno(), termios.TIOCEXCL)
            state['metadata_command_hex'] = '19'
            raw, fields = info.query_metadata(port)
            state.update(raw_metadata=raw.decode('ascii'), metadata_fields=fields)
            tail = port.read(256)
            state['metadata_tail_hex'] = tail.hex()
            v.require(not any(b not in b'\r\n\t ' for b in tail), 'Unexpected metadata tail')
            with owner.open_new('samples.u32le') as sink:
                try:
                    signal.setitimer(signal.ITIMER_REAL, 6)
                    collect(port, sink, fields, state)
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    state['raw_pin'] = owner.finish(sink, 'samples.u32le')
    except BaseException as exc:
        error = exc
        state['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        for s, handler in handlers.items():
            signal.signal(s, handler)
        try:
            v.recheck(pins)
            v.recheck(owner.pins)
        except BaseException as exc:
            error = error or exc
            state['retention_error'] = str(exc)
        if error:
            state['acquisition_completed'] = False
        try:
            owner.write('report.json', v.encoded(state))
            v.recheck({**pins, **owner.pins})
            owner.guard()
        finally:
            owner.close()
    print(json.dumps({k: state[k] for k in ('acquisition_completed', 'output_switch_command_sent',
                     'model_executed', 'energy_measured', 'research_measurement_accepted')}))
    return 1 if error else 0


if __name__ == '__main__':
    raise SystemExit(main())
