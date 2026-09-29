"""Offline decoding and phase analysis of one RM01 power-on capture.

A capture is one PPK2 raw segment spanning a whole autonomous RM01 boot. D0
(P107) carries, in order: 5 wiring pulses, 20 sham pulses, 5 schedules
(3-pulse preamble + BENCH/OVERHEAD windows), then the telemetry frame (300 ms
sync, pulse-width bits) and finally DONE (HIGH until power-off). Telemetry
gives the firmware's own window table and header; the D0 HIGH runs before the
sync are matched one-to-one with the table's marker-HIGH windows, and each
phase is sliced out and passed to the SM07M analysis (analyze_schedule.py)
unchanged, so the N6 and RA4E1 numbers come from the same code.
Never opens hardware.
"""
import struct
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'tools/ppk2_energy'))
import analyze_schedule as az  # noqa: E402

FS = az.FS
RM_MAGIC, RM_VERSION, TEL_MAGIC = 0x31304D52, 1, 0x54314D52
HEADER_WORDS, WINDOW_WORDS = 64, 5
SYNC_S, SYNC_TOL = 0.300, 0.15
BIT0, BIT1, BIT_TOL = 25, 75, 12              # samples at 100 kS/s (0.25 / 0.75 ms)
STAGES = {1: 'BOOT', 2: 'PARITY', 3: 'WIRING', 4: 'SHAM', 5: 'CALIB', 6: 'SCHEDULE',
          7: 'TELEMETRY', 8: 'DONE', 9: 'ERROR'}
# rm01.h header layout, word index -> name (multiplier/sha prefixes are arrays).
FIELDS = ['magic', 'version', 'struct_bytes', 'stage', 'error', 'error_detail', 'system_core_clock',
          'fcachee', 'pq_env', 'cpuid', 'timer_ctrl', 'schedules_done', 'parity_mismatched_words',
          'parity_first_bad_row', 'parity_outputs_fnv', 'parity_rows', 'parity_cycles_total_lo',
          'parity_cycles_total_hi', 'parity_cycles_min', 'parity_cycles_max', 'cal_bench_cycles',
          'cal_overhead_cycles', 'n_rows', 'bench_reps', 'overhead_reps', 'cycles', 'idle_cycles',
          'pulse_cycles', 'pulse_count', 'wiring_cycles', 'wiring_pulses', 'sham_cycles', 'sham_pulses',
          'gap_cycles', 'n_schedules', 'windows_used']
MULT_AT, TEL_WORDS_AT, SETTLE_AT, TIMER_ID_AT, CAL_CK_AT, SHA_AT = 36, 44, 45, 46, 47, 48
CLOCK_FIELDS = ['sckdivcr', 'sckscr', 'pllccr', 'pllcr', 'hococr', 'mococr', 'opccr', 'flwt', 'ofs1_sec']
CLOCK_AT = 52                                    # rm01.h 0xD0
TIMER_ID = 0x31545047                          # 'GPT1': GPT321 at PCLKD/1 (= ICLK)
MODEL_SHA = '22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d'
VECTORS_SHA = 'cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb'


class DecodeError(ValueError):
    pass


def crc32_words(words):
    import zlib
    return zlib.crc32(b''.join(struct.pack('<I', w) for w in words)) & 0xFFFFFFFF


def parse_header(words):
    h = {name: words[i] for i, name in enumerate(FIELDS)}
    h['error'] = struct.unpack('<i', struct.pack('<I', h['error']))[0]
    h['multiplier'] = list(words[MULT_AT:MULT_AT + 8])
    h['telemetry_words'] = words[TEL_WORDS_AT]
    h['settle_cycles'] = words[SETTLE_AT]
    h['timer_id'] = words[TIMER_ID_AT]
    h['cal_checksum'] = words[CAL_CK_AT]
    h['clock_snapshot'] = {k: words[CLOCK_AT + i] for i, k in enumerate(CLOCK_FIELDS)}
    h['model_sha_prefix'] = '%08x%08x' % tuple(words[SHA_AT:SHA_AT + 2])
    h['vectors_sha_prefix'] = '%08x%08x' % tuple(words[SHA_AT + 2:SHA_AT + 4])
    h['stage_name'] = STAGES.get(h['stage'], '?')
    h['parity_cycles_total'] = h['parity_cycles_total_lo'] | (h['parity_cycles_total_hi'] << 32)
    return h


