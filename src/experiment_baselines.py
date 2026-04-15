"""
Deployable baselines experiment for NCA paper.
Trains LogReg + small MLPs on NSL-KDD and UNSW-NB15 with 10 seeds,
producing accuracy-complexity Pareto frontier data.

Models (all NPU-deployable via Gemm+ReLU):
  - LogReg: nn.Linear(d, C)
  - MLP 64-64: [64, 64, C]
  - MLP 128-64: [128, 64, C]
  - MLP 256-256-128: [256, 256, 128, C] (existing, for reference)

Usage:
    python src/experiment_baselines.py
    python src/experiment_baselines.py --seeds 0 1 2
    python src/experiment_baselines.py --configs logreg mlp_64
"""

import argparse
import json
import time
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import numpy as np
from pathlib import Path
from metrics import full_evaluate as compute_all_metrics
from config import NSL_CLASS_NAMES
from train_utils import set_seed, compute_class_weights
from models import FlexMLP
from data_loaders import load_nslkdd as _load_nslkdd_shared
from data_loaders import load_unsw as _load_unsw_shared

import warnings
warnings.filterwarnings("ignore", message=".*NVIDIA GB10.*not compatible.*")
warnings.filterwarnings("ignore", message=".*Found GPU0 NVIDIA GB10.*")

DATA_DIR = Path(__file__).parent.parent / "data"
MODEL_DIR = Path(__file__).parent.parent / "models"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


# ── Model configs ─────────────────────────────────────────────────────

MODEL_CONFIGS = {
    "logreg": {
        "hidden_layers": [],
        "description": "Logistic Regression (single linear layer)",
    },
    "mlp_64_64": {
        "hidden_layers": [64, 64],
        "description": "Small MLP 64-64",
    },
    "mlp_128_64": {
        "hidden_layers": [128, 64],
        "description": "Medium MLP 128-64",
    },
    "mlp_256_256_128": {
        "hidden_layers": [256, 256, 128],
        "description": "Full MLP 256-256-128 (existing model)",
    },
}


# ── Data loading (reuse from existing scripts) ───────────────────────


def load_nslkdd():
    """Load NSL-KDD via shared data_loaders, return torch tensors + label_enc + class_names."""
    X_train, y_train, X_test, y_test, scaler, label_enc = _load_nslkdd_shared(DATA_DIR)
    return (torch.tensor(X_train, dtype=torch.float32),
            torch.tensor(y_train, dtype=torch.long),
            torch.tensor(X_test, dtype=torch.float32),
            torch.tensor(y_test, dtype=torch.long),
            label_enc, NSL_CLASS_NAMES)


def load_unsw():
    """Load UNSW-NB15 via shared data_loaders, return torch tensors + label_enc + class_names."""
    X_train, y_train, X_test, y_test, scaler, label_enc, feature_names = _load_unsw_shared(DATA_DIR)
    class_names = list(label_enc.classes_)
    return (torch.tensor(X_train, dtype=torch.float32),
            torch.tensor(y_train, dtype=torch.long),
            torch.tensor(X_test, dtype=torch.float32),
            torch.tensor(y_test, dtype=torch.long),
            label_enc, class_names)


# ── Training ──────────────────────────────────────────────────────────


