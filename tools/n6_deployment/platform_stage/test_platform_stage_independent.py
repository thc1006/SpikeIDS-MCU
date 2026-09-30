"""Independent literal MMIO oracle, host C only; no ARM tools or target."""
import ctypes as c
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

HERE=Path(__file__).resolve().parent
U=c.c_uint32
READ=c.CFUNCTYPE(U,c.c_void_p,U)
WRITE=c.CFUNCTYPE(None,c.c_void_p,U,U)
BARRIER=c.CFUNCTYPE(None,c.c_void_p)
class IO(c.Structure):
    _fields_=[('context',c.c_void_p),('read',READ),('write',WRITE),('barrier',BARRIER)]


@pytest.fixture(scope='module')
def function(tmp_path_factory):
    srcs=[HERE/n for n in ('platform_init.c','platform_init.h','main.c','startup.c','mailbox.h','linker.ld','ABI.json','build.py')]
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in srcs}
    lib=tmp_path_factory.mktemp('platform_independent')/'sequence.so'
    args=['/usr/bin/cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-fPIC','-shared','-ffreestanding','-fno-builtin',str(HERE/'platform_init.c'),'-o',str(lib)]
    child=subprocess.run(args,capture_output=True,timeout=30,env={'PATH':'/usr/bin:/bin','LC_ALL':'C'})
    assert child.returncode==0,child.stderr.decode()
    library=c.CDLL(str(lib));fn=library.platform_init
    fn.argtypes=[c.POINTER(IO),c.POINTER(U),c.POINTER(U)];fn.restype=c.c_int
    yield fn
    assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in srcs}


class Registers:
    def __init__(self,divider=0,ignore=None,stall_hsi=False):
        self.values={0x56028020:0x22220000,0x56028024:0x80777077,0x56028048:0x4200|divider,
                     0x5602824c:0x20,0x52023100:0x100040,0x5402401c:8,
                     0x5402403c:16,0x54024c14:0x80000000,0x580dfc00:1}
        self.events=[];self.violations=[];self.ignore=ignore;self.stall_hsi=stall_hsi
        self.aliases={}
        for a in (0x56028000,0x56028220,0x5602824c,0x56028254,0x56028258,0x56028260):
            self.aliases[a+0x800]=(a,True);self.aliases[a+0x1000]=(a,False)
        self.allowed_direct={0x56028020,0x56028024,0x52023100,0x5402401c,0x5402403c,0x54024c14}
        def read(_,a):
            self.events.append(('read',a,self.values.get(a,0)));return self.values.get(a,0)
        def write(_,a,v):
            self.events.append(('write',a,v))
            if a not in self.aliases and a not in self.allowed_direct:self.violations.append(('write_scope',a))
            if a in (0x5402401c,0x5402403c,0x54024c14) and not self.values.get(0x56028220,0)&0x80000000:
                self.violations.append(('attribution_before_reset',a))
            if a==self.ignore:return
            if a in self.aliases:
                target,set_bits=self.aliases[a];old=self.values.get(target,0)
                self.values[target]=(old|v) if set_bits else (old&~v)
                if target==0x56028000 and not self.stall_hsi:self.values[0x56028004]=self.values[target]&8
                if target==0x56028220 and not set_bits and v&0x40000000:self.values[0x580dfc00]=0
            elif a==0x56028020:
                # SW status bits are not writable; emulate completed clock selection.
                self.values[a]=(v&~0x30300000)|((v&0x03030000)<<4)
            else:self.values[a]=v
        def barrier(_):self.events.append(('barrier',0,0))
        self.callbacks=(READ(read),WRITE(write),BARRIER(barrier));self.io=IO(None,*self.callbacks)
    def invoke(self,fn,entry=(0,0,1)):
        report=(U*592)();args=(U*3)(*entry)
        ok=fn(c.byref(self.io),args,report)
        assert not self.violations
        assert bool(ok)==bool(report[13]) and report[11]<=192
        return ok,list(report)
    @property
    def writes(self):return [(a,v) for op,a,v in self.events if op=='write']


def test_exact_masks_order_and_both_unchanged_hsi_profiles(function):
    for divider,hz in ((0,64000000),(0x80,32000000)):
        d=Registers(divider);ok,r=d.invoke(function)
        assert ok==1 and r[0]==0 and r[1]==12 and r[9:11]==[divider,hz]
        assert d.values[0x56028048]==0x4200|divider
        assert d.values[0x5602824c]==0x21 and d.values[0x52023100]==0x40
        assert d.values[0x5402401c]==0x408 and d.values[0x5402403c]==0x410 and d.values[0x54024c14]==0x80000310
        assert d.values[0x56028024]==0x80100000 and d.values[0x56028220]&0xc0000000==0
        assert d.values[0x580dfc00]==0
        reset=d.events.index(('write',0x56028a20,0x80000000))
        for a in (0x5402401c,0x5402403c,0x54024c14):
            security=next(i for i,e in enumerate(d.events) if e[0]=='write' and e[1]==a)
            assert reset<security and any(op=='read' and addr==0x56028220 and val&0x80000000 for op,addr,val in d.events[reset+1:security])
        assert d.writes[-1]==(0x56029220,0x80000000)
        assert not any(a in (0x56028048,0x56028000,0x56028220,0x5602824c) for a,_ in d.writes)


