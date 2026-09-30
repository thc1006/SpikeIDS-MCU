"""Root saved ELF/BIN/pin review; independent of the build helper, no hardware."""
import hashlib
import json
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
OUT = HERE / 'build_actual_01'
RESULT_SHA = 'aae2d1f3e3572f8afac200f17a8cc7671d051770c9a3182a2664f983e7e38f42'
FIELDS = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def pin(path):
    require(path.is_absolute() and path == path.resolve(), 'noncanonical file')
    a = path.stat()
    require(stat.S_ISREG(a.st_mode), 'not regular file')
    raw = path.read_bytes()
    b = path.stat()
    require(all(getattr(a, k) == getattr(b, k) for k in FIELDS), 'read changed')
    return dict(sha256=hashlib.sha256(raw).hexdigest(), **{k: getattr(a, k) for k in FIELDS})


def main():
    require(not sys.flags.optimize, 'optimized reviewer')
    result_pin = pin(OUT / 'RESULT.json')
    require(result_pin['sha256'] == RESULT_SHA, 'wrong saved RESULT')
    r = json.loads((OUT / 'RESULT.json').read_bytes())
    held = {Path(p): value for p, value in r['input_pins'].items()}
    held.update({OUT / p: value for p, value in r['artifacts_before_result'].items()})
    held[OUT / 'RESULT.json'] = result_pin
    held[Path(__file__).resolve()] = pin(Path(__file__).resolve())
    namespace = set(r['artifacts_before_result']) | {'RESULT.json'}
    require({p.name for p in OUT.iterdir()} == namespace, 'original namespace')
    for p, expected in held.items():
        require(pin(p) == expected, 'original pin changed: ' + str(p))
    require(len(r['calls']) == 67 and all(type(c['actual_return_code']) is int and
            c['actual_return_code'] == 0 and c['timed_out'] is False for c in r['calls']), 'child exits')
    elf = (OUT / 'n6_sram_trace.elf').read_bytes()
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', elf)
    require(elf[:7] == b'\x7fELF\x01\x01\x01' and h[1:4] == (2, 40, 1) and
            h[4] == 0x34064061 and h[9:11] == (32, 5) and h[11] == 40, 'ARM executable')
    segments = [struct.unpack_from('<8I', elf, h[5] + i * 32) for i in range(h[10])]
    require(all(s[0] == 1 and s[2] == s[3] and s[4] <= s[5] and s[1] + s[4] <= len(elf)
                for s in segments), 'PT_LOAD bounds')
    code, data, stack, mailbox, trace = segments
    require(code[2] == 0x34064000 and code[4] == code[5] and code[6] == 5 and
            code[2] + code[5] <= data[2] and data[2] + data[5] <= 0x340f0000 and
            data[6] == 6, 'code/data bounds')
    require(stack[2:7] == (0x340f0000, 0x340f0000, 0, 0x8000, 6), 'stack')
    require(mailbox[2:7] == (0x340f8000, 0x340f8000, 0, 512, 6), 'mailbox')
    require(trace[2:7] == (0x340f8200, 0x340f8200, 0, 6556, 6), 'trace')
    require(all(s[2] + s[5] <= 0x34200000 for s in segments), 'weight/activation exclusion')
    require(struct.unpack_from('<2I', elf, code[1]) == (0x340f8000, h[4]), 'vectors')
    image = bytearray(data[2] + data[4] - code[2])
    for s in (code, data):
        image[s[2] - code[2]:s[2] - code[2] + s[4]] = elf[s[1]:s[1] + s[4]]
    require(bytes(image) == (OUT / 'n6_sram_trace.bin').read_bytes() and len(image) == 80268, 'ELF/BIN byte match')
    sections = [struct.unpack_from('<10I', elf, h[6] + i * 40) for i in range(h[12])]
    names = sections[h[13]]
    strings = elf[names[4]:names[4] + names[5]]
    selected = [s for s in sections if strings[s[0]:].split(b'\0', 1)[0] == b'.npu_trace']
    require(len(selected) == 1 and selected[0][1:4] == (8, 3, 0x340f8200) and
            selected[0][5] == 6556 and selected[0][8] == 32, 'trace NOBITS section')
    require(not any(s[1] in (4, 9) and s[5] for s in sections), 'runtime relocations')
    require((OUT / 'undefined.stdout').read_bytes() == b'', 'undefined symbols')
    symbols = (OUT / 'symbols.stdout').read_text()
    require(re.search(r'^340f8200 0000199c B g_npu_trace$', symbols, re.M), 'trace symbol size/address')
    objdump = Path('/home/thc1006/opt/arm-gnu-toolchain-13.2.Rel1-x86_64-arm-none-eabi/bin/arm-none-eabi-objdump')
    require(objdump in held, 'disassembler missing from original pins')
    proc = subprocess.run([str(objdump), '-d', str(OUT / 'n6_sram_trace.elf')],
                          capture_output=True, timeout=30, check=False,
                          env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'})
    require(proc.returncode == 0 and proc.stdout == (OUT / 'disassembly.stdout').read_bytes(), 'fresh disassembly mismatch')
    main_block = proc.stdout.decode().split('<main>:\n', 1)[1].split('\n\n', 1)[0]
    ordered = ('stai_nsl_qcfs_seed0_init', 'npu_trace_bind', 'npu_trace_begin',
               'stai_nsl_qcfs_seed0_run', 'npu_trace_finish', 'stai_nsl_qcfs_seed0_get_error')
    positions = []
    for name in ordered:
        found = list(re.finditer(r'\bbl\s+[0-9a-f]+ <' + name + '>', main_block))
        require(len(found) == 1, 'linked main call: ' + name)
        positions.append(found[0].start())
    require(positions == sorted(positions), 'linked call ordering')
    require(all(r[k] is False for k in ('board_ready', 'board_validated', 'hardware_executed',
                'energy_measured', 'independent_hardware_proof', 'performance_accepted',
                'compiler_semantic_parity_verified', 'original_generation_failure_reclassified')), 'scope claims')
    for p, expected in held.items():
        require(pin(p) == expected, 'final pin changed: ' + str(p))
    require({p.name for p in OUT.iterdir()} == namespace, 'late namespace')
    for p, expected in held.items():
        require(p == p.resolve() and all(getattr(p.stat(), k) == expected[k] for k in FIELDS), 'late stat')
    return dict(result_sha256=RESULT_SHA, input_pins=len(r['input_pins']),
                artifact_pins=len(r['artifacts_before_result']), original_child_exits_zero=67,
                independent_disassembler_exit=proc.returncode, elf_bin_equal=True,
                bin_bytes=len(image), trace_address=hex(trace[2]), trace_nobits_bytes=6556,
                main_linked_calls_in_order=list(ordered), source_sha256=held[Path(__file__).resolve()]['sha256'],
                board_executed=False, independent_npu_execution_proven=False, actual_process_exit=None)


if __name__ == '__main__':
    print(json.dumps(main(), sort_keys=True))
