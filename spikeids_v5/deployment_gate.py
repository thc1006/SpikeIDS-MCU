"""Offline board evidence validator. It never flashes, halts, resets or clocks a board.

A passed file-consistency check is not cryptographic attestation of measurements.
Raw board vectors, logs, binary, compiler mapping and clock evidence must be supplied.
Synthetic representative-kernel timing cannot be reclassified as trained-model timing.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
from contracts import *
from export_verified import compare_logits


def cycles_to_microseconds(cycles,cpu_hz):
    values=np.asarray(cycles)
    require(values.ndim==1 and len(values)>0 and values.dtype.kind in 'iu' and (values>0).all(),'Positive integer cycle samples required')
    hz=finite(cpu_hz,'timer clock Hz');require(hz>0,'Timer frequency must be positive')
    return values.astype(float)/hz*1e6


def validate(bundle: Path,evidence: Path):
    bundle,evidence=Path(bundle),Path(evidence)
    report=load_json(bundle/'export_report.json');check_seal(report)
    require(not (bundle/'FAILED.json').exists(),'Export bundle contains a failed gate')
    require({'export_policy.json','validation_vectors.npz','preprocessing.json','calibration_rows.json','model_fp32.onnx'}.issubset(report['files_sha256']),
            'Export inventory is incomplete')
    for name,expected in report['files_sha256'].items():
        require(Path(name).name==name and (bundle/name).is_file(), 'Invalid export artifact path')
        require(sha256(bundle/name)==expected,f'Export artifact changed: {name}')
    policy=load_json(bundle/'export_policy.json');check_seal(policy)
    require(report['policy_sha256']==digest({k:v for k,v in policy.items() if k!='content_sha256'}),'Export policy binding invalid')
    record=load_json(evidence);root=evidence.parent
    require(record['output_atol']==policy['board_atol'] and record['output_rtol']==policy['board_rtol'],
            'Board tolerances differ from the policy frozen before validation')
    require(record.get('schema')==SCHEMA and record.get('role')=='trained_model_inference',
            'Only trained-model evidence is accepted, not synthetic kernel benchmarks')
    require(record['export_report_sha256']==sha256(bundle/'export_report.json'),'Board evidence refers to a different export bundle')
    graph_hash=report.get('quantized_graph_sha256',report['graph_sha256'])
    require(record['compiled_graph_sha256']==graph_hash,'Compiled graph differs from validated ONNX')
    for name in ('firmware_binary','compiler_mapping_report','clock_evidence','raw_timing_log','board_logits'):
        item=record[name];p=root/item['path']
        require(p.resolve().is_relative_to(root.resolve()) and p.is_file(),f'Missing/out-of-scope {name}')
        require(sha256(p)==item['sha256'],f'Changed board evidence: {name}')
    require(record['input_vectors_sha256']==sha256(bundle/'validation_vectors.npz'),'Board inputs are not the checked validation vectors')
    require(record['compiler_version'] and record['compile_options'] is not None and record['board_id'],'Missing build/board identity')
    require(record['timing_scope'] in ('inference_only','end_to_end'),'Explicit timing scope required')
    clock=load_json(root/record['clock_evidence']['path'])
    require(clock['timer_hz']==record['timer_hz'] and clock.get('derivation') and clock.get('raw_registers_or_measurement'),
            'Timer clock needs matching raw evidence and documented derivation, not a marketing clock')
    timing=load_json(root/record['raw_timing_log']['path'])
    cycles=np.asarray(timing['cycles'])
    require(timing.get('includes_warmup') is False and timing.get('counter_wraps_unresolved') is False,
            'Warm-up samples or unresolved timer wraps cannot feed the latency summary')
    us=cycles_to_microseconds(cycles,record['timer_hz'])
    actual=np.load(root/record['board_logits']['path'],allow_pickle=False)
    with np.load(bundle/'validation_vectors.npz',allow_pickle=False) as data:
        check=compare_logits(data['reference_logits'],actual,record['output_atol'],record['output_rtol'])
    require(check['allclose'] and check['prediction_disagreement_fraction']==0,'On-board output parity failed')
    return {'schema':SCHEMA,'evidence_files_consistent':True,'output_parity':check,
            'latency_us':{'n':len(us),'median':float(np.median(us)),'p95':float(np.quantile(us,.95,method='linear')),
                          'min':float(us.min()),'max':float(us.max())},'timing_scope':record['timing_scope'],
            'energy_measured':False,'physical_measurement_authenticity_verified':False,
            'note':'Independent review of raw clock/register/measurement provenance and vendor mapping remains required.'}


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--bundle',required=True,type=Path);p.add_argument('--evidence',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);a=p.parse_args()
    write_json(a.output,seal(validate(a.bundle,a.evidence)))
if __name__=='__main__':main()
