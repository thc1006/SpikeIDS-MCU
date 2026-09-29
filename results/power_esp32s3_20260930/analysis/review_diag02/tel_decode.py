"""Reviewer's own telemetry decode (pulse width bits) + CRC + window-table cross-check."""
import json, zlib, struct
import numpy as np
from pathlib import Path
R = Path('/home/thc1006/dev/SpikeIDS-MCU/results/power_esp32s3_20260930')
w = np.fromfile(R / 'ppk_esp9/seg_000_diag_esp_02_01.u32le', dtype='<u4')
d0 = ((w >> 24) & 1).astype(np.int8); del w
d0[:250512] = 0
d = np.diff(np.concatenate(([0], d0, [0])))
a, b = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
wid = b - a
tel = wid[141:-1]
print('telemetry widths (samples) unique:', np.unique(tel, return_counts=True))
bits = (tel > 50).astype(np.uint64)
words = [int((bits[i*32:(i+1)*32] << np.arange(32, dtype=np.uint64)).sum()) for i in range(len(bits)//32)]
print('n words', len(words), 'magic', hex(words[0]), 'count', words[1])
crc_ok = zlib.crc32(b''.join(struct.pack('<I', x) for x in words[:-1])) == words[-1]
print('CRC ok', crc_ok)
hdr = words[2:66]
names = ['magic','version','struct_bytes','stage','error','error_detail','system_core_clock','psram_enabled','pq_env','chip_info','timer_ctrl','schedules_done','parity_mismatched_words','parity_first_bad_row','parity_outputs_fnv','parity_rows']
print({n: hdr[i] for i, n in enumerate(names)})
print('timer_id', hex(hdr[0xB8//4]), 'snapshot', hdr[0xD0//4:0x100//4], 'windows_used', hdr[0x8C//4], 'overhead_reps', hdr[0x60//4], 'bench_reps', hdr[0x5C//4], 'mult', hdr[0x90//4:0x90//4+8])
A = json.load(open(R / 'diag_esp_02_run/diag_esp_02_01_analysis.json'))
W = A['windows']; tw = words[66:-1]
bad = 0
for i, x in enumerate(W):
    k, s, e, it, ck = tw[5*i:5*i+5]
    if (k & 0xFF, (k >> 8) & 0xFF, k >> 16, s, e, it, ck) != (x['kind'], x['marker_high'], x['phase'], x['start_cycle'], x['end_cycle'], x['iterations'], x['checksum']):
        bad += 1
print('window table rows', len(tw)//5, 'mismatches vs pipeline JSON', bad)
# HIGH-run count vs firmware HIGH windows, and D0 run vs CCOUNT order
print('runs before sync', 140, 'fw high', sum(x['marker_high'] for x in W), 'sync width', wid[140])
