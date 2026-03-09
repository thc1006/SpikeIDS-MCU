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
import pandas as pd
import numpy as np
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
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


def load_unsw_nb15():
    """Load UNSW-NB15 from parquet files."""
    train_path = DATA_DIR / "UNSW_NB15_training-set.parquet"
    test_path = DATA_DIR / "UNSW_NB15_testing-set.parquet"

    train_df = pd.read_parquet(train_path)
    test_df = pd.read_parquet(test_path)

    return train_df, test_df


def preprocess_unsw(train_df, test_df):
    """Preprocess UNSW-NB15: encode categoricals, scale, extract labels."""
    # Drop id column if present
    for col in ["id"]:
        if col in train_df.columns:
            train_df = train_df.drop(columns=[col])
            test_df = test_df.drop(columns=[col])

    # Use attack_cat as label (10-class), drop binary 'label' column
    train_labels_raw = train_df["attack_cat"].astype(str).str.strip()
    test_labels_raw = test_df["attack_cat"].astype(str).str.strip()

    train_df = train_df.drop(columns=["attack_cat", "label"])
    test_df = test_df.drop(columns=["attack_cat", "label"])

    # Identify categorical columns
    cat_cols = train_df.select_dtypes(include=["object", "category"]).columns.tolist()

    # Encode categoricals
    for col in cat_cols:
        le = LabelEncoder()
        combined = pd.concat([train_df[col].astype(str), test_df[col].astype(str)])
        le.fit(combined)
        train_df[col] = le.transform(train_df[col].astype(str))
        test_df[col] = le.transform(test_df[col].astype(str))

    # Encode labels
    all_classes = sorted(set(train_labels_raw.unique()) | set(test_labels_raw.unique()))
    label_enc = LabelEncoder()
    label_enc.fit(all_classes)
    train_labels = label_enc.transform(train_labels_raw)
    test_labels = label_enc.transform(test_labels_raw)

    # Convert to float and scale
    X_train = train_df.values.astype(np.float32)
    X_test = test_df.values.astype(np.float32)

    # Handle NaN/Inf
    X_train = np.nan_to_num(X_train, nan=0.0, posinf=1e6, neginf=-1e6)
    X_test = np.nan_to_num(X_test, nan=0.0, posinf=1e6, neginf=-1e6)

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)

    return (
        torch.tensor(X_train, dtype=torch.float32),
        torch.tensor(train_labels, dtype=torch.long),
        torch.tensor(X_test, dtype=torch.float32),
        torch.tensor(test_labels, dtype=torch.long),
        scaler, label_enc, list(train_df.columns),
    )


class IDS_MLP(nn.Module):
    """Same architecture as NSL-KDD, adapted input/output dims."""
    def __init__(self, input_dim, hidden=256, num_classes=10):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.BatchNorm1d(hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.BatchNorm1d(hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden // 2),
            nn.BatchNorm1d(hidden // 2),
            nn.ReLU(),
            nn.Linear(hidden // 2, num_classes),
        )

    def forward(self, x):
        return self.layers(x)


def compute_class_weights(labels, num_classes):
    counts = np.bincount(labels.numpy(), minlength=num_classes).astype(np.float32)
    counts = np.maximum(counts, 1.0)
    weights = 1.0 / counts
    weights = weights / weights.sum() * num_classes
    return torch.tensor(weights, dtype=torch.float32)


def set_seed(seed):
    torch.manual_seed(seed)
    np.random.seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def full_evaluate(model, X_test, y_test, num_classes, class_names):
    """Full evaluation with P/R/F1/confusion matrix."""
    model.eval()
    loader = DataLoader(TensorDataset(X_test, y_test), batch_size=2048, shuffle=False)
    all_preds, all_labels = [], []
    with torch.no_grad():
        for X_b, y_b in loader:
            preds = model(X_b).argmax(dim=1)
            all_preds.append(preds.numpy())
            all_labels.append(y_b.numpy())
    y_true = np.concatenate(all_labels)
    y_pred = np.concatenate(all_preds)

    cm = confusion_matrix(y_true, y_pred, labels=list(range(num_classes)))
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=list(range(num_classes)), zero_division=0
    )
    per_class_acc = cm.diagonal() / np.maximum(cm.sum(axis=1), 1)
    overall_acc = cm.diagonal().sum() / cm.sum() * 100
    macro_acc = per_class_acc.mean() * 100

    w_precision, w_recall, w_f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average='weighted', zero_division=0
    )

    return {
        "overall_acc": float(overall_acc),
        "macro_acc": float(macro_acc),
        "macro_precision": float(np.mean(precision) * 100),
        "macro_recall": float(np.mean(recall) * 100),
        "macro_f1": float(np.mean(f1) * 100),
        "weighted_precision": float(w_precision * 100),
        "weighted_recall": float(w_recall * 100),
        "weighted_f1": float(w_f1 * 100),
        "per_class": {
            class_names[i]: {
                "accuracy": float(per_class_acc[i] * 100),
                "precision": float(precision[i] * 100),
                "recall": float(recall[i] * 100),
                "f1": float(f1[i] * 100),
                "support": int(support[i]),
            }
            for i in range(num_classes)
        },
        "confusion_matrix": cm.tolist(),
    }


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
    scalar_keys = ["overall_acc", "macro_acc", "macro_precision",
                   "macro_recall", "macro_f1", "weighted_precision",
                   "weighted_recall", "weighted_f1"]
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

    agg["per_class"] = {}
    for cls in class_names:
        agg["per_class"][cls] = {}
        for metric in ["accuracy", "precision", "recall", "f1"]:
            values = [r["per_class"][cls][metric] for r in seed_results]
            agg["per_class"][cls][metric] = {
                "mean": float(np.mean(values)),
                "std": float(np.std(values, ddof=1)) if n > 1 else 0.0,
            }

    cms = np.array([r["confusion_matrix"] for r in seed_results])
    agg["confusion_matrix_mean"] = np.mean(cms, axis=0).tolist()

    return agg


def main():
    parser = argparse.ArgumentParser(description="UNSW-NB15 Multi-seed experiment")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(10)))
    parser.add_argument("--epochs", type=int, default=80)
    args = parser.parse_args()

    print("=" * 70)
    print("SNN-IDS: UNSW-NB15 Multi-Seed Experiment (ReLU MLP)")
    print(f"  Seeds: {args.seeds}")
    print(f"  Epochs: {args.epochs}")
    print(f"  Device: {DEVICE} ({torch.cuda.get_device_name(0) if DEVICE.type == 'cuda' else 'CPU'})")
    print("=" * 70)

    # Load data
    print("\n[1] Loading UNSW-NB15 dataset...")
    train_df, test_df = load_unsw_nb15()
    print(f"    Train: {len(train_df)}, Test: {len(test_df)}")

    # Preprocess
    print("\n[2] Preprocessing...")
    X_train, y_train, X_test, y_test, scaler, label_enc, feature_names = preprocess_unsw(
        train_df.copy(), test_df.copy()
    )
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
        "n_train": int(len(train_df)),
        "n_test": int(len(test_df)),
        "input_dim": int(input_dim),
        "num_classes": num_classes,
        "class_names": class_names,
        "feature_names": feature_names,
        "per_seed": all_results,
        "aggregate": agg,
    }

    out_path = RESULTS_DIR / "unsw_multiseed_experiment.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
