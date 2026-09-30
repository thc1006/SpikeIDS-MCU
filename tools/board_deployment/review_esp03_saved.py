"""Independent saved ESP03 review. No imports of the builder, USB or inference."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'results/esp32s3_v5_build_20260925_03'
RESULT_SHA = '672d89e8ebdd2c1ecf90cdec38d1215b7d0a3b418b5f9c820aa27a93e7c20622'
FIELDS = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
TC = Path('/home/thc1006/.espressif/tools/xtensa-esp-elf/esp-14.2.0_20260121/xtensa-esp-elf/bin')
FORCED = {'__cxx_fatal_exception', 'start_app', 'start_app_other_cores'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def pin(path):
    require(path.is_absolute() and path == path.resolve(), 'noncanonical ' + str(path))
    before = path.stat()
    require(stat.S_ISREG(before.st_mode), 'nonregular file')
    raw = path.read_bytes()
    after = path.stat()
    require(all(getattr(before, k) == getattr(after, k) for k in FIELDS), 'read changed')
    return dict(sha256=hashlib.sha256(raw).hexdigest(), **{k: getattr(before, k) for k in FIELDS})


def namespace():
    files, dirs = set(), []
    for base, children, names in os.walk(OUT, followlinks=False):
        for name in children:
            p = Path(base) / name
            require(p == p.resolve() and stat.S_ISDIR(p.lstat().st_mode), 'directory rebound')
            dirs.append(str(p.relative_to(OUT)))
        files.update(str((Path(base) / name).relative_to(OUT)) for name in names)
    return files, sorted(dirs)


def main():
    require(sys.flags.optimize == 0, 'optimized reviewer forbidden')
    report_pin = pin(OUT / 'RESULT.json')
    require(report_pin['sha256'] == RESULT_SHA, 'original RESULT commitment')
    r = json.loads((OUT / 'RESULT.json').read_bytes())
    held = {Path(p): value for p, value in r['input_pins'].items()}
    held.update({OUT / p: value for p, value in r['artifact_inventory']['files'].items()})
    held[OUT / 'RESULT.json'] = report_pin
    held[Path(__file__).resolve()] = pin(Path(__file__).resolve())
    require(len(r['commands']) == 9 and all(type(c['returncode']) is int and c['returncode'] == 0
            and c['timeout'] is False for c in r['commands']), 'actual child exits')
    expected_namespace = (set(r['artifact_inventory']['files']) | {'RESULT.json'},
                          r['artifact_inventory']['directories'])
    require(namespace() == expected_namespace, 'original namespace')
    for p, expected in held.items():
        require(pin(p) == expected, 'original pin ' + str(p))
    raw = (OUT / 'build/spikeids_v5_qdq.elf').read_bytes()
    require(raw[:7] == b'\x7fELF\x01\x01\x01', 'ELF format')
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', raw)
    require(h[1:4] == (2, 94, 1) and h[9] == 32 and h[10] == 8 and h[11] == 40, 'Xtensa executable')
    sections = [struct.unpack_from('<10I', raw, h[6] + i * 40) for i in range(h[12])]
    require(not any(s[1] in (4, 9) and s[5] for s in sections), 'relocations remain')
    strings_section = sections[h[13]]
    strings = raw[strings_section[4]:strings_section[4] + strings_section[5]]
    rtc = [s for s in sections if strings[s[0]:].split(b'\0', 1)[0] == b'.rtc_reserved']
    require(len(rtc) == 1 and (rtc[0][1], rtc[0][2], rtc[0][3], rtc[0][5], rtc[0][8]) ==
            (8, 3, 0x600fffe8, 24, 8), 'RTC reservation section')
    segments = [struct.unpack_from('<8I', raw, h[5] + i * 32) for i in range(h[10])]
    require(all(s[0] == 1 and s[4] <= s[5] and s[1] + s[4] <= len(raw) for s in segments), 'PT_LOAD bounds')
    rtc_segments = [s for s in segments if s[2] == 0x600fffe8]
    require(len(rtc_segments) == 1 and rtc_segments[0][2:7] ==
            (0x600fffe8, 0x600fffe8, 0, 24, 6), 'RTC payload not permitted')
    areas = ((0x3c000000, 0x3e000000), (0x42000000, 0x44000000),
             (0x3fc88000, 0x3fd00000), (0x40370000, 0x403e0000), (0x50000000, 0x50002000))
    require(all(s in rtc_segments or any(lo <= s[2] < s[2] + s[5] <= hi for lo, hi in areas)
                for s in segments), 'mapped/internal segments')
    require(any(s[6] & 1 and s[2] <= h[4] < s[2] + s[4] for s in segments), 'entry not executable')
    artifacts = r['artifact_inventory']['files']
    archives = sorted(OUT / n for n in artifacts if n.endswith('.a'))
    require(len(archives) == 48, 'archive count')
    tools = {'nm': TC / 'xtensa-esp32s3-elf-nm', 'readelf': TC / 'xtensa-esp32s3-elf-readelf'}
    for tool in tools.values():
        held[tool] = pin(tool)
    observations = {}
    for name, command in (
        ('undefined', [str(tools['nm']), '-u', str(OUT / 'build/spikeids_v5_qdq.elf')]),
        ('references', [str(tools['nm']), '-u', *map(str, archives)]),
        ('relocations', [str(tools['readelf']), '-r', str(OUT / 'build/spikeids_v5_qdq.elf')]),
    ):
        proc = subprocess.run(command, capture_output=True, timeout=30, check=False,
                              env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'})
        require(proc.returncode == 0, name + ' command failed')
        observations[name] = proc.stdout.decode()
    require(set(observations['undefined'].splitlines()) == {'         U ' + n for n in FORCED}, 'exact global forced UND')
    refs = {line.split()[-1] for line in observations['references'].splitlines() if re.match(r'^\s+[Uwv]\s+', line)}
    require(not refs & FORCED, 'archive reference to forced UND')
    require('There are no relocations in this file.' in observations['relocations'], 'readelf relocation corroboration')
    cmake_paths = [Path('/home/thc1006/esp/esp-idf/components') / p / 'CMakeLists.txt' for p in ('esp_system', 'cxx')]
    require(all(p in held for p in cmake_paths), 'SDK inputs omitted')
    cmakes = '\n'.join(p.read_text() for p in cmake_paths)
    for name in FORCED:
        require(re.search(r'^\s*target_link_libraries\(\$\{COMPONENT_LIB\} INTERFACE "-u ' + name + r'"\)\s*$', cmakes, re.M), 'SDK -u provenance')
    commands = json.loads((OUT / 'build/compile_commands.json').read_bytes())
    numeric = []
    for source in (ROOT / 'tools/board_deployment/portable_qdq/portable_qdq.c',
                   ROOT / 'tools/board_deployment/shared_v5/wire.c',
                   ROOT / 'results/portable_qdq_native_20260925_01/model_sources/model.c'):
        rows = [x for x in commands if x['file'] == str(source)]
        require(len(rows) == 1, 'exact source compile unit')
        argv = shlex.split(rows[0]['command'])
        require(argv[argv.index('-c') + 1] == str(source), 'actual compiler input')
        for flag in ('-fno-fast-math', '-ffp-contract=off', '-fexcess-precision=standard'):
            require(flag in argv, 'missing exact FP flag')
        require([v for v in argv if v.startswith('-std=')][-1:] == ['-std=c11'], 'effective C11')
        require([v for v in argv if re.fullmatch(r'-O(?:[0-3gsz]|fast)?', v)][-1:] == ['-O2'], 'effective O2')
        require(not any(v.startswith('@') for v in argv), 'unobserved response file')
        bad = {'-ffast-math', '-Ofast', '-funsafe-math-optimizations', '-ffinite-math-only',
               '-fassociative-math', '-freciprocal-math', '-fno-signed-zeros', '-fno-rounding-math'}
        require(not bad & set(argv), 'unsafe FP flag')
        require(all(v == '-ffp-contract=off' for v in argv if v.startswith('-ffp-contract=')) and
                all(v == '-fexcess-precision=standard' for v in argv if v.startswith('-fexcess-precision=')), 'FP override')
        numeric.append(source.name)
    config = set((OUT / 'build/sdkconfig').read_text().splitlines())
    require({'CONFIG_ESP_CONSOLE_NONE=y', 'CONFIG_ESP_CONSOLE_SECONDARY_NONE=y',
             'CONFIG_ESPTOOLPY_FLASHSIZE_4MB=y', 'CONFIG_ESP_MAIN_TASK_STACK_SIZE=8192'} <= config
            and 'CONFIG_SPIRAM=y' not in config, 'fixed config')
    require(r['hardware_accessed'] is False and r['target_parity_accepted'] is False and
            r['npu_execution_claimed'] is False, 'scope claims')
    require(r['model_sha256'] == '22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d' and
            r['vectors_sha256'] == 'cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb', 'model lineage')
    for p, expected in held.items():
        require(pin(p) == expected, 'final pin ' + str(p))
    require(namespace() == expected_namespace, 'late namespace')
    for p, expected in held.items():
        require(p == p.resolve() and all(getattr(p.stat(), k) == expected[k] for k in FIELDS), 'late stat')
    return dict(result_sha256=RESULT_SHA, input_pins=len(r['input_pins']), artifact_pins=len(artifacts),
                directories=len(expected_namespace[1]), original_child_exits_zero=9, reviewer_child_exits_zero=3,
                archives_checked=len(archives), exact_forced_undefined=sorted(FORCED), archive_references=[],
                runtime_relocations=0, exact_rtc_nobits_bytes=24, numeric_units=numeric,
                source_sha256=held[Path(__file__).resolve()]['sha256'], hardware_accessed=False,
                board_parity_accepted=False, actual_process_exit=None)


if __name__ == '__main__':
    print(json.dumps(main(), sort_keys=True))
