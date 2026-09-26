"""Offline literal-register/mailbox controls, plus frozen-engine fake integration."""
import copy
import importlib.util
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'host_sram'))
import fp_entry as f
from protocol import decode
from orchestrate import run_connected
from test_orchestrate import Core as OldFake, Sink as OldSink, payloads


def fresh_mailbox():
    w = [0] * 128
    w[:4] = [0x53364E36, 1, 512, 1]
    w[12:18] = [0x80000000] * 6
    w[23] = 0x411FD221
    w[26:32] = [0x34200000, 0x40000, 0x34240000, 0x4000, 145457, 0x534D3031]
    raw = bytearray(struct.pack('<128I', *w))
    raw[352:417] = b'22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d\0'
    raw[417:482] = b'cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec\0'
    return raw


class Sink(OldSink):
    def json(self, name, value):
        super().json(name, copy.deepcopy(value))


class Fake:
    def __init__(self):
        self.context = dict(primask=1, pc=0x34064224, msp=0x340F7D70)
        self.halted = True
        self.fpscr = 0x00C40000
        self.ppb = {f.CPACR: 0xF00000, f.FPCCR: 0xC0000004, f.FPDSCR: 0x40000}
        self.raw = fresh_mailbox()
        self.writes = []
        self.corrupt = 0
        self.flush_error = False
        self.core = self

    def entry_snapshot(self):
        if not self.halted:
            raise RuntimeError('not halted')
        return self.context.copy()

    def read(self, address, size):
        assert (address, size) == (f.ADDRESS, 512)
        return bytes(self.raw)

    def read32(self, address):
        return self.ppb[address]

    def read_core_register_raw(self, name):
        assert name == 'fpscr'
        return self.fpscr

    def write_core_register_raw(self, name, value):
        assert name == 'fpscr'
        self.writes.append((name, value))
        self.fpscr = value ^ self.corrupt

    def flush(self):
        if self.flush_error:
            raise OSError('ambiguous write/flush')

    def floating_environment(self):
        if self.fpscr & f.MODES or self.ppb[f.FPDSCR] & f.MODES:
            raise RuntimeError('strict mode rejection')
        return dict(fpscr=self.fpscr, fpdscr=self.ppb[f.FPDSCR])


@pytest.mark.parametrize('rounding', range(4))
@pytest.mark.parametrize('preserved', [0x40000, 0xF804009F])
def test_only_two_rounding_bits_change(rounding, preserved):
    core, sink = Fake(), Sink()
    core.fpscr = preserved | (rounding << 22)
    result = f.establish_rne(core, sink, decode)
    assert result['fpscr'] == preserved
    assert core.writes == ([] if rounding == 0 else [('fpscr', preserved)])
    assert sink.files['fp_entry_before.json']['registers']['fpscr'] == preserved | (rounding << 22)
    assert sink.files['fp_entry_after.json']['registers']['fpdscr'] == 0x40000
    assert sink.files['fp_entry_verified.json']['already_rne'] == (rounding == 0)


@pytest.mark.parametrize('name', ['fpscr', 'fpdscr'])
@pytest.mark.parametrize('bit', [19, 24, 25, 26])
def test_other_modes_are_not_repaired(name, bit):
    c = Fake()
    if name == 'fpscr': c.fpscr |= 1 << bit
    else: c.ppb[f.FPDSCR] |= 1 << bit
    with pytest.raises(RuntimeError): f.establish_rne(c, Sink(), decode)
    assert not c.writes


@pytest.mark.parametrize('mutation', [
    lambda c: setattr(c, 'halted', False),
    lambda c: c.context.update(primask=0),
    lambda c: c.context.update(pc=0x34180539),
    lambda c: c.context.update(msp=0x3418B000),
    lambda c: c.ppb.update({f.CPACR: 0}),
    lambda c: c.ppb.update({f.FPCCR: 1}),
    lambda c: c.ppb.update({f.FPDSCR: 0x400000}),
    lambda c: setattr(c, 'fpscr', True),
    lambda c: setattr(c, 'fpscr', -1),
    lambda c: struct.pack_into('<I', c.raw, 12, 3),
    lambda c: struct.pack_into('<I', c.raw, 16, 0x504C4154),
    lambda c: struct.pack_into('<I', c.raw, 20, 1),
    lambda c: struct.pack_into('<I', c.raw, 48, 0),
    lambda c: struct.pack_into('<I', c.raw, 96, 0x34240000),
    lambda c: c.raw.__setitem__(352, ord('x')),
])
def test_bad_entry_or_identity_never_writes(mutation):
    c = Fake(); mutation(c)
    with pytest.raises((RuntimeError, ValueError)): f.establish_rne(c, Sink(), decode)
    assert not c.writes


@pytest.mark.parametrize('fail_name', ['fp_entry_before.json', 'fp_entry_intent.json'])
def test_retention_failure_before_write(fail_name):
    class BrokenSink(Sink):
        def json(self, name, value):
            if name == fail_name: raise OSError('disk error')
            super().json(name, value)
    c = Fake()
    with pytest.raises(OSError): f.establish_rne(c, BrokenSink(), decode)
    assert not c.writes


