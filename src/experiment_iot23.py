"""
Multi-seed experiment on IoT-23 dataset for SNN-IDS.
Trains ReLU MLP across seeds with full metrics.

Dataset: IoT-23 (Stratosphere Lab, CTU Prague; HuggingFace preprocessed)
  - 6M Zeek conn.log flows, 21 columns, 13 raw labels
  - 5-class grouping: Benign / PortScan / Okiru / DDoS / C&C
  - Binary mode: Benign vs Malicious (for HH-NIDS comparison)

Model: Same IDS_MLP architecture (256-256-128).
Split: 80/20 stratified random.

Usage:
    python src/experiment_iot23.py                       # 5-class, 10 seeds
    python src/experiment_iot23.py --binary               # binary, 10 seeds
    python src/experiment_iot23.py --seeds 0 1 2 --epochs 40
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
warnings.filterwarnings("ignore", message=".*NVIDIA GB10.*")
warnings.filterwarnings("ignore", message=".*Found GPU0 NVIDIA GB10.*")

DATA_DIR = Path(__file__).parent.parent / "data"
IOT23_DIR = DATA_DIR / "iot23"
MODEL_DIR = Path(__file__).parent.parent / "models"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

LABEL_MAP_5CLASS = {
    'PartOfAHorizontalPortScan': 'PortScan',
    'Okiru': 'Okiru',
    'Benign': 'Benign',
    'DDoS': 'DDoS',
    'C&C': 'C&C',
    'C&C-HeartBeat': 'C&C',
    'Attack': 'C&C',
    'C&C-FileDownload': 'C&C',
    'C&C-Torii': 'C&C',
    'FileDownload': 'C&C',
    'C&C-HeartBeat-FileDownload': 'C&C',
    'Okiru-Attack': 'Okiru',
    'C&C-Mirai': 'C&C',
}

DROP_COLS = ['ts', 'uid', 'id.orig_h', 'id.resp_h', 'local_orig', 'local_resp', 'history']

CATEGORICAL_COLS = ['proto', 'service', 'conn_state']

NUMERIC_COLS = [
    'id.orig_p', 'id.resp_p', 'duration',
    'orig_bytes', 'resp_bytes', 'missed_bytes',
    'orig_pkts', 'orig_ip_bytes', 'resp_pkts', 'resp_ip_bytes',
]


def download_iot23():
    """Download IoT-23 from HuggingFace and cache as parquet."""
    parquet_path = IOT23_DIR / "iot23_combined.parquet"
    if parquet_path.exists():
        print("    Found cached parquet, loading...")
        return pd.read_parquet(parquet_path)

    IOT23_DIR.mkdir(parents=True, exist_ok=True)
    print("    Downloading from HuggingFace (19kmunz/iot-23-preprocessed-allcolumns)...")
    from datasets import load_dataset
    ds = load_dataset("19kmunz/iot-23-preprocessed-allcolumns", split="train")
    df = ds.to_pandas()
    print(f"    Downloaded {len(df)} rows, {df.shape[1]} columns")

    df.to_parquet(parquet_path, index=False)
    print(f"    Cached to {parquet_path}")
    return df


def load_iot23(binary=False):
    """Load and preprocess IoT-23."""
    df = download_iot23()

    # Extract labels before dropping
    if 'label' not in df.columns:
        raise ValueError(f"'label' column not found. Columns: {list(df.columns)[:10]}...")

    raw_labels = df['label'].astype(str).str.strip()
    df = df.drop(columns=['label'])

    # Map to 5-class or binary
    if binary:
        labels = raw_labels.apply(lambda x: 'Benign' if x == 'Benign' else 'Malicious')
    else:
        labels = raw_labels.map(LABEL_MAP_5CLASS)
        unmapped = labels.isna()
        if unmapped.any():
            print(f"    WARNING: {unmapped.sum()} unmapped labels dropped")
            df = df[~unmapped].reset_index(drop=True)
            labels = labels[~unmapped].reset_index(drop=True)

    # Drop identifier/high-cardinality columns
    for col in DROP_COLS:
        if col in df.columns:
            df = df.drop(columns=[col])

    # Encode categoricals
    cat_encoders = {}
    for col in CATEGORICAL_COLS:
        if col not in df.columns:
            continue
        df[col] = df[col].astype(str).fillna('unknown')
        enc = LabelEncoder()
        enc.fit(df[col])
        df[col] = enc.transform(df[col])
        cat_encoders[col] = enc

    # Keep only known numeric + encoded categorical columns
    keep_cols = [c for c in NUMERIC_COLS + CATEGORICAL_COLS if c in df.columns]
    df = df[keep_cols]

    # Handle NaN/Inf
    n_nan = df.isna().sum().sum()
    n_inf = np.isinf(df.select_dtypes(include=[np.number]).values).sum()
    if n_nan > 0 or n_inf > 0:
        print(f"    Cleaning: {n_nan} NaN, {n_inf} Inf values")
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.fillna(0.0)

    feature_names = list(df.columns)
    print(f"F={len(feature_names)} C={labels.nunique()} total={len(df)}")

    return df, labels, feature_names


def preprocess_iot23(df, labels, test_size=0.2, random_state=42):
    """Encode labels, split, scale."""
    all_classes = sorted(labels.unique())
    label_enc = LabelEncoder()
    label_enc.fit(all_classes)
    y = label_enc.transform(labels)

    X = df.values.astype(np.float32)
    X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)

    return (
        torch.tensor(X_train, dtype=torch.float32),
        torch.tensor(y_train, dtype=torch.long),
        torch.tensor(X_test, dtype=torch.float32),
        torch.tensor(y_test, dtype=torch.long),
        scaler, label_enc,
    )


def full_evaluate(model, X_test, y_test, num_classes, class_names):
    model.eval()
    loader = DataLoader(TensorDataset(X_test, y_test), batch_size=4096, shuffle=False)
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
                 class_weights, num_classes, class_names, input_dim, epochs=40):
    set_seed(seed)

    model = IDS_MLP(input_dim=input_dim, hidden=256, num_classes=num_classes)
    model = model.to(DEVICE)
    cw = class_weights.to(DEVICE)

    train_loader = DataLoader(
        TensorDataset(X_train, y_train), batch_size=1024, shuffle=True,
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
                for X_b, y_b in DataLoader(
                    TensorDataset(X_test.to(DEVICE), y_test.to(DEVICE)),
                    batch_size=4096, shuffle=False
                ):
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
    model.load_state_dict(best_state)
    metrics = full_evaluate(model, X_test, y_test, num_classes, class_names)

    if seed == 0:
        suffix = "_binary" if num_classes == 2 else ""
        torch.save(best_state, MODEL_DIR / f"iot23_relu_best{suffix}.pth")

    return metrics


def aggregate_results(seed_results, class_names):
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
    parser = argparse.ArgumentParser(description="IoT-23 Multi-seed experiment")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(10)))
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--binary", action="store_true",
                        help="Binary mode (Benign vs Malicious) for HH-NIDS comparison")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    label_mode = "binary" if args.binary else "5-class"

    print("=" * 70)
    print(f"SNN-IDS: IoT-23 Multi-Seed Experiment (ReLU MLP, {label_mode})")
    print(f"  Seeds: {args.seeds}")
    print(f"  Epochs: {args.epochs}")
    print(f"  Device: {DEVICE}")
    print("=" * 70)

    print(f"\n[1] Loading IoT-23 ({label_mode})...")
    df, labels, feature_names = load_iot23(binary=args.binary)
    print(f"    Total records: {len(df)}")
    print(f"    Features: {len(feature_names)}: {feature_names}")

    print(f"\n    Class distribution:")
    for cls, count in labels.value_counts().sort_index().items():
        pct = count / len(labels) * 100
        print(f"      {cls:>20s}: {count:>8d} ({pct:5.2f}%)")

    print(f"\n[2] Preprocessing (80/20 stratified split)...")
    X_train, y_train, X_test, y_test, scaler, label_enc = preprocess_iot23(
        df, labels
    )
    num_classes = len(label_enc.classes_)
    class_names = list(label_enc.classes_)
    input_dim = X_train.shape[1]
    class_weights = compute_class_weights(y_train, num_classes)

    print(f"    Train: {len(X_train)}, Test: {len(X_test)}")
    print(f"    Input dim: {input_dim}, Classes ({num_classes}): {class_names}")

    print(f"\n[3] Training {len(args.seeds)} seeds...")
    all_results = []

    for i, seed in enumerate(args.seeds):
        t0 = time.time()
        print(f"[{i+1}/{len(args.seeds)}] seed={seed}...", end=" ", flush=True)
        metrics = train_single(seed, X_train, y_train, X_test, y_test,
                               class_weights, num_classes, class_names,
                               input_dim, args.epochs)
        elapsed = time.time() - t0
        all_results.append(metrics)
        print(f"done ({elapsed:.1f}s) "
              f"OA={metrics['overall_acc']:.2f}% "
              f"MF1={metrics['macro_f1']:.2f}%")

    print(f"\n{'='*70}")
    print("Aggregated Results")
    print(f"{'='*70}")

    agg = aggregate_results(all_results, class_names)
    print(f"\n  ReLU MLP on IoT-23 {label_mode} (n={len(all_results)} seeds):")
    print(f"    Overall Acc:   {agg['overall_acc']['mean']:.2f} +/- {agg['overall_acc']['std']:.2f}%")
    print(f"    Macro Acc:     {agg['macro_acc']['mean']:.2f} +/- {agg['macro_acc']['std']:.2f}%")
    print(f"    Macro F1:      {agg['macro_f1']['mean']:.2f} +/- {agg['macro_f1']['std']:.2f}%")
    print(f"    Weighted F1:   {agg['weighted_f1']['mean']:.2f} +/- {agg['weighted_f1']['std']:.2f}%")
    print(f"    MCC:           {agg['mcc']['mean']:.4f} +/- {agg['mcc']['std']:.4f}")
    if agg['roc_auc_macro']['mean'] is not None:
        print(f"    ROC-AUC (macro): {agg['roc_auc_macro']['mean']:.4f}")

    print(f"\n  Per-class (mean +/- std):")
    for cls in class_names:
        pc = agg["per_class"][cls]
        print(f"    {cls:>20s}: "
              f"P={pc['precision']['mean']:.1f}+/-{pc['precision']['std']:.1f}  "
              f"R={pc['recall']['mean']:.1f}+/-{pc['recall']['std']:.1f}  "
              f"F1={pc['f1']['mean']:.1f}+/-{pc['f1']['std']:.1f}")

    suffix = "_binary" if args.binary else ""
    output = {
        "experiment": f"IoT-23 multi-seed ReLU MLP ({label_mode})",
        "dataset": "IoT-23",
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

    out_path = RESULTS_DIR / (args.output or f"iot23_multiseed{suffix}.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
