"""Independent finite RAM-transport controls. Pure fake memory, no backend import."""
import struct
import unittest
from protocol import Session,request,hello_query
from ra_mailbox import ADDRESS,MailboxExchange
from test_ra_mailbox import Fake

class IndependentRAMailboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.x=struct.pack('<41f',*range(41))
        cls.requests=tuple(request(i,10000+i,cls.x) for i in range(1,1025))
    def make(self,f=None,**kwargs):
        f=Fake() if f is None else f;events=[]
        e=MailboxExchange(f.read,f.write,events.append,self.requests,**kwargs)
        return f,e,Session(e,1),events
    def test_positive_all1024_fixed_inputs_and_full_outputs(self):
        f,e,s,events=self.make();s.hello()
        for i in range(1,1025):self.assertEqual(s.infer(10000+i,self.x),struct.pack('<5f',1,2,3,4,5))
        self.assertEqual(e.next,1025);self.assertEqual(len(f.writes),2048)
        self.assertEqual(f.writes[-2],(ADDRESS+32,self.requests[-1]))
        self.assertEqual(f.writes[-1],(ADDRESS+16,struct.pack('<I',1024)))
        with self.assertRaises(ValueError):e(self.requests[-1],88)
        self.assertEqual(len(f.writes),2048)
        self.assertTrue(all(x['requested_bytes'] in (512,4) for x in events if x['event']=='ram_read'))
    def test_nonfinite_now_after_finite_deadline_must_refuse(self):
        calls=[0]
        def clock():
            calls[0]+=1
            return 0.0 if calls[0]==1 else float('nan')
        f,e,s,_=self.make(clock=clock)
        with self.assertRaises((ValueError,TimeoutError)):s.hello()
        self.assertTrue(e.poisoned);self.assertEqual(f.writes,[])
    def test_hello_stale_commit_not_fresh(self):
        f=Fake();struct.pack_into('<I',f.ram,20,1)
        f,e,s,_=self.make(f)
        with self.assertRaises(ValueError):s.hello()
        self.assertEqual(f.writes,[])
    def test_sink_fails_before_any_write(self):
        f,e,s,_=self.make()
        def sink(event):raise OSError('retention unavailable')
        e.retain=sink
        with self.assertRaises(OSError):s.hello()
        self.assertTrue(e.poisoned);self.assertEqual(f.writes,[])
    def test_sink_fails_after_commit_no_retry(self):
        f,e,s,events=self.make();s.hello()
        def sink(event):
            events.append(event)
            if event['event']=='ram_write_return' and event['address']==ADDRESS+16:raise OSError('postcommit sink failed')
        e.retain=sink
        with self.assertRaises(OSError):s.infer(10001,self.x)
        self.assertEqual(len(f.writes),2);self.assertTrue(e.poisoned)
        with self.assertRaises(ValueError):e(self.requests[0],88)
        self.assertEqual(len(f.writes),2)
    def test_short_staging_write_never_commits(self):
        f,e,s,_=self.make();s.hello();f.short=True
        with self.assertRaises(ValueError):s.infer(10001,self.x)
        self.assertEqual(len(f.writes),1);self.assertTrue(e.poisoned)
    def test_deadline_crossed_by_final_read_is_retained_and_refused(self):
        f,e,s,events=self.make(clock=lambda:0.0);s.hello();now=[0.0]
        e.clock=lambda:now[0];old=e.read
        def read(a,n):
            answer=old(a,n)
            if a==ADDRESS and struct.unpack_from('<I',f.ram,20)[0]==1:now[0]=11.0
            return answer
        e.read=read
        with self.assertRaises(TimeoutError):s.infer(10001,self.x)
        self.assertEqual(len(f.writes),2);self.assertTrue(e.poisoned)
        self.assertEqual(events[-1]['event'],'ram_read');self.assertEqual(len(bytes.fromhex(events[-1]['raw_hex'])),512)
    def test_stale_crc_valid_response_refused(self):
        from test_protocol import response
        f,e,s,_=self.make();s.hello();old=e.write
        def write(a,b):
            count=old(a,b)
            if a==ADDRESS+16:f.ram[264:352]=response(self.requests[1])
            return count
        e.write=write
        with self.assertRaises(ValueError):s.infer(10001,self.x)
        self.assertEqual(len(f.writes),2);self.assertTrue(e.poisoned)
    def test_deadline_when_target_never_commits(self):
        f,e,s,_=self.make(clock=lambda:0.0);s.hello();now=[0.0]
        def write(a,b):
            f.writes.append((a,b));f.ram[a-ADDRESS:a-ADDRESS+len(b)]=b;return len(b)
        e.write=write;e.clock=lambda:now[0];e.sleep=lambda seconds:now.__setitem__(0,now[0]+seconds)
        e.timeout=.002
        with self.assertRaises(TimeoutError):s.infer(10001,self.x)
        self.assertTrue(e.poisoned);self.assertEqual(len(f.writes),2)
    def test_input_frame_mutated_after_commit_refused(self):
        f,e,s,_=self.make();s.hello();old=e.write
        def write(a,b):
            n=old(a,b)
            if a==ADDRESS+16:f.ram[100]^=1
            return n
        e.write=write
        with self.assertRaises(ValueError):s.infer(10001,self.x)
        self.assertTrue(e.poisoned)
    def test_wrong_request_and_bool_reply_length_never_writes(self):
        for raw,n in ((self.requests[0],160),(hello_query(),True)):
            with self.subTest(n=n):
                f,e,s,_=self.make()
                with self.assertRaises(ValueError):e(raw,n)
                self.assertEqual(f.writes,[])
    def test_staging_header_changed_never_commit(self):
        f,e,s,_=self.make();s.hello();old=e.write
        def write(a,b):
            n=old(a,b)
            if a==ADDRESS+32:struct.pack_into('<I',f.ram,24,2)
            return n
        e.write=write
        with self.assertRaises(ValueError):s.infer(10001,self.x)
        self.assertEqual(len(f.writes),1)

if __name__=='__main__':unittest.main(verbosity=2)
