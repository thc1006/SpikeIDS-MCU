#!/usr/bin/env python3
"""Assemble the legacy TinyCNN result files from the budget-matched, deterministic
train_fast CNN outputs, so the existing consumers (run_globecom_stats,
emit_paper_macros) keep working after TinyCNN was re-run at the MLP's budget
(80 epochs, 20 seeds) instead of the confounded 30/40 epochs.

Inputs : results/cnn_{nslkdd,unsw,cicids}_multiseed.json  (train_fast --arm cnn: top-level per_seed)
Output : results/cnn_baseline_merged.json   (nslkdd + unsw + cicids2017 blocks)
         results/cnn_baseline_cicids.json   (cicids2017 block; read separately by run_globecom_stats)

Each CNN block's n_train/n_test is cross-checked against the matching MLP ReLU
file, guaranteeing the baseline used the identical split — a genuine same-split,
same-budget ReLU-MLP-vs-TinyCNN comparison.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "results"

# dataset -> (train_fast cnn output, matching MLP relu file whose split must agree)
DATASETS = {
    "nslkdd": ("cnn_nslkdd_multiseed.json", "nslkdd_relu_multiseed.json"),
    "unsw": ("cnn_unsw_multiseed.json", "unsw_multiseed_20.json"),
    "cicids2017": ("cnn_cicids_multiseed.json", "cicids2017_multiseed_experiment.json"),
}
EXPECT_SEEDS = list(range(20))


def _load(p: Path) -> dict:
    return json.loads(p.read_text())


def _relu_meta(d: dict) -> tuple[int, int]:
    """n_train/n_test from a train_fast relu file (top-level) or a nested 'relu' block."""
    if "n_train" in d:
        return d["n_train"], d["n_test"]
    b = d.get("relu", d)
    return b.get("n_train"), b.get("n_test")


def main() -> None:
    blocks = {}
    for ds, (cnn_name, relu_name) in DATASETS.items():
        cnn_f, relu_f = R / cnn_name, R / relu_name
        if not cnn_f.exists():
            raise SystemExit(f"missing TinyCNN output: {cnn_f} (run the re-run first)")
        if not relu_f.exists():
            raise SystemExit(f"missing MLP relu file for split cross-check: {relu_f}")
        cnn = _load(cnn_f)
        ps = cnn["per_seed"]
        assert len(ps) == 20, f"{ds} cnn: expected 20 seeds, got {len(ps)}"
        assert cnn["seeds"] == EXPECT_SEEDS, f"{ds} cnn seeds {cnn['seeds']} != {EXPECT_SEEDS}"
        assert cnn.get("model") == "TinyCNN_IDS", f"{ds} cnn model={cnn.get('model')} (expected TinyCNN_IDS)"
        assert cnn["epochs"] == 80, f"{ds} cnn epochs={cnn['epochs']} (expected 80, MLP-matched)"
        rn_train, rn_test = _relu_meta(_load(relu_f))
        assert cnn["n_train"] == rn_train, f"{ds}: cnn n_train {cnn['n_train']} != relu {rn_train} (split mismatch)"
        assert cnn["n_test"] == rn_test, f"{ds}: cnn n_test {cnn['n_test']} != relu {rn_test} (split mismatch)"
        blocks[ds] = {"per_seed": ps, "aggregate": cnn["aggregate"],
                      "n_train": cnn["n_train"], "n_test": cnn["n_test"],
                      "epochs": 80, "model": "TinyCNN_IDS"}

    stamp = ("TinyCNN_IDS Conv2D 1x3, budget-matched 80ep / 20-seed deterministic "
             "(train_fast); assembled by scripts/assemble_cnn_legacy.py")

    merged = {"experiment": stamp, "seeds": EXPECT_SEEDS, "epochs": 80, **blocks}
    cicids_only = {"experiment": stamp, "seeds": EXPECT_SEEDS, "epochs": 80,
                   "cicids2017": blocks["cicids2017"]}

    for target, payload in ((R / "cnn_baseline_merged.json", merged),
                            (R / "cnn_baseline_cicids.json", cicids_only)):
        if target.exists():
            ts = time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(target, target.with_suffix(f".json.bak-{ts}"))
        target.write_text(json.dumps(payload, indent=2, default=str))
        print(f"[assemble_cnn] wrote {target.name}")

    for ds in DATASETS:
        agg = blocks[ds]["aggregate"]["overall_acc"]
        print(f"  [{ds}] TinyCNN OA {agg['mean']:.2f}±{agg['std']:.2f}  (80ep, n=20, {blocks[ds]['n_train']} train)")


if __name__ == "__main__":
    main()
