"""Fail closed on missing artifacts/macros, stale reports, missing TeX inputs.

The strict prose scan is a conservative heuristic, NOT a semantic proof of the paper.
No missing file, missing macro, or failed test is silently treated as success.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from contracts import *
from evidence import verified_suite
from run_globecom_stats import analyze as analyze_difference
from run_v4_equivalence import analyze as analyze_equivalence
from paper_contract import expected_macros,macro_text,prose_findings


def check(run_dir,paper_dir,strict=False):
    context=verified_suite(run_dir);plan,results=context
    require(plan["protocol_role"]=="planned_benchmark" and len(plan["seeds"])==20,
            "Smoke/subset runs cannot validate the 20-seed paper")
    d=analyze_difference(run_dir,context);e=analyze_equivalence(run_dir,context)
    for name,want in (("stats_report_globecom.json",d),("equivalence_v5.json",e)):
        actual=load_json(Path(run_dir)/name);check_seal(actual)
        require(actual==seal(want),f"Stale/inconsistent statistical report: {name}")
    want=macro_text(expected_macros(plan,results,d,e))
    path=Path(paper_dir)/"result_macros_v5.tex"
    require(path.is_file(),"Generated macro file is missing")
    require(path.read_text(encoding="utf-8")==want,"Missing, duplicated, hand-edited, or stale generated macro")
    manifest=load_json(Path(paper_dir)/"result_macros_v5.provenance.json");check_seal(manifest)
    require(manifest["plan_sha256"]==plan["content_sha256"] and manifest["macro_sha256"]==sha256(path),"Macro provenance invalid")
    require(manifest["difference_sha256"]==digest(d) and manifest["equivalence_sha256"]==digest(e),"Macro sources changed")
    findings=prose_findings(Path(paper_dir)/"main.tex") if strict else []
    require(not findings,"Strict manuscript check failed:\n"+'\n'.join(findings))
    return {"numeric_consistency_passed":True,"strict_heuristic_scan_passed":strict,
            "natural_language_scientific_claims_proven":False,"deployment_claims_verified":False}


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument("--run-dir",required=True,type=Path);p.add_argument("--paper-dir",required=True,type=Path)
    p.add_argument("--strict",action="store_true");a=p.parse_args()
    report=check(a.run_dir,a.paper_dir,a.strict)
    write_json(a.run_dir/"paper_numeric_check.json",seal(report));print(report)
if __name__=="__main__":main()
