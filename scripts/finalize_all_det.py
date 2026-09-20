#!/usr/bin/env python3
"""Finalize the deterministic re-run of IoT-23 / CICIDS2017 / UNSW-NB15 (both arms, n=20).

Run AFTER results/{iot23_multiseed,iot23_qcfs_multiseed,cicids2017_multiseed_experiment,
cicids_qcfs_multiseed,unsw_multiseed_20,unsw_qcfs_multiseed}.json are the new n=20 runs.

Steps (each printed for verification):
  1. run_globecom_stats.py  -> stats_report_globecom.json  (paired Wilcoxon, n=20 each)
  2. run_v4_equivalence.py  -> equivalence_v4.json          (TOST family)
  3. surgically replace ONLY the iot23/cicids/unsw accuracy+stats macros in result_macros.tex
     (NSL, TinyCNN and everything else untouched — a full emit regen would drop them)
  4. rebuild the paper; print old->new macros, new per-class recalls, and TOST verdicts so the
     prose (n-counts, per-class F1, accuracy deltas) can be updated by hand from real numbers.
"""
from __future__ import annotations
import json, re, subprocess, sys, statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "results"
MACROS = ROOT / "paper" / "globecom" / "result_macros.tex"
PY = str(ROOT / ".venv" / "bin" / "python")

DATASETS = {
    # NSL now uses the same deterministic train_fast trainer; its two native files are
    # assembled back into multiseed_20.json (legacy schema) by assemble_nsl_legacy.py,
    # which main() runs before the stats scripts read multiseed_20.json.
    "nslkdd": dict(relu="nslkdd_relu_multiseed.json", qcfs="nslkdd_qcfs_multiseed.json",
                   cmp="nslkdd_relu_vs_qcfs", pfx="nsl"),
    "iot23": dict(relu="iot23_multiseed.json", qcfs="iot23_qcfs_multiseed.json",
                  cmp="iot23_relu_vs_qcfs", pfx="iot"),
    "cicids2017": dict(relu="cicids2017_multiseed_experiment.json", qcfs="cicids_qcfs_multiseed.json",
                       cmp="cicids_relu_vs_qcfs", pfx="cic"),
    "unsw": dict(relu="unsw_multiseed_20.json", qcfs="unsw_qcfs_multiseed.json",
                 cmp="unsw_relu_vs_qcfs", pfx="unsw"),
}


def sh(*cmd):
    print(f"$ {' '.join(str(c) for c in cmd)}", flush=True)
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-1500:]); print(r.stderr[-1500:]); raise SystemExit(f"FAILED: {' '.join(cmd)}")


def per_seed(path, key=None):
    d = json.loads(Path(path).read_text())
    if key and key in d:
        return d[key]["per_seed"]
    if "qcfs" in d and (key == "qcfs" or key is None) and "per_seed" not in d:
        return d["qcfs"]["per_seed"]
    return d.get("per_seed") or d.get("relu", {}).get("per_seed")


def ms(ps, m):
    v = [float(r[m]) for r in ps if m in r]
    return (statistics.mean(v), statistics.stdev(v) if len(v) > 1 else 0.0)


def fmt_pm(t): return f"{t[0]:.2f}$\\pm${t[1]:.2f}"
def fmt_p(p): return "--" if p is None else f"{p:.3f}"
def fmt_dz(d): return "--" if d is None else (f"$+{d:.2f}$" if d >= 0 else f"${d:.2f}$")


def replace_macro(txt, cmd, val):
    pat = re.compile(r"(?m)^\\renewcommand\{\\" + cmd + r"\}\{.*\}\s*$")
    repl = f"\\\\renewcommand{{\\\\{cmd}}}{{{val}}}"
    if pat.search(txt):
        return pat.sub(lambda _: f"\\renewcommand{{\\{cmd}}}{{{val}}}", txt, count=1), True
    return txt + f"\n\\renewcommand{{\\{cmd}}}{{{val}}}\n", False


