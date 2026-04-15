"""
Multi-seed experiment on UNSW-NB15 dataset for SNN-IDS paper.
Trains ReLU MLP across 10 seeds with full metrics.

Dataset: UNSW-NB15 (175K train / 82K test, 10-class)
Model: Same IDS_MLP architecture adapted for UNSW-NB15 features.

Usage:
    python src/experiment_unsw.py                # all 10 seeds
    python src/experiment_unsw.py --seeds 0 1 2  # specific seeds
"""

import argparse
import json
import time
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import numpy as np
from metrics import full_evaluate as compute_all_metrics
from models import IDS_MLP
from train_utils import set_seed, compute_class_weights
from data_loaders import load_unsw
from pathlib import Path

import warnings
warnings.filterwarnings("ignore", message=".*NVIDIA GB10.*not compatible.*")
warnings.filterwarnings("ignore", message=".*Found GPU0 NVIDIA GB10.*")

DATA_DIR = Path(__file__).parent.parent / "data"
MODEL_DIR = Path(__file__).parent.parent / "models"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def full_evaluate(model, X_test, y_test, num_classes, class_names):
    """Collect predictions + probabilities, delegate to shared metrics."""
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


def train_single(seed, X_train, y_train, X_test, y_test,
                 class_weights, num_classes, class_names, input_dim, epochs=80):
    """Train one model, return metrics + best state dict."""
    set_seed(seed)

    model = IDS_MLP(input_dim=input_dim, hidden=256, num_classes=num_classes)
    model = model.to(DEVICE)
    cw = class_weights.to(DEVICE)

    train_loader = DataLoader(
        TensorDataset(X_train, y_train), batch_size=512, shuffle=True,
        generator=torch.Generator().manual_seed(seed)
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
                for X_b, y_b in DataLoader(TensorDataset(X_test.to(DEVICE), y_test.to(DEVICE)),
                                            batch_size=2048, shuffle=False):
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
    metrics = full_evaluate(model, X_test, y_test, num_classes, class_names)

    # Save best model from seed 0 for ONNX export
    if seed == 0:
        torch.save(best_state, MODEL_DIR / "unsw_relu_best.pth")

    return metrics


def aggregate_results(seed_results, class_names):
    """Mean +/- std across seeds."""
    n = len(seed_results)
    scalar_keys = ["overall_acc", "macro_acc", "balanced_acc",
                   "macro_precision", "macro_recall", "macro_f1",
                   "weighted_precision", "weighted_recall", "weighted_f1",
                   "mcc"]
    agg = {}
    for key in scalar_keys:
        values = [r[key] for r in seed_results]
        agg[key] = {
            "mean": float(np.mean(values)),
            "std": float(np.std(values, ddof=1)) if n > 1 else 0.0,
            "min": float(np.min(values)),
            "max": float(np.max(values)),
            "values": values,
        }

    # ROC-AUC (may be None)
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

    cms = np.array([r["confusion_matrix"] for r in seed_results])
    agg["confusion_matrix_mean"] = np.mean(cms, axis=0).tolist()
    agg["confusion_matrix_std"] = (np.std(cms, axis=0, ddof=1).tolist()
                                    if n > 1 else np.zeros_like(cms[0]).tolist())

    return agg


def main():
    parser = argparse.ArgumentParser(description="UNSW-NB15 Multi-seed experiment")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(10)))
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--output", type=str, default="unsw_multiseed_experiment.json",
                        help="Output filename (written under results/)")
    args = parser.parse_args()

    print("=" * 70)
    print("SNN-IDS: UNSW-NB15 Multi-Seed Experiment (ReLU MLP)")
    print(f"  Seeds: {args.seeds}")
    print(f"  Epochs: {args.epochs}")
    print(f"  Device: {DEVICE} ({torch.cuda.get_device_name(0) if DEVICE.type == 'cuda' else 'CPU'})")
    print("=" * 70)

    # Load data
    print("\n[1] Loading UNSW-NB15 dataset...")
    X_train, y_train, X_test, y_test, scaler, label_enc, feature_names = load_unsw(DATA_DIR)
    X_train = torch.tensor(X_train, dtype=torch.float32)
    y_train = torch.tensor(y_train, dtype=torch.long)
    X_test = torch.tensor(X_test, dtype=torch.float32)
    y_test = torch.tensor(y_test, dtype=torch.long)
    print(f"    Train: {len(X_train)}, Test: {len(X_test)}")
    num_classes = len(label_enc.classes_)
    class_names = list(label_enc.classes_)
    input_dim = X_train.shape[1]
    class_weights = compute_class_weights(y_train, num_classes)

    print(f"    Input dim: {input_dim}")
    print(f"    Classes ({num_classes}): {class_names}")
    print(f"    Class weights: {dict(zip(class_names, [f'{w:.3f}' for w in class_weights.tolist()]))}")

    # Train
    print(f"\n[3] Training {len(args.seeds)} seeds...")
    all_results = []

    for i, seed in enumerate(args.seeds):
        t0 = time.time()
        print(f"\n  Seed {seed} ({i+1}/{len(args.seeds)})...", end=" ", flush=True)
        metrics = train_single(seed, X_train, y_train, X_test, y_test,
                               class_weights, num_classes, class_names,
                               input_dim, args.epochs)
        elapsed = time.time() - t0
        all_results.append(metrics)
        print(f"done ({elapsed:.1f}s) — "
              f"OA={metrics['overall_acc']:.2f}% "
              f"MA={metrics['macro_acc']:.2f}% "
              f"MF1={metrics['macro_f1']:.2f}%")

    # Aggregate
    print(f"\n{'='*70}")
    print("Aggregated Results")
    print(f"{'='*70}")

    agg = aggregate_results(all_results, class_names)
    print(f"\n  ReLU MLP on UNSW-NB15 (n={len(all_results)} seeds):")
    print(f"    Overall Acc:  {agg['overall_acc']['mean']:.2f} +/- {agg['overall_acc']['std']:.2f}%")
    print(f"    Macro Acc:    {agg['macro_acc']['mean']:.2f} +/- {agg['macro_acc']['std']:.2f}%")
    print(f"    Macro F1:     {agg['macro_f1']['mean']:.2f} +/- {agg['macro_f1']['std']:.2f}%")
    print(f"    Macro Prec:   {agg['macro_precision']['mean']:.2f} +/- {agg['macro_precision']['std']:.2f}%")
    print(f"    Macro Recall: {agg['macro_recall']['mean']:.2f} +/- {agg['macro_recall']['std']:.2f}%")

    print(f"\n  Per-class (mean +/- std):")
    for cls in class_names:
        pc = agg["per_class"][cls]
        print(f"    {cls:>16s}: Acc={pc['accuracy']['mean']:.2f}+/-{pc['accuracy']['std']:.2f}  "
              f"P={pc['precision']['mean']:.2f}+/-{pc['precision']['std']:.2f}  "
              f"R={pc['recall']['mean']:.2f}+/-{pc['recall']['std']:.2f}  "
              f"F1={pc['f1']['mean']:.2f}+/-{pc['f1']['std']:.2f}")

    # Save
    output = {
        "experiment": "UNSW-NB15 multi-seed ReLU MLP",
        "dataset": "UNSW-NB15",
        "seeds": args.seeds,
        "epochs": args.epochs,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "input_dim": int(input_dim),
        "num_classes": num_classes,
        "class_names": class_names,
        "feature_names": feature_names,
        "per_seed": all_results,
        "aggregate": agg,
    }

    out_path = RESULTS_DIR / args.output
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
