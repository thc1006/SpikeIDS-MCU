"""Host C stage report -> real host decoder cross-check; synthetic MMIO only."""
import importlib.util
from pathlib import Path
import struct
import sys

import pytest
from test_platform_stage_independent import function, Registers

HOST=Path(__file__).resolve().parent.parent/'host_sram'
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
protocol=load('stage_cross_protocol',HOST/'protocol.py')
old=sys.modules.get('protocol');sys.modules['protocol']=protocol
try:stage=load('stage_cross_decoder',HOST/'stage_protocol.py')
finally:
    if old is None:sys.modules.pop('protocol',None)
    else:sys.modules['protocol']=old


def actual_report_fixture(function):
    d=Registers();ok,report=d.invoke(function);assert ok==1
    raw=bytearray(4096)
    for offset,value in {0:0x4e365349,4:1,8:4096,12:2,16:2,48:0x411fd221,104:1}.items():
        struct.pack_into('<I',raw,offset,value)
    raw[128:2496]=struct.pack('<592I',*report)
    return d,raw


def test_real_portable_c_report_consumed_by_real_host_decoder(function):
    d,raw=actual_report_fixture(function);s=stage.decode(bytes(raw))
    assert s['nominal_cpu_npu_hz']==64000000 and s['sequence']==2 and s['heartbeat']==0
    observed=stage.live_register_check(lambda a,n:struct.pack('<I',d.values.get(a,0)),s)
    assert observed[0x54024c14]==0x80000310
    def read(a,n):return bytes(raw[a-0x34188000:a-0x34188000+n])
    def write(a,b):
        assert a==0x34188018 and len(b)==4
        raw[24:28]=raw[28:32]=b;struct.pack_into('<2I',raw,16,4,1);return 4
    answer=stage.challenge(read,write,0x12345678)
    assert (answer['sequence'],answer['heartbeat'],answer['echo_nonce'])==(4,1,0x12345678)


def test_live_last_risaf_subregion_corruption_rejected(function):
    d,raw=actual_report_fixture(function);s=stage.decode(bytes(raw))
    d.values[0x5402b000+0x40+10*0x40+0x20]=1
    with pytest.raises(protocol.ProtocolError):stage.live_register_check(lambda a,n:struct.pack('<I',d.values.get(a,0)),s)


def test_one_nonce_cannot_claim_two_publications(function):
    _,raw=actual_report_fixture(function)
    def read(a,n):return bytes(raw[a-0x34188000:a-0x34188000+n])
    def write(a,b):
        assert a==0x34188018;raw[24:28]=raw[28:32]=b
        struct.pack_into('<2I',raw,16,6,2);return 4
    with pytest.raises(protocol.ProtocolError):stage.challenge(read,write,0x11223344)
