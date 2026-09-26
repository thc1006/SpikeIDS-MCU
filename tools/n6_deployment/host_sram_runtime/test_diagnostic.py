"""Hardware-breakpoint diagnostic controls; fake debug transport only."""
from pathlib import Path
import struct
import sys
import pytest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/'host_sram'))
import diagnose_epochs as d
import protocol
import runtime_protocol as rp
from test_runtime_host import message
from test_orchestrate import Sink


class Core:
    def __init__(self):
        raw=bytearray(message(5));struct.pack_into('<2I',raw,20,1024,1024)
        self.previous=bytes(raw);self.memory={d.ADDRESS+i:b for i,b in enumerate(raw)}
        self.core=self;self.bp={};self.halted=True;self.pc=0x3406436c;self.writes=[]
        self.installed=[];self.badpc=False;self.stuck=False;self.support=True;self.short=False
    def read(self,a,n):return bytes(self.memory.get(a+i,0) for i in range(n))
    def put(self,a,v):self.memory.update({a+i:b for i,b in enumerate(v)})
    def write(self,a,v):
        self.writes.append((a,v));self.put(a,v)
        return len(v)-1 if self.short else len(v)
    def entry_snapshot(self):
        assert self.halted
        return dict(primask=1,pc=self.pc)
    def floating_environment(self):return dict(fpscr=0)
    def is_halted(self):return self.halted
    def halt(self):self.halted=True
    def flush(self):pass
    def get_breakpoint_type(self,a):return self.bp.get(a)
    def set_breakpoint(self,a,t):
        self.installed.append(a)
        if not self.support:return False
        self.bp[a]=t;return True
    def remove_breakpoint(self,a):self.bp.pop(a,None)
    def resume_from_halt(self):
        assert self.halted
        if self.stuck:self.halted=False;return
        w=list(struct.unpack('<128I',self.read(d.ADDRESS,512)))
        if self.bp:
            assert len(self.bp)==1
            self.pc=next(iter(self.bp))+(2 if self.badpc else 0)
            w[3]=4;w[11]=5
        else:
            w[3]=5;w[6]=1025;w[19]=w[8];w[10]=5;w[11]=0
            w[12:19]=[0]*7
        self.put(d.ADDRESS,struct.pack('<128I',*w))


def payload():
    return dict(segments=((0x34064000,bytes(256)),(0x34200000,bytes(16)),(0x34240000,bytes(16))),
                rows=((20,bytes(164),bytes(20)),))


def execute(c,s,**kwargs):
    return d.observe(c,payload(),s,lambda b:rp.decode(b,protocol.decode),'hardware',c.previous,**kwargs)


def test_five_real_engine_stops_cleanup_and_one_commit():
    c,s=Core(),Sink();r=execute(c,s)
    assert r['diagnostic_completed'] and r['research_measurement_accepted'] is False
    assert c.installed==[a for _,a in d.POINTS] and not c.bp and c.halted
    assert [a for a,_ in c.writes]==[d.ADDRESS+28,d.ADDRESS+128,d.ADDRESS+20]
    assert len([n for n in s.files if n.endswith('_activation.bin')])==5


@pytest.mark.parametrize('attribute',['badpc','stuck','short'])
def test_ambiguous_or_unexpected_execution_aborts(attribute):
    c,s=Core(),Sink();setattr(c,attribute,True)
    ticks=iter(range(100))
    with pytest.raises(RuntimeError):execute(c,s,clock=lambda:next(ticks),sleep=lambda _:None)
    assert not c.bp and c.halted
    assert len([a for a,_ in c.writes if a==d.ADDRESS+20])<=1
    assert len(c.installed)==1


def test_no_hardware_breakpoint_no_commit():
    c,s=Core(),Sink();c.support=False
    with pytest.raises(RuntimeError):execute(c,s)
    assert not c.writes and not c.bp and c.halted


@pytest.mark.parametrize('name',['previous_mailbox.bin','live_payload_verified.json','staged_mailbox.bin','after_quantize_activation.bin'])
def test_retention_failure_no_continued_diagnostic(name):
    c,s=Core(),Sink();old=s.raw
    def fail(n,v):
        if n==name:raise OSError('disk failure')
        old(n,v)
    s.raw=fail
    with pytest.raises(OSError):execute(c,s)
    assert not c.bp and c.halted
    if name!='after_quantize_activation.bin':assert not any(a==d.ADDRESS+20 for a,_ in c.writes)
    else:assert len(c.installed)==2


def test_live_payload_mismatch_no_breakpoints_or_writes():
    c,s=Core(),Sink();c.put(0x34200000,b'X')
    with pytest.raises(RuntimeError):execute(c,s)
    assert not c.installed and not c.writes


def test_existing_breakpoint_never_removed():
    c,s=Core(),Sink();c.bp[d.POINTS[2][1]]='hardware'
    with pytest.raises(RuntimeError):execute(c,s)
    assert c.bp=={d.POINTS[2][1]:'hardware'} and not c.writes
