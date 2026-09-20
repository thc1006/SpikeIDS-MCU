"""Time only reproducible profiles; never select settings using accuracy or test data.

Two rounds in reversed profile order reduce (but do not eliminate) cache/thermal
order effects. Timing includes process startup, cache validation, transfer,
training, validation and checkpoints. No global optimum or fixed speedup claim.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import statistics
import sys
import time
from contracts import *
from suite import run_command
from evidence import load_fit


def profile(text):
    try:
        optimizer,threads=text.split(':');threads=int(threads)
    except (ValueError,TypeError) as e:raise argparse.ArgumentTypeError('Expected single:4, foreach:4 or fused:4') from e
    require(optimizer in ('single','foreach','fused') and threads>=1,'Invalid profile')
    return optimizer,threads


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--dataset',required=True,choices=DATASETS);p.add_argument('--cache',required=True,type=Path)
    p.add_argument('--work-dir',required=True,type=Path);p.add_argument('--device',choices=('cpu','cuda'),default='cuda')
    p.add_argument('--profiles',nargs='+',type=profile,default=[('single',1),('single',4),('foreach',4),('fused',4)])
    p.add_argument('--models',nargs='+',choices=('relu','qcfs','cnn'),default=['relu','qcfs'])
    p.add_argument('--epochs',type=int,default=10);a=p.parse_args()
    require(a.epochs>=1 and len(a.profiles)==len(set(a.profiles)) and len(a.models)==len(set(a.models)), 'Positive epochs and unique candidates/models required')
    require(all(m in ARMS[a.dataset] for m in a.models),'Unsupported model in dataset protocol')
    a.work_dir.mkdir(parents=True,exist_ok=False)
    observations={f'{o}:{t}':[] for o,t in a.profiles};errors={}
    for repeat in (0,1):
        ordered=a.profiles if repeat==0 else list(reversed(a.profiles))
        for optimizer,threads in ordered:
            key=f'{optimizer}:{threads}';start=time.perf_counter();models_results={}
            try:
                for model in a.models:
                    out=(a.work_dir/f'{optimizer}_{threads}_{repeat}_{model}.json').resolve()
                    cmd=[sys.executable,str(PACKAGE/'experiment_all.py'),'--dataset',a.dataset,'--cache',str(a.cache.resolve()),
                         '--model',model,'--device',a.device,'--optimizer',optimizer,'--threads',str(threads),
                         '--epochs',str(a.epochs),'--seeds','0','--stage','fit','--output',str(out)]
                    run_command(cmd,out.with_suffix('.log'))
                    r=load_fit(out);models_results[model]=(r['fingerprint'],r['training_digest'])
                observations[key].append({'seconds':time.perf_counter()-start,'models':models_results})
            except (ValueError,RuntimeError,OSError) as e:
                # Explicitly failed candidate; never silently fallback to another backend.
                errors.setdefault(key,[]).append(str(e))
    qualified=[]
    for key,obs in observations.items():
        if key not in errors and len(obs)==2 and obs[0]['models']==obs[1]['models']:
            qualified.append({'profile':key,'median_wall_seconds':statistics.median([r['seconds'] for r in obs]),
                              'wall_seconds':[r['seconds'] for r in obs]})
        elif key not in errors:errors[key]=['Independent training hashes did not match']
    qualified.sort(key=lambda x:x['median_wall_seconds'])
    report={'device':a.device,'dataset':a.dataset,'models':a.models,'epochs':a.epochs,'qualified':qualified,'failed':errors,
            'selection':'runtime only, not accuracy; passing short repeats still requires full planned-budget validation',
            'fastest_measured':qualified[0] if qualified else None,'test_evaluated':False}
    write_json(a.work_dir/'benchmark.json',seal(report));print(report)
    require(bool(qualified),'No profile passed the repeatability check')
if __name__=='__main__':main()
