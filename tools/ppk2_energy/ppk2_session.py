"""Persistent PPK2 Ampere-Meter session: keeps DUT power ON across runs.

Why this exists: closing the PPK2 serial port re-enumerates the device (seen
2026-09-25), which drops the output and wipes an SRAM-loaded N6 image. This
process owns the port for the whole experiment, samples continuously, and only
writes full-rate raw frames inside labelled segments.

- Mode is never changed; the session refuses to start unless metadata mode==1.
- Always-on 10 ms summary (CSV) and a live status.json for monitoring.
- Sustained-overcurrent guard (default 950 mA mean over 100 ms, PPK2 AM rating
  is 1 A continuous) switches the output OFF. This is a PPK2 self-protection
  policy, not a validated board protection.
- Control: write one command per line to DIR/control (FIFO):
    start LABEL | stop | on | off | quit
Current uses the Nordic v4.4.1 formula via analyze.coefficients(); the S-term
correction voltage is an ASSUMED nominal value, not a measured VIN.
"""
import argparse
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import signal
import threading
import sys
import termios
import time

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze  # noqa: E402  (Codex-tested coefficient handling)

INFO = Path('/home/thc1006/.local/opt/ppk2-headless/ppk2_info.py')
PPK_SERIAL = 'F4728E9B55E0'
CMD_START, CMD_STOP = b'\x06', b'\x07'
CMD_ON, CMD_OFF = b'\x0c\x01', b'\x0c\x00'
FS = 100_000                 # nominal samples/s (Nordic)
BIN = 1000                   # 10 ms summary bins
GUARD_WINDOW = 10_000        # 100 ms
SILENCE_S = 1.0
READER_GAP_S = 0.1           # > this between USB reads may overflow the kernel tty buffer (~160 ms at 400 kB/s)


def utc():
    return datetime.now(timezone.utc).isoformat()


class Converter:
    """Vectorized Nordic current formula; identical math to analyze.Decoder
    with spike filter 'none'."""
    def __init__(self, metadata, volts, policy='metadata-exact'):
        coef, self.substitutions = analyze.coefficients(metadata, policy)
        self.volts = analyze.voltage(volts)
        self.c = {k: np.asarray(v, dtype=np.float64) for k, v in coef.items()}

    def ua(self, words):
        adc = (words & 0x3FFF).astype(np.float64)
        r = ((words >> 14) & 7).astype(np.int64)
        bad = r > 4
        r = np.where(bad, 0, r)
        c = self.c
        scaled = (adc * 4 - c['O'][r]) * ((1.8 / 163840) / c['R'][r])
        amps = c['UG'][r] * (scaled * (c['GS'][r] * scaled + c['GI'][r])
                             + (c['S'][r] * self.volts + c['I'][r]))
        out = amps * 1e6
        out[bad] = np.nan
        return out, r, bad


