"""One original failing row, actual NPU integer-accumulator diagnostic only."""
import argparse
import importlib.util
import io
import json
from pathlib import Path
import sys
import run as launcher

HERE=Path(__file__).resolve().parent
ENGINE=HERE/'diagnostic_engine.py'
ENGINE_SHA='b7423d6f023039beea7748a2838b87609e8c0530004ee83a328a9ee65e3c1530'
PREVIOUS=HERE.parents[2]/'results/n6_sram_init_20260926_06/final_mailbox.bin'
PREVIOUS_SHA='c9bc7032b456ed87dff2e088819bebf34b882715187bbc723111dc3b53f128c9'

def points(raw):
    from elftools.elf.elffile import ELFFile
    elf=ELFFile(io.BytesIO(raw));symbols={s.name:s['st_value']&~1 for s in elf.get_section_by_name('.symtab').iter_symbols()}
    names=('SM05_Start_19','SM05_Post_19','SM05_Start_31','SM05_Post_31','SM05_Start_43','SM05_Post_43','LL_ATON_End_EpochBlock_44')
    value=tuple((n,symbols[n]) for n in names)
    if len(set(a for _,a in value))!=7 or any(not 0x34064000<=a<0x34077f1d for _,a in value):
        raise ValueError('Bad fixed diagnostic sites')
    return value

def engine(rp):
    if launcher.sha(ENGINE)!=ENGINE_SHA:raise ValueError('Fixed observer changed')
    spec=importlib.util.spec_from_file_location('_sm05_observer',ENGINE);m=importlib.util.module_from_spec(spec)
    prior=sys.modules.get('runtime_protocol')
    try:
        sys.modules['runtime_protocol']=rp;spec.loader.exec_module(m)
    finally:
        if prior is None:sys.modules.pop('runtime_protocol',None)
        else:sys.modules['runtime_protocol']=prior
    return m

def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--execute-diagnostic',action='store_true');p.add_argument('--output',type=Path)
    args=p.parse_args();old,m,pins,_,rp=launcher.bindings();f=old.load_variant(m)
    if launcher.sha(PREVIOUS)!=PREVIOUS_SHA:raise ValueError('Wrong prior initialized target')
    raw=PREVIOUS.read_bytes()
    if f['rows'][20][0]!=2656:raise ValueError('Wrong original row')
    f=dict(f,rows=(f['rows'][20],));d=engine(rp);d.POINTS=points((launcher.BUILD/'n6_sram.elf').read_bytes())
    for source in (HERE/'diagnose.py',ENGINE):pins[str(source)]=launcher.sha(source)
    if not args.execute_diagnostic:
        print(json.dumps(dict(offline_checked=True,hardware_accessed=False,points=d.POINTS,original_row_id=2656)));return
    if args.output is None:p.error('--output required')
    sink=m['orchestrate'].Store(args.output)
    sink.json('INTENT.json',dict(kind='SM05_one_row_NPU_accumulator_diagnostic_not_acceptance',sources=pins,
        model_inputs=f['input_sha256'],previous_mailbox_sha256=PREVIOUS_SHA,points=d.POINTS,
        original_validation_index=20,original_row_id=2656,software_breakpoints=False,power_control=False,flash_write=False))
    try:
        from pyocd.core.target import Target
        with m['pyocd_backend'].attach_exact_probe() as core:
            result=d.observe(core,f,sink,lambda b:rp.decode(b,m['protocol'].decode),Target.BreakpointType.HW,raw)
        if any(launcher.sha(Path(n))!=h for n,h in pins.items()):raise ValueError('Sources changed')
        old.load_variant(m)
        sink.json('RESULT.json',result);print(json.dumps(result))
    except BaseException as exc:
        sink.json('FAILED.json',dict(error=str(exc),research_measurement_accepted=False));raise

if __name__=='__main__':main()