def main():
    # sanity: all 6 JSONs are n=20 with matched budgets
    for ds, c in DATASETS.items():
        for arm in ("relu", "qcfs"):
            ps = per_seed(R / c[arm], "qcfs" if arm == "qcfs" else None)
            assert len(ps) == 20, f"{ds}/{arm}: expected 20 seeds, got {len(ps)}"
    # NSL: rebuild multiseed_20.json (legacy schema) from the train_fast NSL outputs
    # BEFORE the stats scripts read it, so all four datasets are deterministic + consistent.
    sh(PY, "scripts/assemble_nsl_legacy.py")
    sh(PY, "scripts/assemble_cnn_legacy.py")  # budget-matched TinyCNN -> legacy cnn_baseline files
    sh(PY, "scripts/run_globecom_stats.py")
    sh(PY, "scripts/run_v4_equivalence.py", "--delta", "1.0")

    stats = json.loads((R / "stats_report_globecom.json").read_text())
    ev = json.loads((R / "equivalence_v4.json").read_text())
    txt = MACROS.read_text()
    print("\n=== macro updates (old shown by grep after) ===")
    updates = {}
    for ds, c in DATASETS.items():
        pfx = c["pfx"]
        relu_ps = per_seed(R / c["relu"], None)
        qcfs_ps = per_seed(R / c["qcfs"], "qcfs")
        updates[f"{pfx}oarelu"] = fmt_pm(ms(relu_ps, "overall_acc"))
        updates[f"{pfx}mfrelu"] = fmt_pm(ms(relu_ps, "macro_f1"))
        updates[f"{pfx}oaqcfs"] = fmt_pm(ms(qcfs_ps, "overall_acc"))
        updates[f"{pfx}mfqcfs"] = fmt_pm(ms(qcfs_ps, "macro_f1"))
        cmp = stats["datasets"][ds]["comparisons"][c["cmp"]]
        p_raw = cmp.get("p_raw", cmp.get("p")); p_adj = cmp.get("p_adj"); dz = cmp.get("dz")
        reject = bool(cmp.get("reject", (p_adj is not None and p_adj <= 0.05)))
        updates[f"{pfx}pqcfs"] = fmt_p(p_raw)
        updates[f"{pfx}padjqcfs"] = fmt_p(p_adj)
        updates[f"{pfx}dzqcfs"] = fmt_dz(dz)
        updates[f"{pfx}rejqcfs"] = r"\checkmark" if reject else r"\ding{55}"
        updates[f"p{pfx}relu"] = fmt_p(p_raw)
        sp = ev.get("seed_pairing", {}).get(ds, {})
        print(f"  [{ds}] valid={sp.get('valid')} confounds={sp.get('confounds')} "
              f"p={fmt_p(p_raw)} dz={fmt_dz(dz)} reject={reject} "
              f"| ReLU OA {updates[pfx+'oarelu']} QCFS OA {updates[pfx+'oaqcfs']}")

    # ── TinyCNN baseline (budget-matched 80ep / 20-seed): accuracy + ReLU-vs-CNN stats ──
    CNN = {
        "nslkdd": ("cnn_nslkdd_multiseed.json", "nsl", "nslkdd_relu_vs_cnn"),
        "unsw": ("cnn_unsw_multiseed.json", "unsw", "unsw_relu_vs_cnn"),
        "cicids2017": ("cnn_cicids_multiseed.json", "cic", "cicids_relu_vs_cnn"),
    }
    print("\n=== TinyCNN (80ep, n=20) macro updates ===")
    for ds, (fname, pfx, cmpkey) in CNN.items():
        cnn_ps = per_seed(R / fname, None)
        updates[f"{pfx}oacnn"] = fmt_pm(ms(cnn_ps, "overall_acc"))
        updates[f"{pfx}mfcnn"] = fmt_pm(ms(cnn_ps, "macro_f1"))
        cmp = stats["datasets"][ds]["comparisons"][cmpkey]
        p_raw = cmp.get("p_raw", cmp.get("p")); p_adj = cmp.get("p_adj"); dz = cmp.get("dz")
        reject = bool(cmp.get("reject", (p_adj is not None and p_adj <= 0.05)))
        updates[f"{pfx}pcnn"] = fmt_p(p_raw)
        updates[f"{pfx}padjcnn"] = fmt_p(p_adj)
        updates[f"{pfx}dzcnn"] = fmt_dz(dz)
        updates[f"{pfx}rejcnn"] = r"\checkmark" if reject else r"\ding{55}"
        print(f"  [{ds}] TinyCNN OA {updates[pfx+'oacnn']}  ReLU-vs-CNN p={fmt_p(p_raw)} "
              f"padj={fmt_p(p_adj)} dz={fmt_dz(dz)} reject={reject}")

    for cmd, val in updates.items():
        txt, found = replace_macro(txt, cmd, val)
    MACROS.write_text(txt)
    print(f"\n[macros] wrote {len(updates)} macros to {MACROS.name}")

    # per-class recall (mean) for prose (iot23/cicids notable classes)
    print("\n=== per-class recall (QCFS, for prose) ===")
    for ds, c in DATASETS.items():
        d = json.loads((R / c["qcfs"]).read_text())
        agg = (d.get("qcfs") or d)["aggregate"].get("per_class", {})
        items = sorted(((cls, m.get("recall", {}).get("mean", 0.0)) for cls, m in agg.items()),
                       key=lambda x: x[1])
        lohi = items[:2] + items[-2:]
        print(f"  [{ds}] " + ", ".join(f"{cls}:{r*100:.1f}%" for cls, r in lohi))

    sh("latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", "-cd",
       str(ROOT / "paper" / "globecom" / "main.tex"))
    print("\n[finalize] paper rebuilt OK")


if __name__ == "__main__":
    main()
