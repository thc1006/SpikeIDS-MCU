"""Reviewer: per-function, address-insensitive comparison of build_02 vs build_03 em01.elf."""
import re, subprocess, sys, json, collections
OBJ = '/home/thc1006/.espressif/tools/xtensa-esp-elf/esp-14.2.0_20260121/xtensa-esp-elf/bin/xtensa-esp32s3-elf-objdump'
FW = '/home/thc1006/dev/SpikeIDS-MCU/tools/esp32s3_deployment/firmware_measure'
def funcs(elf):
    out = subprocess.run([OBJ, '-d', '--no-show-raw-insn', elf], capture_output=True, text=True, check=True).stdout
    f, cur = collections.OrderedDict(), None
    for l in out.splitlines():
        m = re.match(r'^([0-9a-f]{8}) <(.+)>:$', l)
        if m:
            cur = m.group(2); f.setdefault(cur, []); continue
        m = re.match(r'^\s*[0-9a-f]+:\s+(\S+)\s*(.*)$', l)
        if m and cur:
            op, arg = m.group(1), m.group(2)
            arg = re.sub(r'\b[0-9a-f]{8}\b', 'ADDR', arg)            # absolute addresses
            arg = re.sub(r'<[^>]*\+0x[0-9a-f]+>', '<SYM+OFF>', arg)   # symbol+offset
            f[cur].append(f'{op} {arg}'.strip())
    return f
a, b = funcs(f'{FW}/build_02/build/em01.elf'), funcs(f'{FW}/build_03/build/em01.elf')
res = dict(n_funcs_02=len(a), n_funcs_03=len(b), only_02=sorted(set(a) - set(b)), only_03=sorted(set(b) - set(a)), differing={})
for k in a:
    if k in b and a[k] != b[k]:
        import difflib
        d = [x for x in difflib.unified_diff(a[k], b[k], lineterm='', n=0) if not x.startswith(('---', '+++', '@@'))]
        res['differing'][k] = dict(len02=len(a[k]), len03=len(b[k]), diff=d[:40])
json.dump(res, open('disasm_compare.json', 'w'), indent=1)
print('funcs', res['n_funcs_02'], res['n_funcs_03'], 'only02', res['only_02'], 'only03', res['only_03'])
for k, v in res['differing'].items():
    print('==', k, v['len02'], v['len03']); print('\n'.join('   ' + x for x in v['diff']))
