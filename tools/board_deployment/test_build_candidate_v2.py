"""Pure ESP postcheck controls using the preserved candidate02 ELF, no compiler."""
import copy
import json
import shlex
import struct
import unittest
import build_candidate_v2 as b

class ESPPostcheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=b.ROOT/'results/esp32s3_v5_build_20260925_02'
        cls.raw,cls.pin=b.snapshot(cls.root/'build/spikeids_v5_qdq.elf')
        cls.undef=(cls.root/'undefined.stdout').read_bytes()
        cls.cmakes=tuple(p.read_text() for p in b.ESP_CMAKES)
        cls.cc=json.loads((cls.root/'build/compile_commands.json').read_text())
        cls.headers=struct.unpack_from('<16sHHIIIIIHHHHHH',cls.raw)
    @classmethod
    def tearDownClass(cls):
        if b.snapshot(cls.root/'build/spikeids_v5_qdq.elf')[1]!=cls.pin:raise AssertionError('original ELF changed')
    def ph(self,field,value):
        raw=bytearray(self.raw);h=self.headers
        positions=[h[5]+i*32 for i in range(h[10]) if struct.unpack_from('<I',raw,h[5]+i*32+8)[0]==0x600fffe8]
        self.assertEqual(len(positions),1);struct.pack_into('<I',raw,positions[0]+4*field,value);return bytes(raw)
    def sh(self,field,value):
        raw=bytearray(self.raw);h=self.headers
        pos=[h[6]+i*40 for i in range(h[12]) if struct.unpack_from('<I',raw,h[6]+i*40+12)[0]==0x600fffe8]
        self.assertEqual(len(pos),1);struct.pack_into('<I',raw,pos[0]+4*field,value);return bytes(raw)
    def command(self,mutate):
        rows=copy.deepcopy(self.cc)
        for row in rows:
            if row['file']==str(b.PORTABLE/'portable_qdq.c'):
                row['command']=shlex.join(mutate(shlex.split(row['command'])))
        return rows
    def test_existing_elf_exact_rtc_and_no_relocations(self):
        result=b.elf_layout(self.raw,'esp32s3')
        self.assertEqual(len(result['segments']),8);self.assertEqual(result['runtime_relocations'],0)
    def test_existing_numeric_full_tokens(self):
        self.assertEqual(set(b.numeric_policy(self.cc)),{'portable_qdq.c','wire.c','model.c'})
    def test_forced_symbols_positive(self):
        out=b.esp_symbol_policy(self.undef,b'a.a(foo.o):\n         U malloc\n         w optional\n',self.cmakes,self.raw)
        self.assertEqual(set(out['forced_undefined']),b.ESP_FORCED)
    def test_extra_undefined(self):
        with self.assertRaises(ValueError):b.esp_symbol_policy(self.undef+b' U missing_call\n',b'',self.cmakes,self.raw)
    def test_missing_undefined(self):
        with self.assertRaises(ValueError):b.esp_symbol_policy(b' U start_app\n',b'',self.cmakes,self.raw)
    def test_weak_does_not_impersonate_forced_global(self):
        with self.assertRaises(ValueError):b.esp_symbol_policy(self.undef.replace(b' U ',b' w ',1),b'',self.cmakes,self.raw)
    def test_archive_reference_rejects(self):
        for name in b.ESP_FORCED:
            with self.subTest(name=name),self.assertRaises(ValueError):
                b.esp_symbol_policy(self.undef,('x.a(foo.o):\n U '+name+'\n').encode(),self.cmakes,self.raw)
    def test_missing_sdk_directive(self):
        with self.assertRaises(ValueError):b.esp_symbol_policy(self.undef,b'',('',self.cmakes[1]),self.raw)
    def test_comment_not_directive(self):
        changed=tuple('\n'.join('# '+line for line in text.splitlines()) for text in self.cmakes)
        with self.assertRaises(ValueError):b.esp_symbol_policy(self.undef,b'',changed,self.raw)
    def test_rtc_wrong_address(self):
        with self.assertRaises(ValueError):b.elf_layout(self.ph(2,0x600fffe0),'esp32s3')
    def test_rtc_has_file_payload(self):
        with self.assertRaises(ValueError):b.elf_layout(self.ph(4,1),'esp32s3')
    def test_rtc_wrong_size(self):
        with self.assertRaises(ValueError):b.elf_layout(self.ph(5,32),'esp32s3')
    def test_rtc_executable_segment(self):
        with self.assertRaises(ValueError):b.elf_layout(self.ph(6,7),'esp32s3')
    def test_rtc_not_nobits(self):
        with self.assertRaises(ValueError):b.elf_layout(self.sh(1,1),'esp32s3')
    def test_rtc_section_wrong_size(self):
        with self.assertRaises(ValueError):b.elf_layout(self.sh(5,16),'esp32s3')
    def test_relocation_rejects_even_with_correct_forced_names(self):
        raw=bytearray(self.raw);h=self.headers
        # Convert one nonempty debug section into REL; no address/range widening.
        for i in range(h[12]):
            off=h[6]+i*40;s=struct.unpack_from('<10I',raw,off)
            if s[1]==1 and s[2]==0 and s[5]>8:
                struct.pack_into('<I',raw,off+4,9);break
        else:self.fail('fixture lacks debug section')
        with self.assertRaises(ValueError):b.esp_symbol_policy(self.undef,b'',self.cmakes,bytes(raw))
    def test_substring_cannot_supply_flag(self):
        rows=self.command(lambda argv:['-DFAKE=-ffp-contract=off' if x=='-ffp-contract=off' else x for x in argv])
        with self.assertRaises(ValueError):b.numeric_policy(rows)
    def test_changed_final_language(self):
        with self.assertRaises(ValueError):b.numeric_policy(self.command(lambda x:x+['-std=gnu17']))
    def test_changed_final_optimization(self):
        with self.assertRaises(ValueError):b.numeric_policy(self.command(lambda x:x+['-O0']))
    def test_fast_math_and_contraction_not_tolerated(self):
        for flag in ['-ffast-math','-Ofast','-ffp-contract=fast','-fexcess-precision=fast','-fno-signed-zeros']:
            with self.subTest(flag=flag),self.assertRaises(ValueError):b.numeric_policy(self.command(lambda x:x+[flag]))
    def test_responsefile_not_tolerated(self):
        with self.assertRaises(ValueError):b.numeric_policy(self.command(lambda x:x+['@unobserved.rsp']))
    def test_mismatched_source_argument(self):
        rows=self.command(lambda x:[s if s!=str(b.PORTABLE/'portable_qdq.c') else '/other/portable_qdq.c' for s in x])
        with self.assertRaises(ValueError):b.numeric_policy(rows)

if __name__=='__main__':unittest.main()
