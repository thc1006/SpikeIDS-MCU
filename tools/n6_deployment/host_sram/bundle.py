"""Read only the fixed, actually built S6 bundle. Default CLI is offline.

This does not regenerate, search for a 'latest' model, attach to a board or
reinterpret a failed export. Immutable byte buffers are the load authority.
"""
import hashlib
import io
import json
from pathlib import Path
import struct

REPO = Path(__file__).resolve().parents[3]
BUILD = REPO / 'tools/n6_deployment/firmware_sram/build_actual_01'
GEN = REPO / 'results/ppk2_n6_bringup_20260925_nAivHM/internal_sram_actual_01/generate'
EXPORT = REPO / 'results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq'
PINS = {
    BUILD / 'RESULT.json': '49225e31bc906e86fe73c3ca7f5a0d18592411f7692fa4173fdbe83c059a2e01',
    BUILD / 'n6_sram.elf': '9a68e6893b59d3d8d0952b70ccecdae6af14c3f3561532bd2a22540d69b562ca',
    GEN / 'nsl_qcfs_seed0_atonbuf.SRAM_WEIGHTS.raw': 'cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec',
    EXPORT / 'validation_vectors.npz': 'cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb',
    EXPORT / 'model_qdq_int8.onnx': '22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d',
}


def require(value, message):
    if not value: raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_fixed(path):
    require(path in PINS and path == path.resolve(), 'Not a fixed canonical input')
    raw = path.read_bytes()
    require(digest(raw) == PINS[path], 'Fixed input digest mismatch: '+str(path))
    return raw


def elf_segments(raw):
    require(len(raw) >= 52 and raw[:7] == b'\x7fELF\x01\x01\x01', 'Expected ELF32 LE')
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', raw)
    require(h[1:4] == (2, 40, 1) and h[8:11] == (52, 32, 4), 'Wrong ARM ELF header')
    require(h[5]+4*32 <= len(raw), 'Truncated program headers')
    segments = []
    for i in range(4):
        kind, off, va, pa, filesz, memsz, flags, align = struct.unpack_from('<8I', raw, h[5]+32*i)
        require(kind == 1 and va == pa and 0 <= filesz <= memsz and off+filesz <= len(raw), 'Bad PT_LOAD')
        require(align == 0x1000 and va % align == off % align, 'ELF alignment')
        allowed = ((0x34064000,0x340F0000,5), (0x34064000,0x340F0000,6),
                   (0x340F0000,0x340F8000,6), (0x340F8000,0x340F8200,6))[i]
        lo, hi, expected_flags = allowed
        require(lo <= va < va+memsz <= hi and flags == expected_flags, 'PT_LOAD outside allowed MCU RAM')
        if segments: require(segments[-1][0]+len(segments[-1][1]) <= va, 'Overlapping segments')
        if i >= 2: require(va == lo and memsz == hi-lo and filesz == 0, 'Stack/mailbox layout')
        segments.append((va, raw[off:off+filesz]+bytes(memsz-filesz)))
    msp, entry = struct.unpack_from('<2I', segments[0][1])
    require(segments[0][0] == 0x34064000 and msp == 0x340F8000 and entry == h[4]
            and entry & 1 and 0x34064000 <= entry-1 < 0x34064000+len(segments[0][1]), 'Vectors/entry')
    return entry, msp, segments


def load_bundle():
    import numpy as np
    data = {p: read_fixed(p) for p in PINS}
    report = json.loads(data[BUILD/'RESULT.json'])
    require(report['arm_compile_link_succeeded'] is True and report['hardware_executed'] is False,
            'Unexpected original build scope')
    require(all(type(c['actual_return_code']) is int and c['actual_return_code'] == 0
                for c in report['calls']) and len(report['calls']) == 63, 'Original build command failure')
    entry, msp, segments = elf_segments(data[BUILD/'n6_sram.elf'])
    weights = data[GEN/'nsl_qcfs_seed0_atonbuf.SRAM_WEIGHTS.raw']
    require(len(weights) == 145457, 'Weight file size')
    # Reserve/initialize complete pools, including the compiler's DMA prefetch
    # slack. The raw weight hash is on original bytes, not zero-padding.
    segments += [(0x34200000, weights+bytes(0x40000-len(weights))), (0x34240000, bytes(0x4000))]
    with np.load(io.BytesIO(data[EXPORT/'validation_vectors.npz']), allow_pickle=False) as z:
        require(set(z.files) == {'x','reference_logits','original_logits','validation_row_ids'}, 'NPZ schema')
        x, y, ids = (z[n].copy() for n in ('x','reference_logits','validation_row_ids'))
    require(x.dtype == np.dtype('<f4') and x.shape == (1024,41) and
            y.dtype == np.dtype('<f4') and y.shape == (1024,5), 'Tensor contract')
    require(ids.dtype == np.dtype('<i8') and ids.shape == (1024,) and
            np.all((0 <= ids) & (ids <= 0xFFFFFFFF)) and len(np.unique(ids)) == 1024, 'Row ID contract')
    require(np.isfinite(x).all() and np.isfinite(y).all(), 'Nonfinite validation data')
    rows = tuple((int(ids[i]), x[i].tobytes(order='C'), y[i].tobytes(order='C')) for i in range(1024))
    for p, raw in data.items(): require(p.read_bytes() == raw, 'Input changed during offline load')
    return {'entry': entry, 'msp': msp, 'segments': tuple(segments), 'rows': rows,
            'input_sha256': {str(p): PINS[p] for p in PINS}}


if __name__ == '__main__':
    b = load_bundle()
    print(json.dumps({'offline_bundle_checked': True, 'entry': hex(b['entry']),
                      'regions': [{'address': hex(a), 'bytes': len(v), 'sha256': digest(v)} for a,v in b['segments']],
                      'validation_rows': len(b['rows']), 'hardware_accessed': False}, indent=2))
