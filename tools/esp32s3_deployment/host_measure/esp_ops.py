"""esptool operations for EM01 on an ESP32-S3 N16R8 board, fully logged.

  identify --port P --out DIR           chip, MAC, flash id/size (read-only)
  backup   --port P --out DIR           read the whole 16 MiB flash (read-only; ~3 min)
  flash    --port P --out DIR [--build build_01]
                                        write bootloader/partitions/app from a pinned build,
                                        esptool verifies each region by hash, then hard reset
  restore  --port P --out DIR --image BIN   write a full-flash backup back (manual use)

Each call writes the exact argv, full console output and sha256 of produced
files into DIR. esptool comes from the ESP-IDF 5.4 Python environment.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
FW = HERE.parent / 'firmware_measure'
ESPTOOL = [str(Path.home() / '.espressif/python_env/idf5.4_py3.14_env/bin/python'), '-m', 'esptool']
BUILDS = {
    'build_01': {'em01.bin': '5d28723de1bd4452f25646aba30a3917fa0648b5ac610b06be5f53295e905a31',
                 'bootloader/bootloader.bin': '17fbdd9dede0ad3ca3d9195d789812b533ae29cd5f81411dc80310c25b5c04b6',
                 'partition_table/partition-table.bin': '7f00b6c042a89b15b0cac534f82ed988caf29278ff5700b0c511eb1b5bb7c820'},
}
DEFAULT_BUILD = 'build_01'
FLASH_BYTES = 16 * 1024 * 1024


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def esptool(out, name, port, args, timeout=900):
    out.mkdir(parents=True, exist_ok=True)
    argv = ESPTOOL + ['--chip', 'esp32s3', '--port', port, '--baud', '460800'] + args
    t0 = datetime.now(timezone.utc).isoformat()
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    text = p.stdout + p.stderr
    (out / f'{name}.console.txt').write_text(text)
    (out / f'{name}.json').write_text(json.dumps(dict(argv=argv, returncode=p.returncode, started_utc=t0,
                                                     finished_utc=datetime.now(timezone.utc).isoformat()),
                                                indent=1) + '\n')
    if p.returncode != 0:
        raise SystemExit(f'{name}: esptool rc={p.returncode}; see {out / (name + ".console.txt")}')
    return text


IDENTITY_PATTERNS = {             # esptool 4.x flash_id console lines ("Chip is"/"Crystal is" have no colon)
    'chip': r'^Chip is (.+)$', 'features': r'^Features: (.+)$', 'crystal': r'^Crystal is (.+)$',
    'usb_mode': r'^USB mode: (.+)$', 'mac': r'^MAC: (.+)$', 'flash_manufacturer': r'^Manufacturer: (.+)$',
    'flash_device': r'^Device: (.+)$', 'flash_size': r'^Detected flash size: (.+)$',
    'flash_type_efuse': r'^Flash type set in eFuse: (.+)$', 'flash_voltage_efuse': r'^Flash voltage set by eFuse to (.+)$',
}


def parse_identity(text):
    import re
    info = {}
    for key, pat in IDENTITY_PATTERNS.items():
        m = [re.match(pat, l.strip()) for l in text.splitlines()]
        vals = [x.group(1).strip() for x in m if x]
        info[key] = vals[0] if vals else None
    return info


def identify(out, port):
    text = esptool(out, 'identify', port, ['--before', 'default_reset', '--after', 'no_reset', 'flash_id'])
    info = parse_identity(text)
    (out / 'identity.json').write_text(json.dumps(info, indent=1) + '\n')
    problems = []
    if not (info['chip'] or '').startswith('ESP32-S3'):
        problems.append(f"chip is {info['chip']}, expected ESP32-S3")
    if info['flash_size'] != '16MB':
        problems.append(f"flash size is {info['flash_size']}, expected 16MB (N16)")
    if 'PSRAM 8MB' not in (info['features'] or ''):
        problems.append(f"features {info['features']!r} do not list 8MB PSRAM (R8)")
    if problems:
        raise SystemExit('identity check failed: ' + '; '.join(problems))
    return info


def backup(out, port):
    img = out / 'flash_backup_16MiB.bin'
    if img.exists():
        raise SystemExit(f'refusing to overwrite {img}')
    esptool(out, 'backup', port, ['--before', 'default_reset', '--after', 'no_reset',
                                  'read_flash', '0', hex(FLASH_BYTES), str(img)], timeout=1800)
    if img.stat().st_size != FLASH_BYTES:
        raise SystemExit('backup size mismatch')
    rec = {img.name: sha(img)}
    (out / 'backup_sha256.json').write_text(json.dumps(rec, indent=1) + '\n')
    return rec


def flash(out, port, build):
    d = FW / build / 'build'
    pins = BUILDS[build]
    for n, want in pins.items():
        if sha(d / n) != want:
            raise SystemExit(f'build pin mismatch {n}')
    text = esptool(out, 'flash', port, [
        '--before', 'default_reset', '--after', 'hard_reset', 'write_flash',
        '--flash_mode', 'dio', '--flash_size', '16MB', '--flash_freq', '80m',
        '0x0', str(d / 'bootloader/bootloader.bin'), '0x8000', str(d / 'partition_table/partition-table.bin'),
        '0x10000', str(d / 'em01.bin')])
    verified = text.count('Hash of data verified')
    if verified != 3:
        raise SystemExit(f'expected 3 "Hash of data verified", got {verified}; see flash.console.txt')
    return dict(build=build, pins=pins, regions_verified=verified)


def restore(out, port, image):
    if Path(image).stat().st_size != FLASH_BYTES:
        raise SystemExit('restore image must be a full 16 MiB backup')
    esptool(out, 'restore', port, ['--before', 'default_reset', '--after', 'hard_reset',
                                   'write_flash', '0x0', str(image)], timeout=1800)
    return dict(image=str(image), sha256=sha(image))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('op', choices=('identify', 'backup', 'flash', 'restore'))
    ap.add_argument('--port', required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--build', default=DEFAULT_BUILD, choices=sorted(BUILDS))
    ap.add_argument('--image', type=Path)
    a = ap.parse_args(argv)
    if not a.out.is_absolute():
        raise SystemExit('--out must be absolute')
    res = {'identify': lambda: identify(a.out, a.port), 'backup': lambda: backup(a.out, a.port),
           'flash': lambda: flash(a.out, a.port, a.build),
           'restore': lambda: restore(a.out, a.port, a.image)}[a.op]()
    print(json.dumps(dict(op=a.op, ok=True, result=res), indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
