"""Independent saved NumPy/struct review of SM04; no board or producer imports."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
VECTOR=ROOT/'results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq/validation_vectors.npz'
VECTOR_SHA='cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb'


def require(v,s):
    if not v:raise ValueError(s)


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def review(directory):
    p=Path(directory)
    require(p.is_absolute() and p==p.resolve() and p.parent==ROOT/'results','Require canonical results child')
    require(sha(VECTOR)==VECTOR_SHA,'Original vectors changed')
    artifacts={f.name:sha(f) for f in p.iterdir() if f.is_file()}
    j=lambda n:json.loads((p/n).read_bytes())
    require(('FAILED.json' in artifacts)^('RESULT.json' in artifacts),'Need one finalized outcome')
    intent=j('INTENT.json')
    require(intent['kind']=='SM04_first_layer_semantic_repair_full_validation' and intent['deployment_tag']==0x534d3034,'Wrong intent')
    for group in ('sources','model_inputs','stage_inputs'):
        for name,h in intent[group].items():require(sha(Path(name))==h,'Input/source changed: '+name)
    with np.load(VECTOR,allow_pickle=False) as z:
        x,ref,ids=(z[n].copy() for n in ('x','reference_logits','validation_row_ids'))
    require(x.shape==(1024,41) and ref.shape==(1024,5) and x.dtype==ref.dtype==np.dtype('<f4'),'Vector contract')
    names=sorted(n for n in artifacts if n.startswith('row_'))
    require(len(names)<=1024 and names==[f'row_{i:04d}.json' for i in range(len(names))],'Row files')
    actual=[]
    for i,name in enumerate(names):
        r=j(name);raw=bytes.fromhex(r['raw_mailbox_hex']);require(len(raw)==512,'Short mailbox')
        w=struct.unpack('<128I',raw)
        require(w[:4]==(0x53364e36,1,512,5) and w[31]==0x534d3034,'Wrong firmware/state')
        require(w[4:11]==(0x504c4154,i+1,i+1,1,int(ids[i]),41,5),'Wrong committed request')
        require(w[11:19]==(0,)*8 and w[19]==int(ids[i]) and w[21:23]==(0,0),'API/fault error')
        require(w[73:76]==(0x52544932,0,1) and not any(w[76:80]+w[85:88]) and not any(raw[482:]),'Receipt/reserved fields')
        require(raw[352:417]==b'22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d\0','Model identity')
        require(raw[417:482]==b'cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec\0','Weights identity')
        require((r['sequence'],r['row_id'])==(i+1,int(ids[i])),'Record identity')
        require(raw[128:292]==bytes.fromhex(r['input_hex'])==x[i].tobytes(),'Full input identity')
        require(raw[320:340]==bytes.fromhex(r['output_hex']),'Raw output identity')
        a=np.frombuffer(raw[320:340],dtype='<f4')
        require(np.isfinite(a).all() and a.tolist()==r['logits'],'Invalid/altered logits');actual.append(a)
    completion=j('completion_state.json')
    require(completion['halt_error'] is None and completion['completed_row_ids']==ids[:len(names)].tolist(),'Completion/cleanup mismatch')
    result=dict(saved_only=True,rows=len(names),full_logit_parity_passed=False,energy_measured=False,research_measurement_accepted=False)
    if len(names)==1024:
        a=np.asarray(actual,dtype='<f4');close=np.isclose(ref,a,atol=1e-6,rtol=1e-5)
        failures=np.argwhere(~close);classes=np.flatnonzero(np.argmax(ref,axis=1)!=np.argmax(a,axis=1))
        parity=j('PARITY.json');passed=not len(failures) and not len(classes)
        require(parity['atol']==1e-6 and parity['rtol']==1e-5,'Tolerance changed')
        require([(r['index'],r['column']) for r in parity['failed_logit_values']]==[tuple(r) for r in failures.tolist()],'Mismatch coordinates')
        require([r['index'] for r in parity['argmax_disagreements']]==classes.tolist(),'Class disagreements')
        max_abs=float(np.max(np.abs(ref.astype('f8')-a.astype('f8'))))
        require(parity['max_abs_error']==max_abs and parity['full_logit_parity_passed'] is passed,'Wrong parity summary')
        result.update(full_logit_parity_passed=passed,failed_values=len(failures),failed_rows=int(np.any(~close,axis=1).sum()),
            argmax_disagreements=len(classes),max_abs_error=max_abs,bitwise_equal_values=int((ref.view('u4')==a.view('u4')).sum()))
    if 'RESULT.json' in artifacts:
        require(result['full_logit_parity_passed'] and j('RESULT.json')['completed_rows']==1024,'False pass')
        for name in ('runtime_live_before_inference.json','runtime_live_after_validation.json'):
            o=j(name);require(o['context']['primask']==1,'IRQ state')
            for a in ('0x580e0000','0x580e2000','0x580e3000'):require(o['registers'][a]&1,'NPU disabled')
        for name in ('floating_environment.json','floating_environment_after_init.json','floating_environment_after_validation.json'):
            fp=j(name);require((fp['fpscr']|fp['fpdscr'])&0x07c80000==0,'FP mode')
        result['actual_process_exit_requires_external_receipt']=True
    else:result['failure']=j('FAILED.json')['error']
    require(artifacts=={f.name:sha(f) for f in p.iterdir() if f.is_file()},'Evidence changed while reviewing')
    for group in ('sources','model_inputs','stage_inputs'):
        for name,h in intent[group].items():require(sha(Path(name))==h,'Late source/input change')
    result['artifact_sha256']=artifacts
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    print(json.dumps(review(parser.parse_args().directory),sort_keys=True,indent=2))
