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
    # build_01 is retired (not reproducible: build date/time in the image; review M2).
    'build_02': {'em01.bin': '46a95057c1d371aa99c9166fe00437aeb5076254a4f7ea77a417531eb6c9a625',
                 'em01.elf': '1b296f551600ed76f62ccbcf5ecc61f647edaa4604b41515d7e8553b14c15273',
                 'bootloader/bootloader.bin': 'd5bb0adc4f16d93419b765c948e5bfb53978c905c508e0da21102f640dd7d513',
                 'partition_table/partition-table.bin': '7f00b6c042a89b15b0cac534f82ed988caf29278ff5700b0c511eb1b5bb7c820'},
    # build_03 = build_02 with the marker on GPIO5 (ESP Amendment 1); every other function byte-identical.
    'build_03': {'em01.bin': 'bcf2ca474778490a2e561f6d13ca10df1762c3623dc6d7cdef2a46248db7ccae',
                 'em01.elf': '2a244cc3cad10181e69336a6753a070b4f8f2750fb01e180f4785d088b774da6',
                 'bootloader/bootloader.bin': 'd5bb0adc4f16d93419b765c948e5bfb53978c905c508e0da21102f640dd7d513',
                 'partition_table/partition-table.bin': '7f00b6c042a89b15b0cac534f82ed988caf29278ff5700b0c511eb1b5bb7c820'},
    # build_04 = build_03 with ONE non-inlined IRAM busy-wait (ESP Amendment 2, review B1);
    # only em01.c.obj differs; portable_qdq/model/vectors objects byte-identical.
    'build_04': {'em01.bin': '1dea01cee5deb540d70418b54faa09b07e6c657ebfa184c0853dc8f60db299f1',
                 'em01.elf': '5a8c2233f9c7877c5692fc53979c3c3cae847662cc72e0e6c933aeb33fd66376',
                 'bootloader/bootloader.bin': 'd5bb0adc4f16d93419b765c948e5bfb53978c905c508e0da21102f640dd7d513',
                 'partition_table/partition-table.bin': '7f00b6c042a89b15b0cac534f82ed988caf29278ff5700b0c511eb1b5bb7c820'},
}
DEFAULT_BUILD = 'build_04'
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


def usb_info(port):
    """USB identity of the tty's device from sysfs (vendor, product, iSerial)."""
    try:
        d = (Path('/sys/class/tty') / Path(port).name / 'device').resolve().parent
        rd = lambda n: (d / n).read_text().strip() if (d / n).is_file() else None
        return dict(idVendor=rd('idVendor'), idProduct=rd('idProduct'), serial=rd('serial'),
                    product=rd('product'), sysfs=str(d))
    except OSError as exc:
        return dict(error=str(exc))


def identify(out, port):
    text = esptool(out, 'identify', port, ['--before', 'default_reset', '--after', 'no_reset', 'flash_id'])
    info = parse_identity(text)
    (out / 'identity.json').write_text(json.dumps(info, indent=1) + '\n')
    info['usb'] = usb_info(port)
    problems = []
    if not (info['chip'] or '').startswith('ESP32-S3'):
        problems.append(f"chip is {info['chip']}, expected ESP32-S3")
    if info['flash_size'] != '16MB':
        problems.append(f"flash size is {info['flash_size']}, expected 16MB (N16)")
    if 'PSRAM 8MB' not in (info['features'] or '') or 'AP_3v3' not in (info['features'] or ''):
        problems.append(f"features {info['features']!r} do not list 8MB PSRAM (AP_3v3) (R8)")
    if not (info['flash_type_efuse'] or 'quad').startswith('quad'):
        problems.append(f"flash type {info['flash_type_efuse']!r} is not quad (octal-flash modules cannot boot the DIO image)")
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
    # 'keep': esptool must not rewrite the bootloader header, so the flashed bytes
    # are exactly the pinned files (the header already says DIO/80m/16MB).
    text = esptool(out, 'flash', port, [
        '--before', 'default_reset', '--after', 'hard_reset', 'write_flash',
        '--flash_mode', 'keep', '--flash_size', 'keep', '--flash_freq', 'keep',
        '0x0', str(d / 'bootloader/bootloader.bin'), '0x8000', str(d / 'partition_table/partition-table.bin'),
        '0x10000', str(d / 'em01.bin')])
    verified = text.count('Hash of data verified')
    if verified != 3:
        raise SystemExit(f'expected 3 "Hash of data verified", got {verified}; see flash.console.txt')
    import re
    import shutil
    mac = next((m.group(1).strip().lower() for m in (re.match(r'^MAC: (.+)$', l.strip()) for l in text.splitlines()) if m), None)
    fw = out / 'firmware'
    fw.mkdir(exist_ok=True)
    for n in pins:                                   # keep the exact flashed files with the record
        shutil.copy2(d / n, fw / Path(n).name)
    shutil.copy2(FW / build / 'RESULT.json', fw / 'RESULT.json')
    rec = dict(build=build, pins=pins, regions_verified=verified, mac=mac, usb=usb_info(port))
    (out / 'flash_record.json').write_text(json.dumps(rec, indent=1) + '\n')
    return rec


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
