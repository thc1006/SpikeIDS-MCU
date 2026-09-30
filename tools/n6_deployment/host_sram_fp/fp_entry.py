"""One explicit FPSCR RMode initialization before the frozen S6 platform ACK.

No default-register, flash, reset, resume or power write. Other mode mismatches
are rejected. Preserve LTPSIZE and all non-RMode bits. This is not a numerical
tolerance change or proof of how a future FP context would otherwise behave.
"""
RMODE = 0x00C00000
MODES = 0x07C80000
CPACR, FPCCR, FPDSCR = 0xE000ED88, 0xE000EF34, 0xE000EF3C
ADDRESS = 0x340F8000


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def u32(value):
    require(type(value) is int and 0 <= value <= 0xFFFFFFFF, 'Not an exact uint32')
    return value


def snapshot(core):
    context = core.entry_snapshot()  # existing halted/secure/privileged/cache-off gate
    raw = core.read(ADDRESS, 512)
    require(type(raw) is bytes and len(raw) == 512, 'Incomplete mailbox observation')
    registers = {name: u32(core.core.read32(address)) for name, address in
                 (('cpacr', CPACR), ('fpccr', FPCCR), ('fpdscr', FPDSCR))}
    registers['fpscr'] = u32(core.core.read_core_register_raw('fpscr'))
    return dict(context=context, registers=registers, mailbox_hex=raw.hex())


def validate(observation, decode):
    context, registers = observation['context'], observation['registers']
    require(context['primask'] == 1, 'IRQs must already be masked')
    require(0x34064000 <= context['pc'] < 0x3407621F,
            'Not in the fixed S6 executable segment')
    require(0x340F0000 < context['msp'] <= 0x340F8000 and context['msp'] % 8 == 0,
            'Not on the fixed S6 stack')
    raw = bytes.fromhex(observation['mailbox_hex'])
    words = decode(raw)
    require(words[3:7] == (1, 0, 0, 0), 'Require fresh WAIT_PLATFORM with no ACK/request')
    require(words[7:12] == (0,) * 5 and words[12:18] == (0x80000000,) * 6
            and words[18:23] == (0,) * 5 and words[24:26] == (0, 0),
            'Model initialization or inference already touched mailbox')
    require(registers['cpacr'] & 0x00F00000 == 0x00F00000, 'FPU access not enabled')
    require(registers['fpccr'] & 1 == 0, 'Lazy FP context active')
    require(registers['fpdscr'] & MODES == 0, 'FPDSCR mode mismatch; no default-register repair')
    require(registers['fpscr'] & (MODES & ~RMODE) == 0,
            'Unsupported FPSCR mode mismatch; only RMode may change')


def establish_rne(core, sink, decode):
    before = snapshot(core)
    sink.json('fp_entry_before.json', before)  # durable retention before any FP write
    validate(before, decode)
    expected = before['registers']['fpscr'] & ~RMODE
    changed = expected != before['registers']['fpscr']
    sink.json('fp_entry_intent.json', dict(register='fpscr', mask=RMODE,
        previous=before['registers']['fpscr'], expected=expected,
        write_planned=changed, write_is_not_yet_observed=True,
        preserved_all_other_bits=True, fpdscr_write=False))
    # Check again after durable intent publication; do not act on a stale entry
    # if retention took time or a reset/other agent changed the stopped target.
    require(snapshot(core) == before, 'Entry changed before FPSCR write')
    # A failing write/flush is ambiguous and is never retried.
    if changed:
        core.core.write_core_register_raw('fpscr', expected)
        core.core.flush()
    after = snapshot(core)
    sink.json('fp_entry_after.json', after)
    wanted = {**before, 'registers': {**before['registers'], 'fpscr': expected}}
    require(after == wanted, 'FPSCR readback mismatch or unrelated state change')
    validate(after, decode)
    # Retain the old strict check; it still rejects other FP-mode problems.
    result = core.floating_environment()
    sink.json('fp_entry_verified.json', dict(write_completed_and_verified=changed,
        already_rne=not changed, floating_environment=result,
        research_measurement_accepted=False))
    return result


class EntryCore:
    """Adapter around the frozen backend; later FP checks are read-only.

    Single-session use only. A failed first check poisons this entry adapter.
    Inference/post-validation mode corruption must never trigger reinitialization.
    """
    def __init__(self, core, sink, decode):
        self.delegate, self.sink, self.decode = core, sink, decode
        self.used = False
        self.failed = False

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def floating_environment(self):
        require(not self.failed, 'FP entry adapter is poisoned')
        if self.used:
            return self.delegate.floating_environment()
        self.used = True
        try:
            return establish_rne(self.delegate, self.sink, self.decode)
        except BaseException:
            self.failed = True
            raise
