"""Offline host-C execution of the exact portable sequence; no ARM/USB access.

MMIO semantics are synthetic, not a chip oracle. Target assembly/barriers are
reviewed statically; ARM compile/link/disassembly is a separate required check.
"""
import ctypes as c
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
U=c.c_uint32
READ=c.CFUNCTYPE(U,c.c_void_p,U)
WRITE=c.CFUNCTYPE(None,c.c_void_p,U,U)
BARRIER=c.CFUNCTYPE(None,c.c_void_p)
class IO(c.Structure):
    _fields_=[('context',c.c_void_p),('read32',READ),('write32',WRITE),('barrier',BARRIER)]
class Entry(c.Structure):
    _fields_=[('control',U),('ipsr',U),('primask',U)]
class Observation(c.Structure):
    _fields_=[('address',U),('before',U),('after',U)]
class Report(c.Structure):
    _fields_=[(n,U) for n in ('error','step','failed_address','failed_mask','expected','observed',
      'writes','reads','poll_reads','hsi_divider','nominal_hz','observation_count','source_profile',
      'ready_for_payload','reserved0','reserved1')]+[('observations',Observation*192)]

RCC=0x56028000
CR=RCC;SR=RCC+4;CFGR1=RCC+0x20;CFGR2=RCC+0x24;HSI=RCC+0x48
RESET=RCC+0x220;MEM=RCC+0x24c;AHB2=RCC+0x254;AHB3=RCC+0x258;AHB5=RCC+0x260
SEC=0x5402401c;PRIV=0x5402403c;ATTR=0x54024c14
RIF=0x54024000;LOCK=RIF+0x5c;MASTER=RIF+0xc00
RAM=0x52023100;CACHE=0x580dfc00;CCR=0xe000ed14;MPU=0xe000ed94;SAU=0xe000edd0
ALIASES={a+0x800:(a,True) for a in (CR,RESET,MEM,AHB2,AHB3,AHB5)}
ALIASES.update({a+0x1000:(a,False) for a in (CR,RESET,MEM,AHB2,AHB3,AHB5)})
DIRECT={CFGR1,CFGR2,SEC,PRIV,ATTR,RAM}

class Device:
    def __init__(self,initial=None,ignore=None,no_hsi=False,no_cpu=False,no_sys=False,late=None):
        self.reg={CFGR1:0x33330000,CFGR2:0x03777077,RAM:0x100040,
                  MEM:0x20,AHB2:1,AHB3:1,AHB5:1,SEC:1,PRIV:2,ATTR:0x80000000}
        self.reg.update(initial or {})
        self.ignore=ignore;self.no_hsi=no_hsi;self.no_cpu=no_cpu;self.no_sys=no_sys;self.late=late
        self.writes=[];self.barriers=0;self.errors=[]
        def read(_,a):return self.reg.get(a,0)
        def write(_,a,v):
            self.writes.append((a,v))
            if a not in ALIASES and a not in DIRECT:self.errors.append(('forbidden write',a))
            if a==self.ignore:return
            if a in ALIASES:
                target,add=ALIASES[a]
                self.reg[target]=(self.reg.get(target,0)|v) if add else (self.reg.get(target,0)&~v)
                if target==CR and add and not self.no_hsi:self.reg[SR]=8
                if target==RESET and not add and v&0x40000000:self.reg[CACHE]=0
                if target==RESET and not add and v&0x80000000 and self.late:self.late(self)
            else:
                self.reg[a]=v
                if a==CFGR1:
                    if not self.no_cpu:self.reg[a]=(self.reg[a]&~0x00300000)|((v&0x00030000)<<4)
                    if not self.no_sys:self.reg[a]=(self.reg[a]&~0x30000000)|((v&0x03000000)<<4)
        def barrier(_):self.barriers+=1
        self.callbacks=(READ(read),WRITE(write),BARRIER(barrier));self.io=IO(None,*self.callbacks)

class PlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files=[HERE/n for n in ('platform_init.c','platform_init.h','main.c','startup.c','mailbox.h',
                                      'linker.ld','ABI.json','test_platform_init.py')]
        cls.before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in cls.files}
        cls.tmp=tempfile.TemporaryDirectory(prefix='n6-platform-host-c-')
        lib=Path(cls.tmp.name)/'platform.so'
        args=['/usr/bin/cc','-std=c11','-Wall','-Wextra','-Werror','-O2','-fPIC','-shared',
              '-ffreestanding','-fno-builtin',str(HERE/'platform_init.c'),'-o',str(lib)]
        completed=subprocess.run(args,capture_output=True,text=True,timeout=30,
                                 env={'PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C'})
        print(json.dumps({'host_compile_argv':args,'actual_return_code':completed.returncode,
                          'stdout':completed.stdout,'stderr':completed.stderr}))
        if completed.returncode:raise RuntimeError('host C compilation failed')
        cls.lib=c.CDLL(str(lib));cls.fn=cls.lib.platform_init
        cls.fn.argtypes=[c.POINTER(IO),c.POINTER(Entry),c.POINTER(Report)];cls.fn.restype=c.c_int
    @classmethod
    def tearDownClass(cls):
        after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in cls.files}
        if cls.before!=after:raise AssertionError('source/test changed')
        print(json.dumps({'source_bookends':after,'bookends_equal':True,'target_accessed':False}))
        cls.tmp.cleanup()
    def invoke(self,dev=None,entry=None):
        dev=dev or Device();r=Report();entry=entry or Entry(0,0,1)
        ok=self.fn(c.byref(dev.io),c.byref(entry),c.byref(r))
        self.assertEqual(dev.errors,[])
        self.assertLessEqual(r.observation_count,192)
        self.assertEqual(bool(ok),bool(r.ready_for_payload))
        return dev,r,ok
    def test_div1_positive_and_exact_write_scope(self):
        d,r,ok=self.invoke();self.assertEqual(ok,1);self.assertEqual(r.error,0)
        self.assertEqual(r.nominal_hz,64000000);self.assertGreater(d.barriers,0)
        self.assertEqual(d.reg[ATTR],0x80000310);self.assertEqual(d.reg[MEM],0x21)
        self.assertEqual(d.reg[CFGR2],0x03100000);self.assertEqual(d.reg[RESET]&0xc0000000,0)
        self.assertEqual(d.reg[RAM],0x40)
        self.assertTrue(all(a in ALIASES or a in DIRECT for a,v in d.writes))
        self.assertTrue(all(a not in (CR,RESET,MEM,AHB2,AHB3,AHB5,HSI) for a,v in d.writes))
    def test_div2_preserved(self):
        d,r,ok=self.invoke(Device({HSI:0x4480}));self.assertEqual(ok,1)
        self.assertEqual(d.reg[HSI],0x4480);self.assertEqual(r.nominal_hz,32000000)
    def test_entry_rejections_before_writes(self):
        for e in (Entry(1,0,1),Entry(2,0,1),Entry(0,3,1),Entry(0,0,0)):
            with self.subTest(entry=tuple(getattr(e,n) for n,_ in e._fields_)):
                d,r,ok=self.invoke(entry=e);self.assertFalse(ok);self.assertEqual(r.error,2);self.assertEqual(d.writes,[])
    def test_cache_mpu_sau_divider_refuse(self):
        for a,v,error in ((CCR,0x10000,3),(CCR,0x20000,3),(MPU,1,4),(SAU,1,4),(SAU,2,4),(HSI,0x100,5),(HSI,0x180,5)):
            with self.subTest(address=a,value=v):
                d,r,ok=self.invoke(Device({a:v}));self.assertFalse(ok);self.assertEqual(r.error,error);self.assertEqual(d.writes,[])
    def test_risaf_all_ports_and_subregions_refuse(self):
        for base,count in ((0x54027000,7),(0x54028000,7),(0x54029000,11),(0x5402a000,11),(0x5402b000,11),(0x54034000,2)):
            for off in (0,0x10,0x20):
                with self.subTest(base=base,offset=off):
                    d,r,ok=self.invoke(Device({base+0x40+(count-1)*0x40+off:1}))
                    self.assertFalse(ok);self.assertEqual(r.error,6)
                    self.assertFalse(any(a in (SEC,PRIV,ATTR) for a,v in d.writes))
    def test_existing_rif_error_not_cleared(self):
        d,r,ok=self.invoke(Device({0x54029008:1}));self.assertFalse(ok);self.assertEqual(r.error,11)
        self.assertEqual(d.reg[0x54029008],1)
    def test_incompatible_locks_refuse(self):
        for a,v in ((RIF,1),(LOCK,0x400),(MASTER,1)):
            with self.subTest(lock=a):
                d,r,ok=self.invoke(Device({a:v}));self.assertFalse(ok);self.assertEqual(r.error,7)
    def test_compatible_locked_attributes_no_writes(self):
        d,r,ok=self.invoke(Device({RIF:1,LOCK:0x400,MASTER:1,SEC:0x400,PRIV:0x400,ATTR:0x310}))
        self.assertEqual(ok,1);self.assertFalse(any(a in (SEC,PRIV,ATTR) for a,v in d.writes))
    def test_reset_before_security_attribution(self):
        d,r,ok=self.invoke();self.assertEqual(ok,1)
        reset_index=next(i for i,(a,v) in enumerate(d.writes) if a==RESET+0x800 and v&0x80000000)
        for a in (SEC,PRIV,ATTR):
            self.assertLess(reset_index,next(i for i,(address,v) in enumerate(d.writes) if address==a))
    def test_missing_readback_refuses(self):
        for a in (AHB2+0x800,AHB3+0x800,SEC,PRIV,ATTR,AHB5+0x800,RESET+0x800,CR+0x800,CFGR1,CFGR2,MEM+0x800,RAM,RESET+0x1000):
            with self.subTest(ignore=a):
                d,r,ok=self.invoke(Device(ignore=a));self.assertFalse(ok);self.assertIn(r.error,(8,9))
    def test_waits_are_bounded_without_tick(self):
        for name in ('no_hsi','no_cpu','no_sys'):
            with self.subTest(wait=name):
                d,r,ok=self.invoke(Device(**{name:True}));self.assertFalse(ok);self.assertEqual(r.error,9)
                self.assertGreaterEqual(r.poll_reads,65536);self.assertLessEqual(r.poll_reads,65538)
    def test_late_state_changes_refused(self):
        for a,v in ((SEC,0),(ATTR,0),(HSI,0x80),(MEM,0),(RAM,0x100000),(CACHE,1),
                    (CCR,0x10000),(0x5402b000+0x40,1),(0x5402b008,1)):
            with self.subTest(late=a):
                d,r,ok=self.invoke(Device(late=lambda d,a=a,v=v:d.reg.__setitem__(a,v)))
                self.assertFalse(ok)
    def test_abi_and_target_barriers_static(self):
        abi=json.loads((HERE/'ABI.json').read_bytes())
        self.assertEqual(c.sizeof(Report),2368);self.assertEqual(abi['mailbox_address'],0x34188000)
        self.assertEqual(abi['struct_bytes'],4096);self.assertEqual(abi['offsets']['platform'],128)
        main=(HERE/'main.c').read_text();startup=(HERE/'startup.c').read_text()
        self.assertIn('__DSB(); __ISB();',main);self.assertIn('dsb\\n isb',startup)
        self.assertIn('platform_init(&io,&entry,&g_stage.platform)',main)
        self.assertIn('stage_main',startup)
        self.assertIn('if (nonce!=g_stage.echo_nonce)',main)
        self.assertIn('fresh_nonce_only',abi['liveness_publication'])

if __name__=='__main__':unittest.main(verbosity=2)
