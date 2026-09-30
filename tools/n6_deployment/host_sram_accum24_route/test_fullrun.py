import importlib.util
from pathlib import Path
import pytest
from test_binding import fixture,Core

HERE=Path(__file__).resolve().parent

@pytest.fixture
def full():
    s=importlib.util.spec_from_file_location('sm06_explicit_fullrun',HERE/'fullrun.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def test_actual_saved_gate_and_offline_payload(full):
    r=full.verify_raw_gate();assert r['allows_next_full_validation'] and not r['research_measurement_accepted']
    assert full.main([])==0

@pytest.mark.parametrize('which',['GATE_SHA','REVIEWER_SHA'])
def test_stale_gate_or_checker_stops_before_hardware(full,which):
    setattr(full,which,'0'*64)
    with pytest.raises(ValueError):full.main([])

def test_full_bindings_retain_all1024_policy_not_init_only(full):
    old,m,_,controller,rp=full.bindings()
    assert rp.TAG==0x534d3036 and m['validation'].ATOL==1e-6 and m['validation'].RTOL==1e-5
    c,s=Core(),fixture.Sink();f,p=fixture.payloads();f['segments']=((0x34064000,bytes(256)),)
    r=controller.run_connected(c,f,p,s,nonce=31,modules=fixture.MODULES)
    assert r['completed_rows']==1024 and r['full_logit_parity_passed'] and not r['energy_measured']
    assert 'PARITY.json' in s.files and 'diagnostic_ready.bin' not in s.files
