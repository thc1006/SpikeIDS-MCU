"""Bounded synthetic ELF / fixed source controls. No compiler or target calls."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('sram_build_author',HERE/'build.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

def elf():
    raw=bytearray(0x300)
    ident=b'\x7fELF\x01\x01\x01'+bytes(9)
    struct.pack_into('<16sHHIIIIIHHHHHH',raw,0,ident,2,40,1,0x34064041,52,0,0,52,32,4,40,0,0)
    for i,ph in enumerate([(1,0x200,0x34064000,0x34064000,0x80,0x80,5,4),
        (1,0x280,0x34064080,0x34064080,0x20,0x100,6,4),
        (1,0x2a0,0x340F0000,0x340F0000,0,0x8000,6,4),
        (1,0x2a0,0x340F8000,0x340F8000,0,512,6,4)]):
        struct.pack_into('<IIIIIIII',raw,52+i*32,*ph)
    struct.pack_into('<II',raw,0x200,0x340F8000,0x34064041)
    return raw

class BuildTests(unittest.TestCase):
    def test_valid_four_segment_elf(self):
        self.assertEqual(len(b.elf_layout(elf())['segments']),4)
    def test_bad_machine(self):
        raw=elf();struct.pack_into('<H',raw,18,62)
        with self.assertRaises(Exception):b.elf_layout(raw)
    def test_even_entry(self):
        raw=elf();struct.pack_into('<I',raw,24,0x34064040)
        with self.assertRaises(Exception):b.elf_layout(raw)
    def test_wrong_stack(self):
        raw=elf();struct.pack_into('<I',raw,0x200,0x34185000)
        with self.assertRaises(Exception):b.elf_layout(raw)
    def test_full_weight_pool_excluded(self):
        raw=elf();struct.pack_into('<II',raw,52+32+8,0x3423fff0,0x3423fff0)
        with self.assertRaisesRegex(Exception,'reserved SRAM'):b.elf_layout(raw)
    def test_full_activation_pool_excluded(self):
        raw=elf();struct.pack_into('<II',raw,52+32+8,0x34243000,0x34243000)
        with self.assertRaisesRegex(Exception,'reserved SRAM'):b.elf_layout(raw)
    def test_writable_code(self):
        raw=elf();struct.pack_into('<I',raw,52+24,7)
        with self.assertRaises(Exception):b.elf_layout(raw)
    def test_unknown_cli_refused(self):
        with self.assertRaises(SystemExit) as e:b.main(['--output-dir','/tmp/none','--model','other'])
        self.assertEqual(e.exception.code,2)
    def test_stale_output_before_any_candidate_access(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);out=p/'stale';out.mkdir()
            with patch.object(b,'HERE',p),patch.object(b,'candidate_pins',side_effect=AssertionError('must not read')):
                with self.assertRaisesRegex(RuntimeError,'Existing output'):b.run(out)
    def test_architecture_and_no_npu_cache_define(self):
        self.assertIn('-DLL_ATON_SW_FALLBACK=1',b.DEFS)
        self.assertIn('-DLL_ATON_RT_MODE=LL_ATON_RT_POLLING',b.DEFS)
        self.assertNotIn('-DUSE_NPU_CACHE',b.DEFS)
        self.assertIn('-mfloat-abi=hard',b.FLAGS)
    def test_abi_and_reserved_ranges(self):
        a=json.loads((HERE/'ABI.json').read_bytes())
        self.assertEqual(a['magic'],0x53364E36);self.assertEqual(a['deployment_tag'],0x534D3031)
        self.assertEqual(a['mailbox_address'],0x340F8000)
        self.assertEqual((a['input_count'],a['output_count']),(41,5))
        self.assertEqual((a['input_word_offset'],a['output_word_offset']),(128,320))
        self.assertEqual(a['weights_address']+a['weights_reserved_bytes'],a['activation_address'])
        self.assertEqual(a['activation_address']+a['activation_reserved_bytes'],0x34244000)
    def test_wait_before_vendor_init_and_complete_commit(self):
        s=(HERE/'main.c').read_text()
        self.assertLess(s.index('while (g_mailbox.platform_ack'),s.index('stai_nsl_qcfs_seed0_init('))
        self.assertIn('g_mailbox.state=S6_DONE; __DMB(); g_mailbox.response_sequence=seq;',s)
        self.assertEqual(s.count('if (!request_unchanged(seq,row))'),2)
        self.assertIn('memcpy(output_copy,out[0],20)',s)
        self.assertNotIn('g_mailbox.platform_ack =',s)

if __name__=='__main__':unittest.main()
