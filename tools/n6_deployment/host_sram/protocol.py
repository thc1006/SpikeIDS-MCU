"""Full-logit S6 mailbox transport. No power, reset, loading or platform ACK.

The caller owns a single session and must bound transport calls externally.
Returned CPU cycles cover the mixed CPU/NPU call; they are not energy or a
frequency measurement. These checks cannot authenticate a physical device.
"""
import math
import struct
import time

ADDRESS = 0x340F8000
SIZE = 512
MAGIC = 0x53364E36
TAG = 0x534D3031
ACK = 0x504C4154
MODEL = b'22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d\0'
WEIGHTS = b'cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec\0'


class ProtocolError(ValueError):
    pass


def require(value, message):
    if not value:
        raise ProtocolError(message)


def u32(value):
    require(type(value) is int and 0 <= value <= 0xFFFFFFFF, 'Expected exact uint32')
    return value


def decode(raw):
    require(type(raw) is bytes and len(raw) == SIZE, 'Expected 512 mailbox bytes')
    w = struct.unpack('<128I', raw)
    require(w[:3] == (MAGIC, 1, SIZE), 'Wrong SRAM firmware identity/ABI')
    require(w[3] in range(1, 8), 'Unknown firmware state')
    require(raw[352:417] == MODEL and raw[417:482] == WEIGHTS, 'Wrong model/weights identity')
    require(w[26:32] == (0x34200000, 0x40000, 0x34240000, 0x4000, 145457, TAG),
            'Wrong SRAM placement/deployment')
    require(not any(w[73:80]) and not any(w[85:88]) and not any(raw[482:]),
            'Reserved mailbox bytes changed')
    require((w[23] >> 4) & 0xFFF == 0xD22, 'Not a Cortex-M55 CPUID')
    return w


class Mailbox:
    def __init__(self, read, write, *, events=None, clock=time.monotonic, sleep=time.sleep):
        self.read_memory, self.write_memory = read, write
        self.events = [] if events is None else events
        self.clock, self.sleep = clock, sleep
        self.failed = False

    def read(self, address, size):
        raw = self.read_memory(address, size)
        self.events.append({'op': 'read', 'address': address, 'size': size,
                            'hex': raw.hex() if type(raw) is bytes else None})
        require(type(raw) is bytes and len(raw) == size, 'Short/nonbyte transport reply')
        return raw

    def write(self, address, raw):
        event = {'op': 'write', 'address': address, 'hex': raw.hex(), 'completed': False}
        self.events.append(event)
        n = self.write_memory(address, raw)
        event['returned_count'] = n
        require(type(n) is int and n == len(raw), 'Ambiguous/partial write; do not retry')
        event['completed'] = True

    def snapshot(self):
        # A single outstanding immutable request is essential. This is finite
        # consistency checking, not a proof against device reset/replay/ABA.
        for _ in range(8):
            a, b = self.read(ADDRESS, SIZE), self.read(ADDRESS, SIZE)
            if a == b:
                return a, decode(a)
        raise TimeoutError('No stable mailbox in eight paired reads')

    def infer(self, row_id, input_bytes, *, timeout_seconds=5.0, max_polls=10000):
        require(not self.failed, 'Session already failed; no automatic retry')
        u32(row_id)
        require(type(input_bytes) is bytes and len(input_bytes) == 164, '41 raw FP32 inputs required')
        require(all(math.isfinite(x) for x in struct.unpack('<41f', input_bytes)), 'Nonfinite input')
        require(type(timeout_seconds) in (int, float) and math.isfinite(timeout_seconds)
                and 0 < timeout_seconds <= 30, 'Timeout outside (0,30] seconds')
        require(type(max_polls) is int and 1 <= max_polls <= 10000, 'Invalid poll budget')
        try:
            return self._infer(row_id, input_bytes, timeout_seconds, max_polls)
        except BaseException:
            # A failed write/run may have happened. Do not submit another row.
            self.failed = True
            raise

    def _infer(self, row_id, inputs, timeout, max_polls):
        _, before = self.snapshot()
        require(before[3] in (3, 5) and before[4] == ACK, 'Platform/model is not ready')
        require(before[5] == before[6] < 0xFFFFFFFF, 'Outstanding request or sequence exhausted')
        require(before[24:26] == (0x34240000, 0x34240000), 'Wrong runtime I/O placement')
        require(before[18] == 0 and before[12:16] == (0, 0, 0, 0), 'Initialization failed')
        if before[3] == 3:
            require(before[5] == 0, 'READY with stale request')
        else:
            require(before[5] > 0 and before[16:18] == (0, 0), 'Invalid prior completion')
        seq = before[5] + 1
        start = self.clock()
        self.write(ADDRESS + 28, struct.pack('<3I', 1, row_id, 41))
        self.write(ADDRESS + 128, inputs)
        raw, staged = self.snapshot()
        # No commit until every staged word and the idle identity still agree.
        expected = list(before)
        expected[7:10] = [1, row_id, 41]
        expected[32:73] = struct.unpack('<41I', inputs)
        require(tuple(expected) == staged, 'Precommit target state/input readback mismatch')
        require(self.clock() - start < timeout, 'Deadline before request commit')
        self.write(ADDRESS + 20, struct.pack('<I', seq))  # only commit, never retried
        for _ in range(max_polls):
            require(self.clock() - start < timeout, 'Inference host deadline exceeded')
            raw, w = self.snapshot()
            elapsed = self.clock() - start
            require(elapsed < timeout, 'Inference deadline crossed during transport read')
            require(w[3] not in (6, 7), 'Firmware ERROR/FAULT; preserve raw mailbox')
            require(w[4] == ACK and w[5] == seq and w[7:10] == (1, row_id, 41)
                    and raw[128:292] == inputs, 'Request changed or target restarted')
            require(w[23] == before[23] and w[24:26] == before[24:26], 'Runtime identity changed')
            require(w[6] in (before[6], seq), 'Unexpected completion sequence')
            if w[6] == seq:
                require(w[3] == 5 and w[10] == 5 and w[11] == 0 and w[19] == row_id,
                        'Incomplete/wrong-row response')
                require(w[12:19] == (0,) * 7, 'Non-success runtime/adapter status')
                logits = struct.unpack('<5f', raw[320:340])
                require(all(math.isfinite(x) for x in logits), 'Nonfinite output')
                return {'row_id': row_id, 'sequence': seq, 'input_hex': inputs.hex(),
                        'output_hex': raw[320:340].hex(), 'logits': list(logits),
                        'cpu_cycles_modulo_2_32': w[20], 'raw_mailbox_hex': raw.hex(),
                        'host_elapsed_s': elapsed,
                        'npu_execution_independently_verified': False,
                        'latency_validated': False, 'energy_measured': False}
            self.sleep(0.001)
        raise TimeoutError('Inference poll budget exhausted')
