"""
IoT-23 QCFS L=4 multi-seed experiment.

Mirrors experiment_iot23.py's ReLU pipeline but substitutes IDS_MLP_QCFS.
Validates T=1 SNN-ANN equivalence on IoT-23 (4th dataset).

Output: results/iot23_qcfs_multiseed.json

Usage:
    python src/experiment_iot23_qcfs.py                    # 5-class, 5 seeds
    python src/experiment_iot23_qcfs.py --binary           # binary, 5 seeds
    python src/experiment_iot23_qcfs.py --seeds 0 1 2 3 4 --L 4
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

import warnings
warnings.filterwarnings("ignore", message=".*NVIDIA GB10.*")
warnings.filterwarnings("ignore", message=".*Found GPU0 NVIDIA GB10.*")

RESULTS_DIR = Path(__file__).parent.parent / "results"
MODEL_DIR = Path(__file__).parent.parent / "models"
RESULTS_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _evaluate(model, X_test, y_test, num_classes, class_names):
    model.eval()
    loader = DataLoader(TensorDataset(X_test, y_test), batch_size=4096, shuffle=False)
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


def _train_single(seed, L, X_train, y_train, X_test, y_test,
                   class_weights, num_classes, class_names, input_dim, epochs):
    set_seed(seed)
    model = IDS_MLP_QCFS(input_dim=input_dim, hidden=256,
                          num_classes=num_classes, L=L).to(DEVICE)
    cw = class_weights.to(DEVICE)
    train_loader = DataLoader(
        TensorDataset(X_train, y_train), batch_size=1024, shuffle=True,
        generator=torch.Generator().manual_seed(seed),
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
                loader = DataLoader(
                    TensorDataset(X_test.to(DEVICE), y_test.to(DEVICE)),
                    batch_size=4096, shuffle=False,
                )
                for X_b, y_b in loader:
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

    model = model.cpu()
    if best_state is not None:
        model.load_state_dict(best_state)
    metrics = _evaluate(model, X_test, y_test, num_classes, class_names)

    if seed == 0:
        suffix = "_binary" if num_classes == 2 else ""
        torch.save(best_state, MODEL_DIR / f"iot23_qcfs_L{L}{suffix}_best.pth")
    return metrics


def _aggregate(per_seed, class_names):
    scalar_keys = ["overall_acc", "macro_acc", "balanced_acc",
                    "macro_precision", "macro_recall", "macro_f1",
                    "weighted_precision", "weighted_recall", "weighted_f1",
                    "mcc"]
    agg = {}
    n = len(per_seed)
    for k in scalar_keys:
        vals = [r[k] for r in per_seed]
        agg[k] = {
            "mean": float(np.mean(vals)),
            "std": float(np.std(vals, ddof=1)) if n > 1 else 0.0,
            "min": float(np.min(vals)),
            "max": float(np.max(vals)),
            "values": vals,
        }
    for auc_key in ["roc_auc_macro", "roc_auc_weighted"]:
        vals = [r[auc_key] for r in per_seed if r.get(auc_key) is not None]
        if vals:
            agg[auc_key] = {
                "mean": float(np.mean(vals)),
                "std": float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0,
            }
        else:
            agg[auc_key] = {"mean": None, "std": None}
    agg["per_class"] = {}
    for cls in class_names:
        agg["per_class"][cls] = {}
        for metric in ["accuracy", "precision", "recall", "f1", "fpr", "fnr"]:
            vals = [r["per_class"][cls][metric] for r in per_seed]
            agg["per_class"][cls][metric] = {
                "mean": float(np.mean(vals)),
                "std": float(np.std(vals, ddof=1)) if n > 1 else 0.0,
            }
    cms = np.array([r["confusion_matrix"] for r in per_seed])
    agg["confusion_matrix_mean"] = np.mean(cms, axis=0).tolist()
    return agg


def main():
    ap = argparse.ArgumentParser(description="IoT-23 QCFS multi-seed")
    ap.add_argument("--seeds", type=int, nargs="+", default=list(range(5)))
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--L", type=int, default=4)
    ap.add_argument("--binary", action="store_true",
                     help="Binary mode (Benign vs Malicious)")
    ap.add_argument("--output", type=str, default=None)
    args = ap.parse_args()

    label_mode = "binary" if args.binary else "5-class"
    print("=" * 70)
    print(f"IoT-23 QCFS L={args.L} multi-seed ({len(args.seeds)} seeds, {label_mode})")
    print(f"  Device: {DEVICE}")
    print("=" * 70)

    from experiment_iot23 import load_iot23, preprocess_iot23
    df, labels, feature_names = load_iot23(binary=args.binary)
    X_train, y_train, X_test, y_test, _scaler, label_enc = preprocess_iot23(
        df, labels
    )
    class_names = list(label_enc.classes_)
    num_classes = len(class_names)
    input_dim = X_train.shape[1]
    class_weights = compute_class_weights(y_train, num_classes)

    print(f"F={input_dim} C={num_classes} train={len(X_train)} test={len(X_test)}")
    print(f"Classes: {class_names}")

    per_seed = []
    for i, seed in enumerate(args.seeds):
        t0 = time.time()
        print(f"[{i+1}/{len(args.seeds)}] seed={seed}...", end=" ", flush=True)
        m = _train_single(seed, args.L, X_train, y_train, X_test, y_test,
                           class_weights, num_classes, class_names,
                           input_dim, args.epochs)
        per_seed.append(m)
        elapsed = time.time() - t0
        print(f"done ({elapsed:.1f}s) OA={m['overall_acc']:.2f}% MF1={m['macro_f1']:.2f}%")

    agg = _aggregate(per_seed, class_names)
    print(f"\n{'='*70}")
    print(f"QCFS L={args.L} on IoT-23 {label_mode} (n={len(per_seed)} seeds):")
    print(f"  Overall Acc:  {agg['overall_acc']['mean']:.2f} ± {agg['overall_acc']['std']:.2f}%")
    print(f"  Macro Acc:    {agg['macro_acc']['mean']:.2f} ± {agg['macro_acc']['std']:.2f}%")
    print(f"  Macro F1:     {agg['macro_f1']['mean']:.2f} ± {agg['macro_f1']['std']:.2f}%")
    print(f"  Weighted F1:  {agg['weighted_f1']['mean']:.2f} ± {agg['weighted_f1']['std']:.2f}%")
    print(f"  MCC:          {agg['mcc']['mean']:.4f} ± {agg['mcc']['std']:.4f}")

    print(f"\n  Per-class:")
    for cls in class_names:
        pc = agg["per_class"][cls]
        print(f"    {cls:>12s}: P={pc['precision']['mean']:.1f}±{pc['precision']['std']:.1f}  "
              f"R={pc['recall']['mean']:.1f}±{pc['recall']['std']:.1f}  "
              f"F1={pc['f1']['mean']:.1f}±{pc['f1']['std']:.1f}")

    suffix = "_binary" if args.binary else ""
    result = {
        "experiment": f"IoT-23 QCFS L={args.L} multi-seed ({label_mode})",
        "dataset": "iot23",
        "model": f"IDS_MLP_QCFS L={args.L}",
        "label_mode": label_mode,
        "seeds": args.seeds,
        "epochs": args.epochs,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "input_dim": int(input_dim),
        "num_classes": int(num_classes),
        "class_names": class_names,
        "feature_names": feature_names,
        "qcfs": {
            "per_seed": per_seed,
            "aggregate": agg,
        },
    }
    out_path = RESULTS_DIR / (args.output or f"iot23_qcfs_multiseed{suffix}.json")
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nResults → {out_path}")


if __name__ == "__main__":
    main()