class Session:
    def __init__(self, port, out, conv, guard_ma, clock=time.monotonic):
        self.port, self.out, self.conv, self.clock = port, out, conv, clock
        self.guard_ua = guard_ma * 1000.0
        self.tail = b''
        self.samples = 0
        self.prev_counter = None
        self.discontinuities = []
        self.invalid_range = 0
        self.saturated = 0
        self.ranges = [0] * 5
        self.output_on = False
        self.guard_tripped = False
        self.guard_buf = np.zeros(0)
        self.bin_buf = np.zeros(0)
        self.bin_bits_or = 0
        self.bin_bits_and = 255
        self.bin_rmax = 0
        self.bin_start = 0
        self.last1 = []          # (host_t, mean_ua, max_ua) of recent bins
        self.segment = None
        self.segments = []
        self.events = (out / 'events.jsonl').open('a')
        self.summary = (out / 'summary_10ms.csv').open('a')
        if self.summary.tell() == 0:
            self.summary.write('sample_start,host_monotonic,mean_uA,min_uA,max_uA,'
                               'bits_or,bits_and,range_max\n')
        self.powered_seen = False
        self.reader_gaps = []
        self.last_data = clock()

    # ---- commands -------------------------------------------------------
    def event(self, kind, **kw):
        row = dict(kind=kind, host_monotonic=self.clock(), utc=utc(),
                   sample_index=self.samples, **kw)
        self.events.write(json.dumps(row) + '\n')
        self.events.flush()
        return row

    def write_cmd(self, value, name):
        n = self.port.write(value)
        if n != len(value):
            raise OSError(f'Incomplete {name} write')
        self.port.flush()
        self.event('command', name=name, hex=value.hex())
        if value == CMD_ON:
            self.output_on = True
        elif value == CMD_OFF:
            self.output_on = False

    def start_segment(self, label):
        self.stop_segment()
        safe = ''.join(ch if ch.isalnum() or ch in '-_.' else '_' for ch in label)[:60] or 'seg'
        index = len(self.segments)
        path = self.out / f'seg_{index:03d}_{safe}.u32le'
        fh = path.open('xb')
        self.segment = dict(index=index, label=label, path=path.name, fh=fh,
                            start_sample=self.samples, start_host=self.clock(),
                            sha=hashlib.sha256(), bytes=0, d0_rising=0,
                            d0_last=None)
        self.event('segment_start', label=label, path=path.name)

    def stop_segment(self):
        seg = self.segment
        if not seg:
            return
        seg['fh'].flush()
        os.fsync(seg['fh'].fileno())
        seg['fh'].close()
        row = {k: v for k, v in seg.items() if k not in ('fh', 'sha', 'd0_last')}
        row.update(stop_sample=self.samples, stop_host=self.clock(),
                   sha256=seg['sha'].hexdigest(), frames=seg['bytes'] // 4)
        self.segments.append(row)
        self.segment = None
        self.event('segment_stop', **{k: row[k] for k in ('label', 'path', 'frames', 'sha256',
                                                          'd0_rising')})

    # ---- data path ------------------------------------------------------
    def feed(self, chunk):
        self.last_data = self.clock()
        data = self.tail + chunk
        end = len(data) // 4 * 4
        self.tail = data[end:]
        if not end:
            return
        body = data[:end]
        words = np.frombuffer(body, dtype='<u4')
        counters = (words >> 18) & 63
        expect_first = None if self.prev_counter is None else (self.prev_counter + 1) % 64
        if expect_first is not None and counters[0] != expect_first:
            self.discontinuities.append(self.samples)
        gaps = np.nonzero(counters[1:] != (counters[:-1] + 1) % 64)[0]
        for g in gaps[:100]:
            self.discontinuities.append(self.samples + int(g) + 1)
        self.prev_counter = int(counters[-1])
        ua, r, bad = self.conv.ua(words)
        bits = ((words >> 24) & 255).astype(np.int64)
        adc = words & 0x3FFF
        self.invalid_range += int(bad.sum())
        self.saturated += int((adc == 16383).sum())
        for k in range(5):
            self.ranges[k] += int((r == k).sum())
        if self.segment:
            seg = self.segment
            seg['fh'].write(body)
            seg['sha'].update(body)
            seg['bytes'] += len(body)
            d0 = (bits & 1).astype(np.int8)
            if seg['d0_last'] is not None:
                d0 = np.concatenate(([seg['d0_last']], d0))
                seg['d0_rising'] += int(((d0[1:] == 1) & (d0[:-1] == 0)).sum())
                seg['d0_last'] = int(d0[-1])
            else:
                seg['d0_rising'] += int(((d0[1:] == 1) & (d0[:-1] == 0)).sum())
                seg['d0_last'] = int(d0[-1])
        self.samples += len(words)
        self._bins(ua, bits, r)
        self.summary.flush()
        self._guard(ua)

    def _bins(self, ua, bits, r):
        pos = 0
        n = len(ua)
        while pos < n:
            need = BIN - len(self.bin_buf)
            take = ua[pos:pos + need]
            self.bin_buf = np.concatenate((self.bin_buf, take))
            b = bits[pos:pos + need]
            self.bin_bits_or |= int(np.bitwise_or.reduce(b)) if len(b) else 0
            self.bin_bits_and &= int(np.bitwise_and.reduce(b)) if len(b) else 255
            self.bin_rmax = max(self.bin_rmax, int(r[pos:pos + need].max()) if len(b) else 0)
            pos += len(take)
            if len(self.bin_buf) == BIN:
                v = self.bin_buf[np.isfinite(self.bin_buf)]
                mean = float(v.mean()) if len(v) else float('nan')
                lo = float(v.min()) if len(v) else float('nan')
                hi = float(v.max()) if len(v) else float('nan')
                t = self.clock()
                self.summary.write(f'{self.bin_start},{t:.6f},{mean:.3f},{lo:.3f},{hi:.3f},'
                                   f'{self.bin_bits_or},{self.bin_bits_and},{self.bin_rmax}\n')
                self.last1.append((t, mean, hi))
                self.last1 = self.last1[-100:]
                if mean > 20_000:
                    self.powered_seen = True
                self.bin_start += BIN
                self.bin_buf = np.zeros(0)
                self.bin_bits_or, self.bin_bits_and, self.bin_rmax = 0, 255, 0

    def _guard(self, ua):
        v = np.nan_to_num(ua, nan=0.0)
        self.guard_buf = np.concatenate((self.guard_buf, v))[-GUARD_WINDOW:]
        if (self.output_on and len(self.guard_buf) == GUARD_WINDOW
                and self.guard_buf.mean() > self.guard_ua):
            self.guard_tripped = True
            self.write_cmd(CMD_OFF, 'guard_output_off')
            self.event('guard_trip', mean_uA_100ms=float(self.guard_buf.mean()))

    def status(self):
        recent = self.last1[-100:]
        means = [m for _, m, _ in recent if m == m]
        return dict(utc=utc(), samples=self.samples, seconds=self.samples / FS,
                    output_on=self.output_on, guard_tripped=self.guard_tripped,
                    mean_uA_last_1s=(sum(means) / len(means)) if means else None,
                    max_uA_last_1s=max((h for _, _, h in recent if h == h), default=None),
                    powered_seen=self.powered_seen,
                    counter_discontinuities=len(self.discontinuities),
                    reader_gaps=len(self.reader_gaps),
                    invalid_range_frames=self.invalid_range,
                    adc_upper_rail_frames=self.saturated, range_histogram=self.ranges,
                    recording=None if not self.segment else self.segment['label'],
                    segments_done=len(self.segments))


class Reader(threading.Thread):
    """Drains the PPK2 port into memory and never touches the disk.

    2026-09-29 run_03: with the single-threaded loop, disk-write stalls under
    host IO pressure blocked USB reads and 5.8 s of samples were lost (in
    counter-invisible multiples of 64). Any gap longer than READER_GAP_S
    between reads is queued as a 'gap' marker, in stream order."""
    def __init__(self, port, gap_s=READER_GAP_S, clock=time.monotonic):
        super().__init__(name='ppk2-reader', daemon=True)
        self.port, self.gap_s, self.clock = port, gap_s, clock
        self.q = queue.Queue()
        self.stop_flag = threading.Event()
        self.last_data = clock()

    def run(self):
        prev = None
        try:
            while not self.stop_flag.is_set():
                chunk = self.port.read(65536)
                now = self.clock()
                if chunk:
                    if prev is not None and now - prev > self.gap_s:
                        self.q.put(('gap', now - prev, now))
                    prev = self.last_data = now
                    self.q.put(('data', chunk, now))
        except BaseException as exc:
            self.q.put(('error', exc, self.clock()))


def stlink_present(serial_no, by_id=Path('/dev/serial/by-id')):
    try:
        return any(serial_no in p.name for p in by_id.iterdir())
    except FileNotFoundError:
        return False


class Arm:
    """Switch output ON only after the ST-LINK has been absent for `hold_s`.

    With JP2 1-2 open, CN6 unplugged means 5V_STLK (PPK2 VIN) is dead, so ON
    closes the path with no current. Re-plugging CN6 then brings the board up
    through the ST-LINK's own switch turn-on, not a PPK2 step onto a live rail
    (the 2026-09-25 trip pattern)."""
    def __init__(self, serial_no, hold_s=2.0, present=stlink_present, clock=time.monotonic):
        self.serial_no, self.hold_s, self.present, self.clock = serial_no, hold_s, present, clock
        self.absent_since = None
        self.fired = False
        self.returned_at = None

    def poll(self, session):
        here = self.present(self.serial_no)
        now = self.clock()
        if self.fired:
            if here and self.returned_at is None:
                self.returned_at = now
                session.event('stlink_returned')
            return
        if here:
            self.absent_since = None
            return
        if self.absent_since is None:
            self.absent_since = now
            session.event('stlink_absent')
        elif now - self.absent_since >= self.hold_s:
            session.write_cmd(CMD_ON, 'armed_output_on_while_stlink_absent')
            self.fired = True


def write_json_atomic(path, obj):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, indent=1, allow_nan=True) + '\n')
    os.replace(tmp, path)


