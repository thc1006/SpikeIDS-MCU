import importlib.util
from pathlib import Path
import struct
import sys
import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('sm03_launcher',HERE/'run.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
sys.path.insert(0,str(HERE.parent/'host_sram_runtime'))
import test_runtime_host as fixture


@pytest.fixture
def bound():return launcher.bindings()


def test_private_modules_do_not_change_old_identity(bound):
    _,_,_,controller,rp=bound
    assert rp.TAG==0x534d3033 and fixture.rp.TAG==0x534d3032
    assert sys.modules['runtime_protocol'] is fixture.rp
    assert controller.decode is rp.decode


@pytest.mark.parametrize('old_tag',[0x534d3031,0x534d3032])
def test_old_payload_rejected(bound,old_tag):
    _,m,_,_,rp=bound
    raw=bytearray(fixture.message());struct.pack_into('<I',raw,124,old_tag)
    with pytest.raises(ValueError):rp.decode(bytes(raw),m['protocol'].decode)


@pytest.mark.parametrize('state',range(1,8))
def test_sm03_raw_fields_retained_old_host_rejects(bound,state):
    _,m,_,_,rp=bound
    raw=bytearray(fixture.message(state));struct.pack_into('<I',raw,124,0x534d3033)
    assert struct.pack('<128I',*rp.decode(bytes(raw),m['protocol'].decode))==raw
    with pytest.raises(ValueError):fixture.rp.decode(bytes(raw),m['protocol'].decode)


@pytest.mark.parametrize('word,value',[(73,0),(74,1),(75,2),(76,1),(127,1)])
def test_new_tag_does_not_bypass_existing_receipts(bound,word,value):
    _,m,_,_,rp=bound
    raw=bytearray(fixture.message());struct.pack_into('<I',raw,124,0x534d3033)
    struct.pack_into('<I',raw,4*word,value)
    with pytest.raises(ValueError):rp.decode(bytes(raw),m['protocol'].decode)


class Core(fixture.Core):
    def start_loaded_image(self,entry,msp):
        super().start_loaded_image(entry,msp)
        if entry<0x34100000:self.put(fixture.protocol.ADDRESS+124,struct.pack('<I',0x534d3033))


@pytest.mark.parametrize('bad',['none','irq','bus','receipt','post','retention'])
def test_full_flow_and_adversarial_gates(bound,bad):
    _,_,_,controller,_=bound
    c,s=Core(),fixture.Sink();f,p=fixture.payloads();f['segments']=((0x34064000,bytes(256)),)
    if bad in ['irq','bus','receipt']:setattr(c,bad,0 if bad!='receipt' else False)
    if bad=='post':c.break_after=True
    if bad=='retention':
        original=s.json
        def retain(name,value):
            if name=='runtime_live_before_inference.json':raise OSError('disk')
            original(name,value)
        s.json=retain
    call=lambda:controller.run_connected(c,f,p,s,nonce=31,modules=fixture.MODULES)
    if bad=='none':
        r=call();assert r['completed_rows']==1024 and not r['energy_measured']
        assert struct.unpack_from('<I',bytes.fromhex(s.files['row_1023.json']['raw_mailbox_hex']),124)[0]==0x534d3033
    else:
        with pytest.raises((ValueError,RuntimeError,OSError)):call()
        if bad!='post':assert not any(a==fixture.protocol.ADDRESS+20 for a,_ in c.writes)
    assert not c.running and s.files['completion_state.json']['halt_error'] is None


def test_real_fixed_bundle_offline_only(bound):
    old,m,_,_,rp=bound
    f=old.load_variant(m)
    assert len(f['rows'])==1024 and old.BUILD==launcher.BUILD and rp.TAG==0x534d3033
