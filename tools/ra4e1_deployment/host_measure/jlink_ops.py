"""J-Link (FPB-RA4E1 on-board J-Link OB, J9) operations for RM01, fully logged.

  backup  --out DIR          save code flash (512 KiB) + data flash (8 KiB), read-only
  flash   --out DIR [--build build_02]  program a pinned RM01 build, verify, reset, run
  readback --out DIR         save the RM01 result block (0x2001C000, 0x2100 B) from RAM
  restore --out DIR --image BIN   program a saved code-flash backup back (manual use)

Option-setting memory is never written (the RM01 image has no option section;
build.py refuses one). Each call writes the JLinkExe command file, its full
console output and sha256 of every produced file into DIR.
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
REPO = HERE.parents[2]
JLINK = '/usr/bin/JLinkExe'
DEVICE = 'R7FA4E10D'
JLINK_SERIAL = '000831033862'
FW = REPO / 'tools/ra4e1_deployment/firmware_measure'
# build_01 (DWT time base) is retired: DWT does not count on RA with SYOCDCR.DBGEN=0.
BUILDS = {
    'build_01': {'firmware.bin': '8bf01c103987c019f017fe907e7986c5c0cda1ef09af02ffcf02c1616f626ada',
                 'firmware.hex': '4fc0a643a23cb2ca93a1fc3b8b11a6ada46c51b4fe81ffb78b85a07c5026619b',
                 'firmware.elf': 'fdce1b50482aae7ec17396d79a98e94d39011ff2aff2f6da9bc9bb65557dcbb2'},
    'build_02': {'firmware.bin': 'd77f884b32bf8b394aec39e0f92b3f440dec8296896633220d56571400efd731',
                 'firmware.hex': 'f6d63550ea435d50f4a52fa4d20dd0e9650f4686afd6b94656572d7f52546e73',
                 'firmware.elf': '414c3c0f1812f6c94e4260915b0fc1c944e94f25458caabbc4860b4878cb5a19'},
    # build_03: calibration mirrors the schedule loops; per-boot clock snapshot (review 2026-09-29).
    'build_03': {'firmware.bin': '19532b807902eb39510adfb85358a5f92d14abe5919156c03ed2ce531f89cb7f',
                 'firmware.hex': '7f26d3d8870607cd919c3c5e1207f6023eb293e13b1f841b03f5ca1d640fcd16',
                 'firmware.elf': '1bfcf0d0b8332a6fe2307efdeae70da24c4c2d4a47080455bf0f2d9ec32dbf06'},
}
DEFAULT_BUILD = 'build_03'
RESULT_ADDRESS, RESULT_BYTES = 0x2001C000, 0x2100


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def jlink(out, name, lines, timeout=300):
    out.mkdir(parents=True, exist_ok=True)
    cmd = out / f'{name}.jlink'
    cmd.write_text('\n'.join(lines + ['exit']) + '\n')
    argv = [JLINK, '-NoGui', '1', '-USB', JLINK_SERIAL, '-device', DEVICE, '-if', 'SWD',
            '-speed', '4000', '-autoconnect', '1', '-ExitOnError', '1', '-CommandFile', str(cmd)]
    t0 = datetime.now(timezone.utc).isoformat()
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    (out / f'{name}.console.txt').write_text(p.stdout + p.stderr)
    rec = dict(argv=argv, returncode=p.returncode, started_utc=t0,
               finished_utc=datetime.now(timezone.utc).isoformat())
    (out / f'{name}.json').write_text(json.dumps(rec, indent=1) + '\n')
    text = p.stdout + p.stderr
    body = '\n'.join(l for l in text.splitlines() if 'will now exit on Error' not in l)
    bad = [w for w in ('ERROR', 'Error', 'failed', 'Could not', 'Cannot') if w in body]
    if p.returncode != 0 or bad:
        raise SystemExit(f'{name}: JLinkExe rc={p.returncode} flags={bad}; see {out / (name + ".console.txt")}')
    return text


def backup(out):
    code, data = out / 'code_flash_0x0_512KiB.bin', out / 'data_flash_0x08000000_8KiB.bin'
    for f in (code, data):
        if f.exists():
            raise SystemExit(f'refusing to overwrite {f}')
    jlink(out, 'backup', [f'savebin {code} 0x0 0x80000', f'savebin {data} 0x08000000 0x2000',
                          'mem32 0x0100A100 1', 'mem32 0x0100A180 1', 'mem32 0x0100A200 1',
                          'mem32 0x0100A280 1'])
    if code.stat().st_size != 0x80000 or data.stat().st_size != 0x2000:
        raise SystemExit('backup size mismatch')
    rec = {f.name: sha(f) for f in (code, data)}
    (out / 'backup_sha256.json').write_text(json.dumps(rec, indent=1) + '\n')
    return rec


def flash(out, build):
    pins = BUILDS[build]
    d = FW / build
    for n, want in pins.items():
        if sha(d / n) != want:
            raise SystemExit(f'build pin mismatch {n}')
    text = jlink(out, 'flash', ['r', 'h', f'loadfile {d / "firmware.hex"}',
                                f'verifybin {d / "firmware.bin"} 0x0', 'r', 'g'])
    if 'Verify successful' not in text:
        raise SystemExit('flash: no "Verify successful" in console; inspect flash.console.txt')
    return dict(build=build, pins=pins)


def readback(out, tag):
    f = out / f'rm01_result_{tag}.bin'
    if f.exists():
        raise SystemExit(f'refusing to overwrite {f}')
    jlink(out, f'readback_{tag}', [f'savebin {f} {RESULT_ADDRESS:#x} {RESULT_BYTES:#x}'])
    if f.stat().st_size != RESULT_BYTES:
        raise SystemExit('readback size mismatch')
    return dict(file=str(f), sha256=sha(f))


def restore(out, image):
    if Path(image).stat().st_size != 0x80000:
        raise SystemExit('restore image must be a full 512 KiB code-flash backup')
    jlink(out, 'restore', ['r', 'h', f'loadbin {image} 0x0', f'verifybin {image} 0x0', 'r', 'g'])
    return dict(image=str(image), sha256=sha(image))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('op', choices=('backup', 'flash', 'readback', 'restore'))
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--tag', default='01')
    ap.add_argument('--image', type=Path)
    ap.add_argument('--build', default=DEFAULT_BUILD, choices=sorted(BUILDS))
    a = ap.parse_args(argv)
    if not a.out.is_absolute():
        raise SystemExit('--out must be absolute')
    res = {'backup': lambda: backup(a.out), 'flash': lambda: flash(a.out, a.build),
           'readback': lambda: readback(a.out, a.tag), 'restore': lambda: restore(a.out, a.image)}[a.op]()
    print(json.dumps(dict(op=a.op, ok=True, **res), indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