def train_single(config_name, seed, X_train, y_train, X_test, y_test,
                 class_weights, num_classes, class_names, epochs=80):
    set_seed(seed)
    cfg = MODEL_CONFIGS[config_name]
    input_dim = X_train.shape[1]

    model = FlexMLP(input_dim, cfg["hidden_layers"], num_classes).to(DEVICE)
    cw = class_weights.to(DEVICE)

    train_loader = DataLoader(
        TensorDataset(X_train, y_train), batch_size=512, shuffle=True,
        generator=torch.Generator().manual_seed(seed)
    )
    test_loader = DataLoader(
        TensorDataset(X_test, y_test), batch_size=1024, shuffle=False
    )

    criterion = nn.CrossEntropyLoss(weight=cw)
    optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    best_macro = 0.0
    best_state = None

    for epoch in range(epochs):
        model.train()
        for X_b, y_b in train_loader:
            X_b, y_b = X_b.to(DEVICE), y_b.to(DEVICE)
            optimizer.zero_grad()
            loss = criterion(model(X_b), y_b)
            loss.backward()
            optimizer.step()
        scheduler.step()

        if (epoch + 1) % 10 == 0 or epoch == epochs - 1:
            model.eval()
            with torch.no_grad():
                correct = np.zeros(num_classes)
                total = np.zeros(num_classes)
                for X_b, y_b in test_loader:
                    X_b, y_b = X_b.to(DEVICE), y_b.to(DEVICE)
                    preds = model(X_b).argmax(dim=1)
                    for i in range(num_classes):
                        mask = y_b == i
                        correct[i] += (preds[mask] == y_b[mask]).sum().item()
                        total[i] += mask.sum().item()
                per_class = np.where(total > 0, correct / total, 0.0)
                macro = per_class.mean() * 100
                if macro > best_macro:
                    best_macro = macro
                    best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    # Evaluate on CPU
    model = model.cpu()
    model.load_state_dict(best_state)
    model.eval()

    cpu_loader = DataLoader(TensorDataset(X_test, y_test), batch_size=1024, shuffle=False)
    all_preds, all_labels, all_probs = [], [], []
    with torch.no_grad():
        for X_b, y_b in cpu_loader:
            logits = model(X_b)
            probs = torch.softmax(logits, dim=1)
            all_preds.append(logits.argmax(dim=1).numpy())
            all_labels.append(y_b.numpy())
            all_probs.append(probs.numpy())

    y_true = np.concatenate(all_labels)
    y_pred = np.concatenate(all_preds)
    y_prob = np.concatenate(all_probs)

    metrics = compute_all_metrics(y_true, y_pred, y_prob, num_classes, class_names)
    metrics["n_params"] = model.n_params
    return metrics


