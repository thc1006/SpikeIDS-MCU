import struct
import unittest
from protocol import Session,request
from ra_mailbox import ADDRESS,MailboxExchange,MAGIC
from test_protocol import hello,response


class Fake:
    def __init__(self):
        self.ram=bytearray(512)
        struct.pack_into('<8I',self.ram,0,MAGIC,1,1,1,0,0,1,100000000)
        self.ram[352:]=hello(1);self.writes=[];self.corrupt=False;self.short=False
    def read(self,a,n):return bytes(self.ram[a-ADDRESS:a-ADDRESS+n])
    def write(self,a,raw):
        self.writes.append((a,raw));off=a-ADDRESS;self.ram[off:off+len(raw)]=raw
        if off==32 and self.corrupt:self.ram[32]^=1
        if off==16:
            seq=struct.unpack('<I',raw)[0]
            q=bytes(self.ram[32:264]);self.ram[264:352]=response(q)
            struct.pack_into('<I',self.ram,8,3)
            struct.pack_into('<I',self.ram,20,seq)
            struct.pack_into('<I',self.ram,24,seq+1)
        return len(raw)-int(self.short)


class RAMailboxTests(unittest.TestCase):
    def setUp(self):
        self.x=struct.pack('<41f',*range(41))
        self.requests=tuple(request(i,i+10,self.x) for i in range(1,1025))
    def test_full1024_original_protocol(self):
        fake=Fake();exchange=MailboxExchange(fake.read,fake.write,lambda e:None,self.requests)
        s=Session(exchange,1);s.hello()
        for i in range(1,1025):self.assertEqual(s.infer(i+10,self.x),struct.pack('<5f',1,2,3,4,5))
        self.assertEqual(len(fake.writes),2048)
        self.assertTrue(all(a==ADDRESS+16 for a,_ in fake.writes[1::2]))
    def test_bad_stage_never_commits_and_never_retry(self):
        f=Fake();f.corrupt=True;e=MailboxExchange(f.read,f.write,lambda x:None,self.requests)
        s=Session(e,1);s.hello()
        with self.assertRaises(ValueError):s.infer(11,self.x)
        self.assertEqual(len(f.writes),1)
        with self.assertRaises(ValueError):s.infer(11,self.x)
        self.assertEqual(len(f.writes),1)
    def test_read_crossing_deadline_cannot_pass(self):
        f=Fake();clock=[0.0]
        def read(a,n):clock[0]+=11;return f.read(a,n)
        e=MailboxExchange(read,f.write,lambda e:None,self.requests,clock=lambda:clock[0])
        s=Session(e,1)
        with self.assertRaises(TimeoutError):s.hello()
        self.assertTrue(e.poisoned);self.assertEqual(f.writes,[])
    def test_wrong_board_never_writes(self):
        f=Fake();f.ram[352:]=hello(2)
        e=MailboxExchange(f.read,f.write,lambda e:None,self.requests)
        with self.assertRaises(ValueError):Session(e,1).hello()
        self.assertEqual(f.writes,[])


if __name__=='__main__':unittest.main()
