"""Real CLI/Store/protocol with synthetic rows and an opaque serial context.

All fault-injected file writes target pytest temporary sources/output only.
No real archive, enumeration, serial port, compiler or target access is used.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import struct
import zlib

import pytest
import run_esp as r
import serial_transport as transport


def crc(raw):return struct.pack('<I',zlib.crc32(raw))


@pytest.fixture
def evidence(tmp_path,monkeypatch):
    repo=tmp_path/'repo';(repo/'results').mkdir(parents=True)
    src=repo/'host';src.mkdir();own=src/'run_esp.py';own.write_bytes(Path(r.__file__).read_bytes())
    ref=struct.pack('<5f',1,2,3,4,5)
    rows=tuple((2**40+i*7,struct.pack('<41f',*(float(i+j) for j in range(41))),ref) for i in range(1024))
    e=dict(repo=repo,source=own,rows=rows,output=repo/'results'/'actual',events=[],sessions=[],mode=None)
    monkeypatch.setattr(r,'REPO',repo);monkeypatch.setattr(r,'__file__',str(own))
    monkeypatch.setattr(r,'load_rows',lambda:rows)
    original_session=r.Session
    def session(*args):
        s=original_session(*args);e['sessions'].append(s);return s
    monkeypatch.setattr(r,'Session',session)
    @contextmanager
    def open_fake(port,serial,requests,retain):
        assert port=='/explicit/tty' and serial=='EXACT';e['events'].append('open')
        called=0
        def exchange(raw,n):
            nonlocal called
            called+=1;e['events'].append(('exchange',called))
            if n==160:
                assert raw==struct.pack('<II',0x51483556,1)+crc(struct.pack('<II',0x51483556,1))
                frame=struct.pack('<7I',0x49483556,1,2,1,1,41,5)+r.MODEL.encode()+r.VECTORS.encode()
            else:
                assert raw==requests[called-2] and n==88
                output=struct.pack('<5f',1,2,3,4,6) if e['mode']=='parity' and called==1025 else ref
                frame=struct.pack('<II',0x53523556,1)+raw[8:24]+struct.pack('<II',0,5)+bytes.fromhex(r.MODEL)+output
            answer=frame+crc(frame);retain({'request_hex':raw.hex(),'response_hex':answer.hex()})
            return answer
        try:yield exchange
        finally:
            e['events'].append('close')
            if e['mode']=='source_at_close':own.write_bytes(own.read_bytes()+b'\n# changed at close\n')
            if e['mode']=='close_failure':raise OSError('synthetic close failed')
    monkeypatch.setattr(transport,'open_exact_esp',open_fake)
    return e


def invoke(e):
    return r.main(['--execute-esp-validation','--port','/explicit/tty',
                  '--expected-usb-serial','EXACT','--output',str(e['output'])])


def test_positive_complete_cli_retains_last_row_and_limited_result(evidence):
    e=evidence;assert invoke(e)==0
    result=json.loads((e['output']/'RESULT.json').read_bytes())
    assert result['actual_process_exit'] is None and result['port_close_completed'] is True
    assert result['rows']==1024 and result['outputs_per_row']==5 and result['full_logit_parity_passed']
    assert not result['firmware_readback_verified'] and not result['energy_measured']
    row=json.loads((e['output']/'row_1023.json').read_bytes())
    assert row['row_id']==e['rows'][-1][0] and row['input_hex']==e['rows'][-1][1].hex()
    assert row['actual_logits_hex']==e['rows'][-1][2].hex()
    assert e['events'][0]=='open' and e['events'][-1]=='close'
    assert not (e['output']/'FAILED.json').exists()


@pytest.mark.parametrize('mode',['parity','close_failure','source_at_close'])
def test_failed_gate_close_or_source_change_cannot_create_result(evidence,mode):
    e=evidence;e['mode']=mode
    with pytest.raises((ValueError,OSError)):invoke(e)
    assert (e['output']/'FAILED.json').exists() and not (e['output']/'RESULT.json').exists()
    assert e['events'].count('open')==1 and e['events'][-1]=='close'
    assert (e['output']/'row_1023.json').exists()


def test_last_row_retention_failure_poisons_without_result(evidence,monkeypatch):
    e=evidence;original=r.Store.json
    def retain(store,name,value):
        if name=='row_1023.json':raise OSError('last row durability failed')
        return original(store,name,value)
    monkeypatch.setattr(r.Store,'json',retain)
    with pytest.raises(OSError):invoke(e)
    assert e['sessions'][0].poisoned and not (e['output']/'RESULT.json').exists()
    assert (e['output']/'FAILED.json').exists() and not (e['output']/'row_1023.json').exists()
    assert e['events'][-1]=='close'


def test_final_publication_source_change_cannot_return_success(evidence,monkeypatch):
    e=evidence;original=r.Store.json
    def retain(store,name,value):
        result=original(store,name,value)
        if name=='RESULT.json':e['source'].write_bytes(e['source'].read_bytes()+b'\n# publication change\n')
        return result
    monkeypatch.setattr(r.Store,'json',retain)
    with pytest.raises(ValueError,match='source changed'):invoke(e)
    assert (e['output']/'FAILED.json').exists()  # provisional RESULT may remain, never accepted by actual exit 0


def test_source_change_during_input_load_not_freshly_adopted(evidence,monkeypatch):
    e=evidence
    def load():
        e['source'].write_bytes(e['source'].read_bytes()+b'\n# source changed during load\n')
        return e['rows']
    monkeypatch.setattr(r,'load_rows',load)
    with pytest.raises(ValueError,match='source changed'):invoke(e)
    assert not e['events'] and not (e['output']/'RESULT.json').exists()


def test_existing_output_is_not_adopted_and_offline_does_not_open(evidence):
    e=evidence
    assert r.main([])==0 and not e['events'] and not e['output'].exists()
    e['output'].mkdir();(e['output']/'old').write_bytes(b'keep')
    with pytest.raises(FileExistsError):invoke(e)
    assert not e['events'] and (e['output']/'old').read_bytes()==b'keep'
