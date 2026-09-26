"""RAM-only payload load/readback using an already connected, halted core.

No power, reset, erase, flash, OTP, platform acknowledgement or auto-resume.
All overwritten bytes must first be retained by the caller's backup sink.
The platform initialization stage must precede the NPU SRAM payload load.
"""
import hashlib

RAM_RANGES = ((0x34064000,0x340F8200), (0x34180400,0x3418B000), (0x34200000,0x34244000))


def require(value, message):
    if not value: raise ValueError(message)


def validate_regions(regions):
    require(type(regions) is tuple and 0 < len(regions) <= 8, 'Explicit immutable region tuple required')
    end = 0
    for address, raw in regions:
        require(type(address) is int and type(raw) is bytes and len(raw) > 0, 'Invalid RAM payload')
        require(address >= end and any(lo <= address < address+len(raw) <= hi for lo,hi in RAM_RANGES),
                'Unordered/overlapping/out-of-scope RAM write')
        end = address+len(raw)


def load_and_verify(core, regions, retain_backup, events):
    """Core methods: entry_snapshot(), read(addr,n), write(addr,bytes).

    retain_backup(address, bytes) must durably persist raw bytes before returning.
    No rollback is attempted automatically after an ambiguous transfer failure.
    """
    validate_regions(regions)
    initial = core.entry_snapshot()  # enforces halted secure privileged Thread/cache-off
    events.append({'operation':'entry_preflight','raw':initial})
    # Back up ALL destinations before ANY payload mutation.
    for address, raw in regions:
        prior = bytearray()
        for offset in range(0,len(raw),4096):
            n = min(4096,len(raw)-offset)
            part = core.read(address+offset,n)
            require(type(part) is bytes and len(part)==n, 'Incomplete RAM backup')
            prior.extend(part)
        retain_backup(address, bytes(prior))
        events.append({'operation':'backup','address':address,'bytes':len(prior),
                       'sha256':hashlib.sha256(prior).hexdigest()})
    require(core.entry_snapshot() == initial, 'Entry state changed before RAM write')
    for address, raw in regions:
        for offset in range(0,len(raw),4096):
            part = raw[offset:offset+4096]
            event = {'operation':'write_readback','address':address+offset,'bytes':len(part),
                     'sha256':hashlib.sha256(part).hexdigest(),'attempted':True,'verified':False}
            events.append(event)
            n = core.write(address+offset,part)
            require(type(n) is int and n == len(part), 'Incomplete/ambiguous RAM write; no retry')
            require(core.read(address+offset,len(part)) == part, 'Physical RAM readback mismatch')
            event['verified']=True
    # A second whole-payload pass also detects later overlapping writes.
    for address, raw in regions:
        for offset in range(0,len(raw),4096):
            part = raw[offset:offset+4096]
            require(core.read(address+offset,len(part)) == part, 'Final RAM readback mismatch')
    require(core.entry_snapshot() == initial, 'Entry state changed during RAM load')
    return {'ram_payload_readback_matched':True, 'regions':len(regions),
            'target_started':False, 'model_executed':False, 'energy_measured':False}
