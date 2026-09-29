"""Object-level identity: SM07M build vs accepted SM06 build.

All objects except main.c must disassemble (with relocations) identically; in
main.c's object every function that also exists in SM06 must be identical,
except main itself and the runtime-init wrapper that is no longer inlined."""
import os
from pathlib import Path
import re
import subprocess
import unittest

HERE = Path(__file__).resolve().parent
SM06 = HERE.parent / 'firmware_sram_accum24_route/build_actual_01'
SM07 = Path(os.environ.get('SM07M_BUILD', HERE / 'build_03'))
OBJDUMP = '/home/thc1006/opt/arm-gnu-toolchain-13.2.Rel1-x86_64-arm-none-eabi/bin/arm-none-eabi-objdump'
MAIN_OBJECT = 'object_01.o'          # sources[1] == HERE/main.c in the pinned builder
EXEMPT = {'main', 's6_sm06_main_replaced', 'initialize_runtime_then_model'}


def dump(path):
    out = subprocess.run([OBJDUMP, '-d', '-r', str(path)], capture_output=True, text=True, check=True).stdout
    return out.split('\n', 3)[3]          # drop the header that names the file


def functions(text):
    blocks, name = {}, None
    for line in text.splitlines():
        m = re.match(r'^[0-9a-f]+ <(.+)>:$', line)
        if m:
            name = m.group(1); blocks[name] = []
        elif line.startswith('Disassembly of section'):
            name = None                   # section banner, not function body
        elif name and line.strip():
            blocks[name].append(re.sub(r'^\s*[0-9a-f]+:\s*', '', line))   # drop section offsets
    return blocks


def sections(path):
    """Full contents of every non-debug section (objdump -s), header dropped."""
    out = subprocess.run([OBJDUMP, '-s', str(path)], capture_output=True, text=True, check=True).stdout
    keep, cur = {}, None
    for line in out.split('\n', 3)[3].splitlines():
        m = re.match(r'^Contents of section (\S+):$', line)
        if m:
            cur = m.group(1); keep[cur] = [] if not cur.startswith(('.debug', '.comment', '.ARM.attributes')) else None
        elif cur and keep[cur] is not None:
            keep[cur].append(line)
    return {k: v for k, v in keep.items() if v is not None}


class ObjectIdentity(unittest.TestCase):
    def test_non_main_object_data_identical_except_build_date(self):
        # object_04 (stai_nsl_qcfs_seed0.c) embeds __DATE__/__TIME__ in get_info; nothing else may differ.
        for name in sorted(p.name for p in SM06.glob('object_*.o')):
            if name == MAIN_OBJECT:
                continue
            old, new = sections(SM06 / name), sections(SM07 / name)
            with self.subTest(obj=name):
                self.assertEqual(sorted(old), sorted(new))
                diff = [k for k in old if old[k] != new[k]]
                if name == 'object_04.o':
                    self.assertLessEqual(len(diff), 1, diff)
                    for k in diff:
                        self.assertTrue(k.startswith('.rodata'), k)
                        changed = [(a, b) for a, b in zip(old[k], new[k]) if a != b]
                        self.assertLessEqual(len(changed), 3, changed)   # date/time bytes only
                else:
                    self.assertEqual(diff, [])

    def test_non_main_objects_identical(self):
        objs = sorted(p.name for p in SM06.glob('object_*.o'))
        self.assertEqual(objs, sorted(p.name for p in SM07.glob('object_*.o')))
        self.assertEqual(len(objs), 23)
        for name in objs:
            if name == MAIN_OBJECT:
                continue
            with self.subTest(obj=name):
                self.assertEqual(dump(SM06 / name), dump(SM07 / name))

    def test_main_object_shared_functions_identical(self):
        old, new = functions(dump(SM06 / MAIN_OBJECT)), functions(dump(SM07 / MAIN_OBJECT))
        shared = (set(old) & set(new)) - EXEMPT
        self.assertGreaterEqual(len(shared), 15)
        for fn in sorted(shared):
            with self.subTest(fn=fn):
                self.assertEqual(old[fn], new[fn])
        self.assertFalse((set(old) - set(new)) - EXEMPT, 'SM06 function missing from SM07M')


if __name__ == '__main__':
    unittest.main()
