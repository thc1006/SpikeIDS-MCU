#!/usr/bin/env python3
"""Assemble results/multiseed_20.json (legacy NSL schema) from the deterministic
train_fast NSL outputs, so the existing NSL consumers (run_globecom_stats,
run_v4_equivalence, emit_paper_macros) keep working unchanged after NSL was
migrated to the same bit-reproducible trainer as the other three datasets.

Inputs  : results/nslkdd_relu_multiseed.json   (train_fast --arm relu: top-level per_seed)
          results/nslkdd_qcfs_multiseed.json   (train_fast --arm qcfs: under "qcfs")
Output  : results/multiseed_20.json            (keys: relu, qcfs_L4, + top meta)

The old file is backed up next to it (.bak-<ts>) and to the scratchpad first.
Hard asserts guard the NSL identity (20 seeds, 125973/22544, 5 classes, aligned
seeds) so a bad re-run cannot silently corrupt the flagship result.
"""
from __future__ import annotations

import json
import shutil
import statistics
import time
from pathlib import Path

import numpy as np
from scipy import stats as sp

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "results"

EXPECT_N_TRAIN = 125973
EXPECT_N_TEST = 22544
EXPECT_CLASSES = ["DoS", "Probe", "R2L", "U2R", "normal"]
EXPECT_SEEDS = list(range(20))

# metrics to summarise in the recomputed statistical_tests block (scalars only)
STAT_METRICS = [
    "overall_acc", "macro_acc", "balanced_acc", "macro_precision", "macro_recall",
    "macro_f1", "weighted_precision", "weighted_recall", "weighted_f1", "mcc",
    "roc_auc_macro", "roc_auc_weighted",
]


def _load(p: Path) -> dict:
    return json.loads(p.read_text())


def _recompute_stats(relu_ps: list[dict], qcfs_ps: list[dict]) -> dict:
    out = {}
    for m in STAT_METRICS:
        if not all(m in r for r in relu_ps) or not all(m in q for q in qcfs_ps):
            continue
        rv = np.array([float(r[m]) for r in relu_ps])
        qv = np.array([float(q[m]) for q in qcfs_ps])
        diff = rv - qv
        if np.all(diff == 0):
            w_stat, w_p = 0.0, 1.0
        else:
            res = sp.wilcoxon(rv, qv, zero_method="wilcox", alternative="two-sided")
            w_stat, w_p = float(res.statistic), float(res.pvalue)
        out[m] = {
            "relu_mean": float(rv.mean()), "relu_std": float(rv.std(ddof=1)),
            "qcfs_mean": float(qv.mean()), "qcfs_std": float(qv.std(ddof=1)),
            "mean_diff": float(diff.mean()),
            "wilcoxon_stat": w_stat, "wilcoxon_p": w_p,
            "significant_005": bool(w_p <= 0.05),
        }
    return out


def main() -> None:
    relu_f = R / "nslkdd_relu_multiseed.json"
    qcfs_f = R / "nslkdd_qcfs_multiseed.json"
    for f in (relu_f, qcfs_f):
        if not f.exists():
            raise SystemExit(f"missing NSL train_fast output: {f} (run the re-run first)")

    relu = _load(relu_f)
    qcfs_top = _load(qcfs_f)
    qcfs = qcfs_top["qcfs"]

    relu_ps = relu["per_seed"]
    qcfs_ps = qcfs["per_seed"]

    # ── hard identity guards (a bad re-run must not corrupt the flagship result) ──
    assert len(relu_ps) == 20, f"NSL relu: expected 20 seeds, got {len(relu_ps)}"
    assert len(qcfs_ps) == 20, f"NSL qcfs: expected 20 seeds, got {len(qcfs_ps)}"
    assert relu["seeds"] == EXPECT_SEEDS, f"NSL relu seeds {relu['seeds']} != {EXPECT_SEEDS}"
    assert qcfs_top["seeds"] == EXPECT_SEEDS, f"NSL qcfs seeds {qcfs_top['seeds']} != {EXPECT_SEEDS}"
    for name, d in (("relu", relu), ("qcfs", qcfs_top)):
        assert d["n_train"] == EXPECT_N_TRAIN, f"NSL {name} n_train {d['n_train']} != {EXPECT_N_TRAIN}"
        assert d["n_test"] == EXPECT_N_TEST, f"NSL {name} n_test {d['n_test']} != {EXPECT_N_TEST}"
        assert list(d["class_names"]) == EXPECT_CLASSES, f"NSL {name} classes {d['class_names']} != {EXPECT_CLASSES}"
    assert relu["epochs"] == qcfs_top["epochs"], f"epoch mismatch {relu['epochs']} vs {qcfs_top['epochs']}"
    assert relu["batch_size"] == qcfs_top.get("batch_size", relu["batch_size"]), "batch mismatch"

    out = {
        "experiment": "NSL-KDD 20-seed ReLU vs QCFS L=4 (train_fast, deterministic)",
        "seeds": EXPECT_SEEDS,
        "epochs": relu["epochs"],
        "batch_size": relu["batch_size"],
        "dataset": "NSL-KDD",
        "n_train": EXPECT_N_TRAIN,
        "n_test": EXPECT_N_TEST,
        "class_names": EXPECT_CLASSES,
        "relu": {"per_seed": relu_ps, "aggregate": relu["aggregate"]},
        "qcfs_L4": {"per_seed": qcfs_ps, "aggregate": qcfs["aggregate"]},
        "statistical_tests": _recompute_stats(relu_ps, qcfs_ps),
        "provenance": "assembled by scripts/assemble_nsl_legacy.py from "
                      "nslkdd_{relu,qcfs}_multiseed.json (train_fast, deterministic)",
    }

    target = R / "multiseed_20.json"
    if target.exists():
        ts = time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(target, target.with_suffix(f".json.bak-{ts}"))
    target.write_text(json.dumps(out, indent=2, default=str))

    ra = statistics.mean(float(r["overall_acc"]) for r in relu_ps)
    qa = statistics.mean(float(q["overall_acc"]) for q in qcfs_ps)
    p_oa = out["statistical_tests"]["overall_acc"]["wilcoxon_p"]
    print(f"[assemble_nsl] wrote {target}")
    print(f"[assemble_nsl] ReLU OA {ra:.2f}  QCFS OA {qa:.2f}  Wilcoxon p(OA)={p_oa:.4f} "
          f"reject@0.05={p_oa <= 0.05}")


if __name__ == "__main__":
    main()
