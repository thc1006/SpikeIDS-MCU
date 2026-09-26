"""Offline synthetic mailbox tests only; no USB, serial, programmer or power."""
import json
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host_protocol as h


def values(**changes):
    data = dict.fromkeys(h.FIELDS, 0)
    data.update(magic=h.MAGIC, version=1, struct_bytes=h.SIZE, state=2,
                sequence=2, heartbeat=7, cpuid=0x410FD220, primask=1,
                vtor=h.VECTOR, msp=h.STACK_TOP - 32, msplim=h.STACK_START)
    data.update(changes)
    return data


def raw(data):
    return struct.pack('<64I', *[data[key] for key in h.FIELDS], *([0] * 32))


class FakeMemory:
    def __init__(self, **changes):
        self.data = values(**changes)
        self.writes = []
        self.advance = True
        self.write_count = 4

    def read(self, address, size):
        offset = address - h.ADDRESS
        return raw(self.data)[offset:offset + size]

    def write(self, address, payload):
        self.writes.append((address, payload))
        self.data['host_nonce'] = struct.unpack('<I', payload)[0]
        if self.advance:
            self.data['echo_nonce'] = self.data['host_nonce']
            self.data['heartbeat'] = (self.data['heartbeat'] + 1) & 0xFFFFFFFF
            self.data['sequence'] = (self.data['sequence'] + 2) & 0xFFFFFFFF
        return self.write_count


class ProtocolTests(unittest.TestCase):
    def test_fixed_contract_matches_authored_abi(self):
        abi = json.loads(Path(__file__).with_name('ABI.json').read_text())
        self.assertEqual((abi['mailbox_address'], abi['struct_bytes'], abi['magic']),
                         (h.ADDRESS, h.SIZE, h.MAGIC))
        self.assertEqual(abi['vector_address'], h.VECTOR)
        self.assertEqual(abi['stack_start'], h.STACK_START)
        self.assertEqual(abi['stack_top'], h.STACK_TOP)
        for index, name in enumerate(h.FIELDS):
            self.assertEqual(abi['fields'][index]['name'], name)
            self.assertEqual(abi['fields'][index]['offset'], index * 4)
        self.assertEqual([f['name'] for f in abi['fields'] if f['owner'] == 'host'], ['host_nonce'])

    def test_roundtrip_and_fault_observation(self):
        self.assertEqual(h.decode(raw(values()), 2, 2), values())
        fault = values(state=4, cfsr=0x100, fault_msp=0xDEADBEEF)
        decoded = h.decode(raw(fault), 2, 2)
        self.assertEqual(decoded['fault_msp'], 0xDEADBEEF)
        with self.assertRaises(h.ProtocolError): h.require_running(decoded)

    def test_busy_or_changed_sequence_rejected(self):
        for before, middle, after in ((1,1,1), (2,4,4), (2,2,4)):
            with self.subTest(before=before, middle=middle, after=after):
                with self.assertRaises(h.SnapshotBusy):
                    h.decode(raw(values(sequence=middle)), before, after)

    def test_wrong_identity_size_reserved_initialization(self):
        for change in ({'magic': 0}, {'version': 2}, {'state': 9}, {'reserved0': 1},
                       {'struct_bytes': 128}, {'platform_initialized': 1}):
            with self.subTest(change=change), self.assertRaises(h.ProtocolError):
                h.decode(raw(values(**change)), 2, 2)
        for data in (b'', bytes(255), bytes(257), bytearray(256)):
            with self.assertRaises(h.ProtocolError): h.decode(data, 2, 2)
        with self.assertRaises(h.ProtocolError): h.decode(raw(values()), True, 2)

    def test_running_environment_checks(self):
        for change in ({'ccr': 1 << 16}, {'ccr': 1 << 17}, {'control': 1},
                       {'entry_control': 2}, {'ipsr': 3}, {'vtor': 0}, {'primask': 0},
                       {'msp': h.STACK_START}, {'msp': h.STACK_TOP + 8},
                       {'msp': h.STACK_TOP - 1}, {'msplim': 0}):
            with self.subTest(change=change), self.assertRaises(h.ProtocolError):
                h.require_running(values(**change))

    def test_one_nonce_word_write_only_and_no_acceptance(self):
        memory, events = FakeMemory(), []
        result = h.challenge(memory.read, memory.write, 0x1234, events=events)
        self.assertTrue(result['probe_activity_observed'])
        self.assertEqual(memory.writes, [(h.ADDRESS + 24, struct.pack('<I', 0x1234))])
        for flag in ('platform_initialized', 'model_executed', 'power_measured', 'research_measurement_accepted'):
            self.assertIs(result[flag], False)
        self.assertEqual(sum(event['operation'] == 'write' for event in events), 1)

    def test_no_progress_timeout_no_rewrite(self):
        memory = FakeMemory()
        memory.advance = False
        with self.assertRaises(TimeoutError): h.challenge(memory.read, memory.write, 123, max_polls=2)
        self.assertEqual(len(memory.writes), 1)

    def test_stale_echo_or_existing_host_nonce_no_write(self):
        for changes in ({'echo_nonce': 123}, {'host_nonce': 123}):
            memory = FakeMemory(**changes)
            with self.assertRaises(h.ProtocolError): h.challenge(memory.read, memory.write, 123)
            self.assertEqual(memory.writes, [])

    def test_partial_or_invalid_write_never_retried(self):
        for count in (0, 1, 3, None, True, 4.0):
            memory = FakeMemory()
            memory.write_count = count
            with self.subTest(count=count), self.assertRaises(h.ProtocolError):
                h.challenge(memory.read, memory.write, 123)
            self.assertEqual(len(memory.writes), 1)

    def test_uint32_counter_wrap_still_observes_activity(self):
        memory = FakeMemory(sequence=0xFFFFFFFE, heartbeat=0xFFFFFFFF)
        result = h.challenge(memory.read, memory.write, 123)
        self.assertEqual(result['after']['sequence'], 0)
        self.assertEqual(result['after']['heartbeat'], 0)

    def test_invalid_nonce_and_budget_have_no_write(self):
        for nonce in (True, 1.0, -1, 0, 2**32):
            memory = FakeMemory()
            with self.assertRaises(h.ProtocolError): h.challenge(memory.read, memory.write, nonce)
            self.assertEqual(memory.writes, [])
        for limit in (0, -1, True, 1.5, 1001):
            with self.assertRaises(h.ProtocolError): h.snapshot(FakeMemory().read, max_attempts=limit)

    def test_short_read_and_busy_budget_are_bounded(self):
        with self.assertRaises(h.ProtocolError): h.snapshot(lambda address, size: b'')
        calls = []
        memory = FakeMemory(sequence=1)
        def read(address, size):
            calls.append((address, size))
            return memory.read(address, size)
        with self.assertRaises(TimeoutError): h.snapshot(read, max_attempts=2)
        self.assertEqual(len(calls), 6)


if __name__ == '__main__':
    unittest.main()
