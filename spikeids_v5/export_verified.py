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


QDQ_RECIPE = {
    'quant_format':'QDQ','activation_type':'QInt8','weight_type':'QInt8',
    'per_channel':True,'reduce_range':False,'calibrate_method':'MinMax',
    'op_types_to_quantize':['Gemm','MatMul','Conv'],
    'nodes_to_quantize':[],'nodes_to_exclude':[],
    'use_external_data_format':False,'calibration_providers':['CPUExecutionProvider'],
    'extra_options':{},
    'unspecified_behavior':'bound to the recorded ONNX Runtime version and source',
}


def frozen_export_context(path, plan, dataset, model, mode, checkpoint):
    """Require the runner's already registered policy before doing any numerical work."""
    require(path is not None, 'Formal export requires a registered --export-plan')
    path=Path(path)
    require(path.is_file() and not path.is_symlink() and path.stat().st_nlink==1,
            'Export plan must be a regular unaliased file')
    value=load_json(path);check_seal(value)
    require(value.get('schema')==1 and value.get('kind')=='spikeids_v5_export_plan' and
            value.get('source_plan_sha256')==plan['content_sha256'],
            'Export plan belongs to another neural plan')
    registration=load_json(Path(value['run_dir'])/'export_registration.json');check_seal(registration)
    require(registration.get('export_plan_sha256')==value['content_sha256'] and
            registration.get('export_plan_file_sha256')==sha256(path) and
            registration.get('export_plan_path')==str(path.resolve()),
            'Export registration changed after the pre-attempt freeze')
    for source in value['sources']:
        source_path=Path(source['path'])
        require(source_path.is_file() and not source_path.is_symlink() and
                source_path.stat().st_nlink==1 and sha256(source_path)==source['sha256'],
                'Export source changed after policy freeze')
    protocol=value['protocol']
    require(protocol.get('qdq_recipe')==QDQ_RECIPE and protocol.get('deployment_seed')==0 and
            protocol.get('fold_bn') is True and protocol.get('opset')==17 and
            protocol.get('export_batch')==1 and protocol.get('fp32_atol')==1e-6 and
            protocol.get('fp32_rtol')==1e-5 and protocol.get('fp32_max_prediction_disagreement')==0.0 and
            protocol.get('int8_max_prediction_disagreement')==0.01 and
            protocol.get('validation_samples')==1024 and protocol.get('calibration_samples')==1000,
            'Frozen export numerical/quantization policy differs')
    attempts=[a for a in value['attempts'] if (a['dataset'],a['model'],a['mode'])==(dataset,model,mode)]
    require(len(attempts)==1 and attempts[0]['checkpoint_sha256']==sha256(checkpoint),
            'Checkpoint/mode is not the frozen export attempt')
    return value


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
    p.add_argument('--export-plan',type=Path)
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
    export_plan=None
    if plan.get('protocol_role')=='planned_benchmark' or a.export_plan is not None:
        export_plan=frozen_export_context(a.export_plan,plan,a.dataset,a.model,'qdq' if a.int8 else 'fp32',cp)
        require(a.fold_bn and a.atol==1e-6 and a.rtol==1e-5 and
                a.validation_samples==1024 and a.calibration_samples==1000 and
                (not a.int8 or a.int8_max_disagreement==0.01),
                'Exporter arguments differ from the frozen formal export protocol')
    require(len(arrays['y_validation'])>=a.validation_samples and len(arrays['y_fit'])>=a.calibration_samples,
            'Declared validation/calibration samples exceed partition size; no silent truncation')
    a.output_dir.mkdir(parents=True,exist_ok=False)
    policy={'schema':SCHEMA,'source_plan_sha256':plan['content_sha256'],'checkpoint_sha256':sha256(cp),
            'best_model_sha256':tree_digest(model.state_dict()),'data_fingerprint':meta['data_fingerprint'],
            'preprocessor_sha256':meta['preprocessor_sha256'],'deployment_seed':plan['deployment_seed'],
            'fold_bn':a.fold_bn,'int8':a.int8,'atol':a.atol,'rtol':a.rtol,
            'board_atol':a.board_atol,'board_rtol':a.board_rtol,
            'int8_max_disagreement':a.int8_max_disagreement,'validation_samples':a.validation_samples,
            'calibration_samples':a.calibration_samples,'opset':17,'export_batch':1,
            'onnx':onnx.__version__,'onnxruntime':ort.__version__,'torch':str(torch.__version__),
            'export_plan_sha256':export_plan['content_sha256'] if export_plan else None,
            'qdq_recipe':QDQ_RECIPE,
            'npu_placement':'UNVERIFIED; vendor mapping report and on-board parity required'}
    write_json(a.output_dir/'export_policy.json',seal(policy))
    stage='row_selection';diagnostics={}
    try:
        rng=np.random.default_rng(0)
        vi=np.sort(rng.choice(len(arrays['y_validation']),a.validation_samples,replace=False))
        ci=np.sort(rng.choice(len(arrays['y_fit']),a.calibration_samples,replace=False))
        vectors=np.asarray(arrays['x_validation'][vi],dtype=np.float32)
        if export_plan is not None:
            selection=export_plan['datasets'][a.dataset]['selection']
            require(selection['validation']['indices']==vi.tolist() and selection['fit']['indices']==ci.tolist() and
                    selection['validation']['row_ids']==arrays['ids_validation'][vi].tolist() and
                    selection['fit']['row_ids']==arrays['ids_fit'][ci].tolist() and
                    selection['validation']['x_sha256']==array_sha256(vectors) and
                    selection['fit']['x_sha256']==array_sha256(np.asarray(arrays['x_fit'][ci],dtype=np.float32)),
                    'Actual export/calibration rows differ from the frozen selection')
        stage='freeze'
        frozen=freeze_for_export(model,fold_bn=a.fold_bn)
        with torch.inference_mode():
            # Same batch=1 contract as the deployed graph. Batch-size changes are not silently ignored.
            original=np.concatenate([model(torch.from_numpy(x[None])).numpy() for x in vectors])
            frozen_logits=np.concatenate([frozen(torch.from_numpy(x[None])).numpy() for x in vectors])
        freeze_check=compare_logits(original,frozen_logits,a.atol,a.rtol)
        diagnostics['freeze_check']=freeze_check
        require(freeze_check['allclose'] and freeze_check['prediction_disagreement_fraction']==0,
                'BN folding/freezing changed outputs beyond the predeclared gate; inspect boundary activations')
        fp=a.output_dir/'model_fp32.onnx'
        stage='fp32_export'
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
        stage='fp32_parity'
        onnx_logits=evaluate(fp);onnx_check=compare_logits(original,onnx_logits,a.atol,a.rtol)
        diagnostics['onnx_check']=onnx_check
        require(onnx_check['allclose'] and onnx_check['prediction_disagreement_fraction']==0,'ONNX numerical parity gate failed')
        report={'schema':SCHEMA,'status':'validated_on_sampled_validation_vectors','policy_sha256':digest(policy),
                'freeze_check':freeze_check,'onnx_check':onnx_check,'graph_sha256':sha256(fp),
                'fp32_operators':sorted({node.op_type for node in graph.graph.node}),
                'preprocessor_sha256':meta['preprocessor_sha256'],'checkpoint_sha256':sha256(cp),
                'board_validated':False,'energy_measured':False,'npu_placement_verified':False,
                'reference_kind':'fp32_onnx','data_fingerprint':meta['data_fingerprint'],
                'source_plan_sha256':plan['content_sha256'],
                'export_plan_sha256':export_plan['content_sha256'] if export_plan else None}
        deployed_reference=onnx_logits
        if a.int8:
            stage='qdq_quantization'
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
                            per_channel=True,reduce_range=False,calibrate_method=CalibrationMethod.MinMax,
                            op_types_to_quantize=['Gemm','MatMul','Conv'],
                            nodes_to_quantize=[],nodes_to_exclude=[],use_external_data_format=False,
                            calibration_providers=['CPUExecutionProvider'],extra_options={})
            qgraph=onnx.load(quantized);onnx.checker.check_model(qgraph)
            stage='qdq_parity';deployed_reference=evaluate(quantized)
            check=compare_logits(onnx_logits,deployed_reference,a.atol,a.rtol)
            diagnostics['quantization_check']=check
            require(check['prediction_disagreement_fraction']<=a.int8_max_disagreement,'QDQ validation disagreement gate failed')
            report.update(quantization_check=check,quantized_graph_sha256=sha256(quantized),
                          qdq_operators=sorted({n.op_type for n in qgraph.graph.node}),
                          reference_kind='qdq_int8_onnx',
                          quantization_scope='selected linear/conv operators; QDQ does NOT establish all-integer or all-NPU execution')
        stage='payload_write'
        atomic_write(a.output_dir/'validation_vectors.npz',lambda f:np.savez(f,x=vectors,reference_logits=deployed_reference,
                    original_logits=original,validation_row_ids=arrays['ids_validation'][vi]))
        write_json(a.output_dir/'calibration_rows.json',{'partition':'fit','row_ids':arrays['ids_fit'][ci].tolist(),
                   'ids_sha256':array_sha256(arrays['ids_fit'][ci])})
        write_json(a.output_dir/'preprocessing.json',load_json(Path(job['cache'])/'preprocessing.json'))
        report['files_sha256']={p.name:sha256(p) for p in sorted(a.output_dir.iterdir()) if p.is_file()}
        if export_plan is not None:
            require(frozen_export_context(a.export_plan,plan,a.dataset,a.model,'qdq' if a.int8 else 'fp32',cp)==export_plan,
                    'Export policy changed during graph generation')
        write_json(a.output_dir/'export_report.json',seal(report));print(report)
    except Exception as exc:
        write_json(a.output_dir/'FAILED.json',seal({'schema':1,'status':'failed','stage':stage,
                   'reason':f'{type(exc).__name__}: {exc}','publication_gate':False,
                   'source_plan_sha256':plan['content_sha256'],
                   'export_plan_sha256':export_plan['content_sha256'] if export_plan else None,
                   'checkpoint_sha256':sha256(cp),'diagnostics':diagnostics,
                   'partial_files_sha256':{p.name:sha256(p) for p in sorted(a.output_dir.iterdir()) if p.is_file()}}))
        raise
if __name__=='__main__':main()
