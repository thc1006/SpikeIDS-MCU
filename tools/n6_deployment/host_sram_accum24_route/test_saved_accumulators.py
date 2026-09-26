"""Tamper disposable diagnostic copies; never edit actual retained evidence."""
from pathlib import Path
import importlib.util
import json
import shutil
import struct
import pytest

HERE=Path(__file__).resolve().parent
REAL=HERE.parents[2]/'results/n6_accumulator_diagnostic_20260926_02'

@pytest.fixture
def saved(tmp_path):
    spec=importlib.util.spec_from_file_location('sm06_saved_review',HERE/'review_accumulators.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.ROOT=tmp_path
    p=tmp_path/'results/diagnostic';shutil.copytree(REAL,p);return m,p

def test_actual_three_npu_layers_and_final_match_without_acceptance(saved):
    m,p=saved;r=m.review(p)
    assert [x['exact_integer_matches'] for x in r['npu_integer_layers']]==[256,128,5]
    assert r['final_output_bitwise_equal_values']==5 and not r['research_measurement_accepted']

@pytest.mark.parametrize('bad',['input','raw19','raw31','raw43','final','tag','pc','fp','cleanup','acceptance'])
def test_any_corrupted_capture_or_false_claim_rejected(saved,bad):
    m,p=saved
    if bad=='input':path=p/'SM05_Start_19_activation.bin';offset=0
    elif bad.startswith('raw'):path=p/f'SM05_Post_{bad[3:]}_activation.bin';offset=8192
    elif bad=='final':path=p/'final_mailbox.bin';offset=320
    elif bad=='tag':path=p/'SM05_Post_31_mailbox.bin';offset=124
    else:path=None
    if path is not None:
        raw=bytearray(path.read_bytes());raw[offset]^=1;path.write_bytes(raw)
    else:
        path=p/({'pc':'SM05_Post_31_context.json','fp':'SM05_Post_31_fp.json','cleanup':'cleanup.json','acceptance':'RESULT.json'}[bad]);r=json.loads(path.read_text())
        if bad=='pc':r['pc']+=2
        elif bad=='fp':r['fpscr']|=1<<24
        elif bad=='cleanup':r['errors']=['halt failed']
        else:r['research_measurement_accepted']=True
        path.write_text(json.dumps(r))
    with pytest.raises(ValueError):m.review(p)