def parse_windows(words, n):
    out = []
    for i in range(n):
        k, s, e, it, ck = words[WINDOW_WORDS * i:WINDOW_WORDS * i + WINDOW_WORDS]
        out.append(dict(index=i, kind=k & 0xFF, marker_high=(k >> 8) & 0xFF, phase=k >> 16,
                        start_cycle=s, end_cycle=e, iterations=it, checksum=ck))
    return out


def logic_d0(words):
    """D0 only where the PPK2 logic port is powered. With its VCC (board 3.3 V)
    absent this PPK2 reads all eight bits as 1 (N6 sessions 02/03 and RA
    bring-up 03-05: 255 whenever the board was off); powered, the unconnected
    D1..D7 read 0. So D0 counts as HIGH only when D1..D7 are 0."""
    bits = (words >> 24) & 0xFF
    powered = (bits & 0xFE) == 0
    return ((bits & 1) == 1) & powered, powered


def _bit_class(w):
    if abs(w - BIT0) <= BIT_TOL:
        return 0
    if abs(w - BIT1) <= BIT_TOL:
        return 1
    return None


def decode_telemetry(d0):
    """Returns (header, windows, info, measurement_runs). Raises DecodeError on
    any framing/CRC fault. The sync is the last ~300 ms HIGH run that is followed
    by at least 64 valid bit pulses (a truncated window of similar width cannot
    be mistaken for it)."""
    runs = az.high_runs(d0)
    sync = [k for k, (a, b) in enumerate(runs)
            if abs((b - a) / FS - SYNC_S) <= SYNC_TOL * SYNC_S
            and len(runs) > k + 64
            and all(_bit_class(b2 - a2) is not None for a2, b2 in runs[k + 1:k + 65])]
    if not sync:
        raise DecodeError('no 300 ms telemetry sync followed by >= 64 valid bits')
    k0 = sync[-1]
    bits = []
    for a, b in runs[k0 + 1:]:
        c = _bit_class(b - a)
        if c is None:
            break                            # DONE (long HIGH) or end of capture
        bits.append(c)
    nwords = len(bits) // 32
    words = [sum(bits[32 * i + j] << j for j in range(32)) for i in range(nwords)]
    if nwords < 2 or words[0] != TEL_MAGIC:
        raise DecodeError(f'telemetry magic missing ({nwords} words decoded)')
    count = words[1]
    if nwords < count + 3:
        raise DecodeError(f'telemetry truncated: {nwords} words, need {count + 3}')
    frame = words[:count + 2]
    if crc32_words(frame) != words[count + 2]:
        raise DecodeError('telemetry CRC mismatch')
    payload = frame[2:]
    header = parse_header(payload[:HEADER_WORDS])
    n = header['windows_used']
    if count != HEADER_WORDS + WINDOW_WORDS * n or header['telemetry_words'] != count:
        raise DecodeError('telemetry word count inconsistent with windows_used')
    windows = parse_windows(payload[HEADER_WORDS:], n)
    last_bit_end = runs[k0 + (count + 3) * 32][1]
    done = [(a, b) for a, b in runs[k0 + 1 + (count + 3) * 32:]]
    info = dict(sync_run_index=k0, sync_start_sample=runs[k0][0], bits=len(bits),
                frame_words=count + 3, last_bit_end_sample=int(last_bit_end),
                done_run=[int(done[0][0]), int(done[0][1])] if done else None,
                done_high_s=(done[0][1] - done[0][0]) / FS if done else None,
                extra_bits_after_frame=len(bits) - (count + 3) * 32)
    return header, windows, info, runs[:k0]


def header_problems(h, pins=True):
    p = []
    if h['magic'] != RM_MAGIC or h['version'] != RM_VERSION:
        p.append('bad RM01 magic/version')
    if h['stage_name'] != 'TELEMETRY' or h['error'] != 0:
        p.append(f"firmware stage {h['stage_name']} error {h['error']} detail {h['error_detail']:#x}")
    if h['timer_id'] != TIMER_ID:
        p.append(f"time base is not GPT321 (timer_id {h['timer_id']:#x})")
    if h['pq_env'] != 1:
        p.append('FP environment check failed')
    if h['parity_rows'] != 1024 or h['parity_mismatched_words'] != 0:
        p.append(f"self-parity: {h['parity_mismatched_words']} mismatched words of {h['parity_rows']} rows")
    if h['schedules_done'] != h['n_schedules'] or h['n_schedules'] != 5:
        p.append(f"schedules done {h['schedules_done']}/{h['n_schedules']}")
    if pins and (h['model_sha_prefix'] != MODEL_SHA[:16] or h['vectors_sha_prefix'] != VECTORS_SHA[:16]):
        p.append('model/vectors identity prefix mismatch')
    c = h.get('clock_snapshot', {})
    if pins and c and not clock_ok(c):
        p.append(f'clock configuration differs from HOCO20 -> PLL200 -> ICLK=PCLKD=100 MHz: {c}')
    return p


