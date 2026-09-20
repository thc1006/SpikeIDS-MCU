"""Execute real small CPU fits across all 11 jobs, then test evidence refusal.

Run from any directory with a NEW --work-dir. Synthetic data never enter a paper.
This is intentionally not auto-collected by pytest; it starts many real processes.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
PACKAGE=HERE.parent
sys.path.insert(0,str(PACKAGE))
sys.path.insert(0,str(HERE))
from conftest import make_raw
import contracts as c


def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('--work-dir',required=True,type=Path)
    args=parser.parse_args();work=args.work_dir.resolve();work.mkdir(parents=True,exist_ok=False)
    make_raw(work/'raw');started=time.perf_counter();steps=[]
    def run(script,*arguments,success=True):
        command=[sys.executable,str(PACKAGE/script),*map(str,arguments)]
        index=len(steps);log=work/f'step_{index:02d}_{Path(script).stem}.log'
        print('STEP',index,repr(command),flush=True)
        with log.open('w') as f:
            p=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT)
        c.require((p.returncode==0)==success,f'Unexpected exit {p.returncode}: {command}; see {log}')
        steps.append({'script':script,'arguments':list(map(str,arguments)),
                      'returncode':p.returncode,'expected_success':success,'log':log.name})
    run('suite.py','prepare','--data-dir',work/'raw','--cache-root',work/'cache','--chunksize','31')
    run('suite.py','freeze','--cache-root',work/'cache','--run-dir',work/'run',
        '--device','cpu','--optimizer','single','--threads','1','--seeds','0','1','--smoke-epochs','2')
    run('suite.py','run','--run-dir',work/'run')
    for name in ('run_globecom_stats.py','run_v4_equivalence.py','assemble_nsl_legacy.py','assemble_cnn_legacy.py'):
        run(name,'--run-dir',work/'run')
    run('layerwise_analysis.py','--run-dir',work/'run','--dataset','nslkdd','--model','qcfs','--output',work/'layerwise.json')
    run('snn_analysis.py','--run-dir',work/'run','--dataset','nslkdd','--output',work/'snn.json')
    run('finalize_all_det.py','--run-dir',work/'run','--paper-dir',work/'paper',success=False)
    c.require(not (work/'paper'/'result_macros_v5.tex').exists(),'Smoke metrics were promoted to a paper')
    # The following mutations are of synthetic test evidence ONLY, and are restored in finally.
    from evidence import load_result,verified_suite
    target=work/'run'/'results'/'nslkdd_relu.json';original=target.read_bytes();refused=[]
    for case in ('alter_counts','reorder_seed_ids','alter_aggregate','alter_data_identity'):
        data=json.loads(original);data.pop('content_sha256')
        if case=='alter_counts':data['counts']['fit']+=1
        if case=='reorder_seed_ids':
            data['per_seed'][0]['seed'],data['per_seed'][1]['seed']=data['per_seed'][1]['seed'],data['per_seed'][0]['seed']
        if case=='alter_aggregate':data['aggregate']['overall_acc']['mean']+=1
        if case=='alter_data_identity':data['data_fingerprint']='0'*64
        try:
            c.write_json(target,c.seal(data))
            try:load_result(target)
            except (ValueError,RuntimeError):refused.append(case)
            else:raise AssertionError(f'Evidence mutation was not refused: {case}')
        finally:target.write_bytes(original)
    replica=work/'run'/'replicas'/'nslkdd_relu.json';backup=replica.with_suffix('.missing-test')
    replica.rename(backup)
    try:
        try:verified_suite(work/'run')
        except FileNotFoundError:refused.append('missing_replica')
        else:raise AssertionError('Missing independent replica was ignored')
    finally:backup.rename(replica)
    plan=c.load_json(work/'run'/'plan.json')
    vf=c.load_json(work/'run'/'verification_fit.json');ve=c.load_json(work/'run'/'verification_evaluate.json')
    c.require(vf['passed'] and ve['passed'],'Verification incomplete')
    report={'status':'passed','data':'synthetic raw-shaped CSV fixtures, NOT real benchmark outcomes',
        'n_dataset_model_jobs':len(plan['jobs']),'seeds':[0,1],'epochs':2,
        'independent_model_training_executions':len(plan['jobs'])*2*2,
        'test_checkpoint_evaluations':len(plan['jobs'])*2*2,
        'negative_evidence_checks_passed':refused,'smoke_paper_promotion_refused':True,
        'sources':c.sources(),'plan_sha256':plan['content_sha256'],'steps':steps,
        'wall_seconds':time.perf_counter()-started}
    c.write_json(work/'integration_report.json',report)
    print('ALL_INTEGRATION_STEPS_PASSED',json.dumps(report),flush=True)

if __name__=='__main__':main()
