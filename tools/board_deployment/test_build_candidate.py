import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import build_candidate as b

def elf(board,va,pa,fs=4,ms=4):
    header=struct.pack('<16sHHIIIIIHHHHHH',b'\x7fELF\x01\x01\x01'+bytes(9),2,
                       40 if board=='ra4e1' else 94,1,va|1,52,0,0,52,32,1,0,0,0)
    return header+struct.pack('<8I',1,84,va,pa,fs,ms,5,4)+bytes(fs)

class BuildControls(unittest.TestCase):
    def test_valid_both_architectures(self):
        for board,va in [('ra4e1',0),('esp32s3',0x42000020)]:
            self.assertEqual(b.elf_layout(elf(board,va,va),board)['segments'][0]['file_bytes'],4)
    def test_no_option_or_memory_spill(self):
        for va,pa,fs,ms in [(0x0100a100,0,4,4),(0,0x0100a100,4,4),
                            (0x2001ffff,0,4,4),(0x7ffff,0,4,4)]:
            with self.assertRaises(ValueError):b.elf_layout(elf('ra4e1',va,pa,fs,ms),'ra4e1')
    def test_no_psram_segment(self):
        with self.assertRaises(ValueError):b.elf_layout(elf('esp32s3',0x3d000000,0x3d000000),'ra4e1')
    def test_env_never_inherits_overrides(self):
        with patch.dict(os.environ,CPATH='/bad',LD_PRELOAD='/bad',GCC_EXEC_PREFIX='/bad'):
            for board in ('ra4e1','esp32s3'):
                env=b.environment(board,Path('/tmp/task'))
                self.assertNotIn('CPATH',env);self.assertNotIn('LD_PRELOAD',env)
                self.assertNotIn('GCC_EXEC_PREFIX',env)
                self.assertEqual(env['PYTHONOPTIMIZE'],'0')
    def test_fixed_native_commitments(self):
        for path,sha in b.FIXED.items():self.assertEqual(b.snapshot(path)[1]['sha256'],sha)
    def test_original_stat_and_namespace(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);p=root/'a';p.write_bytes(b'a');inv=b.inventory(root)
            p.write_bytes(b'a')
            with self.assertRaises(ValueError):b.stats({str(p):inv['files']['a']})
            (root/'extra').mkdir()
            with self.assertRaises(ValueError):b.namespace(root,inv)
    def test_stale_output_rejects_before_compiler(self):
        with tempfile.TemporaryDirectory() as td,patch.object(b.subprocess,'run') as child:
            with self.assertRaises(ValueError):b.run('ra4e1',td)
            child.assert_not_called()

if __name__=='__main__':unittest.main()
