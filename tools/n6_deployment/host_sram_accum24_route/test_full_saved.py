"""Saved full-run review with tamper controls on disposable evidence copies."""
from pathlib import Path
import importlib.util
import json
import shutil
import struct
import pytest

HERE=Path(__file__).resolve().parent
REAL=HERE.parents[2]/'results/n6_sram_validation_20260926_08'

@pytest.fixture
def saved(tmp_path):
    s=importlib.util.spec_from_file_location('sm06_full_saved',HERE/'review_saved.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    m.ROOT=tmp_path;p=tmp_path/'results/copied_full';shutil.copytree(REAL,p);return m,p

def test_actual_full_run_has1024_original_rows5120_bitwise_values(saved):
    m,p=saved;r=m.review(p)
    assert r['rows']==1024 and r['bitwise_equal_values']==5120 and r['full_logit_parity_passed']
    assert r['failed_values']==r['failed_rows']==r['argmax_disagreements']==0
    assert not r['research_measurement_accepted'] and not r['energy_measured']

@pytest.mark.parametrize('bad',['tag','model','input','row','receipt','loosen','gate','missing','coherent_wrong_output'])
def test_false_acceptance_or_tampering_rejected(saved,bad):
    m,p=saved
    if bad=='missing':(p/'row_0000.json').unlink()
    elif bad=='gate':
        path=p/'INTENT.json';r=json.loads(path.read_text());r['raw_accumulator_gate_sha256']='0'*64;path.write_text(json.dumps(r))
    elif bad=='loosen':
        path=p/'PARITY.json';r=json.loads(path.read_text());r['atol']=1.0;path.write_text(json.dumps(r))
    else:
        path=p/'row_0020.json';r=json.loads(path.read_text());raw=bytearray.fromhex(r['raw_mailbox_hex'])
        if bad=='input':r['input_hex']='00'*164
        elif bad=='row':r['row_id']+=1
        elif bad=='coherent_wrong_output':
            # Match all redundant serializations; only original scientific
            # reference/parity check can reject this finite wrong output.
            struct.pack_into('<f',raw,320,0.0);r['output_hex']=raw[320:340].hex();r['logits']=list(struct.unpack_from('<5f',raw,320));r['raw_mailbox_hex']=raw.hex()
        else:
            raw[{'tag':124,'model':352,'receipt':292}[bad]]^=1;r['raw_mailbox_hex']=raw.hex()
        path.write_text(json.dumps(r))
    with pytest.raises(ValueError):m.review(p)


@pytest.mark.parametrize('file,field,value',[
    ('RESULT.json','energy_measured',True),
    ('RESULT.json','frequency_measured',True),
    ('RESULT.json','latency_validated',True),
    ('RESULT.json','research_measurement_accepted',True),
    ('RESULT.json','npu_execution_independently_verified',True),
    ('RESULT.json','full_logit_parity_passed',False),
    ('RESULT.json','actual_process_exit',0),
    ('PARITY.json','rows',1023),
    ('PARITY.json','comparison','reversed arguments'),
    ('PARITY.json','energy_measured',True),
    ('INTENT.json','power_control',True),
    ('completion_state.json','npu_quiescence_verified',True),
    ('model_load.json','ram_payload_readback_matched',False),
    ('row_0020.json','latency_validated',True),
    ('row_0020.json','cpu_cycles_modulo_2_32',-1),
])
def test_scope_claims_and_receipt_integrity(saved,file,field,value):
    m,p=saved;f=p/file;j=json.loads(f.read_bytes());j[field]=value;f.write_text(json.dumps(j))
    with pytest.raises(ValueError):m.review(p)


@pytest.mark.parametrize('bad',['subdirectory','symlink','final_mailbox','cpu','placement'])
def test_evidence_and_target_identity(saved,bad):
    m,p=saved
    if bad=='subdirectory':(p/'hidden').mkdir()
    elif bad=='symlink':(p/'alias').symlink_to(p/'RESULT.json')
    elif bad=='final_mailbox':(p/'final_mailbox.bin').write_bytes(bytes(512))
    else:
        f=p/'row_0020.json';j=json.loads(f.read_bytes());raw=bytearray.fromhex(j['raw_mailbox_hex'])
        struct.pack_into('<I',raw,23*4 if bad=='cpu' else 24*4,0);j['raw_mailbox_hex']=raw.hex();f.write_text(json.dumps(j))
    with pytest.raises(ValueError):m.review(p)
