"""Fixed offline initializer payload; never choose an unreviewed latest build."""
import json
import struct

from bundle import REPO, digest, require

BUILD = REPO / 'results/ppk2_n6_bringup_20260925_nAivHM/platform_stage_actual_03'
ABI = REPO / 'tools/n6_deployment/platform_stage/ABI.json'
PINS = {
    BUILD / 'RESULT.json': 'f61956f96cc3a13f690ec75cd17355048cae9eb3e80b4444ed5f84b31676bf73',
    BUILD / 'stage.elf': 'cc3fef71e251ce26e6b024067e673408c0f0bbc323aa985b0987019cb7567ec5',
    BUILD / 'stage.bin': '2c8857750005ee5ca13f634b6d45a3b18a8b5b9d935a67e40ac817a446a3bfaa',
    ABI: '66baa5f6a2499bdaac2e9666e1b3a489c2dddc6d570c347b8bcd6e795fd2bb80',
}


def parse_elf(raw):
    require(len(raw) >= 52 and raw[:7] == b'\x7fELF\x01\x01\x01', 'Stage ELF32 LE required')
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', raw)
    require(h[1:4] == (2, 40, 1) and h[8:11] == (52, 32, 3), 'Stage ARM ELF header')
    require(h[5] + 3 * 32 <= len(raw), 'Truncated stage program headers')
    expected = ((0x34180400, 2760, 2760, 5),
                (0x34188000, 0, 4096, 6), (0x34189000, 0, 8192, 6))
    segments = []
    for i, (address, file_bytes, memory_bytes, expected_flags) in enumerate(expected):
        kind, off, va, pa, filesz, memsz, flags, align = struct.unpack_from('<8I', raw, h[5] + 32*i)
        require(kind == 1 and va == pa == address and
                (filesz, memsz, flags) == (file_bytes, memory_bytes, expected_flags),
                'Unexpected stage PT_LOAD layout')
        require(off + filesz <= len(raw) and align == 0x1000 and off % align == va % align,
                'Stage ELF bounds/alignment')
        segments.append((va, raw[off:off+filesz] + bytes(memsz-filesz)))
    msp, entry = struct.unpack_from('<2I', segments[0][1])
    require(msp == 0x3418B000 and entry == h[4] == 0x34180539, 'Stage vectors/entry')
    return entry, msp, tuple(segments)


def load_stage():
    data = {}
    for path, sha in PINS.items():
        require(path == path.resolve(), 'Stage input path is not canonical')
        raw = path.read_bytes()
        require(digest(raw) == sha, 'Stage input digest mismatch: '+str(path))
        data[path] = raw
    report = json.loads(data[BUILD/'RESULT.json'])
    abi = json.loads(data[ABI])
    require(report['compile_link_succeeded'] is True and report['abi'] == abi,
            'Stage build/ABI mismatch')
    require(all(report[k] is False for k in ('board_ready', 'energy_measured', 'flash_written',
                'hardware_executed', 'model_executed', 'platform_initialized')),
            'Unexpected original stage scope')
    require(len(report['calls']) == 17 and all(type(c['actual_return_code']) is int and
            c['actual_return_code'] == 0 for c in report['calls']), 'Stage compiler command failure')
    entry, msp, segments = parse_elf(data[BUILD/'stage.elf'])
    require(segments[0][1] == data[BUILD/'stage.bin'], 'Stage BIN/ELF mismatch')
    for path, raw in data.items():
        require(path.read_bytes() == raw, 'Stage input changed during offline load')
    return {'entry': entry, 'msp': msp, 'segments': segments,
            'input_sha256': {str(p): sha for p, sha in PINS.items()}}


if __name__ == '__main__':
    payload = load_stage()
    print(json.dumps({'offline_stage_checked': True, 'entry': hex(payload['entry']),
        'regions': [{'address': hex(a), 'bytes': len(b), 'sha256': digest(b)}
                    for a, b in payload['segments']], 'hardware_accessed': False}, indent=2))