def clock_ok(c):
    """R7FA4E10D.h field layouts: SCKSCR 5 = PLL; SCKDIVCR ICK[26:24] and
    PCKD[2:0] = 1 (/2), so the GPT321 count equals the CPU cycle; PLLCCR
    PLIDIV[1:0]=1 (/2), PLSRCSEL[4]=1 (HOCO), PLLMUL[13:8]=39 (x20 = (39+1)/2);
    OFS1_SEC HOCOFRQ[10:9]=2 (20 MHz; FSP bsp_feature.h RA4E1: OFFSET 9, inverted
    mask 0xFFFFF9FF; BSP_CFG_HOCO_FREQUENCY=2)."""
    d, pl = c['sckdivcr'], c['pllccr']
    return (c['sckscr'] == 5 and (d >> 24) & 7 == 1 and d & 7 == 1 and pl & 3 == 1
            and (pl >> 4) & 1 == 1 and (pl >> 8) & 0x3F == 39 and (c['ofs1_sec'] >> 9) & 3 == 2)


def phase_plan(h):
    """[(phase, label, kind, multiplier)] in execution order."""
    plan = [(0, 'wiring', 'wiring', None), (1, 'sham', 'sham', None)]
    for s in range(h['n_schedules']):
        m = h['multiplier'][s]
        kind = 'repeat' if s < 3 else 'dose'
        plan.append((2 + s, f'schedule_{s:02d}_{kind}{m}', kind, m))
    return plan


def slices(runs, windows, n_samples):
    """Map each phase to a [start, stop) sample slice around its D0 HIGH runs.
    Boundaries are midpoints of the LOW gaps between phases."""
    high = [w for w in windows if w['marker_high']]
    if len(runs) != len(high):
        raise DecodeError(f'D0 HIGH runs before telemetry {len(runs)} != firmware HIGH windows {len(high)}')
    idx = {}
    for k, w in enumerate(high):
        idx.setdefault(w['phase'], []).append(k)
    phases = sorted(idx)
    bounds = {}
    for j, ph in enumerate(phases):
        k0, k1 = idx[ph][0], idx[ph][-1]
        prev_end = runs[idx[phases[j - 1]][-1]][1] if j else None
        next_start = runs[idx[phases[j + 1]][0]][0] if j + 1 < len(phases) else None
        a = (prev_end + runs[k0][0]) // 2 if prev_end is not None else max(0, runs[k0][0] - int(1.0 * FS))
        b = (runs[k1][1] + next_start) // 2 if next_start is not None else min(n_samples, runs[k1][1] + int(1.5 * FS))
        bounds[ph] = (int(a), int(b), k0, k1)
    return bounds


def gaps_in(reader_gaps, a, b):
    return [(i - a, g) for i, g in reader_gaps if a <= i < b]


def _dominant(r):
    return int(np.bincount(r, minlength=8).argmax()) if len(r) else None


def range_consistency(seg, res, guard_s=0.05):
    """Per BENCH window: dominant PPK2 range of the window and of the trimmed
    LOW spans before/after it, and range switches inside each. Incremental
    energy compares two spans, so it is only estimable when all three share one
    range with no switch (pre-registered, RA protocol)."""
    r = (seg >> 14) & 7
    g = int(round(guard_s * FS))
    wins = res.get('windows', [])
    out = []
    for row in res.get('bench', []):
        k = row['window']
        a, b = wins[k]['start_sample'], wins[k]['stop_sample']
        pa = wins[k - 1]['stop_sample'] + g if k > 0 else max(0, a - int(FS))
        nb = wins[k + 1]['start_sample'] - g if k + 1 < len(wins) else b + int(FS)
        spans = dict(before=r[pa:a - g], window=r[a:b], after=r[b + g:nb])
        dom = {n: _dominant(v) for n, v in spans.items()}
        sw = {n: int((np.diff(v) != 0).sum()) if len(v) > 1 else 0 for n, v in spans.items()}
        ok = len(set(dom.values())) == 1 and not any(sw.values())
        row['range_dominant'] = dom
        row['range_switches'] = sw
        row['range_consistent'] = bool(ok)
        out.append(ok)
    return out


