"""SM02 wire validation; no output/input/tolerance changes or hardware access."""
import struct

TAG = 0x534D3032
RECEIPT = 0x52544932


def decode(raw, original_decode):
    if type(raw) is not bytes or len(raw) != 512:
        raise ValueError('Require complete SM02 mailbox')
    w = struct.unpack('<128I', raw)
    if w[31] != TAG:
        raise ValueError('Not the runtime-initialized SM02 variant')
    if w[3] == 1:
        if w[73:76] != (0, 0, 0):
            raise ValueError('Runtime touched before ACK')
    elif w[3] in (3, 4, 5):
        if w[73:76] != (RECEIPT, 0, 1):
            raise ValueError('Runtime init missing, failed or repeated')
    elif w[73:76] != (0, 0, 0) and (w[73] != RECEIPT or w[75] != 1):
        raise ValueError('Invalid runtime receipt during initialization/fault')
    # Validate every inherited field using the frozen S6 decoder. Only the
    # separately validated new tag/receipt are projected to their S6 values.
    # Raw retained messages and returned words remain the original SM02 bytes.
    shared = bytearray(raw)
    struct.pack_into('<I', shared, 124, 0x534D3031)
    shared[292:304] = bytes(12)
    original_decode(bytes(shared))
    return w


def mailbox_type(original):
    class RuntimeMailbox(original.Mailbox):
        def snapshot(self):
            for _ in range(8):
                a, b = self.read(original.ADDRESS, 512), self.read(original.ADDRESS, 512)
                if a == b:
                    return a, decode(a, original.decode)
            raise TimeoutError('No stable SM02 mailbox in eight paired reads')
    return RuntimeMailbox


def runtime_live(core, retain=lambda observation: None):
    context = core.entry_snapshot()
    regs = {hex(a): core.core.read32(a) for a in
            (0x580E0000, 0x580E0008, 0x580E000C, 0x580E0010,
             0x580E2000, 0x580E3000)}
    observation=dict(context=context, registers=regs, energy_measured=False,
                     npu_execution_independently_verified=False)
    retain(observation)  # retain even incompatible MMIO/IRQ state before rejection
    if context['primask'] != 1:
        raise RuntimeError('Runtime unmasked external IRQs')
    for a in (0x580E0000, 0x580E2000, 0x580E3000):
        if type(regs[hex(a)]) is not int or regs[hex(a)] & 1 != 1:
            raise RuntimeError('NPU global clock/bus interface not enabled: '+hex(a))
    return observation
