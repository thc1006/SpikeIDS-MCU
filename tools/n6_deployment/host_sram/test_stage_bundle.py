import struct
import unittest
from stage_bundle import BUILD, load_stage, parse_elf


class StageBundleTests(unittest.TestCase):
    def test_actual_fixed_bundle(self):
        b = load_stage()
        self.assertEqual((b['entry'], b['msp']), (0x34180539, 0x3418B000))
        self.assertEqual([(a,len(v)) for a,v in b['segments']],
                         [(0x34180400,2760),(0x34188000,4096),(0x34189000,8192)])
        self.assertEqual(b['segments'][1][1],bytes(4096))
        self.assertEqual(b['segments'][2][1],bytes(8192))

    def test_wrong_segment_address_flags_size_and_vectors(self):
        original = (BUILD/'stage.elf').read_bytes()
        h = struct.unpack_from('<16sHHIIIIIHHHHHH',original)
        first = struct.unpack_from('<8I',original,h[5])
        for offset, word in ((h[5]+8,0x71000000),(h[5]+24,7),
                             (h[5]+20,2764),(first[1],0x34189000),
                             (first[1]+4,0x34180538),(h[5]+32+20,8192)):
            raw=bytearray(original);struct.pack_into('<I',raw,offset,word)
            with self.subTest(offset=offset),self.assertRaises(ValueError):parse_elf(raw)

    def test_truncated_and_wrong_architecture(self):
        original=(BUILD/'stage.elf').read_bytes()
        for raw in (original[:51],original[:140],b'NOPE'+original[4:]):
            with self.assertRaises(ValueError):parse_elf(raw)


if __name__=='__main__':unittest.main()
