"""SM07M on-board power measurement driver. Default: offline checks only.

One connected session on a board that the PPK2 session already powers:
 1. Codex's frozen SM06 controller does platform stage, model load, ACK, READY
    and all its register/runtime checks; only its per-row collector is swapped.
 2. PARITY: all 1024 rows through the SM07M batch path. Requires bitwise equality
    with the accepted SM06 run08 outputs AND the original evaluate() policy.
 3. WIRING: 5 marker pulses (PH8 = Arduino D12) captured by the PPK2 on D0.
 4. SHAM null control: 1 s HIGH / 1 s LOW, both busy-wait; the marker is the
    only difference. Gives the method floor and the marker pin's own load.
 5. CALIBRATION: short schedule (firmware timing only) sizes the windows.
 6. SCHEDULES: K identical (repeatability) + dose schedules at 2x and 4x
    inferences per window (linearity). One PPK2 segment each.
SWD rule: the commit write has no readback, and the first poll comes only after
the schedule should have ended; if that poll finds it still running, the
schedule is invalid (the host touched SWD inside a measured window).
Nothing here powers, resets, flashes, or changes the PPK2 mode or voltage.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import struct
import subprocess
import sys
import time
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
N6 = HERE.parent
REPO = N6.parents[1]
PPK_TOOLS = REPO / 'tools/ppk2_energy'
FULLRUN = N6 / 'host_sram_accum24_route/fullrun.py'
FULLRUN_SHA = 'c6d66ec1f863d5d0646f9dac917746c6fd5b45723d408df8715bd9aa6d178458'
BUILD = N6 / 'firmware_sram_measure/build_03'    # PH8 marker + review fixes
BUILD_PINS = {'RESULT.json': 'caf88a6c102a7a6a2372d99fef68e73251c4b819f9aabb3c269b65a948447b8d',
              'n6_sram.elf': 'f9b82f080f8d4a047a3cd650a6fc670d527b6b01c81df31750a3f5b15c70b55f'}
TAG = 0x534D3037
MARKER = 0x00480008                                # 'H', pin 8 = Arduino D12 (CN12-5)
MAILBOX = 0x340F8000
GPIOH_IDR = 0x56021C10                             # PH8 input level (read-only diagnostic)
ACCEPTED_RUN = REPO / 'results/n6_sram_validation_20260926_08'
SELECTION_GATE = REPO / 'tools/board_deployment/verify_n6_selection.py'

S7_MAGIC, S7_VERSION, S7_BYTES = 0x4D374D53, 1, 0x70 + 32 * 128
IDLE, BUSY, DONE, ERROR = 1, 2, 3, 4
CMD_PARITY, CMD_SCHEDULE, CMD_PULSES = 1, 2, 3
PARAM_FIELDS = ('n_rows', 'bench_reps', 'overhead_reps', 'cycles', 'idle_cycles',
                'pulse_cycles', 'pulse_count')          # offsets 0x30..0x48


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


# ---------------------------------------------------------------- bindings
def bindings():
    require(sha(FULLRUN) == FULLRUN_SHA, 'SM06 fullrun launcher changed')
    spec = importlib.util.spec_from_file_location('_sm07m_fullrun', FULLRUN)
    fullrun = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fullrun)
    old, modules, pins, controller, rp = fullrun.bindings()
    rp.TAG = TAG                      # decode() reads this module global at call time
    old.BUILD, old.BUILD_PINS = BUILD, dict(BUILD_PINS)
    for p in (Path(__file__).resolve(), PPK_TOOLS / 'analyze_schedule.py',
              PPK_TOOLS / 'ppk2_session.py', PPK_TOOLS / 'analyze.py'):
        pins[str(p)] = sha(p)
    return fullrun, old, modules, pins, controller, rp


def symbols():
    table = {}
    for line in (BUILD / 'symbols.stdout').read_text().splitlines():
        parts = line.split()
        if len(parts) == 4:
            table[parts[3]] = (int(parts[0], 16), int(parts[1], 16))
    want = {'g_measure': S7_BYTES, 'g_rows_in': 1024 * 41 * 4, 'g_rows_out': 1024 * 5 * 4,
            'g_mailbox': 512}
    for name, size in want.items():
        require(name in table and table[name][1] == size, f'ELF symbol {name} missing or wrong size')
    require(table['g_mailbox'][0] == MAILBOX, 'Mailbox address changed')
    return {k: table[k][0] for k in want}


def accepted_outputs(rows):
    outs = []
    for i, (row_id, inputs, _) in enumerate(rows):
        rec = json.loads((ACCEPTED_RUN / f'row_{i:04d}.json').read_text())
        require(rec['row_id'] == row_id and rec['input_hex'] == inputs.hex(),
                f'Accepted run08 row {i} does not match the frozen bundle row')
        outs.append(bytes.fromhex(rec['output_hex']))
    return outs


# ---------------------------------------------------------------- PPK2 session
class Ppk:
    def __init__(self, directory):
        self.dir = Path(directory)
        require((self.dir / 'control').exists(), f'No PPK2 session control FIFO in {self.dir}')
        self.active = None

    def status(self):
        for attempt in range(20):             # the session replaces status.json atomically;
            try:                              # retry anyway rather than fail on a racy read
                return json.loads((self.dir / 'status.json').read_text())
            except (json.JSONDecodeError, FileNotFoundError):
                if attempt == 19:
                    raise
                time.sleep(0.05)

    def require_powered(self):
        s = self.status()
        age = time.time() - datetime.fromisoformat(s['utc']).timestamp()
        require(age < 5, 'PPK2 session status is stale (session not running?)')
        require(s['output_on'] and not s['guard_tripped'], 'PPK2 output is not ON (or guard tripped)')
        require(s['powered_seen'] and (s['mean_uA_last_1s'] or 0) > 20_000,
                'Board current < 20 mA: board not powered through the PPK2')
        return s

    def command(self, text):
        fd = os.open(self.dir / 'control', os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, (text + '\n').encode())
        finally:
            os.close(fd)

    def events(self):
        return [json.loads(l) for l in (self.dir / 'events.jsonl').read_text().splitlines() if l.strip()]

    def record(self, label):
        before = len(self.events())
        self.command(f'start {label}')
        self.active = label                       # abandon() must work even if we time out below
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            for e in self.events()[before:]:
                if e['kind'] == 'segment_start' and e['label'] == label:
                    return e
            time.sleep(0.05)
        raise TimeoutError(f'PPK2 segment {label} did not start')

    def stop(self, label):
        before = len(self.events())
        self.command('stop')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for e in self.events()[before:]:
                if e['kind'] == 'segment_stop' and e['label'] == label:
                    self.active = None
                    return self.dir / e['path'], e
            time.sleep(0.05)
        raise TimeoutError(f'PPK2 segment {label} did not close')

    def abandon(self):
        """Best-effort stop after an error so raw recording never runs on."""
        if self.active:
            try:
                self.stop(self.active)
            except BaseException:
                pass


# ---------------------------------------------------------------- SWD helpers
class SwdLog:
    def __init__(self):
        self.ops = []

    def mark(self):
        return len(self.ops)

    def since(self, index):
        return self.ops[index:]


def read_block(core, address, n, log=None):
    out = bytearray()
    t0 = time.monotonic()
    while len(out) < n:
        k = min(4096, n - len(out))
        chunk = core.read(address + len(out), k)
        require(type(chunk) is bytes and len(chunk) == k, 'Short SWD read')
        out += chunk
    if log is not None:
        log.ops.append(('read', address, n, t0, time.monotonic()))
    return bytes(out)


def write_block(core, address, data, log=None, readback=True):
    t0 = time.monotonic()
    for off in range(0, len(data), 4096):
        piece = data[off:off + 4096]
        require(core.write(address + off, piece) == len(piece), 'SWD write count')
    if log is not None:
        log.ops.append(('write', address, len(data), t0, time.monotonic()))
    if readback:
        require(read_block(core, address, len(data), log) == data, 'SWD write readback mismatch')


def words(core, address, count, log=None):
    return struct.unpack(f'<{count}I', read_block(core, address, 4 * count, log))


class Measure:
    def __init__(self, core, sym, log):
        self.core, self.base, self.sym, self.log = core, sym['g_measure'], sym, log
        self.seq = 0

    def header(self):
        w = words(self.core, self.base, 28, self.log)
        return dict(magic=w[0], version=w[1], struct_bytes=w[2], state=w[3], request=w[4],
                    response=w[5], command=w[6], error=struct.unpack('<i', struct.pack('<I', w[7]))[0],
                    rows_in=w[8], rows_out=w[9], max_rows=w[10], marker=w[11],
                    parity_total=w[20] | (w[21] << 32), parity_min=w[22], parity_max=w[23],
                    windows_used=w[24], first_bad_row=w[25], marker_initialized=w[26])

    def check_header(self):
        h = self.header()
        require((h['magic'], h['version'], h['struct_bytes']) == (S7_MAGIC, S7_VERSION, S7_BYTES),
                'SM07M measure block header mismatch')
        require(h['rows_in'] == self.sym['g_rows_in'] and h['rows_out'] == self.sym['g_rows_out'],
                'Buffer addresses disagree with ELF symbols')
        require(h['marker'] == MARKER, f"Image marker {h['marker']:#x} is not PH8 (D12)")
        require(h['state'] in (IDLE, DONE) and h['request'] == h['response'] == self.seq,
                'Measure block not idle')
        return h

    def issue(self, command, params):
        self.check_header()
        values = [params[k] for k in PARAM_FIELDS]
        require(all(type(v) is int and 0 <= v <= 0xFFFFFFFF for v in values), 'Bad params')
        write_block(self.core, self.base + 0x30, struct.pack('<7I', *values), self.log)
        write_block(self.core, self.base + 0x18, struct.pack('<I', command), self.log)
        self.seq += 1
        # Commit: one aligned 32-bit write, NO readback (the command may already be
        # running). Completion is proven later by response_sequence == seq.
        write_block(self.core, self.base + 0x10, struct.pack('<I', self.seq), self.log, readback=False)
        return time.monotonic()

    def adapter_fault(self):
        w = words(self.core, MAILBOX, 20, self.log)
        if w[3] in (6, 7):
            status = [struct.unpack('<i', struct.pack('<I', x))[0] for x in w[12:19]]
            raise RuntimeError(f'SM06 adapter parked: state {w[3]}, api_status/adapter_error {status}')

    def wait(self, timeout_s, first_poll_s=0.0, poll_s=1.0):
        """Returns (header, done_on_first_poll)."""
        time.sleep(first_poll_s)
        deadline = time.monotonic() + timeout_s
        first = True
        while True:
            h = self.header()
            done = h['response'] == self.seq and h['state'] in (DONE, ERROR)
            if done:
                require(h['state'] == DONE, f"Firmware measure error {h['error']} (row {h['first_bad_row']})")
                return h, first
            self.adapter_fault()
            first = False
            require(time.monotonic() < deadline, f'Measure command timeout (state {h["state"]})')
            time.sleep(poll_s)

    def table(self, count):
        require(0 < count <= 128, 'Window count')
        w = words(self.core, self.base + 0x70, 8 * count, self.log)
        keys = ('kind', 'start_cycle', 'end_cycle', 'iterations', 'checksum', 'marker_high')
        return [dict(zip(keys, w[8 * i:8 * i + 6])) for i in range(count)]


# ---------------------------------------------------------------- procedure
def schedule_seconds(p, f, cyc_bench, cyc_over):
    return (2 * p['pulse_count'] * p['pulse_cycles'] + p['cycles'] * (
        2 * p['idle_cycles'] + p['bench_reps'] * p['n_rows'] * cyc_bench +
        p['overhead_reps'] * p['n_rows'] * cyc_over) + p['idle_cycles']) / f


def procedure(core, rows, modules, sink, ppk, args):
    sys.path.insert(0, str(PPK_TOOLS))
    import analyze_schedule as az
    import ppk2_session
    sym = symbols()
    log = SwdLog()
    m = Measure(core, sym, log)
    sink.json('measure_header_ready.json', m.check_header())
    stage = modules['stage_protocol'].decode((sink.path / 'platform_mailbox.bin').read_bytes())
    f_nom = int(stage['nominal_cpu_npu_hz'])
    require(f_nom in (32_000_000, 64_000_000), 'Unexpected nominal clock')
    session = json.loads((ppk.dir / 'session.json').read_text())
    running = [v for k, v in session['source_sha256'].items() if k.endswith('ppk2_session.py')]
    require(running == [sha(PPK_TOOLS / 'ppk2_session.py')],
            'PPK2 recorder is not the current ppk2_session.py (no reader-gap detection): restart the session')
    conv = ppk2_session.Converter(session['metadata'], args.assumed_volts)
    ua = lambda w: conv.ua(w)[0]
    per_code = az.code_mA(conv.c)
    empty = dict(n_rows=0, bench_reps=0, overhead_reps=0, cycles=0, idle_cycles=0, pulse_cycles=0, pulse_count=0)

    # 1. PARITY through the measured code path.
    inputs = b''.join(r[1] for r in rows)
    t0 = time.monotonic()
    write_block(core, sym['g_rows_in'], inputs, log)
    m.issue(CMD_PARITY, dict(empty, n_rows=1024))
    h, _ = m.wait(timeout_s=900, first_poll_s=5, poll_s=2)
    out = read_block(core, sym['g_rows_out'], 1024 * 20, log)
    sink.raw('parity_outputs_sm07m.bin', out)
    outputs = [out[20 * i:20 * i + 20] for i in range(1024)]
    accepted = accepted_outputs(rows)
    bitwise = [i for i in range(1024) if outputs[i] != accepted[i]]
    records = [dict(row_id=r[0], sequence=i + 1, input_hex=r[1].hex(), output_hex=outputs[i].hex())
               for i, r in enumerate(rows)]
    parity = modules['validation'].evaluate(rows, records)
    parity.update(bitwise_equal_to_accepted_run08=not bitwise, bitwise_mismatch_rows=bitwise[:50],
                  path='SM07M PARITY batch path', cycles_per_inference_mean=h['parity_total'] / 1024,
                  cycles_min=h['parity_min'], cycles_max=h['parity_max'],
                  host_seconds=time.monotonic() - t0, nominal_cpu_hz=f_nom,
                  parity_outputs_sha256=hashlib.sha256(out).hexdigest())
    sink.json('PARITY_SM07M.json', parity)
    require(parity['full_logit_parity_passed'] and not bitwise,
            'SM07M batch-path outputs differ from accepted SM06 outputs; no measurement')
    out_words = [struct.unpack('<5I', o) for o in outputs]
    in_words = [struct.unpack('<41I', r[1]) for r in rows]

    def captured(label, command, params, seconds, poll_pin=False):
        """PPK2 segment around one autonomous command; returns (path, seg, table, swd).
        poll_pin (wiring test only, not a measurement) samples the PH8 input
        register over SWD so a pin fault can be told apart from a wiring fault."""
        ppk.require_powered()
        start = ppk.record(label)
        pin = []
        try:
            time.sleep(0.5)
            mark = log.mark()
            t_commit = m.issue(command, params)
            if poll_pin:
                while time.monotonic() - t_commit < seconds + 0.5:
                    idr = struct.unpack('<I', read_block(core, GPIOH_IDR, 4))[0]
                    pin.append((time.monotonic() - t_commit, (idr >> 8) & 1))
                    time.sleep(0.01)
            h, first_done = m.wait(timeout_s=seconds + 120, first_poll_s=0 if poll_pin else seconds * 1.25 + 2, poll_s=1)
            time.sleep(0.3)
            path, seg = ppk.stop(label)
        finally:
            ppk.abandon()
        table = m.table(h['windows_used'])
        ops = [dict(op=o, address=a, bytes=n, t0=s, t1=e) for o, a, n, s, e in log.since(mark)]
        host_s = seg['host_monotonic'] - start['host_monotonic']
        frames_s = seg['frames'] / 100_000.0
        gaps = [(e['sample_index'] - start['sample_index'], e['gap_s']) for e in ppk.events()
                if e['kind'] == 'reader_gap' and start['sample_index'] <= e['sample_index'] <= seg['sample_index']]
        transitions = sum(1 for i in range(1, len(pin)) if pin[i][1] != pin[i - 1][1])
        return path, seg, table, dict(first_poll_found_done=first_done, t_commit=t_commit, swd_ops=ops,
                                      segment_host_s=host_s, segment_frames_s=frames_s,
                                      frames_vs_host_ok=abs(frames_s - host_s) < 0.05, reader_gaps=gaps,
                                      pin_samples=len(pin), pin_transitions=transitions)

    # 2. WIRING: D0 must see exactly the marker pulses.
    wiring_p = dict(empty, pulse_cycles=int(0.1 * f_nom), pulse_count=5)
    path, seg, table, swd = captured('wiring', CMD_PULSES, wiring_p, 1.0, poll_pin=True)
    wiring = az.analyze_pulses(az.load_words(path), ua, 5, 0.1)
    wiring.update(swd=swd, table=table)
    sink.json('WIRING.json', wiring)
    if not wiring['passed']:
        cause = ('PH8 toggled (%d edges seen over SWD) but PPK2 D0 did not follow: loose or wrong D0 wire '
                 '(Arduino D12 = CN12-5)' % swd['pin_transitions']) if swd['pin_transitions'] >= 9 else \
                ('PH8 itself did not toggle (%d edges over SWD): firmware/pin fault' % swd['pin_transitions'])
        require(False, 'D0 did not record the marker pulses. ' + cause)

    # 3. SHAM null control (+ marker pin load check).
    sham_p = dict(empty, pulse_cycles=int(args.sham_s * f_nom), pulse_count=args.sham_pulses)
    path, seg, table, swd = captured('sham', CMD_PULSES, sham_p, 2 * args.sham_s * args.sham_pulses)
    sham = az.analyze_sham(az.load_words(path), ua, table, args.assumed_volts, per_code_mA=per_code,
                           reader_gaps=swd['reader_gaps'])
    sham.setdefault('null_dP_W', None); sham.setdefault('null_dI_mA', None)
    sham.setdefault('null_dI_codes', None); sham.setdefault('marker_load_check_passed', False)
    if not swd['first_poll_found_done']:
        sham['valid'] = False
        sham['problems'].append('SWD poll happened before the sham ended')
    # Amendment 3: frames-vs-host is descriptive (it measures consumer backlog at the
    # segment boundaries in the threaded recorder); loss detection = reader gaps + counters.
    sham.update(segment=str(path), segment_sha256=seg['sha256'], swd=swd, table=table)
    sink.json('SHAM.json', sham)
    require(sham['marker_load_check_passed'], 'Marker pin changes board current by >0.5 mA; no measurement')

    # 4. CALIBRATION (firmware timing only) to size the windows.
    cal = dict(n_rows=4, bench_reps=1, overhead_reps=200, cycles=1, idle_cycles=int(0.05 * f_nom),
               pulse_cycles=int(0.01 * f_nom), pulse_count=1)
    m.issue(CMD_SCHEDULE, cal)
    h, _ = m.wait(timeout_s=60, first_poll_s=1, poll_s=0.5)
    ctable = m.table(h['windows_used'])
    bench_c = next(w for w in ctable if w['kind'] == 2)
    over_c = next(w for w in ctable if w['kind'] == 3)
    cyc_bench = ((bench_c['end_cycle'] - bench_c['start_cycle']) & 0xFFFFFFFF) / 4
    cyc_over = ((over_c['end_cycle'] - over_c['start_cycle']) & 0xFFFFFFFF) / 800
    n = args.rows
    base = dict(n_rows=n, bench_reps=max(1, round(args.bench_s * f_nom / (n * cyc_bench))),
                overhead_reps=max(1, round(args.overhead_s * f_nom / (n * cyc_over))),
                cycles=args.cycles, idle_cycles=int(args.idle_s * f_nom),
                pulse_cycles=int(0.02 * f_nom), pulse_count=3)
    plan = [('repeat', 1)] * args.schedules + [('dose', k) for k in args.dose]
    for _, mult in plan:
        window_s = base['bench_reps'] * mult * n * cyc_bench / f_nom
        require(window_s < 60, f'BENCH window {window_s:.1f} s would wrap the DWT counter at {f_nom} Hz')
    sink.json('CALIBRATION.json', dict(table=ctable, cycles_per_bench=cyc_bench, cycles_per_overhead=cyc_over,
                                       base_params=base, plan=plan))

    # 5. SCHEDULES
    results = []
    for k, (kind, mult) in enumerate(plan):
        params = dict(base, bench_reps=base['bench_reps'] * mult)
        expected = dict(zip(('bench', 'overhead'), az.expected_checksums(
            out_words, in_words, n, params['bench_reps'], params['overhead_reps'])))
        label = f'schedule_{k:02d}_{kind}{mult}'
        est = schedule_seconds(params, f_nom, cyc_bench, cyc_over)
        before = ppk.status()
        path, seg, table, swd = captured(label, CMD_SCHEDULE, params, est)
        after = ppk.status()
        record = dict(label=label, kind=kind, multiplier=mult, params=params, windows=table,
                      expected=expected, estimated_s=est, ppk_status_before=before, ppk_status_after=after,
                      segment=str(path), segment_sha256=seg['sha256'], segment_frames=seg['frames'], swd=swd)
        sink.json(f'{label}_table.json', record)
        res = az.analyze_schedule(az.load_words(path), ua, table, params, args.assumed_volts,
                                  expected=expected, per_code_mA=per_code, reader_gaps=swd['reader_gaps'])
        if not swd['first_poll_found_done']:
            res['valid'] = False
            res['problems'].append('SWD poll happened while the schedule was still running')
        if not swd['frames_vs_host_ok']:
            res.setdefault('notes', []).append('frames vs host differ >= 0.05 s (descriptive: consumer backlog)')
        if not after['output_on'] or after['guard_tripped']:
            res['valid'] = False
            res['problems'].append('PPK2 output dropped or guard tripped during schedule')
        res.update(label=label, kind=kind, multiplier=mult)
        sink.json(f'{label}_analysis.json', res)
        results.append(res)
        print(json.dumps(dict(schedule=label, valid=res['valid'], problems=res['problems'][:5])), flush=True)

    # 6. SUMMARY. Headline = GROSS energy per inference (board-level). Pilot data
    # (2026-09-29 bring-up) showed inference and busy-wait draw the same board
    # current within ~0.3 mA, so incremental-over-spin is reported only as a bound.
    reps = [r for r in results if r['valid'] and r['kind'] == 'repeat']
    valid = [r for r in results if r['valid']]
    sched_gross = [r['summary']['bench_gross_J_per_inference']['mean'] for r in reps]
    sched_inc = [r['summary']['bench_incremental_J_per_inference']['mean'] for r in reps]
    windows = [row for r in reps for row in r['bench']]
    dose_pts = [(row['iterations'], row['incremental_J_window']) for r in valid for row in r['bench']]
    gross_pts = [(row['iterations'], row['gross_J_per_iter'] * row['iterations']) for r in valid for row in r['bench']]
    mean_mA = (sum(row['p_window_W'] for row in windows) / len(windows) / args.assumed_volts * 1000) if windows else None
    sham_dP = (sham.get('null_dP_W') or {}).get('mean')
    t_inf = az.ci95([x['time_s_per_iter_ppk2'] for x in windows])['mean'] if windows else None
    summary = dict(
        schedules=len(results), valid_schedules=len(valid), valid_repeat_schedules=len(reps),
        assumed_volts=args.assumed_volts, per_code_mA=per_code,
        scope='whole-board 5 V input downstream of JP2 (minus ST-LINK); not SoC core/NPU',
        configuration=f'bit-exact SM06 validation build, nominal {f_nom} Hz HSI, I/D caches off, NPU polling',
        headline_gross_J_per_inference_between_schedules=az.ci95(sched_gross),
        gross_J_per_inference_windows=az.ci95([x['gross_J_per_iter'] for x in windows]),
        charge_C_per_inference_windows=az.ci95([x['charge_C_per_iter'] for x in windows]),
        time_s_per_inference_windows=az.ci95([x['time_s_per_iter_ppk2'] for x in windows]),
        board_power_W_bench=az.ci95([x['p_window_W'] for x in windows]),
        board_power_W_idle_spin=az.ci95([x['p_idle_W'] for x in windows]),
        incremental_over_spin_J_per_inference_between_schedules=az.ci95(sched_inc),
        incremental_over_spin_J_per_inference_windows=az.ci95([x['incremental_J_per_iter'] for x in windows]),
        incremental_sham_corrected_J_per_inference_windows=az.ci95(
            [x['incremental_J_per_iter'] - (sham_dP or 0) * x['time_s_per_iter_ppk2'] for x in windows]) if sham_dP is not None else None,
        vs_overhead_J_per_inference_windows=az.ci95([x.get('vs_overhead_J_per_iter') for x in windows]),
        bench_dI_mA=az.ci95([x['dI_mA'] for x in windows]),
        bench_dI_codes=az.ci95([x.get('dI_codes') for x in windows]),
        dose_response_incremental_J_vs_N=az.ols([p[0] for p in dose_pts], [p[1] for p in dose_pts]),
        dose_response_gross_J_vs_N=az.ols([p[0] for p in gross_pts], [p[1] for p in gross_pts]),
        sham_null=dict(dP_W=sham.get('null_dP_W'), dI_mA=sham.get('null_dI_mA'),
                       dI_codes=sham.get('null_dI_codes'), valid=sham.get('valid')),
        cpu_hz_estimate=[r['summary']['cpu_hz_estimate'] for r in valid],
        systematic=az.systematic_budget(mean_mA, volts_assumed=args.assumed_volts,
                                        s4_A_per_V=float(conv.c['S'][az.R5])) if mean_mA else None,
        not_claimable=['SoC/NPU energy', 'deployment-point energy (64 MHz, caches off)',
                       'CPU-vs-NPU attribution (no CPU-only variant)', 'cross-board ranking'],
        between_session_note='One power-on only; repeat on >= 3 power cycles for between-session CI.',
        recorder_source_sha256=session.get('source_sha256'))
    for key, pts in (('dose_response_incremental_J_vs_N', dose_pts), ('dose_response_gross_J_vs_N', gross_pts)):
        fit = summary[key]
        if not fit:
            continue
        n_min = min(pt[0] for pt in pts)
        rel = fit['intercept'] / (fit['slope'] * n_min) if fit['slope'] else None
        fit.update(intercept_rel_to_smallest_window=rel,
                   linear=bool(fit['intercept_ci_contains_zero'] or (rel is not None and abs(rel) < 0.02)))
    sink.json('MEASUREMENT_SUMMARY.json', summary)
    parity['measurement_summary'] = summary
    doses = [r for r in results if r['kind'] == 'dose']
    parity['all_schedules_valid'] = bool(len(valid) == len(results) and sham.get('valid')
                                         and len(reps) >= 2 and wiring['passed'])
    # Amendment 3: pooling eligibility = headline-relevant captures (wiring, sham, >= 2 valid
    # repeat schedules); dose schedules are auxiliary linearity checks, reported separately.
    parity['session_eligible'] = bool(sham.get('valid') and wiring['passed'] and len(reps) >= 2)
    parity['dose_checks'] = dict(schedules=len(doses), valid=sum(r['valid'] for r in doses),
                                 gross_linear=(summary['dose_response_gross_J_vs_N'] or {}).get('linear'))
    return parity


def offline_checks(args):
    r = subprocess.run([sys.executable, str(SELECTION_GATE)], capture_output=True, text=True, timeout=300)
    require(r.returncode == 0, 'SM06 selection gate failed: ' + r.stderr[-400:])
    fullrun, old, modules, pins, controller, rp = bindings()
    gate = fullrun.verify_raw_gate()
    firmware = old.load_variant(modules)
    platform = modules['stage_bundle'].load_stage()
    sym = symbols()
    accepted_outputs(firmware['rows'])
    return dict(fullrun=fullrun, old=old, modules=modules, pins=pins, controller=controller, rp=rp,
                gate=gate, firmware=firmware, platform=platform, symbols=sym)


def validate_args(p, args):
    checks = [(1 <= args.cycles <= 30, '--cycles 1..30'), (1 <= args.rows <= 1024, '--rows 1..1024'),
              (1 <= args.schedules <= 10, '--schedules 1..10'),
              (all(k in (2, 4, 8) for k in args.dose), '--dose values from {2,4,8}'),
              (0.3 <= args.bench_s <= 15, '--bench-s 0.3..15'), (0.3 <= args.overhead_s <= 15, '--overhead-s 0.3..15'),
              (0.6 <= args.idle_s <= 15, '--idle-s 0.6..15 (guards + 0.2 s minimum)'),
              (0.3 <= args.sham_s <= 5 and 3 <= args.sham_pulses <= 64, '--sham-s 0.3..5, --sham-pulses 3..64'),
              (4.4 <= args.assumed_volts <= 5.0, '--assumed-volts 4.4..5.0 (PPK2 AM VIN limit)')]
    for ok, msg in checks:
        if not ok:
            p.error(msg)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--execute', action='store_true', help='connect and measure (board must be powered)')
    p.add_argument('--output', type=Path, help='fresh absolute directory under results/')
    p.add_argument('--ppk-session', type=Path, default=REPO / 'results/power_n6_20260929/session_02')
    p.add_argument('--schedules', type=int, default=3)
    p.add_argument('--dose', type=int, nargs='*', default=[2, 4])
    p.add_argument('--cycles', type=int, default=10)
    p.add_argument('--rows', type=int, default=16)
    p.add_argument('--bench-s', type=float, default=1.5)
    p.add_argument('--overhead-s', type=float, default=1.0)
    p.add_argument('--idle-s', type=float, default=1.0)
    p.add_argument('--sham-s', type=float, default=1.0)
    p.add_argument('--sham-pulses', type=int, default=20)
    p.add_argument('--assumed-volts', type=float, default=5.0)
    args = p.parse_args(argv)
    validate_args(p, args)
    ctx = offline_checks(args)
    ppk = Ppk(args.ppk_session) if (args.ppk_session / 'control').exists() else None
    info = dict(offline_checks_passed=True, build=str(BUILD), symbols={k: hex(v) for k, v in ctx['symbols'].items()},
                validation_rows=len(ctx['firmware']['rows']), ppk_session=str(args.ppk_session),
                ppk_status=ppk.status() if ppk and (ppk.dir / 'status.json').exists() else None)
    if not args.execute:
        print(json.dumps(info, indent=1, default=str))
        return 0
    require(args.output is not None, '--output required with --execute')
    require(ppk is not None, 'PPK2 session directory missing')
    ppk.require_powered()
    modules, sink = ctx['modules'], ctx['modules']['orchestrate'].Store(args.output)
    sink.json('INTENT.json', dict(kind='SM07M_power_measurement', sources=ctx['pins'], args=vars(args) | dict(
        output=str(args.output), ppk_session=str(args.ppk_session)), tag=hex(TAG), marker=hex(MARKER),
        model_inputs=ctx['firmware']['input_sha256'], stage_inputs=ctx['platform']['input_sha256'],
        ppk_status=ppk.status(), power_control=False, flash_write=False))
    local = dict(modules)
    local['validation'] = SimpleNamespace(**vars(modules['validation']))
    outcome = {}
    try:
        with modules['pyocd_backend'].attach_exact_probe() as core:
            wrapped = modules['fp_entry'].EntryCore(core, sink, lambda b: ctx['rp'].decode(b, modules['protocol'].decode))
            def collect(mailbox, rows, retain):
                outcome['parity'] = procedure(wrapped, rows, modules, sink, ppk, args)
                return outcome['parity']
            local['validation'].collect = collect
            result = ctx['controller'].run_connected(wrapped, ctx['firmware'], ctx['platform'], sink,
                                                     nonce=secrets.randbelow(0xfffffffe) + 1, modules=local)
        require(all(sha(n) == d for n, d in ctx['pins'].items()), 'Sources changed during run')
        sink.json('RESULT.json', result)
        par = outcome['parity']
        final = dict(controller_result_is_numerical_phase_only=True, energy_measured=True,
                     all_captures_valid=par['all_schedules_valid'], session_eligible=par['session_eligible'],
                     dose_checks=par['dose_checks'], summary=par['measurement_summary'])
        sink.json('MEASURE_RESULT.json', final)
        print(json.dumps(final['summary']['headline_gross_J_per_inference_between_schedules'], indent=1))
        return 0 if final['all_captures_valid'] else (3 if final['session_eligible'] else 2)
    except BaseException as exc:
        ppk.abandon()
        sink.json('FAILED.json', dict(error=f'{type(exc).__name__}: {exc}', energy_measured=False))
        raise


if __name__ == '__main__':
    raise SystemExit(main())
