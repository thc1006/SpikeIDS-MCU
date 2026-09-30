"""One manifest, one GPU worker, global fit -> independent repeat -> test barrier.

No remote writes, package installation, process killing, or historical-result reuse.
Command failures propagate. Every job's complete output is logged.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from contracts import *
from data_loaders import prepare, open_cache
from evidence import read_plan, load_fit, load_result


def run_command(command, log: Path):
    log.parent.mkdir(parents=True,exist_ok=True)
    print("Running:", " ".join(map(str,command)),flush=True)
    with log.open("a",encoding="utf-8") as f:
        f.write("\nCOMMAND: "+repr(command)+"\n"); f.flush()
        result=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,check=False)
    require(result.returncode==0,f"Command failed with exit {result.returncode}; full log: {log}")


def common_parser(p):
    p.add_argument("--run-dir",type=Path,required=True)


def make_parser():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    sub=p.add_subparsers(dest="action",required=True)
    prep=sub.add_parser("prepare",allow_abbrev=False)
    prep.add_argument("--data-dir",type=Path,required=True)
    prep.add_argument("--cache-root",type=Path,required=True)
    prep.add_argument("--source-spec-dir",type=Path)
    prep.add_argument("--chunksize",type=int,default=65536)
    freeze=sub.add_parser("freeze",allow_abbrev=False);common_parser(freeze)
    freeze.add_argument("--cache-root",type=Path,required=True)
    freeze.add_argument("--device",choices=("cuda","cpu"),default="cuda")
    freeze.add_argument("--optimizer",choices=("single","foreach","fused"),default="single")
    freeze.add_argument("--threads",type=int,default=4)
    freeze.add_argument("--seeds",nargs="+",type=int,default=list(range(20)))
    freeze.add_argument("--delta",type=float,default=1.)
    freeze.add_argument("--alpha",type=float,default=.05)
    # This explicit testing protocol can never pass a paper-finalization gate.
    freeze.add_argument("--smoke-epochs",type=int)
    for name in ("fit","verify","evaluate","run"):
        common_parser(sub.add_parser(name,allow_abbrev=False))
    return p


def freeze(args):
    from stats_tests import validate_alpha
    validate_alpha(args.alpha)
    require(args.delta>0 and args.delta<float('inf'),"Invalid equivalence margin")
    require(args.threads>=1 and args.seeds and len(args.seeds)==len(set(args.seeds)) and
            len(args.seeds)<=100 and all(0<=s<2**32 for s in args.seeds),"Invalid threads/seeds")
    require(args.smoke_epochs is None or args.smoke_epochs>=1,"Invalid smoke budget")
    run_dir=args.run_dir.resolve()
    require(not run_dir.exists(),"Freeze requires a fresh directory; never overwrites an existing protocol")
    run_dir.mkdir(parents=True)
    env_file=run_dir/"environment.json"
    run_command([sys.executable,str(PACKAGE/"experiment_all.py"),"--probe","--device",args.device,
                 "--threads",str(args.threads),"--output",str(env_file)],run_dir/"logs"/"environment.log")
    env=load_json(env_file)
    jobs=[]
    for dataset in DATASETS:
        cache=(args.cache_root/dataset).resolve()
        meta,_=open_cache(cache)
        require(meta["dataset"]==dataset,"Wrong cache directory")
        for arm in ARMS[dataset]:
            h={"dataset":dataset,"model":arm,"seeds":sorted(args.seeds),
               "epochs":args.smoke_epochs or (40 if dataset=="iot23" else 80),
               "batch_size":1024 if dataset=="iot23" else 512,"eval_batch_size":4096,
               "eval_every":10,"checkpoint_every":10,"hidden":256,"levels":4,"qcfs_formula":"shifted_v1",
               "lr":.001,"weight_decay":.00001,"device":args.device,"optimizer":args.optimizer,
               "threads":args.threads,"data_placement":"gpu" if args.device=="cuda" else "cpu","compile":False}
            jobs.append({"id":dataset+"_"+arm,"dataset":dataset,"model":arm,"cache":str(cache),
                         "data_fingerprint":meta["data_fingerprint"],"hyperparameters":h})
    plan={"schema":SCHEMA,"seeds":sorted(args.seeds),"jobs":jobs,"sources":sources(),"environment":env,
          "alpha":args.alpha,"equivalence_margin_pp":args.delta,
          "difference_family":[f"{d}:relu_vs_{a}:{m}" for d in DATASETS for a in ARMS[d] if a!="relu" for m in METRICS],
          "equivalence_family":[f"{d}:{m}" for d in DATASETS for m in METRICS],
          "protocol_role":"smoke_only" if args.smoke_epochs else "planned_benchmark",
          "margin_status":"frozen now; this does not establish historical preregistration",
          "prior_test_exposure":"unknown outside this run directory; disclose historical exploration",
          "deployment_seed":0 if 0 in args.seeds else min(args.seeds)}
    write_json(run_dir/"plan.json",seal(plan))
    print("Frozen",run_dir/"plan.json",flush=True)


def job_command(job, output, stage):
    command=[sys.executable,str(PACKAGE/"experiment_all.py"),"--cache",job["cache"],"--output",str(output),"--stage",stage]
    for key,value in job["hyperparameters"].items():
        flag="--"+key.replace('_','-')
        if isinstance(value,bool):
            if value: command.append(flag)
        elif isinstance(value,list): command.extend([flag,*map(str,value)])
        else: command.extend([flag,str(value)])
    if output.exists() or output.with_suffix("").exists(): command.append("--resume")
    return command


def all_fits(run_dir,plan,replica=False):
    destination=run_dir/("replicas" if replica else "results")
    for job in plan["jobs"]:
        output=destination/f"{job['id']}.json"
        run_command(job_command(job,output,"fit"),run_dir/"logs"/f"{'replica_' if replica else ''}{job['id']}_fit.log")
        load_fit(output,job,plan)


def verify_training(run_dir,plan):
    # Check all primary fits BEFORE spending time on the second independent execution.
    primary={j["id"]:load_fit(run_dir/"results"/f"{j['id']}.json",j,plan) for j in plan["jobs"]}
    all_fits(run_dir,plan,replica=True)
    jobs={}
    for job in plan["jobs"]:
        a=primary[job["id"]];b=load_fit(run_dir/"replicas"/f"{job['id']}.json",job,plan)
        require(a["fingerprint"]==b["fingerprint"] and a["training_digest"]==b["training_digest"],
                f"Independent training differs for {job['id']}; test evaluation remains blocked")
        jobs[job["id"]]=a["training_digest"]
    write_json(run_dir/"verification_fit.json",seal({"plan_sha256":plan["content_sha256"],"passed":True,"jobs":jobs,
        "scope":"two independent initializations/training executions on the recorded stack; not cross-platform proof"}))


def evaluate(run_dir,plan):
    v=load_json(run_dir/"verification_fit.json");check_seal(v)
    require(v["passed"] and v["plan_sha256"]==plan["content_sha256"],"Full training verification not passed")
    for job in plan["jobs"]:
        for folder in ("results","replicas"):
            r=load_fit(run_dir/folder/f"{job['id']}.json",job,plan)
            require(v["jobs"].get(job["id"])==r["training_digest"],"Training verification stale")
    # Global barrier: no test metric in this suite until ALL 22 job executions passed fit verification.
    jobs={}
    for job in plan["jobs"]:
        results=[]
        for folder in ("results","replicas"):
            output=run_dir/folder/f"{job['id']}.json"
            run_command(job_command(job,output,"evaluate"),run_dir/"logs"/f"{folder}_{job['id']}_evaluate.log")
            results.append(load_result(output,job,plan))
        require(results[0]["scientific_digest"]==results[1]["scientific_digest"],f"Test predictions differ: {job['id']}")
        jobs[job["id"]]=results[0]["scientific_digest"]
    write_json(run_dir/"verification_evaluate.json",seal({"plan_sha256":plan["content_sha256"],"passed":True,"jobs":jobs,
           "scope":"per-seed states, logits, probabilities, predictions, and independently recomputed metrics"}))


def main():
    args=make_parser().parse_args()
    if args.action=="prepare":
        for d in DATASETS:
            spec=args.source_spec_dir/(d+".json") if args.source_spec_dir else None
            meta,_=prepare(d,args.data_dir,args.cache_root/d,chunksize=args.chunksize,source_spec=spec)
            print(d,meta["counts"],meta["data_fingerprint"],flush=True)
        return
    if args.action=="freeze": freeze(args);return
    run_dir=args.run_dir.resolve()
    with file_lock(run_dir/"pipeline.lock"):
        plan=read_plan(run_dir)
        if args.action in ("fit","run"): all_fits(run_dir,plan)
        if args.action in ("verify","run"): verify_training(run_dir,plan)
        if args.action in ("evaluate","run"): evaluate(run_dir,plan)

if __name__=="__main__":
    try: main()
    except (ValueError,RuntimeError,FileNotFoundError) as e:
        print("ERROR:",e,file=sys.stderr);raise SystemExit(2) from e
