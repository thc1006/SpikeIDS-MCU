"""Independent saved-build/target-source checks, not ARM execution or emulation.

No compiler, hardware driver, target loader or author build helper is imported.
Negative ELF controls mutate memory copies only. Host protocol negatives belong
to the other independent reviewer; only ABI cross-mapping is checked here.
"""
import ast
import hashlib
import importlib.util
import json
import re
import stat
import struct
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / 'build_actual_01'
STAT_KEYS = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size',
             'st_mtime_ns', 'st_ctime_ns')


def strict(raw):
    def pairs(items):
        answer = {}
        for k, v in items:
            if k in answer:
                raise ValueError('duplicate key')
            answer[k] = v
        return answer
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))


def encoding(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def current_pin(p):
    assert p.is_absolute() and p.resolve() == p
    a = p.lstat()
    # Installed GNU tools legitimately have hardlinks. Preserve their original
    # recorded link count; do not invent a single-link input contract.
    assert stat.S_ISREG(a.st_mode)
    raw = p.read_bytes()
    b = p.lstat()
    assert all(getattr(a, k) == getattr(b, k) for k in STAT_KEYS)
    return {**{k: getattr(a, k) for k in STAT_KEYS},
            'sha256': hashlib.sha256(raw).hexdigest()}


def assembly(source, function):
    body = re.search(r'void ' + function + r'\(void\)\s*\{(.*?)\n\}', source, re.S).group(1)
    return ''.join(ast.literal_eval(s) for s in re.findall(r'"(?:[^"\\]|\\.)*"', body))


def elf(raw):
    """Small independent ELF reader for this one declared three-segment image."""
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', raw)
    assert h[0][:7] == b'\x7fELF\x01\x01\x01'
    assert h[1:4] == (2, 40, 1) and h[8:10] == (52, 32)
    assert h[10] == 3 and h[11] == 40
    ps = [struct.unpack_from('<8I', raw, h[5] + i * 32) for i in range(h[10])]
    for p in ps:
        assert p[0] == 1 and p[2] == p[3] and p[4] <= p[5]
        assert p[1] + p[4] <= len(raw)
    code, stack, mailbox = ps
    assert code[2] == 0x34180400 and code[6] == 5
    assert 64 <= code[4] == code[5] <= 0x3C00
    assert stack[2:7] == (0x34184000, 0x34184000, 0, 0x1000, 6)
    assert mailbox[2:7] == (0x34185000, 0x34185000, 0, 0x100, 6)
    assert h[4] & 1 and code[2] <= h[4] - 1 < code[2] + code[4]
    vectors = struct.unpack_from('<16I', raw, code[1])
    assert vectors[:2] == (0x34185000, h[4])
    for i, p in enumerate(vectors[2:], 2):
        if i in (8, 9, 10, 13):
            assert p == 0
        else:
            assert p & 1 and code[2] <= p - 1 < code[2] + code[4]
    sh = [struct.unpack_from('<10I', raw, h[6] + i * h[11]) for i in range(h[12])]
    names_section = sh[h[13]]
    strings = raw[names_section[4]:names_section[4] + names_section[5]]
    names = [strings[s[0]:].split(b'\0', 1)[0].decode() for s in sh]
    sections = dict(zip(names, sh))
    syms = {}
    for s in sh:
        assert s[1] not in (4, 9) or s[5] == 0  # No runtime relocations.
        if s[1] == 2:
            table = sh[s[6]]
            names_raw = raw[table[4]:table[4] + table[5]]
            assert s[9] == 16
            for off in range(s[4], s[4] + s[5], 16):
                name, value, size, info, other, index = struct.unpack_from('<IIIBBH', raw, off)
                label = names_raw[name:].split(b'\0', 1)[0].decode()
                if label:
                    syms[label] = (value, size, info, other, index)
                    assert index != 0, 'Unresolved symbol ' + label
    return h, ps, sections, syms, vectors


class PlatformProbeIndependent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {n: (HERE / n).read_text() for n in
                       ('startup.c', 'main.c', 'mailbox.h', 'linker.ld', 'build.py')}
        cls.abi = strict((HERE / 'ABI.json').read_bytes())
        cls.report = strict((BUILD / 'RESULT.json').read_bytes())
        cls.raw = (BUILD / 'probe.elf').read_bytes()
        cls.image = elf(cls.raw)
        cls.disasm = (BUILD / 'disassembly.stdout').read_text()
        cls.held = dict(cls.report['input_pins'])
        cls.held.update({str(BUILD / n): p for n, p in cls.report['artifacts_before_result'].items()})
        cls.held[str(BUILD / 'RESULT.json')] = current_pin(BUILD / 'RESULT.json')
        cls.held[str(Path(__file__).resolve())] = current_pin(Path(__file__).resolve())
        cls.held[str(HERE / 'host_protocol.py')] = current_pin(HERE / 'host_protocol.py')
        for name, expected in cls.held.items():
            assert current_pin(Path(name)) == expected, name

    @classmethod
    def tearDownClass(cls):
        for name, expected in cls.held.items():
            assert current_pin(Path(name)) == expected, name

    def test_abi_field_layout_and_ownership(self):
        a = self.abi
        self.assertEqual(a['struct_bytes'], 256)
        self.assertEqual([f['offset'] for f in a['fields'][:-1]], list(range(0, 128, 4)))
        self.assertEqual(a['fields'][-1]['type'], 'uint32[32]')
        self.assertEqual(a['fields'][-1]['offset'], 128)
        self.assertEqual([f['name'] for f in a['fields'] if f['owner'] == 'host'], ['host_nonce'])
        self.assertIn('initialization', a['publication'])
        self.assertEqual(a['cache_enable_mask'], 0x30000)

    def test_ram_ranges_and_original_v5_disjoint(self):
        a = self.abi
        ranges = [(a['code_start'], a['code_end_exclusive']),
                  (a['stack_start'], a['stack_top']),
                  (a['mailbox_address'], a['mailbox_end_exclusive'])]
        self.assertEqual(ranges, [(0x34180400, 0x34184000), (0x34184000, 0x34185000),
                                  (0x34185000, 0x34185100)])
        for start, stop in ranges:
            self.assertTrue(0x34180400 <= start < stop <= 0x34200000)
            for lo, hi in [(0x34064000, 0x34100000), (0x342e0000, 0x342e0800),
                           (0x71000000, 0x71023840)]:
                self.assertTrue(stop <= lo or start >= hi)

    def test_header_fields_equal_data_manifest(self):
        body = re.search(r'typedef struct\s*\{(.*?)\}', self.sources['mailbox.h'], re.S).group(1)
        fields = []
        for declaration in body.split(';'):
            if not declaration.strip():
                continue
            prefix, names = declaration.strip().split(None, 1)
            self.assertEqual(prefix, 'uint32_t')
            fields.extend(n.strip() for n in names.split(','))
        self.assertEqual(fields, [f['name'] + ('[32]' if f['name'] == 'reserved' else '')
                                  for f in self.abi['fields']])
        self.assertIn('volatile probe_mailbox_t g_mailbox', self.sources['main.c'])

    def test_host_constants_match_target_abi(self):
        spec = importlib.util.spec_from_file_location('probe_host_cross_only', HERE / 'host_protocol.py')
        host = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(host)
        self.assertEqual((host.ADDRESS, host.SIZE, host.MAGIC, host.VECTOR),
                         (self.abi['mailbox_address'], 256, self.abi['magic'], self.abi['vector_address']))
        self.assertEqual(list(host.FIELDS), [f['name'] for f in self.abi['fields'][:-1]])

    def test_entry_rejects_before_core_memory_or_c(self):
        a = assembly(self.sources['startup.c'], 'Reset_Handler')
        self.assertLess(a.index('tst r1,#3'), a.index('ldr r4,=0xe000ed08'))
        self.assertLess(a.index('mrs r5,ipsr'), a.index('cpsid i'))
        self.assertEqual(a.count('bne 1f'), 2)
        self.assertNotRegex(a, r'\b(push|pop|bl|blx)\b')
        self.assertLess(a.index('msr msp'), a.index('b probe_main'))

    def test_reset_core_write_allowlist_and_no_control_repair(self):
        a = assembly(self.sources['startup.c'], 'Reset_Handler')
        self.assertEqual(re.findall(r'\bmsr\s+(\w+)', a), ['msplim', 'msp'])
        self.assertEqual(re.findall(r'\bstr\s+([^\n]+)', a), ['r5,[r4]'])
        self.assertNotRegex(a, r'\bcpsie\b|0xe000ed88')
        self.assertIn('str r5,[r4]\n dsb\n isb', a)

    def test_fault_handler_never_dereferences_exception_stack(self):
        a = assembly(self.sources['startup.c'], 'fault_handler')
        self.assertNotRegex(a, r'\b(push|pop|bl|blx|msr)\b|\[(?:sp|msp|psp)\b')
        self.assertIn('mrs r2,msp', a)
        self.assertIn('mrs r2,psp', a)
        self.assertEqual(set(re.findall(r'\bstr\s+\w+,\[(\w+)', a)), {'r0'})
        self.assertIn('ldr r0,=g_mailbox', a)
        self.assertIn('str lr,[r0,#108]', a)

    def test_fault_publication_interrupted_odd_and_wrap(self):
        a = assembly(self.sources['startup.c'], 'fault_handler')
        normalized = '\n'.join(line.strip() for line in a.splitlines())
        self.assertIn('orr r1,r1,#1\nstr r1,[r0,#16]\ndmb', normalized)
        self.assertEqual(a.count('dmb'), 2)
        for old in [0, 1, 2, 3, 0xfffffffe, 0xffffffff]:
            odd = old | 1
            committed = (odd + 1) & 0xffffffff
            self.assertEqual(odd & 1, 1)
            self.assertEqual(committed & 1, 0)

    def test_main_initializes_all_words_and_never_claims_platform_ready(self):
        c = self.sources['main.c']
        self.assertIn('i<64u; ++i) words[i]=0u', c)
        self.assertIn('SCB_CCR_DC_Msk|SCB_CCR_IC_Msk', c)
        self.assertNotRegex(c, r'g_mailbox\.platform_initialized\s*=\s*[1-9]')
        self.assertEqual(re.findall(r'SCB->\w+\s*=', c), [])
        self.assertNotRegex(c, r'\b(?:HAL_\w+|SystemInit|memset|memcpy|malloc)\s*\(')
        self.assertIn('g_mailbox.sequence = odd;\n    __DMB();', c)
        self.assertIn('__DMB();\n    g_mailbox.sequence = odd + 1u;', c)

    def test_saved_result_seal_scope_and_actual_command_results(self):
        r = dict(self.report)
        seal = r.pop('content_sha256')
        self.assertEqual(hashlib.sha256(encoding(r)).hexdigest(), seal)
        self.assertEqual(r['abi'], self.abi)
        self.assertIsNone(r['actual_process_exit'])
        self.assertIs(r['compile_link_succeeded'], True)
        for key in ('hardware_executed', 'ram_access_verified', 'platform_initialized',
                    'board_ready', 'inference_performed', 'energy_measured'):
            self.assertIs(r[key], False)
        for call in r['calls']:
            self.assertIs(type(call['actual_return_code']), int)
            self.assertEqual(call['actual_return_code'], 0)
            self.assertIs(call['timed_out'], False)

    def test_original_inputs_artifacts_and_exact_namespace(self):
        expected = set(self.report['artifacts_before_result']) | {'RESULT.json'}
        self.assertEqual(set(p.name for p in BUILD.iterdir()), expected)
        self.assertNotIn('FAILED.json', expected)
        compiled = strict((BUILD / 'COMPILE_INPUTS.json').read_bytes())
        self.assertEqual(compiled, self.report['input_pins'])
        for call in self.report['calls']:
            exe = str(Path(call['argv'][0]).resolve())
            self.assertIn(exe, compiled)

    def test_elf_vectors_and_only_three_functions(self):
        h, ps, sections, syms, vectors = self.image
        self.assertEqual(vectors[1], syms['Reset_Handler'][0])
        self.assertEqual(set(v for i, v in enumerate(vectors) if i not in (0, 1, 8, 9, 10, 13)),
                         {syms['fault_handler'][0]})
        self.assertEqual(syms['g_mailbox'][:2], (0x34185000, 256))
        self.assertEqual({n for n, s in syms.items() if s[2] & 15 == 2},
                         {'Reset_Handler', 'fault_handler', 'probe_main'})
        self.assertEqual(sections['.stack'][1], 8)
        self.assertEqual(sections['.mailbox'][1], 8)

    def test_bin_is_exact_initialized_segment(self):
        code = self.image[1][0]
        self.assertEqual((BUILD / 'probe.bin').read_bytes(), self.raw[code[1]:code[1] + code[4]])
        self.assertEqual(len((BUILD / 'probe.bin').read_bytes()), 472)

    def test_negative_elf_header_and_entry_in_memory(self):
        for offset, fmt, value in [(4, '<B', 2), (5, '<B', 2), (18, '<H', 62),
                                   (24, '<I', self.image[0][4] & ~1), (24, '<I', 0x71000001)]:
            raw = bytearray(self.raw)
            struct.pack_into(fmt, raw, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(AssertionError):
                elf(raw)

    def test_negative_elf_ram_alias_and_permissions_in_memory(self):
        phoff = self.image[0][5]
        for off, value in [(phoff + 24, 7), (phoff + 32 + 8, 0x340f0000),
                           (phoff + 64 + 8, 0x342e0000), (phoff + 64 + 20, 512)]:
            raw = bytearray(self.raw)
            struct.pack_into('<I', raw, off, value)
            with self.subTest(offset=off), self.assertRaises(AssertionError):
                elf(raw)

    def test_negative_vector_msp_and_fault_pointer_in_memory(self):
        off = self.image[1][0][1]
        for at, value in [(off, 0x340f8000), (off + 8, 0x71000001), (off + 12, 0)]:
            raw = bytearray(self.raw)
            struct.pack_into('<I', raw, at, value)
            with self.subTest(offset=at), self.assertRaises(AssertionError):
                elf(raw)

    def test_disassembly_bytes_match_actual_elf(self):
        code = self.image[1][0]
        checked = 0
        for line in self.disasm.splitlines():
            m = re.match(r'^([0-9a-f]{8}):\s+([0-9a-f]{4}(?: [0-9a-f]{4})?)\s+\S', line)
            if not m:
                continue
            at = int(m[1], 16) - code[2] + code[1]
            b = b''.join(struct.pack('<H', int(x, 16)) for x in m[2].split())
            self.assertEqual(self.raw[at:at + len(b)], b)
            checked += 1
        self.assertGreater(checked, 100)

    def test_disassembly_store_bases_and_core_register_writes(self):
        d = self.disasm
        self.assertEqual(re.findall(r'\tmsr\s+(\w+)', d), ['MSPLIM', 'MSP'])
        self.assertEqual(re.findall(r'\tcpsid\s+(\w+)', d), ['i'])
        self.assertNotRegex(d, r'\t(?:bl|blx|cpsie|wfi|wfe)\s')
        # Manual dataflow review: r4 is VTOR only in reset; fault r0 is mailbox;
        # main r4 starts at mailbox during zeroing, then is read-only SCB base;
        # r7 remains mailbox, and SP remains inside the private stack.
        reset, rest = d.split(' <fault_handler>:', 1)
        fault, main = rest.split(' <probe_main>:', 1)
        self.assertEqual(re.findall(r'\tstr(?:\.w)?\s+[^\n]*?\[(\w+)', reset), ['r4'])
        self.assertEqual(set(re.findall(r'\tstr(?:\.w)?\s+[^\n]*?\[(\w+)', fault)), {'r0'})
        self.assertEqual(set(re.findall(r'\tstr(?:\.w)?\s+[^\n]*?\[(\w+)', main)), {'r4', 'r7', 'sp'})
        self.assertNotRegex(fault, r'\t(?:push|pop)\s|\[sp')

    def test_integer_build_flags_no_fpu_or_mve_data_instructions(self):
        compile_calls = [r['argv'] for r in self.report['calls'] if '-c' in r['argv']]
        self.assertEqual(len(compile_calls), 2)
        for call in compile_calls:
            for flag in ('-mfloat-abi=soft', '-mgeneral-regs-only', '-ffreestanding', '-fno-builtin'):
                self.assertIn(flag, call)
        self.assertNotRegex(self.disasm, r'\tv[a-z0-9]+(?:\.[a-z0-9]+)?\s')
        # DLS/LE are integer low-overhead loop branches, not FP/MVE data ops.
        self.assertIn('\tdls\t', self.disasm)
        self.assertIn('\tle\t', self.disasm)

    def test_map_has_no_library_runtime_or_hidden_data(self):
        mapping = (BUILD / 'probe.map').read_text()
        self.assertNotIn('.a(', mapping)
        self.assertNotIn('libgcc', mapping)
        for name, addr, length in [('.isr_vector', '34180400', '40'),
                                  ('.stack', '34184000', '1000'),
                                  ('.mailbox', '34185000', '100')]:
            self.assertRegex(mapping, re.escape(name) + r'\s+0x' + addr + r'\s+0x' + length + r'\b')
        for name in ('.data', '.bss'):
            section = self.image[2].get(name)
            self.assertTrue(section is None or section[5] == 0)


if __name__ == '__main__':
    unittest.main()
