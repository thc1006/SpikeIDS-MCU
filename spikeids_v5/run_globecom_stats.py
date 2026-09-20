"""Recompute a frozen, complete difference-test family from verified artifacts."""
from __future__ import annotations
import argparse
from pathlib import Path
from contracts import *
from evidence import verified_suite
from stats_tests import wilcoxon_pair, holm, bootstrap_mean


def analyze(run_dir: Path, context=None):
    plan,results=context if context is not None else verified_suite(run_dir)
    tests={};dataset_reports={}
    for dataset in DATASETS:
        left=results[(dataset,"relu")]
        for arm in ARMS[dataset]:
            if arm=="relu": continue
            right=results[(dataset,arm)];same_pairing(left,right)
            l=seed_rows(left["per_seed"],plan["seeds"]);r=seed_rows(right["per_seed"],plan["seeds"])
            for metric in METRICS:
                key=f"{dataset}:relu_vs_{arm}:{metric}"
                x=[l[s][metric] for s in plan["seeds"]];y=[r[s][metric] for s in plan["seeds"]]
                w=wilcoxon_pair(x,y)
                w.update(left_mean=sum(x)/len(x),right_mean=sum(y)/len(y),paired_seeds=plan["seeds"],
                         paired_difference_bootstrap_95ci=bootstrap_mean(w["differences"]),
                         units="percentage_points",difference="ReLU minus comparator")
                tests[key]=w
    require(list(tests)==plan["difference_family"],"The full prespecified difference family must be present")
    adjusted=holm({k:v["p"] for k,v in tests.items()},plan["alpha"])
    for key in tests: tests[key].update(adjusted[key])
    report={"schema":SCHEMA,"plan_sha256":plan["content_sha256"],"alpha":plan["alpha"],"comparisons":tests,
            "family":plan["difference_family"],"family_definition":"all seven model comparisons x two metrics (14 claims)",
            "source_result_digests":{f"{d}_{a}":r["scientific_digest"] for (d,a),r in results.items()},
            "scope":"seed variability conditional on the fixed prepared datasets; not new independent datasets",
            "nonrejection_is_not_equivalence":True}
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument("--run-dir",required=True,type=Path);a=p.parse_args()
    report=analyze(a.run_dir)
    write_json(a.run_dir/"stats_report_globecom.json",seal(report))
    print("Difference family:",len(report["comparisons"]),"hypotheses; all sources independently verified")
if __name__=="__main__":main()
