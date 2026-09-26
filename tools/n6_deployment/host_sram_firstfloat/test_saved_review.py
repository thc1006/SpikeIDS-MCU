"""Adversarial copies of retained failed evidence; never mutate original run."""
import importlib.util
import json
from pathlib import Path
import shutil
import pytest

HERE=Path(__file__).resolve().parent
ORIGINAL=HERE.parents[2]/'results/n6_sram_validation_20260926_05'

@pytest.fixture
def saved(tmp_path):
    spec=importlib.util.spec_from_file_location('sm04_saved_checker',HERE/'review_saved.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    # Namespace changes only for disposable copies; original vector/input/source
    # hashes and fixed run identity are still verified by the real reviewer.
    m.ROOT=tmp_path
    target=tmp_path/'results/copied_negative'
    shutil.copytree(ORIGINAL,target)
    return m,target

def test_actual_negative_evidence_is_not_accepted(saved):
    m,p=saved;r=m.review(p)
    assert (r['rows'],r['failed_values'],r['failed_rows'],r['argmax_disagreements'])==(1024,297,81,0)
    assert r['bitwise_equal_values']==4823
    assert not r['full_logit_parity_passed'] and not r['research_measurement_accepted'] and not r['energy_measured']

@pytest.mark.parametrize('bad',['tag','model','input','output','row','receipt','tolerance','summary','missing','false_result'])
def test_tampered_retained_evidence_rejected(saved,bad):
    m,p=saved
    if bad in ['tolerance','summary']:
        path=p/'PARITY.json';r=json.loads(path.read_text())
        if bad=='tolerance':r['atol']=1.0
        else:r['failed_logit_values']=[]
        path.write_text(json.dumps(r))
    elif bad=='missing':(p/'row_0020.json').unlink()
    elif bad=='false_result':
        (p/'FAILED.json').unlink();(p/'RESULT.json').write_text(json.dumps({'completed_rows':1024}))
    else:
        path=p/'row_0020.json';r=json.loads(path.read_text());raw=bytearray.fromhex(r['raw_mailbox_hex'])
        if bad=='input':r['input_hex']='00'*164
        elif bad=='output':r['output_hex']='00'*20
        elif bad=='row':r['row_id']+=1
        else:
            offset={'tag':124,'model':352,'receipt':292}[bad];raw[offset]^=1;r['raw_mailbox_hex']=raw.hex()
        path.write_text(json.dumps(r))
    with pytest.raises(ValueError):m.review(p)
