"""Bounded mailbox protocol, with injected transport; no hardware driver or CLI.

This is for the minimal RAM activity probe, NOT the v5 inference mailbox.
A future hardware caller must independently establish safe RAM loading, cache
coherence and bounded transport calls. This module never loads or starts code,
changes power, enters debug mode, or acknowledges platform initialization.
"""
import struct

ADDRESS = 0x34185000
SIZE = 256
MAGIC = 0x4E365052
VECTOR = 0x34180400
STACK_START = 0x34184000
STACK_TOP = ADDRESS
FIELDS = (
    'magic', 'version', 'struct_bytes', 'state', 'sequence', 'heartbeat',
    'host_nonce', 'echo_nonce', 'cpuid', 'ccr', 'control', 'vtor',
    'entry_vtor', 'entry_control', 'entry_primask', 'entry_msp', 'primask',
    'ipsr', 'msp', 'msplim', 'cfsr', 'hfsr', 'dfsr', 'afsr', 'mmfar',
    'bfar', 'fault_ipsr', 'fault_exc_return', 'fault_msp', 'fault_psp',
    'platform_initialized', 'reserved0',
)


class ProtocolError(ValueError):
    pass


class SnapshotBusy(ProtocolError):
    """An interrupted publication; retrying a bounded read is permissible."""


def uint32(value, name):
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise ProtocolError(name + ' must be an exact uint32')
    return value


def budget(value):
    if type(value) is not int or not 1 <= value <= 1000:
        raise ProtocolError('Read budget must be an integer in [1, 1000]')
    return value


def decode(raw, sequence_before, sequence_after):
    """Decode a stable snapshot; fault/rejected states remain observations."""
    if not isinstance(raw, bytes) or len(raw) != SIZE:
        raise ProtocolError('Mailbox must contain exactly 256 immutable bytes')
    uint32(sequence_before, 'sequence_before')
    uint32(sequence_after, 'sequence_after')
    words = struct.unpack('<64I', raw)
    if sequence_before & 1 or not sequence_before == words[4] == sequence_after:
        raise SnapshotBusy('Odd or changed publication sequence')
    values = dict(zip(FIELDS, words[:32]))
    if (values['magic'], values['version'], values['struct_bytes']) != (MAGIC, 1, SIZE):
        raise ProtocolError('Wrong probe identity or ABI')
    if values['state'] not in (1, 2, 3, 4, 5):
        raise ProtocolError('Unknown probe state')
    if values['platform_initialized'] != 0:
        raise ProtocolError('Minimal probe cannot attest platform initialization')
    if any(words[31:]):
        raise ProtocolError('Reserved fields must remain zero')
    return values


def require_running(values):
    if values['state'] != 2:
        raise ProtocolError('Probe is not RUNNING; observed state=' + str(values['state']))
    if values['ccr'] & ((1 << 16) | (1 << 17)):
        raise ProtocolError('Cache-enabled mailbox cannot establish coherence')
    if values['control'] & 3 or values['entry_control'] & 3 or values['ipsr'] != 0:
        raise ProtocolError('Unexpected Thread privilege/stack selection')
    if values['primask'] != 1 or values['vtor'] != VECTOR:
        raise ProtocolError('Unexpected vector/interrupt configuration')
    if values['msplim'] != STACK_START or not STACK_START < values['msp'] <= STACK_TOP:
        raise ProtocolError('Private stack bounds not observed')
    if values['msp'] % 8:
        raise ProtocolError('Stack must be eight-byte aligned')


def snapshot(read_memory, *, max_attempts=8, events=None):
    """Three reads per attempt. Caller must bound each transport call itself.

    Equal even uint32 sequences cannot rule out a whole-counter ABA wrap, a
    reset/replayed device or a stale cache. This is not hardware attestation.
    """
    budget(max_attempts)
    def read(address, size):
        raw = read_memory(address, size)
        if events is not None:
            events.append({'operation': 'read', 'address': address,
                           'requested_size': size,
                           'raw_hex': raw.hex() if isinstance(raw, bytes) else None})
        if not isinstance(raw, bytes) or len(raw) != size:
            raise ProtocolError('Short or invalid memory reply')
        return raw
    for _ in range(max_attempts):
        before = struct.unpack('<I', read(ADDRESS + 16, 4))[0]
        raw = read(ADDRESS, SIZE)
        after = struct.unpack('<I', read(ADDRESS + 16, 4))[0]
        try:
            return decode(raw, before, after)
        except SnapshotBusy:
            continue
    raise TimeoutError('No consistent mailbox within bounded read attempts')


def challenge(read_memory, write_memory, nonce, *, max_polls=8, events=None):
    """One nonce write, then bounded polling; no automatic retry of the write.

    write_memory must return the exact number of bytes written. A failed or
    partial write is an ambiguous transport outcome, never retried here.
    Observed nonce echo/activity is not inferred clock speed or model execution.
    """
    uint32(nonce, 'nonce')
    budget(max_polls)
    if nonce == 0:
        raise ProtocolError('Use a nonzero nonce different from existing values')
    before = snapshot(read_memory, events=events)
    require_running(before)
    if nonce in (before['host_nonce'], before['echo_nonce']):
        raise ProtocolError('Nonce already present; would accept a stale echo')
    value = struct.pack('<I', nonce)
    event = {'operation': 'write', 'address': ADDRESS + 24,
             'raw_hex': value.hex(), 'attempted': True, 'completed': False}
    if events is not None:
        events.append(event)
    try:
        count = write_memory(ADDRESS + 24, value)
        event['bytes_written'] = count
        if type(count) is not int or count != 4:
            raise ProtocolError('Nonce write was not completed in full')
        event['completed'] = True
    except BaseException as exc:
        event['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    for _ in range(max_polls):
        after = snapshot(read_memory, events=events)
        require_running(after)
        if after['cpuid'] != before['cpuid']:
            raise ProtocolError('CPU identity observation changed')
        if after['host_nonce'] != nonce:
            raise ProtocolError('Nonce changed/readback failed or target restarted')
        if (after['echo_nonce'] == nonce and
                after['heartbeat'] != before['heartbeat'] and
                after['sequence'] != before['sequence']):
            return {'probe_activity_observed': True, 'before': before, 'after': after,
                    'nonce': nonce, 'platform_initialized': False,
                    'model_executed': False, 'power_measured': False,
                    'research_measurement_accepted': False}
    raise TimeoutError('Fresh echo and heartbeat not observed within bounded polls')
