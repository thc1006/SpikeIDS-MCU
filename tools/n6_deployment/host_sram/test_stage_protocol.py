import struct
import unittest
import stage_protocol as p


def ready():
    w=[0]*1024
    w[:5]=[p.MAGIC,1,4096,2,2];w[12]=0x411FD221;w[26]=1
    obs={a:v for a,(m,v) in p.FINAL.items()};obs[0x56028048]=0
    w[32:48]=[0,12,0,0,0,0,16,400,3,0,64000000,len(obs),0x10400,1,0,0]
    for i,(a,v) in enumerate(obs.items()):w[48+3*i:51+3*i]=[a,v,v]
    return bytearray(struct.pack('<1024I',*w))


class StageTests(unittest.TestCase):
    def test_ready_and_live_values(self):
        raw=ready();s=p.decode(bytes(raw))
        current=p.live_register_check(lambda a,n:struct.pack('<I',s['observations'][a][1]),s)
        self.assertEqual(current[0x54024C14],0x310)

    def test_nonready_wrong_profile_or_claim_refused(self):
        for i,v in ((0,0),(3,3),(4,3),(12,0),(13,0x10000),(26,0),(27,1),
                    (32,1),(33,11),(42,800000000),(44,0),(45,0),(46,1),(624,1)):
            raw=ready();struct.pack_into('<I',raw,4*i,v)
            with self.subTest(index=i):
                with self.assertRaises(p.ProtocolError):p.decode(bytes(raw))

    def test_nonce_publishes_one_stable_response(self):
        raw=ready()
        def read(a,n):return bytes(raw[a-p.ADDRESS:a-p.ADDRESS+n])
        def write(a,b):
            self.assertEqual(a,p.ADDRESS+24)
            raw[24:28]=b;raw[28:32]=b
            struct.pack_into('<2I',raw,16,4,1)
            return 4
        after=p.challenge(read,write,1234)
        self.assertEqual(after['echo_nonce'],1234)
        with self.assertRaises(p.ProtocolError):p.challenge(read,write,1234)

    def test_missing_or_changed_actual_config_refused(self):
        s=p.decode(bytes(ready()))
        def read(a,n):return struct.pack('<I',0 if a==0x54024C14 else s['observations'][a][1])
        with self.assertRaises(p.ProtocolError):p.live_register_check(read,s)


if __name__=='__main__':unittest.main()
