"""Tiny RAM and stub pyOCD providers only. Never enumerate/open real devices."""
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace

import pytest

HERE=Path(__file__).resolve().parent
def module(name,file):
    s=importlib.util.spec_from_file_location(name,HERE/file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
loader=module('independent_ram_loader','ram_loader.py')
backend=module('independent_pyocd_backend','pyocd_backend.py')


class RAM:
    def __init__(self):self.memory={};self.writes=[];self.reads=[];self.short_write=False;self.corrupt_prior=False
    def entry_snapshot(self):return {'pc':0x34064061,'control':0,'halted':True}
    def read(self,a,n):
        self.reads.append((a,n));return bytes(self.memory.get(a+i,0xCC) for i in range(n))
    def write(self,a,raw):
        self.writes.append((a,raw));self.memory.update({a+i:v for i,v in enumerate(raw)})
        if self.corrupt_prior and a==0x34200000:self.memory[0x34064000]^=1
        return None if self.short_write else len(raw)


def test_all_backups_before_any_write_and_multichunk_readback():
    c=RAM();backups=[];events=[];regions=((0x34064000,b'X'*4101),(0x34200000,b'W'*17))
    def retain(a,raw):
        assert not c.writes;assert raw==bytes([0xCC])*len(raw);backups.append((a,raw))
    result=loader.load_and_verify(c,regions,retain,events)
    assert [len(raw) for _,raw in backups]==[4101,17]
    assert [len(raw) for _,raw in c.writes]==[4096,5,17]
    assert sum(e.get('verified') is True for e in events)==3
    assert result=={'ram_payload_readback_matched':True,'regions':2,'target_started':False,'model_executed':False,'energy_measured':False}


def test_second_backup_persistence_failure_no_payload_write():
    c=RAM();count=[]
    def retain(a,raw):
        count.append(a)
        if len(count)==2:raise OSError('durable backup unavailable')
    with pytest.raises(OSError):loader.load_and_verify(c,((0x34064000,b'ab'),(0x34200000,b'cd')),retain,[])
    assert len(count)==2 and not c.writes


def test_ambiguous_write_retains_attempt_and_does_not_retry():
    c=RAM();c.short_write=True;events=[]
    with pytest.raises(ValueError):loader.load_and_verify(c,((0x34064000,b'ab'),),lambda *_:None,events)
    assert len(c.writes)==1 and events[-1]['attempted'] is True and events[-1]['verified'] is False


def test_later_real_readback_corruption_rejected_by_full_pass():
    c=RAM();c.corrupt_prior=True;events=[]
    with pytest.raises(ValueError,match='Final RAM readback'):
        loader.load_and_verify(c,((0x34064000,b'ab'),(0x34200000,b'cd')),lambda *_:None,events)
    assert len(c.writes)==2 and all(e['verified'] for e in events if e['operation']=='write_readback')


@pytest.fixture
def fake_target(monkeypatch):
    target=ModuleType('pyocd.core.target');target.Target=SimpleNamespace(SecurityState=SimpleNamespace(SECURE=17))
    monkeypatch.setitem(sys.modules,'pyocd.core.target',target)
    monkeypatch.setitem(sys.modules,'ram_loader',loader)
    class Target:
        def __init__(self):
            self.halted=True;self.security=17;self.registers={'control':0,'xpsr':1<<24,'pc':0x34180401,'msp':0x3418B000,'primask':1}
            self.ppb={0xE000ED14:0,0xE000ED00:0x411FD221,0xE000EE08:1<<16}
            self.writes=[];self.resumed=False;self.bad_msp=False
        def is_halted(self):return self.halted
        def get_security_state(self):return self.security
        def read_core_register_raw(self,n):return self.registers[n] ^ (8 if self.bad_msp and n=='msp' and self.writes else 0)
        def read32(self,a):return self.ppb[a]
        def write_core_register_raw(self,n,v):self.writes.append((n,v));self.registers[n]=v
        def flush(self):pass
        def resume(self):self.resumed=True
    return Target


def test_backend_start_exact_registers_and_bad_readback_no_resume(fake_target):
    t=fake_target();backend.Core(t).start_loaded_image(0x34064061,0x340F8000)
    assert t.writes==[('primask',1),('msp',0x340F8000),('pc',0x34064061)] and t.resumed
    t=fake_target();t.bad_msp=True
    with pytest.raises(RuntimeError,match='readback'):backend.Core(t).start_loaded_image(0x34064061,0x340F8000)
    assert not t.resumed


def test_backend_bad_context_or_image_stack_never_writes(fake_target):
    mutations=[lambda t:setattr(t,'halted',False),lambda t:setattr(t,'security',0),
               lambda t:t.registers.update(control=1),lambda t:t.registers.update(xpsr=(1<<24)|3),
               lambda t:t.ppb.update({0xE000ED14:1<<16}),lambda t:t.ppb.update({0xE000EE08:0})]
    for mutation in mutations:
        t=fake_target();mutation(t)
        with pytest.raises(RuntimeError):backend.Core(t).start_loaded_image(0x34064061,0x340F8000)
        assert not t.writes and not t.resumed
    for entry,msp in ((0x71000001,0x340F8000),(0x34064060,0x340F8000),(0x34064061,0x3418B000),(0x34180401,0x340F8000)):
        t=fake_target()
        with pytest.raises(RuntimeError):backend.Core(t).start_loaded_image(entry,msp)
        assert not t.writes and not t.resumed


def test_backend_forbidden_writes_before_provider(monkeypatch):
    monkeypatch.setitem(sys.modules,'ram_loader',loader)
    for address in (0x08000000,0x71000000,0xE000ED88,0x580E0000,0x34244000):
        with pytest.raises(RuntimeError):backend.Core(None).write(address,b'abcd')


def test_session_options_are_explicit_and_script_not_ambient(tmp_path,monkeypatch):
    script=tmp_path/'empty_user_script.py';script.write_bytes(b'# Intentionally empty, explicitly selected pyOCD user script. No hooks.\n')
    monkeypatch.setattr(backend,'HERE',tmp_path)
    o=backend.session_options()
    for k in ('auto_unlock','resume_on_disconnect','pack.debug_sequences.enable','cache.enable_memory','cache.enable_register','cache.read_code_from_elf','enable_swv'):assert o[k] is False
    assert o['connect_mode']=='attach' and o['no_config'] is True and o['project_dir']==str(tmp_path)
    assert o['user_script']==str(script) and o['target_override']=='stm32n657x0hxq'
    script.write_bytes(b'raise Exception("ambient hook")\n')
    with pytest.raises(RuntimeError):backend.session_options()


def test_exact_probe_and_session_close_on_open_failure(tmp_path,monkeypatch):
    script=tmp_path/'empty_user_script.py';script.write_bytes(b'# Intentionally empty, explicitly selected pyOCD user script. No hooks.\n')
    pack=tmp_path/'fixed.pack';pack.write_bytes(b'pinned synthetic pack')
    monkeypatch.setattr(backend,'HERE',tmp_path);monkeypatch.setattr(backend,'PACK',pack)
    monkeypatch.setattr(backend,'PACK_SHA',hashlib.sha256(pack.read_bytes()).hexdigest())
    probes=[SimpleNamespace(unique_id='004000183234510E37333934')];actions=[]
    helpers=ModuleType('pyocd.core.helpers')
    def enumerate_mock(*,blocking):assert blocking is False;actions.append('enumerate');return probes
    helpers.ConnectHelper=SimpleNamespace(get_all_connected_probes=enumerate_mock)
    sessions=ModuleType('pyocd.core.session')
    class Session:
        def __init__(self,probe,auto_open,options):assert probe is probes[0] and auto_open is False;actions.append('construct')
        def open(self):actions.append('open');raise OSError('synthetic open failure')
        def close(self):actions.append('close')
    sessions.Session=Session
    monkeypatch.setitem(sys.modules,'pyocd.core.helpers',helpers);monkeypatch.setitem(sys.modules,'pyocd.core.session',sessions)
    with pytest.raises(OSError):
        with backend.attach_exact_probe():raise AssertionError('must not yield')
    assert actions==['enumerate','construct','open','close']
    probes.append(SimpleNamespace(unique_id='004000183234510E37333934'));actions.clear()
    with pytest.raises(RuntimeError):
        with backend.attach_exact_probe():raise AssertionError('must not yield')
    assert actions==['enumerate']
