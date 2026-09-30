import importlib.util
from pathlib import Path
import struct
import sys
import pytest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent/'host_sram'))
import runtime_protocol as rp
import controller
import protocol,orchestrate,ram_loader,validation,stage_protocol
from test_orchestrate import Core as OldCore,Sink,payloads
from test_protocol import ready

MODULES=dict(protocol=protocol,orchestrate=orchestrate,ram_loader=ram_loader,
             validation=validation,stage_protocol=stage_protocol)


def message(state=3):
    raw=ready();struct.pack_into('<I',raw,124,rp.TAG);struct.pack_into('<I',raw,12,state)
    if state!=1:struct.pack_into('<3I',raw,292,rp.RECEIPT,0,1)
    return bytes(raw)


@pytest.mark.parametrize('state',range(1,8))
def test_wire_identity_and_no_output_normalization(state):
    raw=message(state);words=rp.decode(raw,protocol.decode)
    assert struct.pack('<128I',*words)==raw
    with pytest.raises(ValueError):protocol.decode(raw)


@pytest.mark.parametrize('state',[3,4,5])
@pytest.mark.parametrize('word,value',[(31,0x534d3031),(73,0),(74,1),(74,0x80000000),(75,0),(75,2),(76,1),(127,1)])
def test_missing_failed_repeated_or_wrong_receipts(state,word,value):
    raw=bytearray(message(state));struct.pack_into('<I',raw,word*4,value)
    with pytest.raises(ValueError):rp.decode(bytes(raw),protocol.decode)


def test_runtime_before_ack_rejected():
    raw=bytearray(message(1));struct.pack_into('<I',raw,292,rp.RECEIPT)
    with pytest.raises(ValueError):rp.decode(bytes(raw),protocol.decode)


class Core(OldCore):
    def __init__(self):
        super().__init__();self.core=self;self.irq=1;self.bus=1;self.receipt=True;self.break_after=False
    def entry_snapshot(self):
        super().entry_snapshot()
        return dict(primask=self.irq,pc=0x34064070,msp=0x340f7d70)
    def start_loaded_image(self,entry,msp):
        super().start_loaded_image(entry,msp)
        if entry<0x34100000:self.put(protocol.ADDRESS+124,struct.pack('<I',rp.TAG))
    def resume_from_halt(self):
        super().resume_from_halt()
        if self.receipt:self.put(protocol.ADDRESS+292,struct.pack('<3I',rp.RECEIPT,0,1))
    def read32(self,address):
        assert not self.running
        n=struct.unpack('<I',self.read(protocol.ADDRESS+24,4))[0]
        return 0 if self.break_after and n==1024 else self.bus


def run(c,s):
    f,p=payloads()
    f['segments']=((0x34064000,bytes(256)),)
    return controller.run_connected(c,f,p,s,nonce=31,modules=MODULES)


def test_full_1024_rows_preserve_raw_new_receipt():
    c,s=Core(),Sink();result=run(c,s)
    assert result['completed_rows']==1024 and not result['energy_measured']
    assert not c.running and s.files['completion_state.json']['halt_error'] is None
    assert bytes.fromhex(s.files['row_1023.json']['raw_mailbox_hex'])[292:304]==struct.pack('<3I',rp.RECEIPT,0,1)
    assert 'final_mailbox.bin' in s.files and 'runtime_live_after_validation.json' in s.files


@pytest.mark.parametrize('field,value',[('irq',0),('bus',0),('receipt',False)])
def test_bad_runtime_never_commits_request(field,value):
    c,s=Core(),Sink();setattr(c,field,value)
    with pytest.raises((ValueError,RuntimeError)):run(c,s)
    assert not any(a==protocol.ADDRESS+20 for a,_ in c.writes)
    assert not c.running and 'final_mailbox.bin' in s.files
    if field!='receipt':assert 'runtime_live_before_inference.json' in s.files


def test_postrun_mmio_failure_not_accepted_or_repaired():
    c,s=Core(),Sink();c.break_after=True
    with pytest.raises(RuntimeError):run(c,s)
    assert len(s.files['completion_state.json']['completed_row_ids'])==1024
    assert s.files['runtime_live_after_validation.json']['registers']['0x580e2000']==0
    assert not c.running


def test_receipt_retention_failure_no_request():
    c,s=Core(),Sink();original=s.json
    def fail(name,value):
        if name=='runtime_live_before_inference.json':raise OSError('disk')
        original(name,value)
    s.json=fail
    with pytest.raises(OSError):run(c,s)
    assert not any(a==protocol.ADDRESS+20 for a,_ in c.writes)
    assert not c.running
