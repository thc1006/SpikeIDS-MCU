"""Explicit L-sweep using the same fit-only cache and hardened runner.

The level set is REQUIRED because the uploaded handoff and old script disagree
about it. No old sweep is silently reinterpreted. All levels finish both independent
fit repetitions before any test result is calculated. Results are descriptive:
this does not retrofit an L=4 choice as historically preregistered.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
from contracts import *
from data_loaders import open_cache
from evidence import load_fit,load_result
from suite import run_command


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--dataset',required=True,choices=('nslkdd','unsw'))
    p.add_argument('--cache',required=True,type=Path);p.add_argument('--work-dir',required=True,type=Path)
    p.add_argument('--levels',required=True,nargs='+',type=int);p.add_argument('--seeds',nargs='+',type=int,default=list(range(20)))
    p.add_argument('--epochs',type=int,default=80);p.add_argument('--device',choices=('cpu','cuda'),default='cuda')
    p.add_argument('--threads',type=int,default=4);p.add_argument('--optimizer',choices=('single','foreach','fused'),default='single')
    p.add_argument('--stage',choices=('fit','evaluate'),default='fit');a=p.parse_args()
    require(a.levels and min(a.levels)>=1 and len(a.levels)==len(set(a.levels)),'Positive unique L values required')
    require(a.seeds and len(a.seeds)==len(set(a.seeds)) and all(0<=s<2**32 for s in a.seeds),'Invalid seed set')
    meta,_=open_cache(a.cache);require(meta['dataset']==a.dataset,'Wrong cache')
    contract={'schema':SCHEMA,'dataset':a.dataset,'data_fingerprint':meta['data_fingerprint'],
              'levels':sorted(a.levels),'seeds':sorted(a.seeds),'epochs':a.epochs,'device':a.device,'threads':a.threads,
              'optimizer':a.optimizer,'batch_size':512,'formula':'shifted_v1','sources':sources(),
              'role':'descriptive_L_ablation; no retrospectively chosen optimum claim'}
    a.work_dir.mkdir(parents=True,exist_ok=True)
    with file_lock(a.work_dir/'sweep.lock'):
        manifest=a.work_dir/'ablation_plan.json'
        if manifest.exists():
            prior=load_json(manifest);check_seal(prior);require(prior==seal(contract),'Ablation protocol/source changed')
        else:
            require(a.stage=='fit','Evaluation requires completed verified fits')
            write_json(manifest,seal(contract))
        outputs={}
        for L in sorted(a.levels):
            pair=[]
            for replica in ('a','b'):
                out=(a.work_dir/f'L{L}_{replica}.json').resolve()
                cmd=[sys.executable,str(PACKAGE/'experiment_all.py'),'--dataset',a.dataset,'--cache',str(a.cache.resolve()),
                     '--model','qcfs','--levels',str(L),'--epochs',str(a.epochs),'--batch-size','512','--seeds',*map(str,sorted(a.seeds)),
                     '--device',a.device,'--threads',str(a.threads),'--optimizer',a.optimizer,'--stage','fit','--output',str(out)]
                if a.stage=='fit':
                    if out.exists():cmd.append('--resume')
                    run_command(cmd,a.work_dir/f'L{L}_{replica}_fit.log')
                r=load_fit(out)
                pair.append(r)
            require(pair[0]['fingerprint']==pair[1]['fingerprint'] and pair[0]['training_digest']==pair[1]['training_digest'],f'L={L} fit repeat differs')
            outputs[L]=pair
        if a.stage=='fit':
            write_json(a.work_dir/'verification_fit.json',seal({'passed':True,'contract_sha256':digest(contract),
                    'levels':{str(k):v[0]['training_digest'] for k,v in outputs.items()}}));return
        verified=load_json(a.work_dir/'verification_fit.json');check_seal(verified)
        require(verified['passed'] and verified['contract_sha256']==digest(contract),'Ablation fit verification missing or stale')
        for L,pair in outputs.items():require(verified['levels'][str(L)]==pair[0]['training_digest'],'Changed ablation fits')
        result={}
        for L in sorted(a.levels):
            pair=[]
            for replica in ('a','b'):
                out=(a.work_dir/f'L{L}_{replica}.json').resolve()
                cmd=[sys.executable,str(PACKAGE/'experiment_all.py'),'--dataset',a.dataset,'--cache',str(a.cache.resolve()),
                     '--model','qcfs','--levels',str(L),'--epochs',str(a.epochs),'--batch-size','512','--seeds',*map(str,sorted(a.seeds)),
                     '--device',a.device,'--threads',str(a.threads),'--optimizer',a.optimizer,'--stage','evaluate','--resume','--output',str(out)]
                run_command(cmd,a.work_dir/f'L{L}_{replica}_evaluate.log');pair.append(load_result(out))
            require(pair[0]['scientific_digest']==pair[1]['scientific_digest'],f'L={L} predictions differ')
            result[str(L)]={'scientific_digest':pair[0]['scientific_digest'],'per_seed':pair[0]['per_seed'],'aggregate':pair[0]['aggregate']}
        write_json(a.work_dir/'ablation_results.json',seal({'contract':contract,'results':result,
                   'scope':'all declared L values; no selective deletion of unfavorable levels or claims of T=1 SNN identity'}))
if __name__=='__main__':main()
