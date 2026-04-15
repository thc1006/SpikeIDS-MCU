"""
Focal loss ablation experiment for NCA paper.
Tests whether focal loss improves minority class performance.

Focal Loss: FL(p_t) = -alpha_t * (1-p_t)^gamma * log(p_t)
  gamma=0: uses nn.CrossEntropyLoss(weight=cw) directly (standard weighted CE)
  gamma=1,2,3: progressively down-weights easy examples via FocalLoss class

Expected finding: marginal improvement — data scarcity (52 U2R samples
in 41D) is the bottleneck, not loss function design.

Usage:
    python src/experiment_focal.py
    python src/experiment_focal.py --gammas 0 2
    python src/experiment_focal.py --seeds 0 1 2
"""

import argparse
import json
import time
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import numpy as np
from pathlib import Path
from metrics import full_evaluate as compute_all_metrics
from config import NSL_CLASS_NAMES
from models import IDS_MLP
from train_utils import set_seed, compute_class_weights
from data_loaders import load_nslkdd as _load_nslkdd_shared
from data_loaders import load_unsw as _load_unsw_shared

import warnings
warnings.filterwarnings("ignore", message=".*NVIDIA GB10.*not compatible.*")
warnings.filterwarnings("ignore", message=".*Found GPU0 NVIDIA GB10.*")

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


# ── Focal Loss ────────────────────────────────────────────────────────

class FocalLoss(nn.Module):
    """Focal loss with per-class alpha weights.

    FL(p_t) = -alpha_t * (1-p_t)^gamma * log(p_t)

    Note: FocalLoss(gamma=0) uses mean() normalization, which differs
    from nn.CrossEntropyLoss(weight=...) normalization. The train_single()
    function handles this by using nn.CrossEntropyLoss directly for gamma=0.
    """
    def __init__(self, alpha, gamma=2.0):
        super().__init__()
        self.register_buffer("alpha", alpha)
        self.gamma = gamma

    def forward(self, logits, targets):
        ce_loss = F.cross_entropy(logits, targets, reduction='none')
        pt = torch.exp(-ce_loss)
        alpha_t = self.alpha[targets]
        focal_loss = alpha_t * (1 - pt) ** self.gamma * ce_loss
        return focal_loss.mean()


# ── Data + Model ──────────────────────────────────────────────────────

def load_nslkdd():
    """Load NSL-KDD via shared data_loaders, return torch tensors + class_names."""
    X_train, y_train, X_test, y_test, scaler, label_enc = _load_nslkdd_shared(DATA_DIR)
    return (torch.tensor(X_train, dtype=torch.float32),
            torch.tensor(y_train, dtype=torch.long),
            torch.tensor(X_test, dtype=torch.float32),
            torch.tensor(y_test, dtype=torch.long),
            NSL_CLASS_NAMES)


def load_unsw():
    """Load UNSW-NB15 via shared data_loaders, return torch tensors + class_names."""
    X_train, y_train, X_test, y_test, scaler, label_enc, feature_names = _load_unsw_shared(DATA_DIR)
    return (torch.tensor(X_train, dtype=torch.float32),
            torch.tensor(y_train, dtype=torch.long),
            torch.tensor(X_test, dtype=torch.float32),
            torch.tensor(y_test, dtype=torch.long),
            list(label_enc.classes_))


def train_single(gamma, seed, X_train, y_train, X_test, y_test,
                 class_weights, num_classes, class_names, epochs=80):
    set_seed(seed)
    input_dim = X_train.shape[1]
    model = IDS_MLP(input_dim, 256, num_classes).to(DEVICE)
    cw = class_weights.to(DEVICE)

    train_loader = DataLoader(
        TensorDataset(X_train, y_train), batch_size=512, shuffle=True,
        generator=torch.Generator().manual_seed(seed)
    )

    if gamma == 0:
        criterion = nn.CrossEntropyLoss(weight=cw)
    else:
        criterion = FocalLoss(alpha=cw, gamma=gamma)

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
                test_loader = DataLoader(
                    TensorDataset(X_test.to(DEVICE), y_test.to(DEVICE)),
                    batch_size=1024, shuffle=False
                )
                for X_b, y_b in test_loader:
                    preds = model(X_b).argmax(dim=1)
                    for i in range(num_classes):
                        mask = y_b == i
                        correct[i] += (preds[mask] == y_b[mask]).sum().item()
                        total[i] += mask.sum().item()
                macro = np.where(total > 0, correct / total, 0.0).mean() * 100
                if macro > best_macro:
                    best_macro = macro
                    best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    model = model.cpu()
    model.load_state_dict(best_state)
    model.eval()

    cpu_loader = DataLoader(TensorDataset(X_test, y_test), batch_size=1024, shuffle=False)
    all_preds, all_labels, all_probs = [], [], []
    with torch.no_grad():
        for X_b, y_b in cpu_loader:
            logits = model(X_b)
            all_preds.append(logits.argmax(dim=1).numpy())
            all_labels.append(y_b.numpy())
            all_probs.append(torch.softmax(logits, dim=1).numpy())

    y_true = np.concatenate(all_labels)
    y_pred = np.concatenate(all_preds)
    y_prob = np.concatenate(all_probs)
    return compute_all_metrics(y_true, y_pred, y_prob, num_classes, class_names)


