"""Independent offline byte-level controls, not a hardware/transport oracle.

Uses a literal 256-byte ABI fixture, not the author's values/raw/FakeMemory.
No USB, serial, debugger, power, board runtime or artifact loading is performed.
"""
import ast
import json
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host_protocol as h

BASE = 0x34185000
FIELDS = ('magic version struct_bytes state sequence heartbeat host_nonce echo_nonce '
          'cpuid ccr control vtor entry_vtor entry_control entry_primask entry_msp '
          'primask ipsr msp msplim cfsr hfsr dfsr afsr mmfar bfar fault_ipsr '
          'fault_exc_return fault_msp fault_psp platform_initialized reserved0').split()
OFFSETS = {name: index * 4 for index, name in enumerate(FIELDS)}


def packet(**changes):
    data = bytearray(256)
    defaults = dict(magic=0x4E365052, version=1, struct_bytes=256, state=2,
                    sequence=12, heartbeat=41, host_nonce=5, echo_nonce=6,
                    cpuid=0x410FD220, vtor=0x34180400, primask=1,
                    msp=0x34184FE0, msplim=0x34184000)
    defaults.update(changes)
    for name, value in defaults.items(): struct.pack_into('<I', data, OFFSETS[name], value)
    return bytes(data)


class Memory:
    def __init__(self, after=None):
        self.data = packet()
        self.calls, self.writes = [], []
        self.after = after or {}
        self.write_fault = None

    def read(self, address, length):
        self.calls.append((address, length))
        offset = address - BASE
        return self.data[offset:offset + length]

    def write(self, address, data):
        self.writes.append((address, data))
        if self.write_fault: raise self.write_fault
        nonce = struct.unpack('<I', data)[0]
        following = dict(host_nonce=nonce, echo_nonce=nonce, sequence=14, heartbeat=42)
        following.update(self.after)
        self.data = packet(**following)
        return 4


