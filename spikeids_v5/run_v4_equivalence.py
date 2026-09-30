"""Version-5 replacement for the v4 entry point: equivalence of ANN mean metrics.

No T=1 SNN assertion, no invented seed IDs, no family shrinking, no p-value-driven
margin or test selection, and no hardcoded CI confidence when alpha changes.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from contracts import *
from evidence import verified_suite
from stats_tests import tost_paired,tost_wilcoxon,holm


def analyze(run_dir, context=None):
    plan,results=context if context is not None else verified_suite(run_dir);pairs={}
    for dataset in DATASETS:
        a,b=results[(dataset,"relu")],results[(dataset,"qcfs")];same_pairing(a,b)
        ar=seed_rows(a["per_seed"],plan["seeds"]);br=seed_rows(b["per_seed"],plan["seeds"])
        for metric in METRICS:
            x=[ar[s][metric] for s in plan["seeds"]];y=[br[s][metric] for s in plan["seeds"]]
            pairs[f"{dataset}:{metric}"]={"tost_t":tost_paired(x,y,plan["equivalence_margin_pp"],plan["alpha"]),
                "tost_signed_rank_robustness":tost_wilcoxon(x,y,plan["equivalence_margin_pp"],plan["alpha"]),
                "paired_seeds":plan["seeds"]}
    require(list(pairs)==plan["equivalence_family"],"Complete frozen equivalence family required")
    family=holm({k:v["tost_t"]["p_tost"] for k,v in pairs.items()},plan["alpha"])
    for key in pairs:
        pairs[key]["holm"]=family[key]
        pairs[key]["equivalent_familywise"]=family[key]["reject"]
    return {"schema":SCHEMA,"plan_sha256":plan["content_sha256"],"alpha":plan["alpha"],
            "margin_pp":plan["equivalence_margin_pp"],"pairs":pairs,"family":plan["equivalence_family"],
            "source_result_digests":{f"{d}_{a}":r["scientific_digest"] for (d,a),r in results.items()},
            "ci_scope":"individual 1-2alpha intervals; not simultaneous Holm-adjusted intervals",
            "margin_provenance":plan["margin_status"],
            "interpretation":"A significant difference can coexist with practical equivalence. Nonrejection of a difference test alone does not establish equivalence.",
            "power":"No observed-power or data-chosen sample-size claim is made; explicit normal-model planning is available in stats_tests.py."}


def markdown(r):
    lines=["# ReLU ANN vs shifted-QCFS ANN: mean-difference equivalence", "",
           f"Margin ±{r['margin_pp']} percentage points; alpha={r['alpha']}; full family={len(r['family'])}.",
           "Intervals are individual, not simultaneous familywise intervals. Undefined variance remains inconclusive.","",
           "| Pair | n | Mean difference | Individual CI | raw TOST p | Holm p | Equivalence supported |",
           "|---|---:|---:|---|---:|---:|---|"]
    for key,v in r["pairs"].items():
        t,h=v["tost_t"],v["holm"]
        ci="undefined" if t["ci"] is None else f"[{t['ci'][0]:.6g}, {t['ci'][1]:.6g}]"
        p="undefined" if t["p_tost"] is None else f"{t['p_tost']:.6g}"
        lines.append(f"| {key} | {t['n']} | {t['mean_diff']:.6g} | {ci} | {p} | {h['p_adj']:.6g} | {v['equivalent_familywise']} |")
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument("--run-dir",required=True,type=Path);a=p.parse_args()
    report=analyze(a.run_dir)
    write_json(a.run_dir/"equivalence_v5.json",seal(report))
    write_text(a.run_dir/"equivalence_v5.md",markdown(report))
    print("Equivalence family:",len(report["pairs"]),"hypotheses")
if __name__=="__main__":main()
