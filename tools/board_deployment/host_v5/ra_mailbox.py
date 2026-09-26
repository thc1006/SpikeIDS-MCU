"""RA full-frame RAM transport; caller owns reviewed debug/programming session.

No USB, reset, programming, power or debug backend is selected here. This runs
only with explicit read/write callbacks; constructor itself never accesses RAM.
"""
import math
import struct
import time
from protocol import decode_hello,decode_response,hello_query,require
from serial_transport import checked_requests

ADDRESS=0x2001F000
SIZE=512
MAGIC=0x41353556


class MailboxExchange:
    def __init__(self,read,write,retain,requests,*,timeout_s=10,clock=time.monotonic,sleep=time.sleep):
        self.requests=checked_requests(requests)
        require(all(callable(x) for x in (read,write,retain,clock,sleep)),'Callbacks required')
        require(type(timeout_s) in (int,float) and math.isfinite(timeout_s) and
                0<timeout_s<=30,'Finite deadline required')
        self.read=read;self.write=write;self.retain=retain
        self.timeout=timeout_s;self.clock=clock;self.sleep=sleep
        self.next=0;self.poisoned=False

    def __call__(self,raw,count):
        require(not self.poisoned,'Poisoned RA session; no retry')
        try:
            hello=self.next==0
            require(self.next<=1024 and type(raw) is bytes and type(count) is int,'Request type/count')
            require(raw==(hello_query() if hello else self.requests[self.next-1]) and
                    count==(160 if hello else 88),'Expected fixed ordered request')
            deadline=self.clock()+self.timeout
            def remaining():
                left=deadline-self.clock()
                if not math.isfinite(left) or left<=0:raise TimeoutError('RA mailbox deadline')
            def read(address,n):
                remaining();b=self.read(address,n)
                require(type(b) is bytes,'RAM read must return bytes')
                self.retain({'event':'ram_read','address':address,'requested_bytes':n,'raw_hex':b.hex()})
                remaining();require(len(b)==n,'Short RAM read');return b
            def snapshot():
                for _ in range(8):
                    a=read(ADDRESS,SIZE);b=read(ADDRESS,SIZE)
                    if a==b:
                        header=struct.unpack_from('<8I',a)
                        require(header[0:2]==(MAGIC,1) and header[3]==1,'RA ABI/FP environment')
                        decode_hello(a[352:],1)
                        return a,header
                raise ValueError('No stable RA snapshot')
            def write(address,b):
                self.retain({'event':'ram_write_intent','address':address,'raw_hex':b.hex()})
                remaining();n=self.write(address,b)
                self.retain({'event':'ram_write_return','address':address,
                             'bytes_written':n if type(n) is int else None})
                remaining();require(type(n) is int and n==len(b),'Ambiguous RAM write')
            first,h=snapshot()
            if hello:
                require(h[2]==1 and h[4:7]==(0,0,1),'RA not freshly booted and ready')
                self.next=1;return first[352:]
            seq=self.next
            require(h[2]==(1 if seq==1 else 3) and h[4:7]==(seq-1,seq-1,seq),
                    'RA previous transaction not complete')
            write(ADDRESS+32,raw)
            staged,h2=snapshot()
            require(h2==h and staged[32:264]==raw,'Request staging/readback changed')
            write(ADDRESS+16,struct.pack('<I',seq))  # final request commit
            require(read(ADDRESS+16,4)==struct.pack('<I',seq),'Commit readback')
            for _ in range(10000):
                completed,h3=snapshot()
                require(h3[4]==seq and completed[32:264]==raw,'RA request changed during execution')
                if h3[5]==seq:
                    require(h3[2]==3 and h3[6]==seq+1,'RA error/incomplete response')
                    reply=completed[264:352]
                    decode_response(reply,seq,struct.unpack_from('<Q',raw,16)[0])
                    remaining();self.next+=1;return reply
                require(h3[5]==seq-1 and h3[2] in (1,2,3,4),'RA response sequence/state')
                self.sleep(.001)
            raise TimeoutError('RA poll budget exhausted')
        except BaseException:
            self.poisoned=True;raise
