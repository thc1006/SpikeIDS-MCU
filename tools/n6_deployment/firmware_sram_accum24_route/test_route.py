"""Derive expected route from original graph topology,NOT duplicated IDs."""
from pathlib import Path
import importlib.util
import re
import subprocess
import pytest

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'firmware_sram_accum24'
ORIGINAL=HERE.parents[2]/'results/ppk2_n6_bringup_20260925_nAivHM/internal_sram_actual_01/generate/nsl_qcfs_seed0.c'

def callback(text,name):return re.search(r'static void '+name+r'\(.*?\n\}',text,re.S).group()
def routes(text):
    return [tuple(x) for x in re.findall(r'ATONN_DSTPORT\(STRSWITCH, 0, (\w+), (\d+), (\d+)\).*?ATONN_SRCPORT\(STRSWITCH, 0, (\w+), (\d+), (\d+)\)',text)]

def validate(original,candidate):
    for e in [19,31,43]:
        for kind in ['Start','End']:
            before=callback(original,f'LL_ATON_{kind}_EpochBlock_{e}')
            after=callback(candidate,f'SM05_{kind}_{e}')
            links={v[:3]:v[3:] for v in routes(before)}
            output=next(dst for dst,src in links.items() if dst[0]=='STRENG' and src[0]=='ARITH')
            bias=links[output];producer=links[bias]
            assert producer[0]=='CONVACC'
            expected={dst:(producer if dst==output else src) for dst,src in links.items() if dst!=bias}
            actual={v[:3]:v[3:] for v in routes(after)}
            if len(routes(after))!=len(expected):raise ValueError('Duplicate/extra routing record')
            if actual!=expected:raise ValueError('Does not preserve original dot-product producer')
            enabled=set(re.findall(r'\{ \{(\w+), (\d+)\} \}',after))
            if producer[:2] not in enabled:raise ValueError('Producer not enabled/disabled by this epoch')
            if kind=='Start':
                configured=set(re.findall(r'LL_Convacc_Init\((\d+),',after))
                if producer[1] not in configured:raise ValueError('Producer not configured by this epoch')

def test_original_bad_candidate_is_rejected():
    with pytest.raises(ValueError):validate(ORIGINAL.read_text(),(BASE/'accum_epochs.c').read_text())

def test_new_candidate_topology_and_exactly_two_numeric_changes():
    old=(BASE/'accum_epochs.c').read_text();new=(HERE/'accum_epochs.c').read_text();validate(ORIGINAL.read_text(),new)
    differences=[(a,b) for a,b in zip(old.splitlines(),new.splitlines()) if a!=b]
    assert len(old.splitlines())==len(new.splitlines()) and len(differences)==2
    for a,b in differences:assert b==a.replace('ATONN_SRCPORT(STRSWITCH, 0, CONVACC, 1, 0)','ATONN_SRCPORT(STRSWITCH, 0, CONVACC, 3, 0)')

@pytest.mark.parametrize('unit',[0,1,2,4,5,6,7])
def test_every_other_third_dense_producer_rejected(unit):
    source=(HERE/'accum_epochs.c').read_text()
    pattern=r'(ATONN_DSTPORT\(STRSWITCH, 0, STRENG, 5, 0\).*?ATONN_SRCPORT\(STRSWITCH, 0, CONVACC, )3(, 0\))'
    changed,n=re.subn(pattern,r'\g<1>'+str(unit)+r'\2',source);assert n==2
    with pytest.raises(ValueError):validate(ORIGINAL.read_text(),changed)

@pytest.fixture(scope='module')
def executable(tmp_path_factory):
    spec=importlib.util.spec_from_file_location('sm06_actual_main',BASE/'test_integration.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    # Reuse source-only host CMSIS/STAI fixtures but compile actual SM06 main.
    m.HERE=HERE
    original=m.module
    def fixture(name,path):
        value=original(name,path)
        if hasattr(value,'HARNESS'):value.HARNESS=value.HARNESS.replace('0x534d3032','0x534d3036')
        return value
    m.module=fixture
    return m.main_executable.__wrapped__(tmp_path_factory)

@pytest.mark.parametrize('scenario',range(7))
def test_actual_new_tag_runtime_initialization(executable,scenario):
    r=subprocess.run([str(executable),str(scenario)],capture_output=True,text=True,timeout=3);assert r.returncode==0,r.stderr
