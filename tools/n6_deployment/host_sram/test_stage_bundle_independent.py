"""Fixed saved stage bytes only; no model payloads, compiler or target access.

Failure injection changes returned bytes in memory, never held files. The
typed-exit controls explicitly replace the report's in-memory policy hash to
reach that guard; they do not claim to bypass the fixed production digest.
"""
import hashlib
import json
from pathlib import Path
import struct

import pytest
import stage_bundle as s


def test_fixed_saved_stage_crossbinds_original_report_and_load_bytes():
    source = Path(s.__file__).read_bytes()
    assert hashlib.sha256(source).hexdigest() == 'b1eefbe71b122efe4393ddd42e1d54a75acaba9b20cbaf2fbed04b9a80e1a6f9'
    payload = s.load_stage()
    report = json.loads((s.BUILD / 'RESULT.json').read_bytes())
    for name in ('stage.elf', 'stage.bin'):
        assert report['artifact_pins_before_result']['files'][name]['sha256'] == s.PINS[s.BUILD/name]
    assert report['source_pins'][str(s.ABI)]['sha256'] == s.PINS[s.ABI]
    assert type(payload['segments']) is tuple and len(payload['segments']) == 3
    assert all(type(raw) is bytes for _, raw in payload['segments'])
    assert payload['entry'] == report['elf_layout']['entry_thumb'] == 0x34180539
    assert payload['msp'] == report['elf_layout']['initial_msp'] == 0x3418B000
    assert payload['segments'][0] == (0x34180400, (s.BUILD/'stage.bin').read_bytes())
    assert payload['segments'][1:] == ((0x34188000,bytes(4096)),(0x34189000,bytes(8192)))
    assert payload['input_sha256'] == {str(p): v for p,v in s.PINS.items()}
    assert Path(s.__file__).read_bytes() == source


def test_wrong_saved_elf_digest_rejected_before_parser(monkeypatch):
    read = Path.read_bytes
    def changed(path):
        raw = read(path)
        return raw[:-1] + bytes([raw[-1] ^ 1]) if path == s.BUILD/'stage.elf' else raw
    monkeypatch.setattr(Path,'read_bytes',changed)
    def forbidden(*_):raise AssertionError('parser must not consume wrong-digest bytes')
    monkeypatch.setattr(s,'parse_elf',forbidden)
    with pytest.raises(ValueError,match='digest mismatch'):s.load_stage()


@pytest.mark.parametrize('value',[False,0.0])
def test_noninteger_zero_receipt_is_rejected_after_explicit_policy_seam(monkeypatch,value):
    path = s.BUILD/'RESULT.json'; report = json.loads(path.read_bytes())
    report['calls'][0]['actual_return_code'] = value
    raw = json.dumps(report).encode(); pins = dict(s.PINS); pins[path] = hashlib.sha256(raw).hexdigest()
    read = Path.read_bytes
    monkeypatch.setattr(s,'PINS',pins)
    monkeypatch.setattr(Path,'read_bytes',lambda p:raw if p==path else read(p))
    with pytest.raises(ValueError,match='compiler command failure'):s.load_stage()


def test_late_saved_abi_byte_change_rejected_not_newly_adopted(monkeypatch):
    read = Path.read_bytes; seen = 0
    def changed(path):
        nonlocal seen
        raw = read(path)
        if path == s.ABI:
            seen += 1
            if seen == 2:return raw + b'\n'
        return raw
    monkeypatch.setattr(Path,'read_bytes',changed)
    with pytest.raises(ValueError,match='changed during offline load'):s.load_stage()
    assert seen == 2


def test_nobits_may_not_load_bytes_or_alias_payload_ram():
    original = (s.BUILD/'stage.elf').read_bytes()
    h = struct.unpack_from('<16sHHIIIIIHHHHHH',original)
    for index, offset, value in ((1,16,4),(2,16,4),(1,8,0x34200000),(2,8,0x34240000)):
        raw = bytearray(original); struct.pack_into('<I',raw,h[5]+32*index+offset,value)
        with pytest.raises(ValueError,match='PT_LOAD layout'):s.parse_elf(raw)
