"""Checkpoint-bound ONNX/QDQ export, fit-only calibration, validation-vector gate.

Optional onnx/onnxruntime dependencies are required only when this command runs.
No board is touched. Operator names never establish full NPU placement.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import torch
from contracts import *
from evidence import read_plan,load_fit
from data_loaders import open_cache
from models import build,freeze_for_export
from experiment_all import load_checkpoint,tree_digest,array_sha256


def checkpoint_context(run_dir,dataset,arm):
    run_dir=Path(run_dir);plan=read_plan(run_dir)
    job=next((j for j in plan['jobs'] if j['dataset']==dataset and j['model']==arm),None)
    require(job is not None,'Model/dataset not part of frozen plan')
    verification=load_json(run_dir/'verification_fit.json');check_seal(verification)
    require(verification['passed'] and verification['plan_sha256']==plan['content_sha256'],'Training repeatability must pass before export')
    path=run_dir/'results'/f"{job['id']}.json"
    result=load_fit(path,job,plan)
    require(verification['jobs'][job['id']]==result['training_digest'],'Training verification stale')
    seed=plan['deployment_seed'];cp=path.with_suffix('')/'runs'/f'{arm}_seed_{seed}.pt'
    state=load_checkpoint(cp,result['fingerprint'])
    meta,arrays=open_cache(Path(job['cache']));p=result['protocol']
    model=build(arm,len(meta['features']),len(meta['class_names']),p['hidden'],p['levels'],p['qcfs_formula'])
    model.load_state_dict(state['best_model'],strict=True);model.eval()
    require(tree_digest(model.state_dict())==state['fit_result']['best_state_sha256'],'Checkpoint reconstruction mismatch')
    return plan,job,result,meta,arrays,model,cp


def compare_logits(reference,actual,atol,rtol):
    reference,actual=np.asarray(reference),np.asarray(actual)
    require(reference.shape==actual.shape and reference.ndim==2 and len(reference)>0,'Logit shape mismatch')
    require(np.isfinite(reference).all() and np.isfinite(actual).all(),'Non-finite validation logits')
    require(np.isfinite(atol) and np.isfinite(rtol) and atol>=0 and rtol>=0,'Invalid tolerance')
    return {'allclose':bool(np.allclose(reference,actual,atol=atol,rtol=rtol)),
            'max_abs_error':float(np.max(np.abs(reference.astype(float)-actual))),
            'prediction_disagreement_fraction':float(np.mean(reference.argmax(1)!=actual.argmax(1))),
            'vectors_checked':len(reference),'scope':'only these validation vectors, not every possible input'}


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--run-dir',required=True,type=Path);p.add_argument('--dataset',required=True,choices=DATASETS)
    p.add_argument('--model',required=True,choices=('relu','qcfs','cnn'));p.add_argument('--output-dir',required=True,type=Path)
    p.add_argument('--fold-bn',action='store_true');p.add_argument('--int8',action='store_true')
    p.add_argument('--int8-max-disagreement',type=float)
    p.add_argument('--validation-samples',type=int,default=1024);p.add_argument('--calibration-samples',type=int,default=1000)
    p.add_argument('--atol',type=float,default=1e-6);p.add_argument('--rtol',type=float,default=1e-5)
    p.add_argument('--board-atol',type=float,default=1e-6);p.add_argument('--board-rtol',type=float,default=1e-5)
    a=p.parse_args()
    require(a.validation_samples>0 and a.calibration_samples>0,'Positive sample counts required')
    require(all(np.isfinite(v) and v>=0 for v in (a.atol,a.rtol,a.board_atol,a.board_rtol)), 'Invalid numerical tolerance')
    require(not a.int8 or (a.int8_max_disagreement is not None and 0<=a.int8_max_disagreement<=1),
            '--int8 requires an explicitly chosen --int8-max-disagreement before evaluation')
    try:
        import onnx
        import onnxruntime as ort
    except ImportError as e:
        raise RuntimeError('ONNX export requires onnx and onnxruntime in the selected uv environment; no package is auto-installed') from e
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True,warn_only=False)
    torch.set_float32_matmul_precision('highest')
    plan,job,result,meta,arrays,model,cp=checkpoint_context(a.run_dir,a.dataset,a.model)
    a.output_dir.mkdir(parents=True,exist_ok=False)
    policy={'schema':SCHEMA,'source_plan_sha256':plan['content_sha256'],'checkpoint_sha256':sha256(cp),
            'best_model_sha256':tree_digest(model.state_dict()),'data_fingerprint':meta['data_fingerprint'],
            'preprocessor_sha256':meta['preprocessor_sha256'],'deployment_seed':plan['deployment_seed'],
            'fold_bn':a.fold_bn,'int8':a.int8,'atol':a.atol,'rtol':a.rtol,
            'board_atol':a.board_atol,'board_rtol':a.board_rtol,
            'int8_max_disagreement':a.int8_max_disagreement,'validation_samples':a.validation_samples,
            'calibration_samples':a.calibration_samples,'opset':17,'export_batch':1,
            'onnx':onnx.__version__,'onnxruntime':ort.__version__,'torch':str(torch.__version__),
            'npu_placement':'UNVERIFIED; vendor mapping report and on-board parity required'}
    write_json(a.output_dir/'export_policy.json',seal(policy))
    try:
        rng=np.random.default_rng(0)
        vi=np.sort(rng.choice(len(arrays['y_validation']),min(a.validation_samples,len(arrays['y_validation'])),replace=False))
        ci=np.sort(rng.choice(len(arrays['y_fit']),min(a.calibration_samples,len(arrays['y_fit'])),replace=False))
        vectors=np.asarray(arrays['x_validation'][vi],dtype=np.float32)
        frozen=freeze_for_export(model,fold_bn=a.fold_bn)
        with torch.inference_mode():
            # Same batch=1 contract as the deployed graph. Batch-size changes are not silently ignored.
            original=np.concatenate([model(torch.from_numpy(x[None])).numpy() for x in vectors])
            frozen_logits=np.concatenate([frozen(torch.from_numpy(x[None])).numpy() for x in vectors])
        freeze_check=compare_logits(original,frozen_logits,a.atol,a.rtol)
        require(freeze_check['allclose'] and freeze_check['prediction_disagreement_fraction']==0,
                'BN folding/freezing changed outputs beyond the predeclared gate; inspect boundary activations')
        fp=a.output_dir/'model_fp32.onnx'
        torch.onnx.export(frozen,torch.from_numpy(vectors[:1]),str(fp),dynamo=False,
                          input_names=['input'],output_names=['logits'],opset_version=17,
                          do_constant_folding=False,training=torch.onnx.TrainingMode.EVAL)
        graph=onnx.load(fp);onnx.checker.check_model(graph)
        def session(path):
            o=ort.SessionOptions();o.intra_op_num_threads=1;o.inter_op_num_threads=1
            o.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
            o.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
            return ort.InferenceSession(str(path),sess_options=o,providers=['CPUExecutionProvider'])
        def evaluate(path):
            s=session(path)
            return np.concatenate([s.run(['logits'],{'input':x[None]})[0] for x in vectors])
        onnx_logits=evaluate(fp);onnx_check=compare_logits(original,onnx_logits,a.atol,a.rtol)
        require(onnx_check['allclose'] and onnx_check['prediction_disagreement_fraction']==0,'ONNX numerical parity gate failed')
        report={'schema':SCHEMA,'status':'validated_on_sampled_validation_vectors','policy_sha256':digest(policy),
                'freeze_check':freeze_check,'onnx_check':onnx_check,'graph_sha256':sha256(fp),
                'fp32_operators':sorted({node.op_type for node in graph.graph.node}),
                'preprocessor_sha256':meta['preprocessor_sha256'],'checkpoint_sha256':sha256(cp),
                'board_validated':False,'energy_measured':False,'npu_placement_verified':False,
                'reference_kind':'fp32_onnx','data_fingerprint':meta['data_fingerprint'],
                'source_plan_sha256':plan['content_sha256']}
        deployed_reference=onnx_logits
        if a.int8:
            from onnxruntime.quantization import quantize_static,QuantFormat,QuantType,CalibrationMethod,CalibrationDataReader
            class Reader(CalibrationDataReader):
                def __init__(self):self.position=0
                def get_next(self):
                    if self.position==len(ci):return None
                    index=int(ci[self.position]);self.position+=1
                    return {'input':np.asarray(arrays['x_fit'][index:index+1],dtype=np.float32)}
            quantized=a.output_dir/'model_qdq_int8.onnx'
            quantize_static(str(fp),str(quantized),Reader(),quant_format=QuantFormat.QDQ,
                            activation_type=QuantType.QInt8,weight_type=QuantType.QInt8,
                            per_channel=True,calibrate_method=CalibrationMethod.MinMax,
                            op_types_to_quantize=['Gemm','MatMul','Conv'],calibration_providers=['CPUExecutionProvider'])
            qgraph=onnx.load(quantized);onnx.checker.check_model(qgraph)
            deployed_reference=evaluate(quantized)
            check=compare_logits(onnx_logits,deployed_reference,a.atol,a.rtol)
            require(check['prediction_disagreement_fraction']<=a.int8_max_disagreement,'QDQ validation disagreement gate failed')
            report.update(quantization_check=check,quantized_graph_sha256=sha256(quantized),
                          qdq_operators=sorted({n.op_type for n in qgraph.graph.node}),
                          reference_kind='qdq_int8_onnx',
                          quantization_scope='selected linear/conv operators; QDQ does NOT establish all-integer or all-NPU execution')
        atomic_write(a.output_dir/'validation_vectors.npz',lambda f:np.savez(f,x=vectors,reference_logits=deployed_reference,
                    original_logits=original,validation_row_ids=arrays['ids_validation'][vi]))
        write_json(a.output_dir/'calibration_rows.json',{'partition':'fit','row_ids':arrays['ids_fit'][ci].tolist(),
                   'ids_sha256':array_sha256(arrays['ids_fit'][ci])})
        write_json(a.output_dir/'preprocessing.json',load_json(Path(job['cache'])/'preprocessing.json'))
        report['files_sha256']={p.name:sha256(p) for p in sorted(a.output_dir.iterdir()) if p.is_file()}
        write_json(a.output_dir/'export_report.json',seal(report));print(report)
    except Exception as exc:
        write_json(a.output_dir/'FAILED.json',{'status':'failed','reason':str(exc),'publication_gate':False})
        raise
if __name__=='__main__':main()