def aggregate(seed_results, class_names):
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
            "values": values,
        }
    for auc_key in ["roc_auc_macro", "roc_auc_weighted"]:
        values = [r[auc_key] for r in seed_results if r[auc_key] is not None]
        if values:
            agg[auc_key] = {"mean": float(np.mean(values)),
                            "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0}
        else:
            agg[auc_key] = {"mean": None, "std": None}
    agg["per_class"] = {}
    for cls in class_names:
        agg["per_class"][cls] = {}
        for m in ["accuracy", "precision", "recall", "f1", "fpr", "fnr"]:
            values = [r["per_class"][cls][m] for r in seed_results]
            agg["per_class"][cls][m] = {
                "mean": float(np.mean(values)),
                "std": float(np.std(values, ddof=1)) if n > 1 else 0.0,
            }
    return agg


def main():
    parser = argparse.ArgumentParser(description="Focal loss ablation")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(10)))
    parser.add_argument("--gammas", type=float, nargs="+", default=[0, 1, 2, 3])
    parser.add_argument("--epochs", type=int, default=80)
    args = parser.parse_args()

    print("=" * 70)
    print("Focal Loss Ablation Experiment")
    print(f"  Gammas: {args.gammas}")
    print(f"  Seeds: {args.seeds}")
    print(f"  Device: {DEVICE}")
    print("=" * 70)

    datasets = {}

    print("\n[1] Loading NSL-KDD...")
    X_tr, y_tr, X_te, y_te, cn = load_nslkdd()
    cw = compute_class_weights(y_tr, len(cn))
    datasets["nslkdd"] = {
        "X_train": X_tr, "y_train": y_tr, "X_test": X_te, "y_test": y_te,
        "class_names": cn, "num_classes": len(cn), "class_weights": cw,
    }

    print("[2] Loading UNSW-NB15...")
    X_tr, y_tr, X_te, y_te, cn = load_unsw()
    cw = compute_class_weights(y_tr, len(cn))
    datasets["unsw"] = {
        "X_train": X_tr, "y_train": y_tr, "X_test": X_te, "y_test": y_te,
        "class_names": cn, "num_classes": len(cn), "class_weights": cw,
    }

    output = {"experiment": "Focal loss ablation",
              "gammas": args.gammas, "seeds": args.seeds, "epochs": args.epochs}

    for ds_name, ds in datasets.items():
        print(f"\n{'='*70}")
        print(f"Dataset: {ds_name}")
        print(f"{'='*70}")
        output[ds_name] = {}

        for gamma in args.gammas:
            gamma_key = f"gamma_{gamma:.0f}" if gamma == int(gamma) else f"gamma_{gamma}"
            print(f"\n  Focal Loss gamma={gamma} {'(= weighted CE)' if gamma == 0 else ''}")
            seed_results = []

            for seed in args.seeds:
                t0 = time.time()
                metrics = train_single(
                    gamma, seed,
                    ds["X_train"], ds["y_train"],
                    ds["X_test"], ds["y_test"],
                    ds["class_weights"], ds["num_classes"],
                    ds["class_names"], args.epochs
                )
                elapsed = time.time() - t0
                seed_results.append(metrics)
                print(f"    seed={seed}: OA={metrics['overall_acc']:.2f}% "
                      f"MA={metrics['macro_acc']:.2f}% "
                      f"MF1={metrics['macro_f1']:.2f}% ({elapsed:.1f}s)")

            agg = aggregate(seed_results, ds["class_names"])
            output[ds_name][gamma_key] = {
                "gamma": gamma,
                "per_seed": seed_results,
                "aggregate": agg,
            }
            print(f"    => OA={agg['overall_acc']['mean']:.2f}±{agg['overall_acc']['std']:.2f}% "
                  f"MA={agg['macro_acc']['mean']:.2f}±{agg['macro_acc']['std']:.2f}% "
                  f"MF1={agg['macro_f1']['mean']:.2f}±{agg['macro_f1']['std']:.2f}%")

            # Highlight minority classes
            minority = ["R2L", "U2R"] if ds_name == "nslkdd" else ["Worms", "Analysis", "Backdoor"]
            for cls in minority:
                if cls in agg["per_class"]:
                    pc = agg["per_class"][cls]
                    print(f"       {cls}: R={pc['recall']['mean']:.1f}±{pc['recall']['std']:.1f}% "
                          f"F1={pc['f1']['mean']:.1f}±{pc['f1']['std']:.1f}%")

    out_path = RESULTS_DIR / "focal_experiment.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
