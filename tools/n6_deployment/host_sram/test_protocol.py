import math
import struct
import unittest
from protocol import ADDRESS, ACK, MAGIC, TAG, MODEL, WEIGHTS, Mailbox, ProtocolError, decode


def ready():
    w = [0] * 128
    w[:7] = [MAGIC, 1, 512, 3, ACK, 0, 0]
    w[16:18] = [0x80000000] * 2
    w[23:32] = [0x411FD221, 0x34240000, 0x34240000, 0x34200000, 0x40000,
                0x34240000, 0x4000, 145457, TAG]
    raw = bytearray(struct.pack('<128I', *w))
    raw[352:417], raw[417:482] = MODEL, WEIGHTS
    return raw


class Fake:
    def __init__(self):
        self.raw, self.writes, self.mutate, self.reply = ready(), [], None, True

    def read(self, address, size):
        return bytes(self.raw[address-ADDRESS:address-ADDRESS+size])

    def write(self, address, raw):
        self.writes.append((address, raw))
        self.raw[address-ADDRESS:address-ADDRESS+len(raw)] = raw
        if address == ADDRESS+20 and self.reply:
            w = list(struct.unpack('<128I', self.raw))
            w[3], w[6], w[10], w[19], w[20] = 5, w[5], 5, w[8], 1234
            w[12:19] = [0]*7
            self.raw[:] = struct.pack('<128I', *w)
            self.raw[320:340] = struct.pack('<5f', -1, 2, 3, 4, 5)
            if self.mutate:
                self.mutate(self.raw)
        return len(raw)


class ProtocolTests(unittest.TestCase):
    def test_full_results_and_order(self):
        f = Fake(); m = Mailbox(f.read, f.write, sleep=lambda _: None)
        x = struct.pack('<41f', *range(41))
        a, b = m.infer(123, x), m.infer(456, x)
        self.assertEqual(a['logits'], [-1, 2, 3, 4, 5])
        self.assertEqual(b['sequence'], 2)
        self.assertEqual([a for a, _ in f.writes[:3]], [ADDRESS+28, ADDRESS+128, ADDRESS+20])
        self.assertFalse(a['latency_validated'])

    def test_all_response_corruption_rejected_and_session_poisoned(self):
        cases = [(0, 0), (3, 4), (4, 0), (5, 0), (6, 9), (7, 0), (8, 99),
                 (9, 1), (10, 1), (11, 5), (12, 1), (16, 1), (18, 1), (19, 99),
                 (23, 0), (24, 0), (26, 0), (31, 0), (32, 1), (80, 0x7F800000)]
        for index, value in cases:
            with self.subTest(index=index):
                f = Fake()
                f.mutate = lambda raw, i=index, v=value: struct.pack_into('<I', raw, 4*i, v)
                m = Mailbox(f.read, f.write, sleep=lambda _: None)
                with self.assertRaises((ProtocolError, TimeoutError)):
                    m.infer(1, bytes(164))
                n = len(f.writes)
                with self.assertRaises(ProtocolError): m.infer(2, bytes(164))
                self.assertEqual(n, len(f.writes))

    def test_bad_input_no_write(self):
        for row, x in [(True, bytes(164)), (-1, bytes(164)), (1, bytes(160)),
                       (1, struct.pack('<f', math.nan)+bytes(160))]:
            f = Fake(); m = Mailbox(f.read, f.write)
            with self.assertRaises(ProtocolError): m.infer(row, x)
            self.assertEqual(f.writes, [])

    def test_short_write_never_commit(self):
        for returned in (True, None, 11):
            f = Fake(); m = Mailbox(f.read, lambda a, r: returned)
            with self.assertRaises(ProtocolError): m.infer(1, bytes(164))
            self.assertTrue(m.failed)
            self.assertEqual(len(m.events), 3)

    def test_wrong_model_or_old_mailbox(self):
        for offset in (0, 352, 417, 482):
            raw = ready(); raw[offset] ^= 1
            with self.assertRaises(ProtocolError): decode(bytes(raw))

    def test_timeout_no_retry(self):
        f = Fake(); f.reply = False
        m = Mailbox(f.read, f.write, sleep=lambda _: None)
        with self.assertRaises(TimeoutError): m.infer(1, bytes(164), max_polls=2)
        self.assertEqual(len(f.writes), 3)

    def test_changed_staging_no_commit(self):
        f = Fake()
        def write(a, raw):
            count = f.write(a, raw)
            f.raw[128] ^= 1
            return count
        m = Mailbox(f.read, write)
        with self.assertRaises(ProtocolError): m.infer(1, bytes(164))
        self.assertEqual(len(f.writes), 2)


if __name__ == '__main__': unittest.main()
