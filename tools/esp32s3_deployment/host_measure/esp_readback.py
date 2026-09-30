"""Read the EM01 result block from ESP32-S3 RAM over the built-in USB-Serial/JTAG.

Bring-up only (board powered from its native USB port, PPK2 VOUT disconnected):
the ESP analogue of the RA4E1 J-Link readback. OpenOCD attaches through the
native USB port, halts the cores (after DONE this changes nothing measured),
dumps g_rm (address/size from the pinned build ELF) and resumes.

usage: .venv/bin/python esp_readback.py --out DIR [--build build_01] [--tag T]
Prints the decoded header (same parser as the telemetry decoder).
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / 'tools/ra4e1_deployment/host_measure'))
sys.path.insert(0, str(HERE))
import esp_ops  # noqa: E402
import rm01_decode as rd  # noqa: E402

OPENOCD_DIR = sorted((Path.home() / '.espressif/tools/openocd-esp32').glob('*/openocd-esp32'))[-1]
OPENOCD = OPENOCD_DIR / 'bin/openocd'
SCRIPTS = OPENOCD_DIR / 'share/openocd/scripts'


def g_rm_location(build):
    res = json.loads((esp_ops.FW / build / 'RESULT.json').read_text())
    addr, size = res['symbols']['g_rm']
    return int(addr, 16), int(size)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--build', default=esp_ops.DEFAULT_BUILD, choices=sorted(esp_ops.BUILDS))
    ap.add_argument('--tag', default='01')
    a = ap.parse_args(argv)
    if not a.out.is_absolute():
        raise SystemExit('--out must be absolute')
    a.out.mkdir(parents=True, exist_ok=True)
    addr, size = g_rm_location(a.build)
    if size != 0x2100:
        raise SystemExit(f'unexpected g_rm size {size}')
    img = a.out / f'em01_result_{a.tag}.bin'
    if img.exists():
        raise SystemExit(f'refusing to overwrite {img}')
    argv_ = [str(OPENOCD), '-s', str(SCRIPTS), '-f', 'board/esp32s3-builtin.cfg',
             '-c', f'init; halt; dump_image {img} {addr:#x} {size:#x}; resume; shutdown']
    p = subprocess.run(argv_, capture_output=True, text=True, timeout=120)
    (a.out / f'readback_{a.tag}.console.txt').write_text(p.stdout + p.stderr)
    (a.out / f'readback_{a.tag}.json').write_text(json.dumps(dict(argv=argv_, returncode=p.returncode), indent=1) + '\n')
    if p.returncode != 0 or not img.exists() or img.stat().st_size != size:
        raise SystemExit(f'OpenOCD readback failed (rc={p.returncode}); see readback_{a.tag}.console.txt')
    raw = img.read_bytes()
    words = list(struct.unpack(f'<{len(raw) // 4}I', raw))
    h = rd.parse_header(words[:rd.HEADER_WORDS])
    problems = rd.header_problems(dict(h, stage_name='TELEMETRY') if h['stage_name'] == 'DONE' else h)
    summary = {k: h.get(k) for k in ('platform', 'stage_name', 'error', 'error_detail', 'pq_env', 'parity_rows',
                                      'parity_mismatched_words', 'parity_first_bad_row', 'schedules_done',
                                      'bench_reps', 'overhead_reps', 'windows_used', 'system_core_clock')}
    summary.update(parity_outputs_fnv=hex(h['parity_outputs_fnv']), clock_snapshot=h['clock_snapshot'],
                   header_problems=problems, sha256=hashlib.sha256(raw).hexdigest(), file=str(img))
    (a.out / f'readback_{a.tag}_decoded.json').write_text(json.dumps(summary, indent=1) + '\n')
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
