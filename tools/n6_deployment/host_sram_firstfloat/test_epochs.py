"""SM04 46-stop binding controls; no real hardware in tests."""
import importlib.util
from pathlib import Path
import struct
import sys
import pytest
from test_binding import launcher

HERE=Path(__file__).resolve().parent


@pytest.fixture
def modules():
    old,m,_,_,rp=launcher.bindings()
    prior=sys.modules.get('run');sys.modules['run']=launcher
    try:
        spec=importlib.util.spec_from_file_location('sm04_epoch_binding',HERE/'diagnose_epochs.py')
        d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
    finally:
        if prior is None:sys.modules.pop('run',None)
        else:sys.modules['run']=prior
    engine=d.engine(rp)
    generated=HERE.parents[2]/'results/ppk2_n6_bringup_20260925_nAivHM/internal_sram_actual_01/generate/nsl_qcfs_seed0.c'
    engine.POINTS=d.points((launcher.BUILD/'n6_sram.elf').read_bytes(),generated.read_text())
    # Reuse fake transport with the original engine address constants. The
    # new observer is explicitly passed the new wire decoder below.
    prior=sys.modules.get('diagnose_epochs');sys.modules['diagnose_epochs']=engine
    try:
        spec=importlib.util.spec_from_file_location('epoch_fakes',HERE.parent/'host_sram_runtime/test_diagnostic.py')
        f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
    finally:
        if prior is None:sys.modules.pop('diagnose_epochs',None)
        else:sys.modules['diagnose_epochs']=prior
    c=f.Core();raw=bytearray(c.previous);struct.pack_into('<I',raw,124,0x534d3034)
    c.previous=bytes(raw);c.put(engine.ADDRESS,c.previous)
    return d,engine,rp,m,c,f


@pytest.mark.parametrize('bad',['none','stuck','badpc','short','retention'])
def test_46_ordered_stops_one_commit_and_no_ambiguous_retry(modules,bad):
    _,d,rp,m,c,f=modules;s=f.Sink()
    if bad in ['stuck','badpc','short']:setattr(c,bad,True)
    if bad=='retention':
        original=s.raw
        def raw(name,value):
            if name==d.POINTS[20][0]+'_activation.bin':raise OSError('disk')
            original(name,value)
        s.raw=raw
    ticks=iter(range(10000))
    payload=f.payload();payload['rows']=((2656,bytes(164),bytes(20)),)
    call=lambda:d.observe(c,payload,s,lambda b:rp.decode(b,m['protocol'].decode),'hardware',c.previous,
        clock=lambda:next(ticks),sleep=lambda _:None)
    if bad=='none':
        r=call();assert r['diagnostic_completed'] and not r['research_measurement_accepted']
        assert r['original_row_id']==2656
        assert c.installed==[a for _,a in d.POINTS]
        assert len([n for n in s.files if n.endswith('_activation.bin')])==46
    else:
        with pytest.raises((RuntimeError,OSError)):call()
    assert c.halted and not c.bp
    assert len([a for a,_ in c.writes if a==d.ADDRESS+20])<=1


def test_wrong_schedule_rejected(modules):
    d,_,_,_,_,_=modules
    with pytest.raises((ValueError,IndexError)):
        d.points((launcher.BUILD/'n6_sram.elf').read_bytes(),'no fixed table')
