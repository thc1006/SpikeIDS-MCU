"""Saved-only independent NumPy cross-check; never imports a board backend."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
VECTORS=ROOT/'results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq/validation_vectors.npz'
VECTORS_SHA='cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb'


def require(value,message):
    if not value:raise ValueError(message)


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def review(directory):
    p=Path(directory)
    require(p.is_absolute() and p==p.resolve() and p.parent==ROOT/'results','Canonical results child required')
    pins={n.name:digest(n) for n in p.iterdir() if n.is_file()}
    j=lambda n:json.loads((p/n).read_bytes())
    require('completion_state.json' in pins,'Run has not retained final cleanup')
    require(('RESULT.json' in pins)^('FAILED.json' in pins),'Exactly one outcome required')
    require(digest(VECTORS)==VECTORS_SHA,'Wrong original vectors')
    intent=j('INTENT.json')
    for domain in ('sources','model_inputs','stage_inputs'):
        for name,sha in intent[domain].items():require(digest(Path(name))==sha,'Input/source changed: '+name)
    with np.load(VECTORS,allow_pickle=False) as z:
        x=z['x'].copy();ref=z['reference_logits'].copy();ids=z['validation_row_ids'].copy()
    require(x.shape==(1024,41) and x.dtype==np.dtype('<f4'),'Input contract')
    require(ref.shape==(1024,5) and ref.dtype==np.dtype('<f4'),'Reference contract')
    names=sorted(n for n in pins if n.startswith('row_'))
    require(names==[f'row_{i:04d}.json' for i in range(len(names))],'Missing/reordered row file')
    actual=[]
    for i,name in enumerate(names):
        r=j(name);raw=bytes.fromhex(r['raw_mailbox_hex']);w=struct.unpack('<128I',raw)
        require((r['row_id'],r['sequence'])==(int(ids[i]),i+1),'Wrong row/sequence')
        require(bytes.fromhex(r['input_hex'])==raw[128:292]==x[i].tobytes(),'Wrong full input')
        require(bytes.fromhex(r['output_hex'])==raw[320:340],'Output not raw target bytes')
        require(w[:4]==(0x53364e36,1,512,5) and w[31]==0x534d3032,'Wrong firmware/state')
        require(w[4:11]==(0x504c4154,i+1,i+1,1,int(ids[i]),41,5),'Wrong completed request')
        require(w[11:19]==(0,)*8 and w[19]==int(ids[i]),'Runtime/adapter failure')
        require(w[73:76]==(0x52544932,0,1),'Missing/failed/repeated runtime init')
        require(not any(w[76:80]+w[85:88]) and not any(raw[482:]),'Reserved byte corruption')
        require(raw[352:417]==b'22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d\0','Wrong model')
        require(raw[417:482]==b'cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec\0','Wrong weights')
        vals=np.frombuffer(raw[320:340],dtype='<f4')
        require(np.isfinite(vals).all() and list(map(float,vals))==r['logits'],'Nonfinite or altered logits')
        actual.append(vals)
    completed=j('completion_state.json')
    require(completed['completed_row_ids']==ids[:len(names)].tolist(),'Completion rows disagree')
    require(completed['halt_error'] is None,'CPU halt cleanup failed')
    out=dict(saved_only=True,hardware_accessed=False,rows=len(names),energy_measured=False,
             research_measurement_accepted=False,full_logit_parity_passed=False)
    if len(names)==1024:
        actual=np.asarray(actual,dtype='<f4')
        close=np.isclose(ref,actual,atol=1e-6,rtol=1e-5)
        failures=np.argwhere(~close)
        classes=np.flatnonzero(np.argmax(ref,axis=1)!=np.argmax(actual,axis=1))
        parity=j('PARITY.json')
        require(parity['atol']==1e-6 and parity['rtol']==1e-5,'Tolerance changed')
        require([(r['index'],r['column']) for r in parity['failed_logit_values']]==[tuple(r) for r in failures.tolist()],'Mismatch locations differ')
        require([r['index'] for r in parity['argmax_disagreements']]==classes.tolist(),'Class disagreements differ')
        max_abs=float(np.max(np.abs(ref.astype('f8')-actual.astype('f8'))))
        require(parity['max_abs_error']==max_abs,'Max error differs')
        passed=len(failures)==0 and len(classes)==0
        require(parity['full_logit_parity_passed'] is passed,'Parity flag differs')
        out.update(full_logit_parity_passed=passed,failed_values=len(failures),
            failed_rows=int(np.count_nonzero(np.any(~close,axis=1))),argmax_disagreements=len(classes),
            bitwise_equal_values=int(np.count_nonzero(ref.view('u4')==actual.view('u4'))),max_abs_error=max_abs)
    if 'RESULT.json' in pins:
        require(out['full_logit_parity_passed'] and j('RESULT.json')['completed_rows']==1024,'False successful result')
        for name in ('runtime_live_before_inference.json','runtime_live_after_validation.json'):
            live=j(name);require(live['context']['primask']==1,'IRQs unmasked')
            for a in ('0x580e0000','0x580e2000','0x580e3000'):require(live['registers'][a]&1,'Global NPU disabled')
        for name in ('floating_environment.json','floating_environment_after_init.json','floating_environment_after_validation.json'):
            fp=j(name);require((fp['fpscr']|fp['fpdscr'])&0x07c80000==0,'FP mode mismatch')
        out['successful_exit_still_requires_external_receipt']=True
    else:out['failure']=j('FAILED.json')['error']
    require(pins=={n.name:digest(n) for n in p.iterdir() if n.is_file()},'Saved artifacts changed during review')
    require(digest(VECTORS)==VECTORS_SHA,'Vectors changed during review')
    out['artifact_sha256']=pins
    return out


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    print(json.dumps(review(parser.parse_args().directory),sort_keys=True,indent=2))
