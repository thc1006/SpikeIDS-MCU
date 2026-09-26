"""SM05 fresh-init observer controls; all device calls are explicit fakes."""
import importlib.util
from pathlib import Path
import struct
import sys
import pytest
from test_binding import launcher,fixture

HERE=Path(__file__).resolve().parent

def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

@pytest.fixture
def setup():
    _,m,_,_,rp=launcher.bindings()
    previous=sys.modules.get('run');sys.modules['run']=launcher
    try:d=load('sm05_diagnostic',HERE/'diagnose.py');engine=d.engine(rp)
    finally:
        if previous is None:sys.modules.pop('run',None)
        else:sys.modules['run']=previous
    engine.POINTS=d.points((launcher.BUILD/'n6_sram.elf').read_bytes())
    previous=sys.modules.get('diagnose_epochs');sys.modules['diagnose_epochs']=engine
    try:f=load('sm05_observer_fakes',HERE.parent/'host_sram_runtime/test_diagnostic.py')
    finally:
        if previous is None:sys.modules.pop('diagnose_epochs',None)
        else:sys.modules['diagnose_epochs']=previous
    class Core(f.Core):
        def resume_from_halt(self):
            super().resume_from_halt()
            if not self.bp and not self.stuck:
                self.put(engine.ADDRESS+24,struct.pack('<I',1))
    c=Core();raw=bytearray(fixture.message(3));struct.pack_into('<2I',raw,20,0,0);struct.pack_into('<I',raw,124,0x534d3035)
    c.previous=bytes(raw);c.put(engine.ADDRESS,c.previous)
    return d,engine,m,rp,f,c

@pytest.mark.parametrize('bad',['none','stuck','badpc','short','retention','code','previous','existing','unsupported'])
def test_exactly_one_new_diagnostic_commit_with_cleanup(setup,bad):
    _,d,m,rp,f,c=setup;s=f.Sink();payload=f.payload();payload['rows']=((2656,bytes(164),bytes(20)),)
    if bad in ['stuck','badpc','short']:setattr(c,bad,True)
    if bad=='code':c.put(0x34064000,b'X')
    if bad=='previous':c.put(d.ADDRESS+24,struct.pack('<I',1))
    if bad=='existing':c.bp[d.POINTS[3][1]]='hardware'
    if bad=='unsupported':c.support=False
    if bad=='retention':
        original=s.raw
        def raw(name,value):
            if name==d.POINTS[3][0]+'_activation.bin':raise OSError('disk')
            original(name,value)
        s.raw=raw
    ticks=iter(range(10000))
    call=lambda:d.observe(c,payload,s,lambda b:rp.decode(b,m['protocol'].decode),'hardware',c.previous,
        clock=lambda:next(ticks),sleep=lambda _:None)
    if bad=='none':
        r=call();assert r['sequence']==1 and r['original_row_id']==2656 and not r['research_measurement_accepted']
        assert c.installed==[a for _,a in d.POINTS] and len(d.POINTS)==7
        assert len([n for n in s.files if n.endswith('_activation.bin')])==7
        assert struct.unpack_from('<2I',s.files['final_mailbox.bin'],20)==(1,1)
    else:
        with pytest.raises((RuntimeError,ValueError,OSError)):call()
    assert c.halted
    assert c.bp==({d.POINTS[3][1]:'hardware'} if bad=='existing' else {})
    assert len([a for a,_ in c.writes if a==d.ADDRESS+20])<=1
    if bad in ['code','previous','existing','unsupported']:assert not c.writes