def analyze_capture(words, ua_fn, volts, inputs_words, outputs_words, reader_gaps=(),
                    per_code_mA=None, top_range_only=False, pins=True, unpowered_before=0):
    """`problems` = boot-level faults (telemetry, firmware header, slicing): any of
    them makes the whole capture unusable. Per-phase validity stays in phases[*]
    (RA protocol Amendment 3: eligibility is decided from wiring, sham and the
    repeat schedules; dose schedules are reported only). `unpowered_before`:
    frames before this index are treated as logic-unpowered, because the PPK2
    latches its last logic byte while the board is off (review 2026-09-30 B1)."""
    d0, powered = logic_d0(words)
    if unpowered_before:
        d0[:unpowered_before] = False
        powered[:unpowered_before] = False
    try:
        header, windows, tel, runs = decode_telemetry(d0)
    except DecodeError as exc:
        return dict(header=None, telemetry=None, phases={}, windows=[],
                    problems=[f'telemetry decode failed: {exc}'],
                    logic_powered_fraction=float(powered.mean()) if len(powered) else None)
    problems = header_problems(header, pins)
    out = dict(header=header, telemetry=tel, phases={}, problems=problems, windows=windows,
               logic_powered_fraction=float(powered.mean()) if len(powered) else None,
               unpowered_before=int(unpowered_before), phase_problems=[])
    if problems:                      # fail closed: no energy from a non-conforming boot
        return out
    try:
        bounds = slices(runs, windows, len(words))
    except DecodeError as exc:
        problems.append(str(exc))
        return out
    f_nom = header['system_core_clock']
    for ph, label, kind, mult in phase_plan(header):
        a, b, _, _ = bounds[ph]
        seg = words[a:b]
        unpowered = not powered[a:b].all()
        table = [w for w in windows if w['phase'] == ph]
        g = gaps_in(reader_gaps, a, b)
        if kind == 'wiring':
            res = az.analyze_pulses(seg, ua_fn, header['wiring_pulses'], header['wiring_cycles'] / f_nom)
            res['valid'] = res['passed'] and not g
        elif kind == 'sham':
            res = az.analyze_sham(seg, ua_fn, table, volts, per_code_mA=per_code_mA, reader_gaps=g,
                                  top_range_only=top_range_only)
        else:
            params = dict(n_rows=header['n_rows'], bench_reps=header['bench_reps'] * mult,
                          overhead_reps=header['overhead_reps'], cycles=header['cycles'],
                          idle_cycles=header['idle_cycles'], pulse_cycles=header['pulse_cycles'],
                          pulse_count=header['pulse_count'])
            expected = dict(zip(('bench', 'overhead'), az.expected_checksums(
                outputs_words, inputs_words, params['n_rows'], params['bench_reps'], params['overhead_reps'])))
            res = az.analyze_schedule(seg, ua_fn, table, params, volts, expected=expected,
                                      per_code_mA=per_code_mA, reader_gaps=g, top_range_only=top_range_only)
            cons = range_consistency(seg, res)
            inc_ok = [x['incremental_J_per_iter'] for x in res.get('bench', []) if x.get('range_consistent')]
            res.update(params=params, expected=expected, multiplier=mult,
                       range_consistent_windows=int(sum(cons)), bench_windows=len(cons),
                       incremental_J_per_inference_range_consistent=az.ci95(inc_ok))
        if unpowered:
            res['valid'] = False
            res.setdefault('problems', []).append('logic port unpowered or D1-D7 not LOW inside the slice')
        res.update(label=label, kind=kind, slice=[a, b], reader_gaps=g,
                   scope='FPB-RA4E1 whole board at its main 5 V net (J2-5, PPK2 source 5.0 V setpoint), J9 unplugged; not MCU core')
        out['phases'][label] = res
        if not res.get('valid'):
            out['phase_problems'].append(f"{label}: " + '; '.join(res.get('problems', ['failed'])[:3]))
    return out


def eligible(res):
    """RA protocol Amendment 3 (same rule as the N6 Amendment 3): a session is
    eligible iff there is no boot-level problem, the wiring gate and the sham
    control are valid, and >= 2 repeat schedules are valid. Dose schedules are
    auxiliary linearity checks and do not affect eligibility."""
    ph = res.get('phases', {})
    reps = [v for k, v in ph.items() if k.startswith('schedule') and v.get('kind') == 'repeat' and v.get('valid')]
    return bool(res.get('header') and not res.get('problems') and ph.get('wiring', {}).get('valid')
                and ph.get('sham', {}).get('valid') and len(reps) >= 2)
