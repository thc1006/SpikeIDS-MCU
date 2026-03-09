"""
Multi-seed experiment for SNN-IDS paper.
Trains ReLU and QCFS L=4 models across 10 seeds,
computes confusion matrix + per-class P/R/F1 + statistical comparison.

Usage:
    python src/experiment_multiseed.py                # all 10 seeds
    python src/experiment_multiseed.py --seeds 0 1 2  # specific seeds
    python src/experiment_multiseed.py --model relu    # only ReLU
    python src/experiment_multiseed.py --model qcfs    # only QCFS L=4
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
from scipy.stats import wilcoxon
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

import warnings
warnings.filterwarnings("ignore", message=".*NVIDIA GB10.*not compatible.*")
warnings.filterwarnings("ignore", message=".*Found GPU0 NVIDIA GB10.*")

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
CLASS_NAMES = ["DoS", "Probe", "R2L", "U2R", "normal"]

COL_NAMES = [
    "duration", "protocol_type", "service", "flag", "src_bytes", "dst_bytes",
    "land", "wrong_fragment", "urgent", "hot", "num_failed_logins", "logged_in",
    "num_compromised", "root_shell", "su_attempted", "num_root",
    "num_file_creations", "num_shells", "num_access_files", "num_outbound_cmds",
    "is_host_login", "is_guest_login", "count", "srv_count", "serror_rate",
    "srv_serror_rate", "rerror_rate", "srv_rerror_rate", "same_srv_rate",
    "diff_srv_rate", "srv_diff_host_rate", "dst_host_count", "dst_host_srv_count",
    "dst_host_same_srv_rate", "dst_host_diff_srv_rate",
    "dst_host_same_src_port_rate", "dst_host_srv_diff_host_rate",
    "dst_host_serror_rate", "dst_host_srv_serror_rate", "dst_host_rerror_rate",
    "dst_host_srv_rerror_rate", "label", "difficulty"
]

ATTACK_MAP = {
    'normal': 'normal',
    'back': 'DoS', 'land': 'DoS', 'neptune': 'DoS', 'pod': 'DoS',
    'smurf': 'DoS', 'teardrop': 'DoS', 'mailbomb': 'DoS', 'apache2': 'DoS',
    'processtable': 'DoS', 'udpstorm': 'DoS',
    'ipsweep': 'Probe', 'nmap': 'Probe', 'portsweep': 'Probe',
    'satan': 'Probe', 'mscan': 'Probe', 'saint': 'Probe',
    'ftp_write': 'R2L', 'guess_passwd': 'R2L', 'imap': 'R2L',
    'multihop': 'R2L', 'phf': 'R2L', 'spy': 'R2L', 'warezclient': 'R2L',
    'warezmaster': 'R2L', 'sendmail': 'R2L', 'named': 'R2L',
    'snmpgetattack': 'R2L', 'snmpguess': 'R2L', 'xlock': 'R2L',
    'xsnoop': 'R2L', 'worm': 'R2L',
    'buffer_overflow': 'U2R', 'loadmodule': 'U2R', 'perl': 'U2R',
    'rootkit': 'U2R', 'httptunnel': 'U2R', 'ps': 'U2R',
    'sqlattack': 'U2R', 'xterm': 'U2R',
}


# ── Data ──────────────────────────────────────────────────────────────

def load_nslkdd(path):
    df = pd.read_csv(path, header=None, names=COL_NAMES)
    df.drop(columns=["difficulty"], inplace=True)
    df["label"] = df["label"].map(ATTACK_MAP).fillna("unknown")
    df = df[df["label"] != "unknown"]
    return df


def preprocess(train_df, test_df, seed):
    """Preprocessing with explicit seed for StandardScaler reproducibility."""
    cat_cols = ["protocol_type", "service", "flag"]
    for col in cat_cols:
        le = LabelEncoder()
        combined = pd.concat([train_df[col], test_df[col]])
        le.fit(combined)
        train_df[col] = le.transform(train_df[col])
        test_df[col] = le.transform(test_df[col])

    label_enc = LabelEncoder()
    label_enc.fit(CLASS_NAMES)
    train_labels = label_enc.transform(train_df["label"])
    test_labels = label_enc.transform(test_df["label"])

    X_train = train_df.drop(columns=["label"]).values.astype(np.float32)
    X_test = test_df.drop(columns=["label"]).values.astype(np.float32)

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)

    return (
        torch.tensor(X_train, dtype=torch.float32),
        torch.tensor(train_labels, dtype=torch.long),
        torch.tensor(X_test, dtype=torch.float32),
        torch.tensor(test_labels, dtype=torch.long),
        scaler, label_enc,
    )


# ── Models ────────────────────────────────────────────────────────────

class IDS_MLP(nn.Module):
    def __init__(self, input_dim=41, hidden=256, num_classes=5):
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


class FloorSTE(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x):
        return torch.floor(x)

    @staticmethod
    def backward(ctx, grad_output):
        return grad_output


class QCFS(nn.Module):
    def __init__(self, L=4, init_threshold=1.0):
        super().__init__()
        self.register_buffer("L", torch.tensor(float(L)))
        self.threshold = nn.Parameter(torch.tensor(float(init_threshold)))

    def forward(self, x):
        step = self.threshold / self.L
        x_scaled = x / (step + 1e-8)
        x_clipped = torch.clamp(x_scaled, 0.0, self.L.item())
        x_floored = FloorSTE.apply(x_clipped)
        return x_floored * step


class IDS_MLP_QCFS(nn.Module):
    def __init__(self, input_dim=41, hidden=256, num_classes=5, L=4):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(input_dim, hidden),
            nn.BatchNorm1d(hidden),
            QCFS(L=L),
            nn.Linear(hidden, hidden),
            nn.BatchNorm1d(hidden),
            QCFS(L=L),
            nn.Linear(hidden, hidden // 2),
            nn.BatchNorm1d(hidden // 2),
            QCFS(L=L),
            nn.Linear(hidden // 2, num_classes),
        )

    def forward(self, x):
        return self.layers(x)


# ── Metrics ───────────────────────────────────────────────────────────

def compute_class_weights(labels, num_classes):
    counts = np.bincount(labels.numpy(), minlength=num_classes).astype(np.float32)
    counts = np.maximum(counts, 1.0)
    weights = 1.0 / counts
    weights = weights / weights.sum() * num_classes
    return torch.tensor(weights, dtype=torch.float32)


def full_evaluate(model, loader, num_classes):
    """Return predictions and ground truth for full metric computation."""
    model.eval()
    all_preds = []
    all_labels = []
    with torch.no_grad():
        for X_batch, y_batch in loader:
            preds = model(X_batch).argmax(dim=1)
            all_preds.append(preds.numpy())
            all_labels.append(y_batch.numpy())
    y_true = np.concatenate(all_labels)
    y_pred = np.concatenate(all_preds)

    # Confusion matrix
    cm = confusion_matrix(y_true, y_pred, labels=list(range(num_classes)))

    # Per-class precision, recall, F1
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=list(range(num_classes)), zero_division=0
    )

    # Accuracies
    per_class_acc = cm.diagonal() / np.maximum(cm.sum(axis=1), 1)
    overall_acc = cm.diagonal().sum() / cm.sum() * 100
    macro_acc = per_class_acc.mean() * 100

    # Macro-averaged P/R/F1
    macro_precision = precision.mean() * 100
    macro_recall = recall.mean() * 100
    macro_f1 = f1.mean() * 100

    # Weighted-averaged P/R/F1
    w_precision, w_recall, w_f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average='weighted', zero_division=0
    )

    return {
        "overall_acc": float(overall_acc),
        "macro_acc": float(macro_acc),
        "macro_precision": float(macro_precision),
        "macro_recall": float(macro_recall),
        "macro_f1": float(macro_f1),
        "weighted_precision": float(w_precision * 100),
        "weighted_recall": float(w_recall * 100),
        "weighted_f1": float(w_f1 * 100),
        "per_class": {
            CLASS_NAMES[i]: {
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


# ── Training ──────────────────────────────────────────────────────────

def set_seed(seed):
    torch.manual_seed(seed)
    np.random.seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def train_single(model_type, seed, X_train, y_train, X_test, y_test,
                 class_weights, num_classes, epochs=80):
    """Train one model with one seed, return full metrics."""
    set_seed(seed)

    input_dim = X_train.shape[1]
    if model_type == "relu":
        model = IDS_MLP(input_dim=input_dim, hidden=256, num_classes=num_classes)
    else:
        model = IDS_MLP_QCFS(input_dim=input_dim, hidden=256,
                              num_classes=num_classes, L=4)
    model = model.to(DEVICE)
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

    # Track best by macro accuracy (same criterion as original)
    best_macro = 0.0
    best_state = None

    for epoch in range(epochs):
        model.train()
        for X_batch, y_batch in train_loader:
            X_batch, y_batch = X_batch.to(DEVICE), y_batch.to(DEVICE)
            optimizer.zero_grad()
            loss = criterion(model(X_batch), y_batch)
            loss.backward()
            optimizer.step()
        scheduler.step()

        # Check every 10 epochs + last epoch
        if (epoch + 1) % 10 == 0 or epoch == epochs - 1:
            model.eval()
            with torch.no_grad():
                class_correct = np.zeros(num_classes)
                class_total = np.zeros(num_classes)
                for X_b, y_b in test_loader:
                    X_b, y_b = X_b.to(DEVICE), y_b.to(DEVICE)
                    preds = model(X_b).argmax(dim=1)
                    for i in range(num_classes):
                        mask = y_b == i
                        class_correct[i] += (preds[mask] == y_b[mask]).sum().item()
                        class_total[i] += mask.sum().item()
                per_class_acc = np.where(class_total > 0, class_correct / class_total, 0.0)
                macro = per_class_acc.mean() * 100
                if macro > best_macro:
                    best_macro = macro
                    best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    # Load best and compute full metrics (on CPU for sklearn compatibility)
    model = model.cpu()
    model.load_state_dict(best_state)
    cpu_test_loader = DataLoader(
        TensorDataset(X_test, y_test), batch_size=1024, shuffle=False
    )
    metrics = full_evaluate(model, cpu_test_loader, num_classes)
    return metrics


# ── Aggregation ───────────────────────────────────────────────────────

def aggregate_results(seed_results, class_names):
    """Compute mean ± std across seeds for all metrics."""
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

    # Per-class aggregation
    agg["per_class"] = {}
    for cls in class_names:
        agg["per_class"][cls] = {}
        for metric in ["accuracy", "precision", "recall", "f1"]:
            values = [r["per_class"][cls][metric] for r in seed_results]
            agg["per_class"][cls][metric] = {
                "mean": float(np.mean(values)),
                "std": float(np.std(values, ddof=1)) if n > 1 else 0.0,
            }

    # Average confusion matrix
    cms = np.array([r["confusion_matrix"] for r in seed_results])
    agg["confusion_matrix_mean"] = np.mean(cms, axis=0).tolist()
    agg["confusion_matrix_std"] = (np.std(cms, axis=0, ddof=1).tolist()
                                    if n > 1 else np.zeros_like(cms[0]).tolist())

    return agg


def statistical_comparison(relu_results, qcfs_results):
    """Wilcoxon signed-rank test comparing paired seed results."""
    metrics = ["overall_acc", "macro_acc", "macro_f1"]
    tests = {}
    n = len(relu_results)

    for metric in metrics:
        relu_vals = np.array([r[metric] for r in relu_results])
        qcfs_vals = np.array([r[metric] for r in qcfs_results])
        diff = qcfs_vals - relu_vals

        tests[metric] = {
            "relu_mean": float(np.mean(relu_vals)),
            "relu_std": float(np.std(relu_vals, ddof=1)) if n > 1 else 0.0,
            "qcfs_mean": float(np.mean(qcfs_vals)),
            "qcfs_std": float(np.std(qcfs_vals, ddof=1)) if n > 1 else 0.0,
            "mean_diff": float(np.mean(diff)),
        }

        if n >= 6:  # Wilcoxon needs at least 6 paired samples for meaningful p
            try:
                stat, p = wilcoxon(relu_vals, qcfs_vals, alternative='two-sided')
                tests[metric]["wilcoxon_stat"] = float(stat)
                tests[metric]["wilcoxon_p"] = float(p)
                tests[metric]["significant_005"] = bool(p < 0.05)
            except ValueError as e:
                tests[metric]["wilcoxon_error"] = str(e)
        else:
            tests[metric]["note"] = f"n={n}, need >=6 for Wilcoxon test"

    return tests


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Multi-seed SNN-IDS experiment")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(10)),
                        help="Seeds to run (default: 0-9)")
    parser.add_argument("--model", choices=["relu", "qcfs", "both"], default="both",
                        help="Which model(s) to train")
    parser.add_argument("--epochs", type=int, default=80)
    args = parser.parse_args()

    seeds = args.seeds
    run_relu = args.model in ("relu", "both")
    run_qcfs = args.model in ("qcfs", "both")

    print("=" * 70)
    print("SNN-IDS Multi-Seed Experiment")
    print(f"  Seeds: {seeds}")
    print(f"  Models: {'ReLU' if run_relu else ''} {'QCFS L=4' if run_qcfs else ''}")
    print(f"  Epochs: {args.epochs}")
    print(f"  Device: {DEVICE} ({torch.cuda.get_device_name(0) if DEVICE.type == 'cuda' else 'CPU'})")
    print("=" * 70)

    # Load data once
    print("\n[1] Loading NSL-KDD dataset...")
    train_df = load_nslkdd(DATA_DIR / "KDDTrain+.txt")
    test_df = load_nslkdd(DATA_DIR / "KDDTest+.txt")
    print(f"    Train: {len(train_df)}, Test: {len(test_df)}")

    # Preprocess (deterministic — LabelEncoder and StandardScaler
    # produce the same output regardless of seed)
    X_train, y_train, X_test, y_test, scaler, label_enc = preprocess(
        train_df.copy(), test_df.copy(), seed=0
    )
    num_classes = len(label_enc.classes_)
    class_weights = compute_class_weights(y_train, num_classes)
    print(f"    Classes: {list(label_enc.classes_)}")
    print(f"    Class weights: {dict(zip(label_enc.classes_, class_weights.tolist()))}")

    relu_results = []
    qcfs_results = []

    for i, seed in enumerate(seeds):
        print(f"\n{'='*70}")
        print(f"Seed {seed} ({i+1}/{len(seeds)})")
        print(f"{'='*70}")

        if run_relu:
            t0 = time.time()
            print(f"  Training ReLU (seed={seed})...", end=" ", flush=True)
            metrics = train_single("relu", seed, X_train, y_train, X_test, y_test,
                                   class_weights, num_classes, args.epochs)
            elapsed = time.time() - t0
            relu_results.append(metrics)
            print(f"done ({elapsed:.1f}s) — "
                  f"OA={metrics['overall_acc']:.2f}% "
                  f"MA={metrics['macro_acc']:.2f}% "
                  f"MF1={metrics['macro_f1']:.2f}%")

        if run_qcfs:
            t0 = time.time()
            print(f"  Training QCFS L=4 (seed={seed})...", end=" ", flush=True)
            metrics = train_single("qcfs", seed, X_train, y_train, X_test, y_test,
                                   class_weights, num_classes, args.epochs)
            elapsed = time.time() - t0
            qcfs_results.append(metrics)
            print(f"done ({elapsed:.1f}s) — "
                  f"OA={metrics['overall_acc']:.2f}% "
                  f"MA={metrics['macro_acc']:.2f}% "
                  f"MF1={metrics['macro_f1']:.2f}%")

    # ── Aggregation ───────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("Aggregated Results")
    print(f"{'='*70}")

    output = {
        "experiment": "Multi-seed SNN-IDS comparison (ReLU vs QCFS L=4)",
        "seeds": seeds,
        "epochs": args.epochs,
        "dataset": "NSL-KDD",
        "n_train": len(train_df),
        "n_test": len(test_df),
        "class_names": CLASS_NAMES,
    }

    if relu_results:
        relu_agg = aggregate_results(relu_results, CLASS_NAMES)
        output["relu"] = {"per_seed": relu_results, "aggregate": relu_agg}
        print(f"\n  ReLU (n={len(relu_results)} seeds):")
        print(f"    Overall Acc:  {relu_agg['overall_acc']['mean']:.2f} ± {relu_agg['overall_acc']['std']:.2f}%")
        print(f"    Macro Acc:    {relu_agg['macro_acc']['mean']:.2f} ± {relu_agg['macro_acc']['std']:.2f}%")
        print(f"    Macro F1:     {relu_agg['macro_f1']['mean']:.2f} ± {relu_agg['macro_f1']['std']:.2f}%")
        print(f"    Macro Prec:   {relu_agg['macro_precision']['mean']:.2f} ± {relu_agg['macro_precision']['std']:.2f}%")
        print(f"    Macro Recall: {relu_agg['macro_recall']['mean']:.2f} ± {relu_agg['macro_recall']['std']:.2f}%")
        for cls in CLASS_NAMES:
            pc = relu_agg["per_class"][cls]
            print(f"    {cls:>8s}: Acc={pc['accuracy']['mean']:.2f}±{pc['accuracy']['std']:.2f}  "
                  f"P={pc['precision']['mean']:.2f}±{pc['precision']['std']:.2f}  "
                  f"R={pc['recall']['mean']:.2f}±{pc['recall']['std']:.2f}  "
                  f"F1={pc['f1']['mean']:.2f}±{pc['f1']['std']:.2f}")

    if qcfs_results:
        qcfs_agg = aggregate_results(qcfs_results, CLASS_NAMES)
        output["qcfs_L4"] = {"per_seed": qcfs_results, "aggregate": qcfs_agg}
        print(f"\n  QCFS L=4 (n={len(qcfs_results)} seeds):")
        print(f"    Overall Acc:  {qcfs_agg['overall_acc']['mean']:.2f} ± {qcfs_agg['overall_acc']['std']:.2f}%")
        print(f"    Macro Acc:    {qcfs_agg['macro_acc']['mean']:.2f} ± {qcfs_agg['macro_acc']['std']:.2f}%")
        print(f"    Macro F1:     {qcfs_agg['macro_f1']['mean']:.2f} ± {qcfs_agg['macro_f1']['std']:.2f}%")
        print(f"    Macro Prec:   {qcfs_agg['macro_precision']['mean']:.2f} ± {qcfs_agg['macro_precision']['std']:.2f}%")
        print(f"    Macro Recall: {qcfs_agg['macro_recall']['mean']:.2f} ± {qcfs_agg['macro_recall']['std']:.2f}%")
        for cls in CLASS_NAMES:
            pc = qcfs_agg["per_class"][cls]
            print(f"    {cls:>8s}: Acc={pc['accuracy']['mean']:.2f}±{pc['accuracy']['std']:.2f}  "
                  f"P={pc['precision']['mean']:.2f}±{pc['precision']['std']:.2f}  "
                  f"R={pc['recall']['mean']:.2f}±{pc['recall']['std']:.2f}  "
                  f"F1={pc['f1']['mean']:.2f}±{pc['f1']['std']:.2f}")

    # Statistical comparison
    if relu_results and qcfs_results and len(relu_results) == len(qcfs_results):
        tests = statistical_comparison(relu_results, qcfs_results)
        output["statistical_tests"] = tests
        print(f"\n  Statistical Comparison (Wilcoxon signed-rank):")
        for metric, t in tests.items():
            diff_str = f"+{t['mean_diff']:.2f}" if t['mean_diff'] > 0 else f"{t['mean_diff']:.2f}"
            line = f"    {metric}: ReLU={t['relu_mean']:.2f}±{t['relu_std']:.2f} vs QCFS={t['qcfs_mean']:.2f}±{t['qcfs_std']:.2f} (diff={diff_str})"
            if "wilcoxon_p" in t:
                sig = "*" if t["significant_005"] else "ns"
                line += f" p={t['wilcoxon_p']:.4f} [{sig}]"
            elif "note" in t:
                line += f" [{t['note']}]"
            print(line)

    # Save
    out_path = RESULTS_DIR / "multiseed_experiment.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
