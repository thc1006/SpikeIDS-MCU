"""Selected-checkpoint layerwise ANN -> frozen-ANN checks on validation inputs.

This replaces the stale, name-guessed analysis entry. It does NOT claim to compare
INT8 ONNX intermediates or to prove ReLU == T=1 LIF. Such a claim must not consume
this report. QDQ end-output checks are supplied separately by export_verified.py.
"""
from __future__ import annotations
import argparse
import numpy as np
import torch
from contracts import *
from export_verified import checkpoint_context,compare_logits
from models import QCFS,FrozenQCFS,freeze_for_export


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--run-dir',required=True,type=Path);p.add_argument('--dataset',required=True,choices=DATASETS)
    p.add_argument('--model',required=True,choices=('relu','qcfs'));p.add_argument('--output',required=True,type=Path)
    p.add_argument('--samples',type=int,default=256);a=p.parse_args();require(a.samples>0,'Positive sample count required')
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True,warn_only=False)
    plan,job,result,meta,arrays,model,cp=checkpoint_context(a.run_dir,a.dataset,a.model)
    frozen=freeze_for_export(model,fold_bn=False)
    x=torch.from_numpy(np.array(arrays['x_validation'][:a.samples],copy=True))
    def capture(net):
        values={};handles=[]
        def hook(name):
            def save(module,inputs,output):values[name]=output.detach().cpu().numpy().copy()
            return save
        for name,m in net.named_modules():
            if isinstance(m,(QCFS,FrozenQCFS,torch.nn.ReLU,torch.nn.Linear)):
                handles.append(m.register_forward_hook(hook(name)))
        try:
            with torch.inference_mode():net(x)
        finally:
            for h in handles:h.remove()
        return values
    left,right=capture(model),capture(frozen);require(left.keys()==right.keys(),'Layer correspondence differs')
    checks={name:compare_logits(left[name],right[name],0.,0.) for name in left}
    require(all(v['allclose'] for v in checks.values()),'Frozen activation arithmetic changed')
    write_json(a.output,seal({'schema':SCHEMA,'checkpoint_sha256':sha256(cp),'data_fingerprint':meta['data_fingerprint'],
                              'comparisons':checks,'scope':'PyTorch ANN vs frozen ANN only; no INT8/SNN identity assertion'}))
if __name__=='__main__':main()
