"""End-to-end driver tests: emulated SM07M firmware + emulated PPK2 session."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'ppk2_energy'))
sys.path.insert(0, str(HERE.parent / 'host_sram'))
import measure  # noqa: E402
import validation  # noqa: E402
import test_ppk2_session as tps  # noqa: E402  (real device metadata)
import test_analyze_schedule as tas  # noqa: E402

F = 64_000_000
BENCH_CYC, OVER_CYC = 6_039_413, 480
BASE_CUR, BENCH_CUR, OVER_CUR = 330, 372, 331      # range-4 ADC codes (~0.24 A / ~0.27 A)
LO = 0x34070000


class FakeFirmware:
    """RAM image + SM07M command semantics with a cycle timeline.
    `delay_s` > 0 makes commands finish only after that many host seconds."""
    def __init__(self, sym, outputs, marker=measure.MARKER, delay_s=0.0, marker_load=0, pin_ok=True):
        self.pin_ok = pin_ok
        self.mem = bytearray(0x100000 - (LO & 0xFFFFF))
        self.sym, self.outputs, self.delay_s, self.marker_load = sym, outputs, delay_s, marker_load
        self.timeline, self.pending, self.commit_readbacks = [], None, 0
        struct.pack_into('<4I', self.mem, self.off(sym['g_measure']), measure.S7_MAGIC, 1, measure.S7_BYTES, 1)
        struct.pack_into('<4I', self.mem, self.off(sym['g_measure']) + 0x20, sym['g_rows_in'], sym['g_rows_out'], 1024, marker)
        struct.pack_into('<I', self.mem, self.off(measure.MAILBOX) + 12, 3)

    def off(self, a):
        return a - LO

    def read(self, a, n):
        if a == measure.GPIOH_IDR and n == 4:      # simulated PH8 level: 0.1 s pulses for 1 s after commit
            dt = time.monotonic() - getattr(self, 't_commit', -9.0)
            level = int(0 <= dt < 1.0 and int(dt / 0.1) % 2 == 0) if self.pin_ok else 0
            return struct.pack('<I', level << 8)
        if self.pending and time.monotonic() >= self.pending:
            self.finish()
        if a == self.sym['g_measure'] + 0x10 and n == 4:
            self.commit_readbacks += 1
        return bytes(self.mem[self.off(a):self.off(a) + n])

    def write(self, a, raw):
        self.mem[self.off(a):self.off(a) + len(raw)] = raw
        if a == self.sym['g_measure'] + 0x10:
            self.t_commit = time.monotonic()
            self.put(0x0C, 2)                                   # BUSY
            self.pending = time.monotonic() + self.delay_s
            if not self.delay_s:
                self.finish()
        return len(raw)

    def u32(self, o):
        return struct.unpack_from('<I', self.mem, self.off(self.sym['g_measure']) + o)[0]

    def put(self, o, *vals):
        struct.pack_into(f'<{len(vals)}I', self.mem, self.off(self.sym['g_measure']) + o, *vals)

    def finish(self):
        self.pending = None
        import analyze_schedule as az
        cmd = self.u32(0x18)
        p = dict(zip(measure.PARAM_FIELDS, struct.unpack_from('<7I', self.mem, self.off(self.sym['g_measure']) + 0x30)))
        self.timeline, windows, t = [], [], 0.0
        def win(kind, dur, iters, high, ck, adc):
            nonlocal t
            s = int(t * F) & 0xFFFFFFFF
            self.timeline.append((dur, high, adc + (self.marker_load if high else 0)))
            t += dur
            windows.append((kind, s, int(t * F) & 0xFFFFFFFF, iters, ck, high))
        def gap(dur):
            nonlocal t
            self.timeline.append((dur, 0, BASE_CUR)); t += dur
        if cmd == 1:
            out = b''.join(self.outputs[:p['n_rows']])
            o = self.off(self.sym['g_rows_out'])
            self.mem[o:o + len(out)] = out
            self.put(0x50, (BENCH_CYC * p['n_rows']) & 0xFFFFFFFF, (BENCH_CYC * p['n_rows']) >> 32, BENCH_CYC, BENCH_CYC)
        else:
            rows_in = [struct.unpack_from('<41I', self.mem, self.off(self.sym['g_rows_in']) + 164 * r) for r in range(1024)]
            outs = [struct.unpack('<5I', o) for o in self.outputs]
            w = p['pulse_cycles'] / F
            for _ in range(p['pulse_count']):
                win(4, w, 0, 1, 2166136261, BASE_CUR); gap(w)
            if cmd == 2:
                ckb, cko = az.expected_checksums(outs, rows_in, p['n_rows'], p['bench_reps'], p['overhead_reps'])
                for _ in range(p['cycles']):
                    win(1, p['idle_cycles'] / F, 0, 0, 2166136261, BASE_CUR)
                    n = p['bench_reps'] * p['n_rows']
                    win(2, n * BENCH_CYC / F, n, 1, ckb, BENCH_CUR)
                    win(1, p['idle_cycles'] / F, 0, 0, 2166136261, BASE_CUR)
                    n2 = p['overhead_reps'] * p['n_rows']
                    win(3, n2 * OVER_CYC / F, n2, 1, cko, OVER_CUR)
                win(1, p['idle_cycles'] / F, 0, 0, 2166136261, BASE_CUR)
        for i, rec in enumerate(windows):
            self.put(0x70 + 32 * i, *rec, 0, 0)
        self.put(0x60, len(windows))
        self.put(0x0C, 3)
        self.put(0x14, self.u32(0x10))


class FakePpk:
    """Session directory with FIFO, status, events and synthesized segments."""
    def __init__(self, root, firmware):
        self.dir, self.fw = Path(root), firmware
        os.mkfifo(self.dir / 'control')
        (self.dir / 'session.json').write_text(json.dumps(dict(metadata=dict(tps.META, mode='1'), source_sha256={
            str(measure.PPK_TOOLS / 'ppk2_session.py'): measure.sha(measure.PPK_TOOLS / 'ppk2_session.py')})))
        self.samples = 0
        (self.dir / 'events.jsonl').write_text('')
        self.label, self.n, self.stop_flag, self.clock_skew_s, self.inject_gap = None, 0, False, 0.0, False
        self.status()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def status(self):                         # atomic, like ppk2_session.write_json_atomic
        tmp = self.dir / 'status.tmp'
        tmp.write_text(json.dumps(dict(
            utc=datetime.now(timezone.utc).isoformat(), output_on=True, guard_tripped=False,
            powered_seen=True, mean_uA_last_1s=240_000.0)))
        os.replace(tmp, self.dir / 'status.json')

    def event(self, **kw):
        with (self.dir / 'events.jsonl').open('a') as f:
            f.write(json.dumps(kw) + '\n')

    def loop(self):
        fd = os.open(self.dir / 'control', os.O_RDONLY | os.O_NONBLOCK)
        keep = os.open(self.dir / 'control', os.O_WRONLY | os.O_NONBLOCK)
        buf = b''
        while not self.stop_flag:
            self.status()
            try:
                buf += os.read(fd, 4096)
            except BlockingIOError:
                pass
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                word, _, arg = line.decode().partition(' ')
                if word == 'start':
                    self.label = arg
                    self.t_start = time.monotonic()
                    self.event(kind='segment_start', label=arg, path=f'seg_{self.n:03d}_{arg}.u32le',
                               host_monotonic=self.t_start, sample_index=self.samples)
                elif word == 'stop' and self.label:
                    frames = tas.synth([(0.4, BASE_CUR, 0)] + [(d, a, m) for d, m, a in self.fw.timeline]
                                       + [(0.4, BASE_CUR, 0)])
                    path = self.dir / f'seg_{self.n:03d}_{self.label}.u32le'
                    path.write_bytes(frames.tobytes())
                    if self.inject_gap:
                        self.event(kind='reader_gap', gap_s=0.4, sample_index=self.samples + 1000)
                    self.samples += len(frames)
                    self.event(kind='segment_stop', label=self.label, path=path.name, frames=len(frames),
                               sha256=hashlib.sha256(frames.tobytes()).hexdigest(), sample_index=self.samples,
                               host_monotonic=self.t_start + len(frames) / 100_000 + self.clock_skew_s)
                    self.n += 1
                    self.label = None
            time.sleep(0.02)
        os.close(fd); os.close(keep)


def run_procedure(tmp, delay_s=0.0, marker=measure.MARKER, marker_load=0, pin_ok=True, skew=0.0, gap=False,
                  stale_recorder=False):
    sym = measure.symbols()
    rng = np.random.default_rng(3)
    x = rng.normal(size=(1024, 41)).astype('<f4')
    y = rng.normal(size=(1024, 5)).astype('<f4')
    rows = tuple((i + 7, x[i].tobytes(), y[i].tobytes()) for i in range(1024))
    fw = FakeFirmware(sym, [r[2] for r in rows], marker=marker, delay_s=delay_s, marker_load=marker_load,
                      pin_ok=pin_ok)
    ppk_dir = Path(tmp) / 'ppk'; ppk_dir.mkdir()
    fake = FakePpk(ppk_dir, fw)
    fake.clock_skew_s = skew
    fake.inject_gap = gap
    if stale_recorder:
        (ppk_dir / 'session.json').write_text(json.dumps(dict(metadata=dict(tps.META, mode='1'),
                                                              source_sha256={'x/ppk2_session.py': 'old'})))
    sink_dir = Path(tmp) / 'sink'; sink_dir.mkdir()
    (sink_dir / 'platform_mailbox.bin').write_bytes(b'x')

    class Sink:
        path = sink_dir
        def json(self, name, value):
            with (sink_dir / name).open('x') as f:
                f.write(json.dumps(value, sort_keys=True, indent=1, allow_nan=False))
        def raw(self, name, payload):
            (sink_dir / name).write_bytes(payload)
    modules = dict(validation=validation,
                   stage_protocol=SimpleNamespace(decode=lambda raw: dict(nominal_cpu_npu_hz=F)))
    args = SimpleNamespace(rows=16, bench_s=1.5, overhead_s=1.0, idle_s=0.6, cycles=3, schedules=2,
                           dose=[2], sham_s=0.5, sham_pulses=4, assumed_volts=5.0)
    old_acc, old_sleep = measure.accepted_outputs, measure.time.sleep
    measure.accepted_outputs = lambda rws: [r[2] for r in rws]
    measure.time.sleep = lambda s: old_sleep(min(s, 0.3))
    try:
        return measure.procedure(fw, rows, modules, Sink(), measure.Ppk(ppk_dir), args), sink_dir, fw
    finally:
        measure.accepted_outputs, measure.time.sleep = old_acc, old_sleep
        fake.stop_flag = True
        fake.thread.join(2)


def _wiring_fault(tmp):
    """Pin toggles over SWD but the PPK2 never sees D0 (loose wire)."""
    import test_analyze_schedule as tas2
    orig = FakePpk.loop
    def loop(self):
        synth = tas2.synth
        tas2.synth = lambda parts: synth([(d, a, 0) for d, a, m in parts])    # drop every D0 edge
        try:
            orig(self)
        finally:
            tas2.synth = synth
    FakePpk.loop = loop
    try:
        run_procedure(tmp)
    finally:
        FakePpk.loop = orig


class DriverTest(unittest.TestCase):
    def test_procedure_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, sink_dir, fw = run_procedure(tmp)
            self.assertTrue(result['full_logit_parity_passed'])
            self.assertTrue(result['bitwise_equal_to_accepted_run08'])
            self.assertTrue(result['all_schedules_valid'])
            summ = json.loads((sink_dir / 'MEASUREMENT_SUMMARY.json').read_text())
            self.assertEqual(summ['valid_schedules'], 3)
            self.assertEqual(summ['headline_gross_J_per_inference_between_schedules']['n'], 2)
            self.assertGreater(summ['incremental_over_spin_J_per_inference_between_schedules']['mean'], 0)
            self.assertTrue(summ['dose_response_gross_J_vs_N']['linear'])
            dose = summ['dose_response_incremental_J_vs_N']
            self.assertTrue(dose['linear'])
            self.assertLess(abs(dose['intercept_rel_to_smallest_window']), 1e-4)
            self.assertAlmostEqual(summ['cpu_hz_estimate'][0]['mean'], F, delta=F * 1e-4)
            self.assertTrue(json.loads((sink_dir / 'WIRING.json').read_text())['passed'])
            sham = json.loads((sink_dir / 'SHAM.json').read_text())
            self.assertTrue(sham['valid'], sham['problems'])
            self.assertAlmostEqual(sham['null_dI_mA']['mean'], 0.0, places=6)
            self.assertEqual(fw.commit_readbacks, 0, 'commit write must not be read back')
            self.assertTrue((sink_dir / 'parity_outputs_sm07m.bin').exists())
            self.assertIsNotNone(summ['systematic']['gross_rel_bounds'])
            self.assertGreater(summ['headline_gross_J_per_inference_between_schedules']['mean'], 0)
            self.assertTrue(json.loads((sink_dir / 'WIRING.json').read_text())['swd']['frames_vs_host_ok'])

    def test_wire_fault_is_diagnosed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, 'PH8 toggled .* PPK2 D0 did not follow'):
                _wiring_fault(tmp)

    def test_reader_gap_invalidates_captures(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, sink_dir, fw = run_procedure(tmp, gap=True)
            self.assertFalse(result['all_schedules_valid'])
            a = json.loads((sink_dir / 'schedule_00_repeat1_analysis.json').read_text())
            self.assertTrue(any('reader gap' in p for p in a['problems']))

    def test_stale_recorder_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, 'restart the session'):
                run_procedure(tmp, stale_recorder=True)

    def test_frames_vs_host_skew_is_descriptive(self):
        # Amendment 3: consumer backlog at segment boundaries is not loss (reader gaps are)
        with tempfile.TemporaryDirectory() as tmp:
            result, sink_dir, fw = run_procedure(tmp, skew=0.5)
            self.assertTrue(result['all_schedules_valid'])
            self.assertTrue(result['session_eligible'])
            a = json.loads((sink_dir / 'schedule_00_repeat1_analysis.json').read_text())
            self.assertTrue(any('consumer backlog' in n for n in a.get('notes', [])))

    def test_wrong_marker_image_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, 'not PH8'):
                run_procedure(tmp, marker=0x0045000F)

    def test_marker_load_stops_measurement(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, 'Marker pin changes board current'):
                run_procedure(tmp, marker_load=2)          # ~1.6 mA while marker HIGH

    def test_poll_inside_window_invalidates(self):
        m = measure.Measure(None, dict(g_measure=0, g_rows_in=0, g_rows_out=0), measure.SwdLog())
        states = iter([dict(response=0, state=2, error=0, first_bad_row=0), dict(response=1, state=3, error=0, first_bad_row=0)])
        m.seq = 1
        m.header = lambda: next(states)
        m.adapter_fault = lambda: None
        old = measure.time.sleep
        measure.time.sleep = lambda s: None
        try:
            _, first = m.wait(timeout_s=5, first_poll_s=0, poll_s=0)
        finally:
            measure.time.sleep = old
        self.assertFalse(first)


if __name__ == '__main__':
    unittest.main()