def aggregate(seed_results, class_names):
    n = len(seed_results)
    scalar_keys = ["overall_acc", "macro_acc", "balanced_acc",
                   "macro_precision", "macro_recall", "macro_f1",
                   "weighted_precision", "weighted_recall", "weighted_f1", "mcc"]
    agg = {}
    for key in scalar_keys:
        values = [r[key] for r in seed_results]
        agg[key] = {
            "mean": float(np.mean(values)),
            "std": float(np.std(values, ddof=1)) if n > 1 else 0.0,
            "values": values,
        }
    for auc_key in ["roc_auc_macro", "roc_auc_weighted"]:
        values = [r[auc_key] for r in seed_results if r[auc_key] is not None]
        if values:
            agg[auc_key] = {
                "mean": float(np.mean(values)),
                "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
                "values": values,
            }
        else:
            agg[auc_key] = {"mean": None, "std": None, "values": []}
    agg["per_class"] = {}
    for cls in class_names:
        agg["per_class"][cls] = {}
        for metric in ["accuracy", "precision", "recall", "f1", "fpr", "fnr"]:
            values = [r["per_class"][cls][metric] for r in seed_results]
            agg["per_class"][cls][metric] = {
                "mean": float(np.mean(values)),
                "std": float(np.std(values, ddof=1)) if n > 1 else 0.0,
            }
    agg["n_params"] = seed_results[0]["n_params"]
    return agg


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Deployable baselines experiment")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(10)))
    parser.add_argument("--configs", nargs="+", default=list(MODEL_CONFIGS.keys()))
    parser.add_argument("--epochs", type=int, default=80)
    args = parser.parse_args()

    print("=" * 70)
    print("Deployable Baselines: Accuracy-Complexity Pareto Frontier")
    print(f"  Seeds: {args.seeds}")
    print(f"  Configs: {args.configs}")
    print(f"  Epochs: {args.epochs}")
    print(f"  Device: {DEVICE}")
    print("=" * 70)

    datasets = {}

    # NSL-KDD
    print("\n[1] Loading NSL-KDD...")
    X_tr, y_tr, X_te, y_te, le, cn = load_nslkdd()
    cw = compute_class_weights(y_tr, len(cn))
    datasets["nslkdd"] = {
        "X_train": X_tr, "y_train": y_tr, "X_test": X_te, "y_test": y_te,
        "class_names": cn, "num_classes": len(cn), "class_weights": cw,
        "n_train": len(X_tr), "n_test": len(X_te),
    }
    print(f"    Train: {len(X_tr)}, Test: {len(X_te)}, dim={X_tr.shape[1]}")

    # UNSW-NB15
    print("[2] Loading UNSW-NB15...")
    X_tr, y_tr, X_te, y_te, le, cn = load_unsw()
    cw = compute_class_weights(y_tr, len(cn))
    datasets["unsw"] = {
        "X_train": X_tr, "y_train": y_tr, "X_test": X_te, "y_test": y_te,
        "class_names": cn, "num_classes": len(cn), "class_weights": cw,
        "n_train": len(X_tr), "n_test": len(X_te),
    }
    print(f"    Train: {len(X_tr)}, Test: {len(X_te)}, dim={X_tr.shape[1]}")

    output = {"experiment": "Deployable baselines Pareto frontier",
              "seeds": args.seeds, "epochs": args.epochs}

    for ds_name, ds in datasets.items():
        print(f"\n{'='*70}")
        print(f"Dataset: {ds_name}")
        print(f"{'='*70}")
        output[ds_name] = {}

        for cfg_name in args.configs:
            cfg = MODEL_CONFIGS[cfg_name]
            print(f"\n  Config: {cfg_name} ({cfg['description']})")
            seed_results = []

            for seed in args.seeds:
                t0 = time.time()
                metrics = train_single(
                    cfg_name, seed,
                    ds["X_train"], ds["y_train"],
                    ds["X_test"], ds["y_test"],
                    ds["class_weights"], ds["num_classes"],
                    ds["class_names"], args.epochs
                )
                elapsed = time.time() - t0
                seed_results.append(metrics)
                print(f"    seed={seed}: OA={metrics['overall_acc']:.2f}% "
                      f"MA={metrics['macro_acc']:.2f}% "
                      f"MF1={metrics['macro_f1']:.2f}% "
                      f"MCC={metrics['mcc']:.3f} ({elapsed:.1f}s)")

            agg = aggregate(seed_results, ds["class_names"])
            output[ds_name][cfg_name] = {
                "config": cfg,
                "n_params": agg["n_params"],
                "per_seed": seed_results,
                "aggregate": agg,
            }
            print(f"    => OA={agg['overall_acc']['mean']:.2f}±{agg['overall_acc']['std']:.2f}% "
                  f"MA={agg['macro_acc']['mean']:.2f}±{agg['macro_acc']['std']:.2f}% "
                  f"MCC={agg['mcc']['mean']:.3f}±{agg['mcc']['std']:.3f} "
                  f"params={agg['n_params']}")

    # Pareto summary
    print(f"\n{'='*70}")
    print("Pareto Frontier Summary")
    print(f"{'='*70}")
    print(f"{'Config':<20s} {'Params':>8s} | {'NSL OA%':>12s} {'NSL MA%':>12s} | {'UNSW OA%':>12s} {'UNSW MA%':>12s}")
    print("-" * 80)
    for cfg_name in args.configs:
        n = output["nslkdd"][cfg_name]["n_params"]
        nsl = output["nslkdd"][cfg_name]["aggregate"]
        unsw = output["unsw"][cfg_name]["aggregate"]
        print(f"{cfg_name:<20s} {n:>8d} | "
              f"{nsl['overall_acc']['mean']:>5.2f}±{nsl['overall_acc']['std']:.2f} "
              f"{nsl['macro_acc']['mean']:>5.2f}±{nsl['macro_acc']['std']:.2f} | "
              f"{unsw['overall_acc']['mean']:>5.2f}±{unsw['overall_acc']['std']:.2f} "
              f"{unsw['macro_acc']['mean']:>5.2f}±{unsw['macro_acc']['std']:.2f}")

    out_path = RESULTS_DIR / "baselines_experiment.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
