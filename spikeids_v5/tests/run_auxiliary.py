"""Small real CPU CLI checks for benchmark, standalone verifier and explicit L-sweep."""
import argparse
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import contracts as c


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache',required=True,type=Path);p.add_argument('--work-dir',required=True,type=Path)
    a=p.parse_args();a.work_dir.mkdir(parents=True,exist_ok=False)
    steps=[]
    def run(script,*args):
        command=[sys.executable,str(c.PACKAGE/script),*map(str,args)]
        log=a.work_dir/f'{len(steps)}_{Path(script).stem}.log'
        with log.open('w') as f:r=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT)
        c.require(r.returncode==0,f'Command failed; see {log}')
        steps.append({'script':script,'args':list(map(str,args)),'returncode':r.returncode,'log':log.name})
    run('benchmark_profiles.py','--dataset','nslkdd','--cache',a.cache,'--work-dir',a.work_dir/'bench',
        '--device','cpu','--profiles','single:1','foreach:1','--models','relu','qcfs','--epochs','1')
    benchmark=c.load_json(a.work_dir/'bench'/'benchmark.json');c.check_seal(benchmark)
    c.require(len(benchmark['qualified'])==2 and not benchmark['failed'] and not benchmark['test_evaluated'],'Benchmark did not qualify both CPU candidates')
    run('verify_reproducibility.py','--work-dir',a.work_dir/'verify','--','--dataset','nslkdd','--cache',a.cache,
        '--model','qcfs','--device','cpu','--optimizer','single','--threads','1','--seeds','0','1','--epochs','1')
    c.require(c.load_json(a.work_dir/'verify'/'verification.json')['passed'],'Standalone verifier failed')
    for stage in ('fit','evaluate'):
        run('experiment_qcfs_lsweep.py','--dataset','nslkdd','--cache',a.cache,'--work-dir',a.work_dir/'levels',
            '--levels','1','4','--seeds','0','1','--epochs','2','--device','cpu','--optimizer','single','--threads','1','--stage',stage)
    sweep=c.load_json(a.work_dir/'levels'/'ablation_results.json');c.check_seal(sweep)
    c.require(set(sweep['results'])=={'1','4'},'Level outputs incomplete')
    report={'status':'passed','scope':'synthetic NSL-shaped CSV/CPU CLI only; NOT GPU speed ranking or paper L-sweep',
        'independent_training_executions':{'benchmark':8,'verifier':4,'L_sweep':8},
        'test_checkpoint_evaluations':8,'steps':steps,'sources':c.sources()}
    c.write_json(a.work_dir/'auxiliary_report.json',report);print('AUXILIARY_INTEGRATION_PASSED',flush=True)

if __name__=='__main__':main()
