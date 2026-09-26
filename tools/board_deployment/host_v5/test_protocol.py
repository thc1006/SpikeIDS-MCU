import struct
import unittest
from protocol import (HELLO,MODEL,VECTORS,RESPONSE,Session,crc,request,
                      decode_response,decode_hello,hello_query)
from validate import load_rows,run


def hello(board=2,flags=1):
    r=struct.pack('<7I',HELLO,1,board,1,flags,41,5)+MODEL.encode()+VECTORS.encode()
    return r+crc(r)


def response(q,output=None,status=0):
    r=struct.pack('<2I',RESPONSE,1)+q[8:24]+struct.pack('<2I',status,5 if not status else 0)
    r+=bytes.fromhex(MODEL)+(output if output is not None else struct.pack('<5f',1,2,3,4,5))
    return r+crc(r)


class ProtocolTests(unittest.TestCase):
    def setUp(self):self.input=struct.pack('<41f',*range(41))

    def test_sizes_full_identity_fields_and_raw_output(self):
        q=request(7,2**40+17,self.input)
        self.assertEqual(len(q),232)
        self.assertEqual(q[64:228],self.input)
        self.assertEqual(decode_response(response(q),7,2**40+17),struct.pack('<5f',1,2,3,4,5))
        self.assertEqual(len(hello_query()),12)
        self.assertEqual(decode_hello(hello(),2)['validation_sha256'],VECTORS)

    def test_crc_mutations_identity_and_nonwinning_nan_fail(self):
        q=request(1,9,self.input);r=response(q)
        for offset in (0,4,8,12,16,24,28,32,63,64,83,84):
            bad=bytearray(r);bad[offset]^=1
            with self.subTest(offset=offset),self.assertRaises(ValueError):decode_response(bytes(bad),1,9)
        for offset,value in ((0,0),(4,2),(8,2),(12,5),(24,256),(28,1),(80,0x7FC00000)):
            bad=bytearray(r[:-4]);struct.pack_into('<I',bad,offset,value);bad=bytes(bad)
            with self.subTest(offset=offset),self.assertRaises(ValueError):decode_response(bad+crc(bad),1,9)

    def test_wrong_hello_backend_board_environment_or_model(self):
        for r in (hello(1),hello(flags=0),hello(flags=3),hello()[:-1]):
            with self.assertRaises(ValueError):decode_hello(r,2)
        bad=bytearray(hello()[:-4]);bad[92]^=1;bad=bytes(bad)
        with self.assertRaises(ValueError):decode_hello(bad+crc(bad),2)

    def test_invalid_requests_never_transport(self):
        for seq,rid,data in ((True,1,self.input),(0,1,self.input),(1025,1,self.input),
                (1,-1,self.input),(1,True,self.input),(1,1,self.input[:-1]),
                (1,1,struct.pack('<f',float('nan'))+self.input[4:])):
            with self.subTest(seq=seq,rid=rid),self.assertRaises(ValueError):request(seq,rid,data)

    def test_failed_exchange_or_identity_poison_no_retry(self):
        for how in ('io','crc','row','hello'):
            calls=[]
            def exchange(q,n):
                calls.append(q)
                if n==160:return hello(1 if how=='hello' else 2)
                if how=='io':raise OSError('disconnected')
                if how=='crc':return bytes(88)
                wrong=request(1,10,self.input)
                return response(wrong)
            session=Session(exchange,2)
            with self.assertRaises((ValueError,OSError)):
                session.hello();session.infer(9,self.input)
            old=len(calls)
            with self.assertRaises(ValueError):session.infer(9,self.input)
            self.assertEqual(len(calls),old)

    def test_actual_archive_load_offline(self):
        rows=load_rows()
        self.assertEqual(len(rows),1024)
        self.assertEqual(len(set(r[0] for r in rows)),1024)

    def test_1024_all_words_complete_and_last_logit_failure(self):
        rows=tuple((100000+i,self.input,struct.pack('<5f',1,2,3,4,5)) for i in range(1024))
        for corrupt in (False,True):
            retained=[];calls=[]
            def exchange(q,n):
                calls.append(q)
                if n==160:return hello()
                seq=struct.unpack_from('<I',q,8)[0]
                out=struct.pack('<5f',1,2,3,4,6) if corrupt and seq==1024 else rows[seq-1][2]
                return response(q,out)
            metrics=run(Session(exchange,2),rows,retained.append)
            self.assertEqual(len(calls),1025)
            self.assertEqual(len(retained),1024)
            self.assertEqual(metrics['full_logit_parity_passed'],not corrupt)
            self.assertEqual(metrics['failed_coordinates'],[[1023,4]] if corrupt else [])
            self.assertEqual(metrics['argmax_disagreements'],0)

    def test_persist_failure_prevents_second_inference(self):
        rows=tuple((i,self.input,struct.pack('<5f',1,2,3,4,5)) for i in range(1024))
        calls=[]
        def exchange(q,n):
            calls.append(q);return hello() if n==160 else response(q)
        def fail(record):raise OSError('disk full')
        session=Session(exchange,2)
        with self.assertRaises(OSError):run(session,rows,fail)
        self.assertEqual(len(calls),2)
        self.assertTrue(session.poisoned)
        with self.assertRaises(ValueError):session.infer(1,self.input)
        self.assertEqual(len(calls),2)


if __name__=='__main__':unittest.main()
