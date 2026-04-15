"""
Multi-seed experiment on CICIDS2017 dataset for SNN-IDS paper.
Trains ReLU MLP across 10 seeds with full metrics.

Dataset: CICIDS2017 (2.83M records, 15-class or grouped)
Model: Same IDS_MLP architecture adapted for CICIDS2017 features.
Split: 80/20 stratified random (no standard split exists).

Known issues:
- BENIGN ~80.3% of traffic (extreme imbalance)
- Heartbleed: 11 samples, Infiltration: 36 samples
- CICFlowMeter TCP single-FIN termination bug (Engelen et al. 2021)
- Some features contain NaN/Inf values

Usage:
    python src/experiment_cicids2017.py                # all 10 seeds
    python src/experiment_cicids2017.py --seeds 0 1 2  # specific seeds
    python src/experiment_cicids2017.py --grouped       # 7-class grouped
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
from sklearn.model_selection import train_test_split
from metrics import full_evaluate as compute_all_metrics
from models import IDS_MLP
from train_utils import set_seed, compute_class_weights
from pathlib import Path

import warnings
warnings.filterwarnings("ignore", message=".*NVIDIA GB10.*not compatible.*")
warnings.filterwarnings("ignore", message=".*Found GPU0 NVIDIA GB10.*")

DATA_DIR = Path(__file__).parent.parent / "data"
CICIDS_DIR = DATA_DIR / "cicids2017"
MODEL_DIR = Path(__file__).parent.parent / "models"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# 7-class grouping (15 → 7)
ATTACK_GROUP_MAP = {
    'BENIGN': 'Benign',
    'Bot': 'Bot',
    'DDoS': 'DoS',
    'DoS GoldenEye': 'DoS',
    'DoS Hulk': 'DoS',
    'DoS Slowhttptest': 'DoS',
    'DoS slowloris': 'DoS',
    'FTP-Patator': 'BruteForce',
    'Heartbleed': 'Heartbleed',
    'Infiltration': 'Infiltration',
    'PortScan': 'PortScan',
    'SSH-Patator': 'BruteForce',
    'Web Attack \x96 Brute Force': 'WebAttack',
    'Web Attack \x96 Sql Injection': 'WebAttack',
    'Web Attack \x96 XSS': 'WebAttack',
    # Alternative encoding (some CSVs use en-dash)
    'Web Attack – Brute Force': 'WebAttack',
    'Web Attack – Sql Injection': 'WebAttack',
    'Web Attack – XSS': 'WebAttack',
}

# Columns to drop (identifiers, not features)
DROP_COLS = [
    'Flow ID', 'Source IP', 'Destination IP',
    'Source Port', 'Destination Port', 'Timestamp',
    # Also handle stripped versions
    'flow id', 'source ip', 'destination ip',
    'source port', 'destination port', 'timestamp',
]

CSV_FILES = [
    "Monday-WorkingHours.pcap_ISCX.csv",
    "Tuesday-WorkingHours.pcap_ISCX.csv",
    "Wednesday-workingHours.pcap_ISCX.csv",
    "Thursday-WorkingHours-Morning-WebAttacks.pcap_ISCX.csv",
    "Thursday-WorkingHours-Afternoon-Infilteration.pcap_ISCX.csv",
    "Friday-WorkingHours-Morning.pcap_ISCX.csv",
    "Friday-WorkingHours-Afternoon-PortScan.pcap_ISCX.csv",
    "Friday-WorkingHours-Afternoon-DDos.pcap_ISCX.csv",
]


def load_cicids2017(grouped=False):
    """Load CICIDS2017 from individual CSV files or combined parquet."""
    # Try parquet first (faster if pre-converted)
    parquet_path = CICIDS_DIR / "cicids2017_combined.parquet"
    if parquet_path.exists():
        print("    Loading from parquet (fast path)...")
        df = pd.read_parquet(parquet_path)
    else:
        # Load from CSVs
        print("    Loading from CSVs (slow path, consider converting to parquet)...")
        dfs = []
        for fname in CSV_FILES:
            fpath = CICIDS_DIR / fname
            if not fpath.exists():
                print(f"    WARNING: {fname} not found, skipping")
                continue
            print(f"    Loading {fname}...")
            chunk = pd.read_csv(fpath, encoding='utf-8', low_memory=False)
            dfs.append(chunk)

        if not dfs:
            raise FileNotFoundError(
                f"No CICIDS2017 CSV files found in {CICIDS_DIR}.\n"
                f"Download from: https://www.unb.ca/cic/datasets/ids-2017.html\n"
                f"Place the 8 CSV files in {CICIDS_DIR}/"
            )

        df = pd.concat(dfs, ignore_index=True)
        print(f"    Combined: {len(df)} records")

        # Save as parquet for future fast loading
        df.to_parquet(parquet_path, index=False)
        print(f"    Saved to {parquet_path} for future use")

    # Strip column names (CICIDS2017 CSVs have leading spaces)
    df.columns = df.columns.str.strip()

    # Extract labels
    label_col = None
    for candidate in ['Label', 'label']:
        if candidate in df.columns:
            label_col = candidate
            break
    if label_col is None:
        raise ValueError(f"Label column not found. Columns: {list(df.columns)[:10]}...")

    labels = df[label_col].astype(str).str.strip()
    df = df.drop(columns=[label_col])

    # Apply grouping if requested
    if grouped:
        labels = labels.map(ATTACK_GROUP_MAP)
        unmapped = labels.isna()
        if unmapped.any():
            unique_unmapped = df.loc[unmapped, label_col] if label_col in df.columns else "unknown"
            print(f"    WARNING: {unmapped.sum()} unmapped labels dropped")
            df = df[~unmapped]
            labels = labels[~unmapped]

    # Drop identifier columns
    for col in DROP_COLS:
        if col in df.columns:
            df = df.drop(columns=[col])

    # Drop non-numeric columns that slipped through
    non_numeric = df.select_dtypes(exclude=[np.number]).columns.tolist()
    if non_numeric:
        print(f"    Dropping non-numeric columns: {non_numeric}")
        df = df.drop(columns=non_numeric)

    # Handle NaN/Inf
    n_nan = df.isna().sum().sum()
    n_inf = np.isinf(df.select_dtypes(include=[np.number]).values).sum()
    if n_nan > 0 or n_inf > 0:
        print(f"    Cleaning: {n_nan} NaN, {n_inf} Inf values")

    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.fillna(0.0)

    # Drop constant columns (zero variance)
    constant_cols = [c for c in df.columns if df[c].nunique() <= 1]
    if constant_cols:
        print(f"    Dropping {len(constant_cols)} constant columns: {constant_cols}")
        df = df.drop(columns=constant_cols)

    # Drop negative-only columns that shouldn't be negative
    # (CICFlowMeter bug: some byte/packet counts are negative)
    for col in df.columns:
        if df[col].min() < 0 and ('byte' in col.lower() or 'packet' in col.lower()
                                    or 'length' in col.lower()):
            neg_count = (df[col] < 0).sum()
            if neg_count > 0:
                df[col] = df[col].clip(lower=0)

    return df, labels


def preprocess_cicids(df, labels, test_size=0.2, random_state=42):
    """Preprocess CICIDS2017: encode labels, split, scale."""
    # Encode labels
    all_classes = sorted(labels.unique())
    label_enc = LabelEncoder()
    label_enc.fit(all_classes)
    y = label_enc.transform(labels)

    X = df.values.astype(np.float32)

    # Handle any remaining NaN/Inf
    X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

    # Stratified train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )

    # Scale
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)

    return (
        torch.tensor(X_train, dtype=torch.float32),
        torch.tensor(y_train, dtype=torch.long),
        torch.tensor(X_test, dtype=torch.float32),
        torch.tensor(y_test, dtype=torch.long),
        scaler, label_enc, list(df.columns),
    )


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
        torch.save(best_state, MODEL_DIR / "cicids_relu_best.pth")

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

    return agg


def main():
    parser = argparse.ArgumentParser(description="CICIDS2017 Multi-seed experiment")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(10)))
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--grouped", action="store_true",
                        help="Use 7-class grouped labels instead of 15-class")
    parser.add_argument("--output", type=str, default=None,
                        help="Output filename (written under results/)")
    args = parser.parse_args()

    label_mode = "7-class grouped" if args.grouped else "15-class"

    print("=" * 70)
    print(f"SNN-IDS: CICIDS2017 Multi-Seed Experiment (ReLU MLP, {label_mode})")
    print(f"  Seeds: {args.seeds}")
    print(f"  Epochs: {args.epochs}")
    print(f"  Device: {DEVICE} ({torch.cuda.get_device_name(0) if DEVICE.type == 'cuda' else 'CPU'})")
    print("=" * 70)

    # Load data
    print(f"\n[1] Loading CICIDS2017 dataset ({label_mode})...")
    df, labels = load_cicids2017(grouped=args.grouped)
    print(f"    Total records: {len(df)}")
    print(f"    Features: {df.shape[1]}")

    # Class distribution
    print(f"\n    Class distribution:")
    for cls, count in labels.value_counts().sort_index().items():
        pct = count / len(labels) * 100
        print(f"      {cls:>30s}: {count:>8d} ({pct:5.2f}%)")

    # Preprocess
    print(f"\n[2] Preprocessing (80/20 stratified split)...")
    X_train, y_train, X_test, y_test, scaler, label_enc, feature_names = preprocess_cicids(
        df, labels
    )
    num_classes = len(label_enc.classes_)
    class_names = list(label_enc.classes_)
    input_dim = X_train.shape[1]
    class_weights = compute_class_weights(y_train, num_classes)

    print(f"    Train: {len(X_train)}, Test: {len(X_test)}")
    print(f"    Input dim: {input_dim}")
    print(f"    Classes ({num_classes}): {class_names}")

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
    print(f"\n  ReLU MLP on CICIDS2017 {label_mode} (n={len(all_results)} seeds):")
    print(f"    Overall Acc:   {agg['overall_acc']['mean']:.2f} +/- {agg['overall_acc']['std']:.2f}%")
    print(f"    Macro Acc:     {agg['macro_acc']['mean']:.2f} +/- {agg['macro_acc']['std']:.2f}%")
    print(f"    Balanced Acc:  {agg['balanced_acc']['mean']:.2f} +/- {agg['balanced_acc']['std']:.2f}%")
    print(f"    Macro F1:      {agg['macro_f1']['mean']:.2f} +/- {agg['macro_f1']['std']:.2f}%")
    print(f"    Macro Prec:    {agg['macro_precision']['mean']:.2f} +/- {agg['macro_precision']['std']:.2f}%")
    print(f"    Macro Recall:  {agg['macro_recall']['mean']:.2f} +/- {agg['macro_recall']['std']:.2f}%")
    print(f"    MCC:           {agg['mcc']['mean']:.4f} +/- {agg['mcc']['std']:.4f}")
    if agg['roc_auc_macro']['mean'] is not None:
        print(f"    ROC-AUC (macro): {agg['roc_auc_macro']['mean']:.4f} +/- {agg['roc_auc_macro']['std']:.4f}")

    print(f"\n  Per-class (mean +/- std):")
    for cls in class_names:
        pc = agg["per_class"][cls]
        print(f"    {cls:>30s}: Acc={pc['accuracy']['mean']:.2f}+/-{pc['accuracy']['std']:.2f}  "
              f"P={pc['precision']['mean']:.2f}+/-{pc['precision']['std']:.2f}  "
              f"R={pc['recall']['mean']:.2f}+/-{pc['recall']['std']:.2f}  "
              f"F1={pc['f1']['mean']:.2f}+/-{pc['f1']['std']:.2f}")

    # Save
    suffix = "_grouped" if args.grouped else ""
    output = {
        "experiment": f"CICIDS2017 multi-seed ReLU MLP ({label_mode})",
        "dataset": "CICIDS2017",
        "label_mode": label_mode,
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

    out_path = RESULTS_DIR / (args.output or f"cicids2017_multiseed_experiment{suffix}.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