def test_missing_reset_readback_never_changes_security(function):
    d=Registers(ignore=0x56028a20);ok,r=d.invoke(function)
    assert not ok and r[0]==8 and r[1]==3
    assert not any(a in (0x5402401c,0x5402403c,0x54024c14) for a,_ in d.writes)


def test_context_and_cache_reject_before_writes(function):
    for entry in ((1,0,1),(2,0,1),(0,5,1),(0,0,0)):
        d=Registers();ok,r=d.invoke(function,entry);assert not ok and r[0]==2 and not d.writes
    for address,value in ((0xe000ed14,0x20000),(0xe000ed94,1),(0xe000edd0,2),(0x56028048,0x180)):
        d=Registers();d.values[address]=value;ok,r=d.invoke(function);assert not ok and not d.writes


def test_locked_wrong_attributes_stop_without_unlock_or_release(function):
    for lock in (0x54024000,0x5402405c,0x54024c00):
        d=Registers();d.values[lock]=0x400 if lock==0x5402405c else 1
        ok,r=d.invoke(function);assert not ok and r[0]==7
        assert not any(a==lock for a,_ in d.writes)
        assert (0x56029220,0x80000000) not in d.writes


def test_risaf_last_subregion_and_error_are_not_cleared(function):
    for address in (0x5402b000+0x40+10*0x40+0x20,0x54034008):
        d=Registers();d.values[address]=1;ok,r=d.invoke(function)
        assert not ok and r[0] in (6,11) and d.values[address]==1
        assert not any(a==address for a,_ in d.writes)
        assert not any(a in (0x5402401c,0x5402403c,0x54024c14) for a,_ in d.writes)


def test_hsi_wait_is_iteration_bounded_and_npu_remains_reset(function):
    d=Registers(stall_hsi=True);ok,r=d.invoke(function)
    assert not ok and r[0]==9 and r[8]==65536 and d.values[0x56028220]&0x80000000
    assert not any(a==0x56028020 for a,_ in d.writes)


def test_naked_startup_fault_and_integer_build_source_contract():
    startup=(HERE/'startup.c').read_text();build=(HERE/'build.py').read_text()
    entry=startup.split('void Reset_Handler(void)\n{',1)[1].split('/* Fault status',1)[0]
    assert entry.index('mrs r5,ipsr')<entry.index('tst r1,#3')<entry.index('cpsid i')<entry.index('msr msplim,')<entry.index('msr msp,')<entry.index('str r5,[r4]')<entry.index('b stage_main')
    assert 'msr control' not in entry and '0xe000ed88' not in entry.lower()
    fault=startup.split('void fault_handler(void)\n{',1)[1]
    assert 'orr r1,r1,#1' in fault and 'mrs r2,msp' in fault and 'mrs r2,psp' in fault
    assert 'push' not in fault and 'pop' not in fault and '[sp' not in fault
    assert "'-mfloat-abi=soft','-mgeneral-regs-only'" in build
    assert "'-nostdlib','-nostartfiles','-nodefaultlibs'" in build
    linker=(HERE/'linker.ld').read_text()
    assert 'SIZEOF(.data)==0 && SIZEOF(.bss)==0' in linker


def test_nonce_only_publication_and_literal_memory_abi():
    main=(HERE/'main.c').read_text();body=main.split('for (;;) {',1)[1]
    assert body.index('if (nonce!=g_stage.echo_nonce)')<body.index('g_stage.sequence=odd')<body.index('g_stage.echo_nonce=nonce')<body.index('g_stage.heartbeat++')<body.index('g_stage.sequence=odd+1u')
    assert 'g_stage.sequence=2' in main and '__DSB(); __ISB();' in main
    assert 'g_stage.model_executed=' not in main and 'g_stage.board_accepted=' not in main
    abi=json.loads((HERE/'ABI.json').read_bytes())
    assert (abi['code_start'],abi['code_end_exclusive'],abi['mailbox_address'],abi['stack_start'],abi['stack_top'])==(0x34180400,0x34188000,0x34188000,0x34189000,0x3418b000)
    assert abi['struct_bytes']==4096 and abi['platform_report_bytes']==2368 and abi['offsets']['platform']==128
    assert abi['offsets']['host_nonce']==24 and abi['host_write_bytes']==4
    assert abi['hardware_accepted'] is False and abi['energy_accepted'] is False
