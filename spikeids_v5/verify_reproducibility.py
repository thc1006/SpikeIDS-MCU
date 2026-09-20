"""Two genuinely separate, fit-only executions for one declared configuration.

Use suite.py for all 11 models/seeds and full test-prediction verification. This
helper is for smoke checks and narrow ablations; it never declares the paper valid.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
import time
from contracts import *
from suite import run_command
from evidence import load_fit


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument("--work-dir",required=True,type=Path)
    p.add_argument("arguments",nargs=argparse.REMAINDER)
    a=p.parse_args();forwarded=a.arguments[1:] if a.arguments[:1]==["--"] else a.arguments
    forbidden=("--stage","--resume","--output","--probe")
    require(not any(x==k or x.startswith(k+'=') for x in forwarded for k in forbidden),
            "Do not forward stage/resume/output/probe; independent fit-only runs are required")
    a.work_dir.mkdir(parents=True,exist_ok=False)
    results=[];times=[]
    for name in ('a','b'):
        out=(a.work_dir/(name+'.json')).resolve()
        start=time.perf_counter()
        run_command([sys.executable,str(PACKAGE/'experiment_all.py'),*forwarded,'--stage','fit','--output',str(out)],a.work_dir/(name+'.log'))
        times.append(time.perf_counter()-start);results.append(load_fit(out))
    passed=results[0]['fingerprint']==results[1]['fingerprint'] and results[0]['training_digest']==results[1]['training_digest']
    report={'passed':passed,'wall_seconds':times,'fingerprint':results[0]['fingerprint'],
            'training_digest':results[0]['training_digest'],'scope':'same recorded hardware/software/protocol; fit only'}
    write_json(a.work_dir/'verification.json',seal(report));print(report)
    require(passed,'Independent repeats diverged')
if __name__=='__main__':main()