def load_info():
    spec = importlib.util.spec_from_file_location('_ppk2_info', INFO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(args):
    import serial
    out = args.out
    if not out.is_absolute() or os.path.lexists(out):
        raise SystemExit('Use a fresh absolute --out directory')
    out.mkdir(parents=True, mode=0o755)
    fifo = out / 'control'
    os.mkfifo(fifo)
    info = load_info()
    matches = [p for p in info.devices() if p['serial'] == args.serial]
    if len(matches) != 1:
        raise SystemExit(f'PPK2 {args.serial} not uniquely present')
    header = dict(schema='ppk2-session-v1', utc=utc(), ppk=matches[0], argv=sys.argv,
                  source_sha256={str(p): hashlib.sha256(Path(p).read_bytes()).hexdigest()
                                 for p in (Path(__file__).resolve(), HERE / 'analyze.py', INFO)},
                  correction_voltage_assumed_v=args.volts, policy=args.policy,
                  guard_mA=args.guard_ma, fs_nominal=FS, summary_bin_samples=BIN,
                  note='VIN not measured; S-term uses assumed voltage.')
    stop = {'flag': False}

    def on_signal(signum, frame):
        stop['flag'] = True
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    ctl = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    keep = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)  # avoid EOF spin
    ctl_buf = b''
    with serial.Serial(matches[0]['port'], baudrate=115200, timeout=0.02,
                       write_timeout=0.5, exclusive=True) as port:
        fcntl.ioctl(port.fileno(), termios.TIOCEXCL)
        raw_meta, meta = info.query_metadata(port)
        header.update(raw_metadata=raw_meta.decode('ascii'), metadata=meta)
        if meta.get('mode') != '1':
            write_json_atomic(out / 'session.json', dict(header, error='mode is not Ampere (1)'))
            raise SystemExit('PPK2 not in Ampere mode; refusing (mode is never changed here)')
        conv = Converter(meta, args.volts, args.policy)
        header['coefficient_substitutions'] = conv.substitutions
        write_json_atomic(out / 'session.json', header)
        s = Session(port, out, conv, args.guard_ma)
        port.read(4096)  # discard metadata tail if any
        if args.record_initial:
            s.start_segment(args.record_initial)
        s.write_cmd(CMD_START, 'sampling_start')
        if args.initial_output == 'on':
            s.write_cmd(CMD_ON, 'output_on')
        arm = Arm(args.arm_on_when_absent) if args.arm_on_when_absent else None
        if arm:
            s.event('armed', stlink_serial=args.arm_on_when_absent,
                    stlink_present_now=stlink_present(args.arm_on_when_absent))
        last_status = last_arm = 0.0
        error = None
        reader = Reader(port)
        reader.start()

        def consume(timeout):
            try:
                kind, value, t = reader.q.get(timeout=timeout)
            except queue.Empty:
                return False
            if kind == 'data':
                s.feed(value)
            elif kind == 'gap':
                s.reader_gaps.append((s.samples, value))
                s.event('reader_gap', gap_s=value)
            else:
                raise value
            return True
        try:
            while not stop['flag']:
                consume(0.05)
                if time.monotonic() - reader.last_data > SILENCE_S:
                    raise TimeoutError('PPK2 stream silent > 1 s')
                if arm and time.monotonic() - last_arm > 0.2:
                    arm.poll(s)
                    last_arm = time.monotonic()
                try:
                    ctl_buf += os.read(ctl, 4096)
                except BlockingIOError:
                    pass
                while b'\n' in ctl_buf:
                    line, ctl_buf = ctl_buf.split(b'\n', 1)
                    cmd = line.decode('utf-8', 'replace').strip()
                    if not cmd:
                        continue
                    s.event('control', text=cmd)
                    word, _, arg = cmd.partition(' ')
                    if word == 'start':
                        s.start_segment(arg.strip() or 'seg')
                    elif word == 'stop':
                        s.stop_segment()
                    elif word == 'on':
                        s.write_cmd(CMD_ON, 'output_on')
                    elif word == 'off':
                        s.write_cmd(CMD_OFF, 'output_off')
                    elif word == 'quit':
                        stop['flag'] = True
                    else:
                        s.event('control_rejected', text=cmd)
                now = time.monotonic()
                if now - last_status > 0.5:
                    write_json_atomic(out / 'status.json', s.status())
                    last_status = now
        except BaseException as exc:
            error = f'{type(exc).__name__}: {exc}'
            s.event('error', text=error)
        finally:
            for value, name in ((CMD_OFF, 'final_output_off'), (CMD_STOP, 'sampling_stop')):
                try:
                    s.write_cmd(value, name)
                except BaseException as exc:
                    s.event('cleanup_error', name=name, text=str(exc))
            time.sleep(0.3)                           # let the reader collect the tail
            reader.stop_flag.set()
            reader.join(2.0)
            try:
                while consume(0):
                    pass
            except BaseException as exc:  # e.g. USB unplugged: still publish the report
                s.event('drain_error', text=f'{type(exc).__name__}: {exc}')
            s.stop_segment()
            final = dict(header, finished_utc=utc(), error=error, status=s.status(),
                         segments=s.segments, discontinuities_first=s.discontinuities[:200],
                         reader_gaps=s.reader_gaps[:1000])
            write_json_atomic(out / 'session.json', final)
            write_json_atomic(out / 'status.json', s.status())
            os.close(ctl)
            os.close(keep)
            s.events.close()
            s.summary.close()
    return 0 if error is None else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--serial', default=PPK_SERIAL)
    p.add_argument('--volts', type=float, default=5.0,
                   help='ASSUMED correction voltage for the S-term (not measured)')
    p.add_argument('--policy', default='metadata-exact', choices=analyze.POLICIES)
    p.add_argument('--guard-ma', type=float, default=950.0)
    p.add_argument('--initial-output', choices=('on', 'off'), default='off')
    p.add_argument('--record-initial', default=None, metavar='LABEL')
    p.add_argument('--arm-on-when-absent', default=None, metavar='STLINK_SERIAL',
                   help='turn output ON once this ST-LINK has been unplugged for 2 s')
    args = p.parse_args(argv)
    if args.arm_on_when_absent and args.initial_output == 'on':
        p.error('--arm-on-when-absent requires --initial-output off')
    return run(args)


if __name__ == '__main__':
    sys.exit(main())
