"""Literal S6 byte fixtures, no author fake, backend, hardware, or compiler."""
import importlib.util
from pathlib import Path
import struct

import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('s6_protocol_independent',HERE/'protocol.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
BASE=0x340F8000


class Device:
    def __init__(self):
        self.raw=bytearray(512);self.writes=[];self.reads=0;self.committed=False
        self.reply=True;self.post=None;self.read_hook=None;self.write_hook=None;self.now=0.0
        for offset,value in {0:0x53364E36,4:1,8:512,12:3,16:0x504C4154,
                             64:0x80000000,68:0x80000000,92:0x411FD221,
                             96:0x34240000,100:0x34240000,104:0x34200000,
                             108:0x40000,112:0x34240000,116:0x4000,
                             120:145457,124:0x534D3031}.items():self.set(offset,value)
        self.raw[352:417]=b'22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d\0'
        self.raw[417:482]=b'cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec\0'
        self.logit_words=(0x80000000,0x00000001,0xBF800000,0x40400000,0x40A00000)
    def set(self,offset,value):struct.pack_into('<I',self.raw,offset,value)
    def word(self,offset):return struct.unpack_from('<I',self.raw,offset)[0]
    def read(self,address,size):
        assert (address,size)==(BASE,512)
        self.reads+=1
        if self.read_hook:self.read_hook(self)
        return bytes(self.raw)
    def write(self,address,data):
        self.writes.append((address,bytes(data)))
        offset=address-BASE;self.raw[offset:offset+len(data)]=data
        if self.write_hook:self.write_hook(self,address,data)
        if offset==20:
            self.committed=True
            if self.reply:
                for off,value in {12:5,24:self.word(20),40:5,44:0,76:self.word(32),80:123}.items():self.set(off,value)
                self.raw[48:76]=bytes(28)
                self.raw[320:340]=struct.pack('<5I',*self.logit_words)
                if self.post:self.post(self)
        return len(data)
    def mailbox(self,**kwargs):return p.Mailbox(self.read,self.write,clock=lambda:self.now,sleep=lambda _:None,**kwargs)


def test_two_requests_exact_raw_all_outputs_and_no_platform_write():
    d=Device();m=d.mailbox();inputs=struct.pack('<41I',*([0x80000000]+[0x00000001]*40))
    a=m.infer(0xffffffff,inputs);b=m.infer(0,inputs)
    assert (a['sequence'],b['sequence'])==(1,2)
    assert a['output_hex']==struct.pack('<5I',*d.logit_words).hex()
    assert a['row_id']==0xffffffff and b['row_id']==0
    assert a['input_hex']==inputs.hex()
    assert [address-BASE for address,_ in d.writes]==[28,128,20,28,128,20]
    assert all(a[k] is False for k in ('npu_execution_independently_verified','latency_validated','energy_measured'))


def test_deadline_crossed_inside_final_snapshot_is_not_accepted():
    d=Device();m=d.mailbox()
    def elapsed(dev):
        if dev.committed:dev.now+=3.0
    d.read_hook=elapsed
    with pytest.raises((p.ProtocolError,TimeoutError)):m.infer(19,bytes(164),timeout_seconds=5)
    assert m.failed and len(d.writes)==3


def test_staged_last_word_changed_no_commit():
    d=Device();m=d.mailbox()
    def corrupt(dev,address,data):
        if address==BASE+128:dev.raw[288]^=1
    d.write_hook=corrupt
    with pytest.raises(p.ProtocolError):m.infer(5,bytes(164))
    assert len(d.writes)==2 and not d.committed and m.failed


def test_incomplete_commit_wrong_row_status_and_last_logit_rejected():
    for offset,value in ((12,4),(40,4),(76,8),(64,1),(72,1),(336,0x7f800000),(288,1),(124,0)):
        d=Device();d.post=lambda dev,o=offset,v=value:dev.set(o,v);m=d.mailbox()
        with pytest.raises(p.ProtocolError):m.infer(7,bytes(164))
        before=list(d.writes)
        with pytest.raises(p.ProtocolError):m.infer(8,bytes(164))
        assert d.writes==before and m.failed


def test_ready_is_not_inferred_from_wait_or_wrong_placement():
    for offset,value in ((12,1),(16,0),(96,0x342e0000),(104,0x71000000),(120,145472),(0,0x56354e36)):
        d=Device();d.set(offset,value);m=d.mailbox()
        with pytest.raises(p.ProtocolError):m.infer(1,bytes(164))
        assert not d.writes


def test_partial_commit_uncertainty_poisoned_without_retry():
    d=Device()
    def write(address,data):
        n=d.write(address,data)
        return None if address==BASE+20 else n
    m=p.Mailbox(d.read,write,clock=lambda:0,sleep=lambda _:None)
    with pytest.raises(p.ProtocolError):m.infer(11,bytes(164))
    assert d.committed and len(d.writes)==3 and m.events[-1]['completed'] is False
    with pytest.raises(p.ProtocolError):m.infer(12,bytes(164))
    assert len(d.writes)==3


def test_transport_exception_after_commit_poisoned():
    d=Device()
    def read(address,size):
        if d.committed:raise OSError('read transport gone')
        return d.read(address,size)
    m=p.Mailbox(read,d.write,clock=lambda:0,sleep=lambda _:None)
    with pytest.raises(OSError):m.infer(3,bytes(164))
    assert m.failed and len(d.writes)==3
    with pytest.raises(p.ProtocolError):m.infer(4,bytes(164))
    assert len(d.writes)==3


def test_unstable_snapshot_bounded_no_write():
    d=Device();d.read_hook=lambda dev:dev.set(80,dev.reads)
    m=d.mailbox()
    with pytest.raises(TimeoutError):m.infer(1,bytes(164))
    assert d.reads==16 and not d.writes


def test_sequence_exhausted_and_poll_limit_fail_closed():
    d=Device();d.set(12,5);d.set(20,0xffffffff);d.set(24,0xffffffff);d.raw[64:72]=bytes(8);m=d.mailbox()
    with pytest.raises(p.ProtocolError):m.infer(1,bytes(164))
    assert not d.writes
    d=Device();d.reply=False;m=d.mailbox()
    with pytest.raises(TimeoutError):m.infer(1,bytes(164),max_polls=2)
    assert len(d.writes)==3 and m.failed


def test_bad_scalar_input_rejected_before_transport():
    for row,raw in ((True,bytes(164)),(-1,bytes(164)),(1,bytearray(164)),(1,bytes(160)),
                    (1,bytes(160)+struct.pack('<I',0x7fc00001))):
        d=Device();m=d.mailbox()
        with pytest.raises(p.ProtocolError):m.infer(row,raw)
        assert d.reads==0 and not d.writes
