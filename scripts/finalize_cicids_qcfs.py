#!/usr/bin/env python3
"""Finalize the CICIDS2017 QCFS confound fix after the matched-budget re-run.

Run AFTER results/cicids_qcfs_multiseed.json has been regenerated at 80 ep / batch 512 /
10 seeds. Steps (all mechanical, each printed for verification):
  1. re-run run_globecom_stats.py  -> stats_report_globecom.json  (matched 10-seed Wilcoxon)
  2. re-run run_v4_equivalence.py  -> equivalence_v4.json         (CICIDS pair now VALID)
  3. surgically replace ONLY the 7 CICIDS macros in result_macros.tex (leaves NSL/UNSW/
     IoT-23/CNN untouched — emit_paper_macros.py can't regenerate IoT-23, so a full regen
     would regress it; this edits exact \\renewcommand lines instead).
  4. rebuild the paper and report old->new values + the equivalence validity.

Does NOT touch prose; it prints the new \\pcicrelu so you can sanity-check the narrative.
"""
from __future__ import annotations
import json, re, subprocess, sys, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "results"
MACROS = ROOT / "paper" / "globecom" / "result_macros.tex"
PY = str(ROOT / ".venv" / "bin" / "python")


def sh(*cmd):
    print(f"$ {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:]); print(r.stderr[-2000:])
        raise SystemExit(f"FAILED ({r.returncode}): {' '.join(cmd)}")
    return r.stdout


def mean_std(per_seed, metric):
    vals = [float(s[metric]) for s in per_seed if metric in s]
    return statistics.mean(vals), (statistics.stdev(vals) if len(vals) > 1 else 0.0)


def main():
    q = json.loads((R / "cicids_qcfs_multiseed.json").read_text())
    ps = q["qcfs"]["per_seed"]
    assert len(ps) == 10, f"expected 10 QCFS seeds, got {len(ps)} — did the re-run finish?"
    assert q.get("epochs") == 80 and q.get("batch_size") == 512, \
        f"QCFS budget not matched: epochs={q.get('epochs')} batch={q.get('batch_size')}"
    oa_m, oa_s = mean_std(ps, "overall_acc")
    mf_m, mf_s = mean_std(ps, "macro_f1")

    # 1 + 2: regenerate stats + equivalence from the new run
    sh(PY, "scripts/run_globecom_stats.py")
    sh(PY, "scripts/run_v4_equivalence.py", "--delta", "1.0")

    st = json.loads((R / "stats_report_globecom.json").read_text())
    cq = st["datasets"]["cicids2017"]["comparisons"]["cicids_relu_vs_qcfs"]
    p_raw = cq.get("p_raw", cq.get("p")); p_adj = cq.get("p_adj"); dz = cq.get("dz")
    reject = bool(cq.get("reject", (p_adj is not None and p_adj <= 0.05)))
    n = cq.get("n")

    ev = json.loads((R / "equivalence_v4.json").read_text())
    sp = ev.get("seed_pairing", {}).get("cicids2017", {})
    cic_valid = bool(sp.get("valid"))
    cic_conf = sp.get("confounds", "?")

    def fmt_pm(m, s): return f"{m:.2f}$\\pm${s:.2f}"
    def fmt_p(p): return "--" if p is None else f"{p:.3f}"
    def fmt_dz(d): return "--" if d is None else (f"$+{d:.2f}$" if d >= 0 else f"${d:.2f}$")
    reject_mark = r"\checkmark" if reject else r"\ding{55}"

    new = {
        "cicoaqcfs": fmt_pm(oa_m, oa_s),
        "cicmfqcfs": fmt_pm(mf_m, mf_s),
        "cicpqcfs": fmt_p(p_raw),
        "cicpadjqcfs": fmt_p(p_adj),
        "cicdzqcfs": fmt_dz(dz),
        "cicrejqcfs": reject_mark,
        "pcicrelu": fmt_p(p_raw),
    }

    # 3: surgical replace of the 7 macros
    txt = MACROS.read_text()
    print("\n=== CICIDS macro update (old -> new) ===")
    for cmd, val in new.items():
        # match the WHOLE line (greedy .* handles values with braces, e.g. \ding{55})
        pat = re.compile(r"(?m)^\\renewcommand\{\\" + cmd + r"\}\{.*\}\s*$")
        m = pat.search(txt)
        old = m.group(0) if m else "(absent)"
        repl = f"\\renewcommand{{\\{cmd}}}{{{val}}}"
        if m:
            txt = pat.sub(repl.replace("\\", "\\\\"), txt, count=1)
        else:
            txt += "\n" + repl + "\n"
        print(f"  {cmd:12s}: {old}  ->  {repl}")
    MACROS.write_text(txt)

    print(f"\n=== CICIDS re-run summary (n={len(ps)} seeds, 80ep/512) ===")
    print(f"  QCFS OA = {new['cicoaqcfs']}   MF1 = {new['cicmfqcfs']}")
    print(f"  ReLU-vs-QCFS: p_raw={fmt_p(p_raw)} p_adj={fmt_p(p_adj)} dz={dz:.3f} "
          f"reject={reject} (n={n})")
    print(f"  equivalence_v4 CICIDS pair VALID (no confound): {cic_valid}  confounds={cic_conf}")
    print(f"  narrative check: \\pcicrelu={fmt_p(p_raw)} "
          f"({'NON-rejection (QCFS≈ReLU holds)' if not reject else 'REJECTED — revise prose!'})")

    # 4: rebuild paper
    sh("latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error",
       "-cd", str(ROOT / "paper" / "globecom" / "main.tex"))
    print("\n[finalize] paper rebuilt OK")


if __name__ == "__main__":
    main()
