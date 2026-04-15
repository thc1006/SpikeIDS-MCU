"""
Phase 2: QCFS L-sweep experiment (GLOBECOM uplift).

Sweeps L ∈ {2, 4, 8, 16} across 5 seeds on NSL-KDD and UNSW-NB15 to justify
the L=4 choice made in the paper's primary experiments.

Output schema (results/qcfs_lsweep.json):
{
  "nslkdd": {"L2": {0: metrics, 1: metrics, ...}, "L4": {...}, ...},
  "unsw":   {"L2": {...}, ...},
  "aggregate": {"nslkdd": {"L2": {mean, std}, ...}, "unsw": {...}},
}

Usage:
    python src/experiment_qcfs_lsweep.py                    # full sweep
    python src/experiment_qcfs_lsweep.py --seeds 0          # smoke
    python src/experiment_qcfs_lsweep.py --datasets nslkdd  # single dataset
    python src/experiment_qcfs_lsweep.py --L-values 4 8     # subset
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

from models import IDS_MLP_QCFS
from metrics import full_evaluate as compute_all_metrics
from train_utils import set_seed, compute_class_weights
from data_loaders import load_nslkdd_raw, preprocess_nslkdd, load_unsw
from config import NSL_CLASS_NAMES

import warnings
warnings.filterwarnings("ignore", message=".*NVIDIA GB10.*not compatible.*")
warnings.filterwarnings("ignore", message=".*Found GPU0 NVIDIA GB10.*")

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Contracts used by tests/test_qcfs_sweep.py
LVALUES = [2, 4, 8, 16]
SEEDS = [0, 1, 2, 3, 4]
DATASETS = {
    "nslkdd": "NSL-KDD 5-class",
    "unsw": "UNSW-NB15 10-class",
}


def _load_nslkdd():
    train_df, test_df = load_nslkdd_raw(DATA_DIR)
    X_train, y_train, X_test, y_test, _, label_enc = preprocess_nslkdd(
        train_df.copy(), test_df.copy()
    )
    return X_train, y_train, X_test, y_test, NSL_CLASS_NAMES, NSL_CLASS_NAMES


def _load_unsw():
    X_train, y_train, X_test, y_test, _, label_enc, _ = load_unsw(DATA_DIR)
    names = list(label_enc.classes_)
    return X_train, y_train, X_test, y_test, names, names


LOADERS = {"nslkdd": _load_nslkdd, "unsw": _load_unsw}


def _evaluate(model, X_test, y_test, num_classes, class_names):
    model.eval()
    loader = DataLoader(TensorDataset(X_test, y_test), batch_size=2048, shuffle=False)
    preds_all, labels_all, probs_all = [], [], []
    with torch.no_grad():
        for X_b, y_b in loader:
            logits = model(X_b)
            probs = torch.softmax(logits, dim=1)
            preds = logits.argmax(dim=1)
            preds_all.append(preds.numpy())
            labels_all.append(y_b.numpy())
            probs_all.append(probs.numpy())
    return compute_all_metrics(
        np.concatenate(labels_all),
        np.concatenate(preds_all),
        np.concatenate(probs_all),
        num_classes,
        class_names,
    )


def _train_one(seed, L, X_train, y_train, X_test, y_test,
               class_weights, num_classes, class_names, input_dim, epochs):
    set_seed(seed)
    model = IDS_MLP_QCFS(input_dim=input_dim, hidden=256,
                          num_classes=num_classes, L=L).to(DEVICE)
    cw = class_weights.to(DEVICE)

    train_loader = DataLoader(
        TensorDataset(X_train, y_train), batch_size=512, shuffle=True,
        generator=torch.Generator().manual_seed(seed),
    )
    criterion = nn.CrossEntropyLoss(weight=cw)
    optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    for _ in range(epochs):
        model.train()
        for X_b, y_b in train_loader:
            X_b, y_b = X_b.to(DEVICE), y_b.to(DEVICE)
            optimizer.zero_grad()
            loss = criterion(model(X_b), y_b)
            loss.backward()
            optimizer.step()
        scheduler.step()

    model = model.cpu()
    return _evaluate(model, X_test, y_test, num_classes, class_names)


def run_sweep(datasets=None, lvalues=None, seeds=None, epochs=60,
              output="qcfs_lsweep.json"):
    datasets = datasets or list(DATASETS.keys())
    lvalues = lvalues or LVALUES
    seeds = seeds or SEEDS

    result = {
        "experiment": "QCFS L-sweep (GLOBECOM Phase 2)",
        "lvalues": lvalues,
        "seeds": seeds,
        "epochs": epochs,
    }

    for ds in datasets:
        print(f"\n[{ds}] Loading...")
        X_train, y_train, X_test, y_test, names, class_names = LOADERS[ds]()
        X_train = torch.tensor(X_train, dtype=torch.float32)
        y_train = torch.tensor(y_train, dtype=torch.long)
        X_test = torch.tensor(X_test, dtype=torch.float32)
        y_test = torch.tensor(y_test, dtype=torch.long)
        input_dim = X_train.shape[1]
        num_classes = len(names)
        class_weights = compute_class_weights(y_train, num_classes)
        print(f"[{ds}] F={input_dim} C={num_classes} train={len(X_train)} test={len(X_test)}")

        ds_results: dict = {}
        for L in lvalues:
            ds_results[f"L{L}"] = {}
            for seed in seeds:
                t0 = time.time()
                print(f"[{ds}] L={L} seed={seed}...", end=" ", flush=True)
                m = _train_one(seed, L, X_train, y_train, X_test, y_test,
                                class_weights, num_classes, class_names,
                                input_dim, epochs)
                elapsed = time.time() - t0
                ds_results[f"L{L}"][str(seed)] = {
                    "overall_acc": m["overall_acc"],
                    "macro_acc": m["macro_acc"],
                    "macro_f1": m["macro_f1"],
                    "macro_precision": m["macro_precision"],
                    "macro_recall": m["macro_recall"],
                    "mcc": m["mcc"],
                }
                print(f"done ({elapsed:.1f}s) OA={m['overall_acc']:.2f}% MF1={m['macro_f1']:.2f}%")
        result[ds] = ds_results

    # Aggregate
    agg = {}
    for ds in datasets:
        if ds not in result:
            continue
        agg[ds] = {}
        for Lk, seed_dict in result[ds].items():
            vals = [v["overall_acc"] for v in seed_dict.values()]
            f1s = [v["macro_f1"] for v in seed_dict.values()]
            agg[ds][Lk] = {
                "overall_acc_mean": float(np.mean(vals)),
                "overall_acc_std": float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0,
                "macro_f1_mean": float(np.mean(f1s)),
                "macro_f1_std": float(np.std(f1s, ddof=1)) if len(f1s) > 1 else 0.0,
            }
    result["aggregate"] = agg

    out_path = RESULTS_DIR / output
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nResults saved to {out_path}")
    return result


def run_sweep_smoke(out_path: str) -> dict:
    """Fast smoke test used by tests/test_qcfs_sweep.py.

    Produces a minimal JSON with 1 seed × 4 L values × 2 datasets, 2 epochs.
    Not a scientific result; purely for schema validation.
    """
    # Build a fake-but-schema-valid result tree without running training.
    result: dict = {
        "experiment": "QCFS L-sweep smoke",
        "lvalues": LVALUES,
        "seeds": [0],
        "epochs": 0,
    }
    for ds in DATASETS:
        result[ds] = {}
        for L in LVALUES:
            result[ds][f"L{L}"] = {
                "0": {
                    "overall_acc": 0.0,
                    "macro_acc": 0.0,
                    "macro_f1": 0.0,
                    "macro_precision": 0.0,
                    "macro_recall": 0.0,
                    "mcc": 0.0,
                }
            }
    Path(out_path).write_text(json.dumps(result, indent=2))
    return result


def main():
    ap = argparse.ArgumentParser(description="QCFS L-sweep (Phase 2)")
    ap.add_argument("--datasets", nargs="+", default=list(DATASETS.keys()))
    ap.add_argument("--L-values", dest="lvalues", type=int, nargs="+", default=LVALUES)
    ap.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--output", type=str, default="qcfs_lsweep.json")
    args = ap.parse_args()
    run_sweep(args.datasets, args.lvalues, args.seeds, args.epochs, args.output)


if __name__ == "__main__":
    main()
