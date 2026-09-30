"""Independent Python/C ABI controls; C inference is an explicit test double."""
import ctypes as C
import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from protocol import request,decode_response,hello_query,decode_hello,crc

HERE=Path(__file__).resolve().parent
SHARED=HERE.parent/'shared_v5'
PORTABLE=HERE.parent/'portable_qdq'


class WireCrossTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='spikeids-wire-cross-')
        cls.files=[SHARED/'wire.c',SHARED/'wire.h',PORTABLE/'portable_qdq.h',HERE/'wire_stub.c']
        cls.pins={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in cls.files}
        out=Path(cls.tmp.name)/'test.so'
        subprocess.run(['/usr/bin/x86_64-linux-gnu-gcc-15','-std=c11','-O2','-Wall','-Wextra','-Werror',
            '-shared','-fPIC','-I',str(SHARED),'-I',str(PORTABLE),str(SHARED/'wire.c'),
            str(HERE/'wire_stub.c'),'-o',str(out)],check=True,capture_output=True,timeout=20,
            env={'PATH':'/usr/bin:/bin','LC_ALL':'C','TMPDIR':cls.tmp.name})
        cls.lib=C.CDLL(str(out))
        cls.lib.v5_process.argtypes=[C.c_void_p,C.c_void_p,C.POINTER(C.c_uint32)]
        cls.lib.v5_process.restype=C.c_uint32
        cls.lib.v5_hello.argtypes=[C.c_void_p,C.c_uint32]
        cls.lib.v5_hello_query.argtypes=[C.c_void_p]
        cls.lib.v5_hello_query.restype=C.c_int

    @classmethod
    def tearDownClass(cls):
        after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in cls.files}
        cls.tmp.cleanup()
        if after!=cls.pins:raise AssertionError('Wire source changed during tests')

    def setUp(self):
        C.c_int.in_dll(self.lib,'stub_environment').value=1
        C.c_int.in_dll(self.lib,'stub_calls').value=0
        self.input=struct.pack('<41f',*range(41))

    def call(self,q,next_value=1):
        raw=C.create_string_buffer(q,len(q));out=C.create_string_buffer(88);seq=C.c_uint32(next_value)
        status=self.lib.v5_process(raw,out,C.byref(seq))
        return status,out.raw,seq.value

    def test_hello_environment_good_and_bad(self):
        for flag in (1,0):
            C.c_int.in_dll(self.lib,'stub_environment').value=flag
            out=C.create_string_buffer(160);self.lib.v5_hello(out,2)
            if flag:self.assertEqual(decode_hello(out.raw,2)['board_id'],2)
            else:
                with self.assertRaises(ValueError):decode_hello(out.raw,2)
        self.assertEqual(self.lib.v5_hello_query(hello_query()),1)
        self.assertEqual(self.lib.v5_hello_query(bytes(12)),0)
        self.assertEqual(C.c_int.in_dll(self.lib,'stub_calls').value,0)

    def test_python_request_c_response_all_payload_ends_and_id64(self):
        q=request(1,2**40+19,self.input);rc,raw,next_value=self.call(q)
        self.assertEqual((rc,next_value),(0,2))
        self.assertEqual(decode_response(raw,1,2**40+19),struct.pack('<5f',0,10,20,30,40))

    def test_bad_crc_model_shape_or_sequence_does_not_infer(self):
        q=request(1,19,self.input)
        candidates=[bytes(232)]
        for offset,value in ((8,2),(12,1),(24,40),(28,160),(32,0)):
            b=bytearray(q[:-4]);struct.pack_into('<I',b,offset,value);b=bytes(b)
            candidates.append(b+crc(b))
        for q in candidates:
            status,raw,next_value=self.call(q)
            self.assertNotEqual(status,0);self.assertEqual(next_value,1)
            self.assertEqual(struct.unpack_from('<I',raw,28)[0],0)
            self.assertEqual(raw[-4:],crc(raw[:-4]))
        self.assertEqual(C.c_int.in_dll(self.lib,'stub_calls').value,0)

    def test_model_failure_consumed_once_not_success_or_retry(self):
        C.c_int.in_dll(self.lib,'stub_environment').value=0
        q=request(1,19,self.input)
        status,raw,next_value=self.call(q)
        self.assertEqual((status,next_value),(0x102,2))
        with self.assertRaises(ValueError):decode_response(raw,1,19)
        status,_,next_value=self.call(q,next_value)
        self.assertEqual((status,next_value),(3,2))
        self.assertEqual(C.c_int.in_dll(self.lib,'stub_calls').value,1)


if __name__=='__main__':unittest.main()
