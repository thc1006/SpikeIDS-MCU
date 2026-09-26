"""Explicit one-row SM04 epoch diagnostic after full negative run05, no acceptance."""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import run as launcher

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'host_sram_runtime/diagnose_epochs.py'


def points(elf_raw,generated):
    from elftools.elf.elffile import ELFFile
    elf=ELFFile(io.BytesIO(elf_raw))
    symbols={s.name:s['st_value']&~1 for s in elf.get_section_by_name('.symtab').iter_symbols()}
    table=generated.split('static const EpochBlock_ItemTypeDef ll_atonn_rt_epoch_block_array[] = {',1)[1]
    names=re.findall(r'\.(?:start|end)_epoch_block = (LL_ATON_(?:Start|End)_EpochBlock_\d+)',table)
    if len(names)!=48 or len(set(names))!=48:raise ValueError('Unexpected fixed epoch schedule')
    names=[n for n in names if n not in ('LL_ATON_Start_EpochBlock_7','LL_ATON_End_EpochBlock_7')]
    if len(names)!=46:raise ValueError('Wrong repaired scheduling domain')
    result=tuple((n.replace('LL_ATON_',''),symbols[n]) for n in names)
    if any(not 0x34064000<=a<0x34076065 for _,a in result):raise ValueError('Breakpoint outside fixed RX')
    return result


def engine(rp):
    if launcher.sha(BASE)!='ee1151a1c3462fbb871daab24001b57b1457ec729a29c3dd2f109145587bd0f6':
        raise ValueError('Original diagnostic engine changed')
    spec=importlib.util.spec_from_file_location('_sm04_epoch_engine',BASE)
    module=importlib.util.module_from_spec(spec)
    previous=sys.modules.get('runtime_protocol')
    try:
        sys.modules['runtime_protocol']=rp;spec.loader.exec_module(module)
    finally:
        if previous is None:sys.modules.pop('runtime_protocol',None)
        else:sys.modules['runtime_protocol']=previous
    return module


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--execute-diagnostic',action='store_true');p.add_argument('--output',type=Path)
    args=p.parse_args()
    old,m,pins,_,rp=launcher.bindings();f=old.load_variant(m)
    previous=HERE.parents[2]/'results/n6_sram_validation_20260926_05/final_mailbox.bin'
    raw=previous.read_bytes()
    # Fixed prior run identity is further checked by exact live mailbox equality.
    if hashlib.sha256(raw).hexdigest()!='d2f741c967d15f6ac7d7b51594e0c282852661ccbd4b2b199f7c19d35fa498cf':
        raise ValueError('Wrong previous negative outcome')
    parity=previous.parent/'PARITY.json'
    if launcher.sha(parity)!='4442ff73620419d93803f69eee70690ce1da72cb1996aec1e987642e282ea24b':
        raise ValueError('Wrong previous parity record')
    first=json.loads(parity.read_bytes())['failed_logit_values'][0]
    if (first['index'],first['row_id'])!=(20,2656):raise ValueError('Not first failed original row')
    generated=HERE.parents[2]/'results/ppk2_n6_bringup_20260925_nAivHM/internal_sram_actual_01/generate/nsl_qcfs_seed0.c'
    # Explicit first failing original validation index, not acceptance subset.
    if f['rows'][20][0]!=2656:raise ValueError('Wrong diagnostic row identity')
    f=dict(f,rows=(f['rows'][20],))
    d=engine(rp);d.POINTS=points((launcher.BUILD/'n6_sram.elf').read_bytes(),generated.read_text())
    for source in (Path(__file__).resolve(),BASE):pins[str(source)]=launcher.sha(source)
    if not args.execute_diagnostic:
        print(json.dumps(dict(offline_checked=True,hardware_accessed=False,points=d.POINTS)));return
    if args.output is None:p.error('--output required')
    sink=m['orchestrate'].Store(args.output)
    sink.json('INTENT.json',dict(sources=pins,model_inputs=f['input_sha256'],points=d.POINTS,
        previous_mailbox_sha256=hashlib.sha256(raw).hexdigest(),kind='SM04_first_failed_row_46_stop_diagnostic_not_acceptance',
        original_validation_index=20,original_row_id=2656,
        software_breakpoints=False,power_control=False,flash_write=False))
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