class IndependentHostTests(unittest.TestCase):
    def test_complete_abi_mapping_including_reserved_and_owners(self):
        abi = json.loads(Path(__file__).with_name('ABI.json').read_bytes())
        expected = [dict(name=name, offset=index * 4, type='uint32',
                         owner='host' if name == 'host_nonce' else 'target')
                    for index, name in enumerate(FIELDS)]
        expected.append(dict(name='reserved', offset=128, type='uint32[32]', owner='target'))
        self.assertEqual(abi['fields'], expected)
        self.assertEqual(h.FIELDS, tuple(FIELDS))
        for key, value in dict(schema=1, byte_order='little', word_type='uint32', struct_bytes=256,
                magic=0x4E365052, version=1, mailbox_address=BASE, vector_address=0x34180400,
                code_start=0x34180400, code_end_exclusive=0x34184000,
                stack_start=0x34184000, stack_top=BASE, mailbox_end_exclusive=BASE + 256,
                cache_enable_mask=0x30000).items():
            self.assertEqual(abi[key], value)
        self.assertEqual(abi['states'], dict(initializing=1, running=2, cache_unsupported=3,
                                             fault=4, entry_rejected=5))
        self.assertIs(abi['platform_initialized'], False)
        self.assertIs(abi['hardware_executed'], False)

    def test_literal_unique_words_decode_to_exact_field_names(self):
        data = bytearray(packet(state=4))
        for name, offset in OFFSETS.items():
            if name not in ('magic', 'version', 'struct_bytes', 'state', 'sequence',
                            'platform_initialized', 'reserved0'):
                struct.pack_into('<I', data, offset, 0x10000000 + offset)
        result = h.decode(bytes(data), 12, 12)
        self.assertEqual(result, dict(zip(FIELDS, struct.unpack('<32I', data[:128]))))

    def test_last_reserved_word_cannot_hide_nonzero(self):
        data = bytearray(packet())
        struct.pack_into('<I', data, 252, 1)
        with self.assertRaises(h.ProtocolError): h.decode(bytes(data), 12, 12)

    def test_non_bytes_and_all_wrong_lengths_are_refused(self):
        for value in (bytearray(packet()), memoryview(packet()), packet().hex(), packet()[:-1], packet() + b'\0'):
            with self.subTest(type=type(value), size=len(value)), self.assertRaises(h.ProtocolError):
                h.decode(value, 12, 12)

    def test_exact_sequence_uint32_types_on_both_sides(self):
        for value in (True, False, 12.0, -1, 2**32, None):
            for sides in ((value, 12), (12, value)):
                with self.subTest(sides=sides), self.assertRaises(h.ProtocolError):
                    h.decode(packet(), *sides)

    def test_body_sequence_is_not_ignored_when_outer_reads_match(self):
        with self.assertRaises(h.SnapshotBusy): h.decode(packet(sequence=14), 12, 12)
        with self.assertRaises(h.SnapshotBusy): h.decode(packet(sequence=13), 13, 13)

    def test_busy_retry_reads_only_exact_abi_ranges(self):
        replies = [struct.pack('<I', 11), packet(sequence=11), struct.pack('<I', 11),
                   struct.pack('<I', 12), packet(), struct.pack('<I', 12)]
        calls = []
        def reader(address, length):
            calls.append((address, length))
            return replies.pop(0)
        result = h.snapshot(reader, max_attempts=2)
        self.assertEqual(result['heartbeat'], 41)
        self.assertEqual(calls, [(BASE + 16, 4), (BASE, 256), (BASE + 16, 4)] * 2)

    def test_torn_snapshot_budget_never_returns_last_body(self):
        calls = []
        replies = [struct.pack('<I', 12), packet(), struct.pack('<I', 14)] * 2
        def reader(address, length):
            calls.append((address, length))
            return replies.pop(0)
        with self.assertRaises(TimeoutError): h.snapshot(reader, max_attempts=2)
        self.assertEqual(len(calls), 6)

    def test_success_single_four_byte_little_endian_nonce_write(self):
        memory, events = Memory(), []
        result = h.challenge(memory.read, memory.write, 0x12345678, events=events)
        self.assertEqual(memory.writes, [(BASE + 24, b'\x78\x56\x34\x12')])
        self.assertEqual(memory.calls, [(BASE + 16, 4), (BASE, 256), (BASE + 16, 4)] * 2)
        self.assertEqual([event['operation'] for event in events], ['read'] * 3 + ['write'] + ['read'] * 3)
        self.assertIs(result['probe_activity_observed'], True)
        self.assertEqual({key: value for key, value in result.items()
                          if key not in ('probe_activity_observed', 'before', 'after', 'nonce')},
                         dict(platform_initialized=False, model_executed=False,
                              power_measured=False, research_measurement_accepted=False))

    def test_partial_progress_is_not_nonce_liveness(self):
        for after in (dict(echo_nonce=6), dict(heartbeat=41), dict(sequence=12),
                      dict(heartbeat=41, sequence=12)):
            memory = Memory(after)
            with self.subTest(after=after), self.assertRaises(TimeoutError):
                h.challenge(memory.read, memory.write, 123, max_polls=2)
            self.assertEqual(memory.writes, [(BASE + 24, struct.pack('<I', 123))])
            self.assertEqual(len(memory.calls), 9)

    def test_stale_before_host_or_echo_value_never_writes(self):
        for nonce in (5, 6):
            memory = Memory()
            with self.subTest(nonce=nonce), self.assertRaises(h.ProtocolError):
                h.challenge(memory.read, memory.write, nonce)
            self.assertEqual(memory.writes, [])

    def test_after_nonce_readback_or_cpu_identity_mismatch_is_rejected(self):
        for after in (dict(host_nonce=999), dict(cpuid=0x410FD210)):
            memory = Memory(after)
            with self.subTest(after=after), self.assertRaises(h.ProtocolError):
                h.challenge(memory.read, memory.write, 123)
            self.assertEqual(len(memory.writes), 1)

    def test_after_rejected_state_cache_or_scope_flag_never_activity(self):
        for after in (dict(state=1), dict(state=3), dict(state=4), dict(state=5),
                      dict(ccr=0x10000), dict(ccr=0x20000), dict(platform_initialized=1)):
            memory = Memory(after)
            with self.subTest(after=after), self.assertRaises(h.ProtocolError):
                h.challenge(memory.read, memory.write, 123)
            self.assertEqual(len(memory.writes), 1)

    def test_invalid_before_state_prevents_nonce_write(self):
        memory = Memory()
        memory.data = packet(state=4)
        with self.assertRaises(h.ProtocolError): h.challenge(memory.read, memory.write, 123)
        self.assertEqual(memory.writes, [])

    def test_write_exception_is_recorded_and_not_retried(self):
        memory, events = Memory(), []
        memory.write_fault = OSError('synthetic transport write failure')
        with self.assertRaises(OSError): h.challenge(memory.read, memory.write, 123, events=events)
        self.assertEqual(len(memory.writes), 1)
        self.assertEqual(len(memory.calls), 3)
        self.assertFalse(events[-1]['completed'])
        self.assertIn('OSError', events[-1]['error'])

    def test_after_short_read_keeps_failed_raw_event_and_does_not_rewrite(self):
        memory, events = Memory(), []
        def reader(address, length):
            if memory.writes: return b'\x00'
            return memory.read(address, length)
        with self.assertRaises(h.ProtocolError): h.challenge(reader, memory.write, 123, events=events)
        self.assertEqual(len(memory.writes), 1)
        self.assertEqual(events[-1]['raw_hex'], '00')
        self.assertEqual(events[-1]['requested_size'], 4)

    def test_poll_budget_types_are_rejected_before_any_transport(self):
        for limit in (True, 1.0, 0, 1001, None):
            memory = Memory()
            with self.subTest(limit=limit), self.assertRaises(h.ProtocolError):
                h.challenge(memory.read, memory.write, 123, max_polls=limit)
            self.assertEqual(memory.calls, [])
            self.assertEqual(memory.writes, [])

    def test_module_is_transport_injected_no_driver_or_cli_imports(self):
        tree = ast.parse(Path(h.__file__).read_text())
        imports = [name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names]
        self.assertEqual(imports, ['struct'])
        self.assertFalse(any(isinstance(node, ast.ImportFrom) for node in ast.walk(tree)))
        self.assertFalse(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                             and node.func.id in ('open', 'eval', 'exec', '__import__')
                             for node in ast.walk(tree)))


if __name__ == '__main__':
    unittest.main()