def test_changed_snapshot_before_write():
    c = Fake()
    class MutatingSink(Sink):
        def json(self, name, value):
            super().json(name, value)
            if name == 'fp_entry_before.json': c.context['pc'] += 2
    with pytest.raises(RuntimeError, match='Entry changed'):
        f.establish_rne(c, MutatingSink(), decode)
    assert not c.writes


@pytest.mark.parametrize('corrupt', [1, 0x400000, 0x40000, 1 << 19, 1 << 24, 1 << 25, 1 << 26])
def test_every_other_bit_preserved_or_fail_with_after_evidence(corrupt):
    c, s = Fake(), Sink(); c.corrupt = corrupt
    with pytest.raises(RuntimeError, match='readback mismatch'):
        f.establish_rne(c, s, decode)
    assert len(c.writes) == 1 and 'fp_entry_after.json' in s.files
    assert 'fp_entry_verified.json' not in s.files


def test_change_during_intent_retention_refuses_register_write():
    c = Fake()
    class MutatingSink(Sink):
        def json(self, name, value):
            super().json(name, value)
            if name == 'fp_entry_intent.json': c.ppb[f.FPDSCR] ^= 1 << 22
    with pytest.raises(RuntimeError, match='Entry changed'):
        f.establish_rne(c, MutatingSink(), decode)
    assert not c.writes


def test_after_retention_failure_poison_no_second_write():
    c = Fake()
    class BrokenSink(Sink):
        def json(self, name, value):
            if name == 'fp_entry_after.json': raise OSError('disk full after write')
            super().json(name, value)
    wrapped = f.EntryCore(c, BrokenSink(), decode)
    with pytest.raises(OSError): wrapped.floating_environment()
    with pytest.raises(RuntimeError, match='poisoned'): wrapped.floating_environment()
    assert len(c.writes) == 1


def test_ambiguous_write_never_retried():
    c, s = Fake(), Sink(); c.flush_error = True
    wrapped = f.EntryCore(c, s, decode)
    with pytest.raises(OSError): wrapped.floating_environment()
    with pytest.raises(RuntimeError, match='poisoned'): wrapped.floating_environment()
    assert len(c.writes) == 1 and 'fp_entry_intent.json' in s.files


def test_post_validation_mismatch_is_not_healed():
    c, s = Fake(), Sink(); wrapped = f.EntryCore(c, s, decode)
    wrapped.floating_environment()
    c.fpscr |= 0x400000
    with pytest.raises(RuntimeError, match='strict'): wrapped.floating_environment()
    assert len(c.writes) == 1


class Integrated(OldFake, Fake):
    def __init__(self):
        OldFake.__init__(self); Fake.__init__(self)
        self.fp_writes = []

    def read(self, address, count): return OldFake.read(self, address, count)
    def entry_snapshot(self):
        if self.running: raise RuntimeError('not halted')
        return self.context.copy()
    def start_loaded_image(self, entry, msp):
        OldFake.start_loaded_image(self, entry, msp)
        if entry < 0x34100000: self.put(f.ADDRESS, fresh_mailbox())
    def write_core_register_raw(self, name, value):
        assert name == 'fpscr' and self.read(f.ADDRESS + 16, 12) == bytes(12)
        self.fp_writes.append((name, value)); self.fpscr = value
    def floating_environment(self): return Fake.floating_environment(self)
    def resume_from_halt(self):
        for offset, payload in ((48, bytes(16)), (96, struct.pack('<2I', 0x34240000, 0x34240000))):
            self.put(f.ADDRESS + offset, payload)
        OldFake.resume_from_halt(self)


def test_frozen_full_engine_1024_rows_and_post_check():
    core, sink = Integrated(), Sink()
    result = run_connected(f.EntryCore(core, sink, decode), *payloads(), sink, nonce=66)
    assert result['completed_rows'] == 1024
    assert core.fp_writes == [('fpscr', 0x40000)]
    assert len([n for n in sink.files if n.startswith('row_')]) == 1024
    assert not core.running and not result['energy_measured']
    assert 'floating_environment_after_validation.json' in sink.files


def test_bad_initialization_no_ack_no_inference_in_engine():
    core, sink = Integrated(), Sink(); core.ppb[f.FPDSCR] |= 1 << 22
    with pytest.raises(RuntimeError):
        run_connected(f.EntryCore(core, sink, decode), *payloads(), sink, nonce=66)
    assert not core.fp_writes and not core.running
    assert not any(a in (f.ADDRESS + 16, f.ADDRESS + 20) for a, _ in core.writes)


def test_end_of_validation_mode_corruption_is_never_repaired():
    class CorruptLate(Integrated):
        def write(self, address, raw):
            result = super().write(address, raw)
            if address == f.ADDRESS + 20 and struct.unpack('<I', raw)[0] == 1024:
                self.fpscr |= 1 << 22
            return result
    c, s = CorruptLate(), Sink()
    with pytest.raises(RuntimeError, match='strict mode'):
        run_connected(f.EntryCore(c, s, decode), *payloads(), s, nonce=33)
    assert c.fp_writes == [('fpscr', 0x40000)]
    assert s.files['PARITY.json']['full_logit_parity_passed'] is True
    assert len(s.files['completion_state.json']['completed_row_ids']) == 1024
    assert not c.running
