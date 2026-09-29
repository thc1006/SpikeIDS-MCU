"""Build EM01 (ESP32-S3 N16R8) into a fresh directory with ESP-IDF 5.4.

Steps: verify pinned inputs; require em01.c == derive(rm01.c); generate the
embedded vectors (same generator as RM01, include switched to em01.h); run
idf.py with an out-of-tree build dir and sdkconfig; check the resolved config
and the result block; record sha256 of every artifact. Never touches hardware.

usage: .venv/bin/python build.py --output-dir <fresh absolute dir>
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location('rm01_build', REPO / 'tools/ra4e1_deployment/firmware_measure/build.py')
rm_build = importlib.util.module_from_spec(_spec)   # RM01 vector generator and pins (loaded by path:
_spec.loader.exec_module(rm_build)                  # this file is also named build.py)
import derive_em01  # noqa: E402

IDF = Path('/home/thc1006/esp/esp-idf')
NM = Path('/home/thc1006/.espressif/tools/xtensa-esp-elf/esp-14.2.0_20260121/xtensa-esp-elf/bin/xtensa-esp-elf-nm')
PINS = {k: v for k, v in rm_build.PINS.items() if 'ra4e1_v5_build' not in str(k)}   # npz, onnx, model.c
REQUIRED_CONFIG = {
    'CONFIG_IDF_TARGET': '"esp32s3"', 'CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ': '240',
    'CONFIG_ESPTOOLPY_FLASHSIZE': '"16MB"', 'CONFIG_ESP_CONSOLE_NONE': 'y', 'CONFIG_FREERTOS_HZ': '100',
}
FORBIDDEN_CONFIG = ('CONFIG_SPIRAM=y', 'CONFIG_PM_ENABLE=y', 'CONFIG_ESP_TASK_WDT_EN=y',
                    'CONFIG_BT_ENABLED=y')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def require(ok, msg):
    if not ok:
        raise SystemExit('BUILD REFUSED: ' + msg)


def run(argv, out, name, env=None, cwd=None):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=1800, env=env, cwd=cwd)
    (out / f'{name}.stdout').write_text(p.stdout)
    (out / f'{name}.stderr').write_text(p.stderr)
    (out / f'{name}.json').write_text(json.dumps(dict(argv=argv, returncode=p.returncode), indent=1) + '\n')
    require(p.returncode == 0, f'{name} failed (see {out / (name + ".stderr")}): {p.stderr[-1500:]}')
    return p.stdout


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--output-dir', type=Path, required=True)
    a = ap.parse_args(argv)
    out = a.output_dir
    require(out.is_absolute() and not os.path.lexists(out), 'use a fresh absolute --output-dir')
    for p, want in PINS.items():
        require(sha(p) == want, f'pin mismatch {p}')
    require((HERE / 'em01.c').read_text() == derive_em01.derive(derive_em01.RM01.read_text()),
            'em01.c is not derive(rm01.c); run derive_em01.py')
    out.mkdir(parents=True)
    text, vec = rm_build.vectors_c(rm_build.BUNDLE / 'validation_vectors.npz')
    text = text.replace('#include "rm01.h"', '#include "em01.h"', 1)
    gen = HERE / 'main/generated/rm_vectors.c'
    gen.parent.mkdir(exist_ok=True)
    gen.write_text(text)
    (out / 'rm_vectors.c').write_text(text)

    build = out / 'build'
    cmd = (f'. {IDF}/export.sh >/dev/null 2>&1 && idf.py --version && '
           f'idf.py -C {HERE} -B {build} -D SDKCONFIG={out / "sdkconfig"} '
           f'-D SDKCONFIG_DEFAULTS={HERE / "sdkconfig.defaults"} build')
    env = {k: v for k, v in os.environ.items() if k in ('HOME', 'USER', 'LANG', 'LC_ALL', 'TERM')}
    env['PATH'] = '/usr/bin:/bin'
    env['IDF_PATH'] = str(IDF)
    log = run(['bash', '-c', cmd], out, 'idf_build', env=env)
    idf_version = log.splitlines()[0] if log else ''

    cfg = (out / 'sdkconfig').read_text()
    kv = dict(l.split('=', 1) for l in cfg.splitlines() if l.startswith('CONFIG_') and '=' in l)
    for k, v in REQUIRED_CONFIG.items():
        require(kv.get(k) == v, f'sdkconfig {k}={kv.get(k)} (want {v})')
    for bad in FORBIDDEN_CONFIG:
        require(bad not in cfg.splitlines(), f'sdkconfig has {bad}')

    elf = build / 'em01.elf'
    nm = run([str(NM), '-S', str(elf)], out, 'symbols')
    syms = {f[3]: (int(f[0], 16), int(f[1], 16)) for f in (l.split() for l in nm.splitlines()) if len(f) == 4}
    require(syms.get('g_rm', (0, 0))[1] == 0x2100, f"g_rm size {syms.get('g_rm')}")
    require(syms['rm_inputs'][1] == 1024 * 41 * 4 and syms['rm_expected'][1] == 1024 * 5 * 4, 'vector sizes')
    arts = {n: build / n for n in ('em01.bin', 'em01.elf', 'bootloader/bootloader.bin',
                                     'partition_table/partition-table.bin', 'flasher_args.json')}
    result = dict(
        schema='em01-build-v1', firmware='EM01 (RM01 logic, ESP32-S3 port)', board='ESP32-S3 N16R8 (module)',
        marker='GPIO4', time_base='Xtensa CCOUNT at CPU clock (240 MHz)', idf=idf_version,
        pins={str(k): v for k, v in PINS.items()},
        derived_from={'rm01.c': sha(derive_em01.RM01), 'derive_em01.py': sha(HERE / 'derive_em01.py')},
        sources_sha256={str(p): sha(p) for p in [HERE / 'em01.c', HERE / 'em01.h', HERE / 'em01_port.h',
                                                 HERE / 'main/app_main.c', HERE / 'main/CMakeLists.txt',
                                                 HERE / 'CMakeLists.txt', HERE / 'sdkconfig.defaults',
                                                 Path(__file__).resolve()]},
        vectors=vec, sdkconfig_sha256=sha(out / 'sdkconfig'),
        sha256={n: sha(p) for n, p in arts.items()}, app_bytes=(build / 'em01.bin').stat().st_size,
        symbols={k: [hex(v[0]), v[1]] for k, v in syms.items() if k in ('g_rm', 'rm_inputs', 'rm_expected', 'hal_entry')},
        hardware_accessed=False)
    (out / 'RESULT.json').write_text(json.dumps(result, indent=1) + '\n')
    print(json.dumps(dict(ok=True, out=str(out), app_bytes=result['app_bytes'], **result['sha256']), indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
