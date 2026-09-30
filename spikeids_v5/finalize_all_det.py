"""Generate numerical evidence before optional checked LaTeX compilation.

Never rewrites the manuscript's scientific conclusions or old hand-maintained macros.
A new, separately named macro file must be integrated deliberately by the author.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import sys
from contracts import *
from evidence import verified_suite
from run_globecom_stats import analyze as analyze_difference
from run_v4_equivalence import analyze as analyze_equivalence,markdown
from paper_contract import expected_macros,macro_text
from tree_baseline import load_verified_tree_suite


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument("--run-dir",required=True,type=Path);p.add_argument("--tree-run-dir",required=True,type=Path)
    p.add_argument("--paper-dir",required=True,type=Path)
    p.add_argument("--export-root",type=Path)
    p.add_argument("--build-output",type=Path)
    p.add_argument("--build",action="store_true");a=p.parse_args()
    require(not a.build or (a.export_root is not None and a.build_output is not None),
            "--build requires --export-root and a fresh --build-output directory")
    with file_lock(a.run_dir/"finalize.lock"):
        context=verified_suite(a.run_dir);plan,results=context
        tree_plan,tree_report=load_verified_tree_suite(a.tree_run_dir)
        require(plan["protocol_role"]=="planned_benchmark" and len(plan["seeds"])==20,"Only full planned 20-seed results may feed these paper macros")
        d=analyze_difference(a.run_dir,context);e=analyze_equivalence(a.run_dir,context)
        write_json(a.run_dir/"stats_report_globecom.json",seal(d))
        write_json(a.run_dir/"equivalence_v5.json",seal(e));write_text(a.run_dir/"equivalence_v5.md",markdown(e))
        a.paper_dir.mkdir(parents=True,exist_ok=True)
        path=a.paper_dir/"result_macros_v5.tex"
        write_text(path,macro_text(expected_macros(plan,results,d,e,tree_report)))
        write_json(a.paper_dir/"result_macros_v5.provenance.json",seal({"plan_sha256":plan["content_sha256"],
                   "tree_plan_sha256":tree_plan["content_sha256"],"tree_result_sha256":sha256(a.tree_run_dir/"results.json"),
                   "macro_sha256":sha256(path),"difference_sha256":digest(d),"equivalence_sha256":digest(e),
                   "scope":"classification/statistics numbers only; no claim of SNN identity, all-INT8 mapping, latency or energy"}))
        print("Generated",path,"; main.tex and legacy result_macros.tex were not modified",flush=True)
        if a.build:
            from check_paper_consistency import check
            report=check(a.run_dir,a.tree_run_dir,a.paper_dir,strict=True,export_root=a.export_root)
            write_json(a.run_dir/"paper_numeric_check.json",seal(report))
            repo=Path(__file__).resolve().parent.parent
            builder=repo/"tools"/"build_v5_paper.py"
            require(builder.is_file(),"Independent isolated paper builder is missing")
            subprocess.run([sys.executable,str(builder),"--repo-root",str(repo),
                            "--paper-dir",str(a.paper_dir.resolve()),
                            "--output-dir",str(a.build_output.resolve()),
                            "--neural-plan",str((a.run_dir/"plan.json").resolve()),
                            "--tree-plan",str((a.tree_run_dir/"plan.json").resolve()),
                            "--export-plan",str((a.export_root/"export_plan.json").resolve())],check=True)
            print("Two isolated paper builds passed; free scientific prose still requires review")
if __name__=="__main__":main()
