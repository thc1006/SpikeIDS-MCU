"""Measure, rather than assume, shifted-QCFS ANN -> explicit IF simulation error.

Uses validation inputs only; reset membrane per batch. Latency here is not MCU/NPU
latency. This optional diagnostic does not create an unregistered paper test claim.
"""
from __future__ import annotations
import argparse
import numpy as np
import torch
from contracts import *
from export_verified import checkpoint_context
from models import simulate_if
from metrics import full_evaluate


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--run-dir',required=True,type=Path);p.add_argument('--dataset',required=True,choices=DATASETS)
    p.add_argument('--T',nargs='+',type=int,default=[1,2,4,8,16]);p.add_argument('--samples',type=int,default=1024)
    p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    require(a.samples>0 and a.T and min(a.T)>=1 and len(set(a.T))==len(a.T),'Invalid simulation protocol')
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True,warn_only=False)
    plan,job,result,meta,arrays,model,cp=checkpoint_context(a.run_dir,a.dataset,'qcfs')
    x=torch.from_numpy(np.array(arrays['x_validation'][:a.samples],copy=True));y=np.array(arrays['y_validation'][:a.samples])
    with torch.inference_mode():ann=model(x).numpy()
    rows={}
    for t in a.T:
        logits=simulate_if(model,x,t)
        prob=torch.softmax(logits,1).numpy();z=logits.numpy()
        rows[str(t)]={'ann_if_prediction_disagreement_fraction':float(np.mean(ann.argmax(1)!=z.argmax(1))),
                     'logit_max_absolute_error':float(np.abs(ann-z).max()),
                     'validation_metrics':full_evaluate(y,z.argmax(1),prob,len(meta['class_names']),meta['class_names'])}
    write_json(a.output,seal({'schema':SCHEMA,'checkpoint_sha256':sha256(cp),'data_fingerprint':meta['data_fingerprint'],
       'T':rows,'protocol':'one binary theta-amplitude spike per step; initial membrane theta/2; subtractive reset; constant input; averaged readout',
       'scope':'validation diagnostic on the preregistered deployment seed; not a multi-seed SNN performance claim'}))
if __name__=='__main__':main()
