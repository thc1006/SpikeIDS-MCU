"""
Phase 5: NPU-deployable CNN baseline (GLOBECOM uplift).

Trains TinyCNN_IDS (Conv2D 1×K) on NSL-KDD, UNSW-NB15, and CICIDS2017 across
multiple seeds. Used to provide a non-MLP deep-learning baseline that still
satisfies the Neural-ART operator constraint.

Neural-ART operator notes:
- Conv2D is explicitly supported (Conv1D is not confirmed) — model uses Conv2D (1, K)
- Kernel width ≤ 6, height ≤ 3 (stride=1) — we use (1, 3)
- Input is reshaped from (B, F) to (B, 1, 1, F) at the model boundary

Usage:
    python src/experiment_cnn_baseline.py                     # 5 seeds × 3 datasets
    python src/experiment_cnn_baseline.py --datasets nslkdd   # single dataset
    python src/experiment_cnn_baseline.py --seeds 0 1 2       # custom seeds
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

from models import TinyCNN_IDS
from metrics import full_evaluate as compute_all_metrics
from train_utils import set_seed, compute_class_weights
from data_loaders import load_nslkdd_raw, preprocess_nslkdd, load_unsw
from config import NSL_CLASS_NAMES

import warnings
warnings.filterwarnings("ignore", message=".*NVIDIA GB10.*not compatible.*")
warnings.filterwarnings("ignore", message=".*Found GPU0 NVIDIA GB10.*")

DATA_DIR = Path(__file__).parent.parent / "data"
MODEL_DIR = Path(__file__).parent.parent / "models"
RESULTS_DIR = Path(__file__).parent.parent / "results"
MODEL_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


# ── Dataset loaders ──────────────────────────────────────────────────

def _load_nslkdd():
    train_df, test_df = load_nslkdd_raw(DATA_DIR)
    X_train, y_train, X_test, y_test, _, label_enc = preprocess_nslkdd(
        train_df.copy(), test_df.copy()
    )
    return X_train, y_train, X_test, y_test, list(label_enc.classes_), NSL_CLASS_NAMES


def _load_unsw():
    X_train, y_train, X_test, y_test, _, label_enc, _ = load_unsw(DATA_DIR)
    names = list(label_enc.classes_)
    return X_train, y_train, X_test, y_test, names, names


def _load_cicids():
    """Load pre-processed CICIDS2017 (if available) via experiment_cicids2017 helpers."""
    try:
        from experiment_cicids2017 import load_cicids2017, preprocess_cicids
    except ImportError:
        return None
    df, labels = load_cicids2017(grouped=False)
    X_train, y_train, X_test, y_test, _scaler, label_enc, _feats = preprocess_cicids(
        df, labels
    )
    names = list(label_enc.classes_)
    return X_train.numpy(), y_train.numpy(), X_test.numpy(), y_test.numpy(), names, names


DATASET_LOADERS = {
    "nslkdd": _load_nslkdd,
    "unsw": _load_unsw,
    "cicids2017": _load_cicids,
}


# ── Training / evaluation ────────────────────────────────────────────

def _evaluate(model, X_test, y_test, num_classes, class_names):
    model.eval()
    loader = DataLoader(TensorDataset(X_test, y_test), batch_size=2048, shuffle=False)
    all_preds, all_labels, all_probs = [], [], []
    with torch.no_grad():
        for X_b, y_b in loader:
            logits = model(X_b)
            probs = torch.softmax(logits, dim=1)
            preds = logits.argmax(dim=1)
            all_preds.append(preds.numpy())
            all_labels.append(y_b.numpy())
            all_probs.append(probs.numpy())
    y_true = np.concatenate(all_labels)
    y_pred = np.concatenate(all_preds)
    y_prob = np.concatenate(all_probs)
    return compute_all_metrics(y_true, y_pred, y_prob, num_classes, class_names)


def _train_single(seed, X_train, y_train, X_test, y_test,
                  class_weights, num_classes, class_names, input_dim, epochs):
    set_seed(seed)
    model = TinyCNN_IDS(input_dim=input_dim, num_classes=num_classes).to(DEVICE)
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
    metrics = _evaluate(model, X_test, y_test, num_classes, class_names)
    return metrics, model


def _aggregate(per_seed, class_names):
    keys = ["overall_acc", "macro_acc", "macro_f1", "macro_precision",
            "macro_recall", "mcc"]
    agg = {}
    for k in keys:
        vals = [r[k] for r in per_seed]
        agg[k] = {
            "mean": float(np.mean(vals)),
            "std": float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0,
            "values": vals,
        }
    return agg


def _run_dataset(name, loader_fn, seeds, epochs):
    print(f"\n[{name}] Loading...")
    loaded = loader_fn()
    if loaded is None:
        print(f"[{name}] loader returned None — skipping")
        return None
    X_train, y_train, X_test, y_test, names, class_names = loaded
    X_train = torch.tensor(X_train, dtype=torch.float32)
    y_train = torch.tensor(y_train, dtype=torch.long)
    X_test = torch.tensor(X_test, dtype=torch.float32)
    y_test = torch.tensor(y_test, dtype=torch.long)
    input_dim = X_train.shape[1]
    num_classes = len(names)
    class_weights = compute_class_weights(y_train, num_classes)
    print(f"[{name}] Train={len(X_train)}, Test={len(X_test)}, F={input_dim}, C={num_classes}")

    per_seed = []
    best_state = None
    for seed in seeds:
        t0 = time.time()
        print(f"[{name}] seed {seed}...", end=" ", flush=True)
        metrics, model = _train_single(seed, X_train, y_train, X_test, y_test,
                                        class_weights, num_classes, class_names,
                                        input_dim, epochs)
        elapsed = time.time() - t0
        per_seed.append(metrics)
        print(f"done ({elapsed:.1f}s) OA={metrics['overall_acc']:.2f}% "
              f"MF1={metrics['macro_f1']:.2f}%")
        if seed == seeds[0]:
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            torch.save(best_state, MODEL_DIR / f"cnn_{name}_best.pth")

    agg = _aggregate(per_seed, class_names)
    return {
        "per_seed": per_seed,
        "aggregate": agg,
        "input_dim": int(input_dim),
        "num_classes": int(num_classes),
        "class_names": class_names,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
    }


def main():
    ap = argparse.ArgumentParser(description="NPU-deployable CNN baseline (Phase 5)")
    ap.add_argument("--datasets", nargs="+",
                     default=["nslkdd", "unsw", "cicids2017"],
                     choices=list(DATASET_LOADERS.keys()))
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--output", type=str, default="cnn_baseline.json")
    args = ap.parse_args()

    print("=" * 70)
    print("Phase 5: NPU-deployable CNN baseline (TinyCNN_IDS, Conv2D 1×3)")
    print(f"  Datasets: {args.datasets}")
    print(f"  Seeds: {args.seeds}")
    print(f"  Epochs: {args.epochs}")
    print(f"  Device: {DEVICE}")
    print("=" * 70)

    result = {
        "experiment": "TinyCNN_IDS Conv2D 1x3 (GLOBECOM Phase 5)",
        "seeds": args.seeds,
        "epochs": args.epochs,
    }
    for name in args.datasets:
        ds_result = _run_dataset(name, DATASET_LOADERS[name], args.seeds, args.epochs)
        if ds_result is not None:
            result[name] = ds_result

    out_path = RESULTS_DIR / args.output
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
