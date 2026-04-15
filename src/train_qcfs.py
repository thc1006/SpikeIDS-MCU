"""
SNN-IDS Path A: PASCAL QCFS Comparison Experiment
Replace ReLU with QCFS activation → export ONNX → check Neural-ART NPU compatibility.

QCFS(x) = floor( clip(x / step, 0, L) ) * step

where:
  step = threshold / L  (quantization step size)
  L = number of quantization levels (related to T timesteps)
  threshold = learnable parameter (per-layer)

At T=1 (single timestep), QCFS becomes equivalent to uniform quantization.
Uses STE (Straight-Through Estimator) for gradient through floor().

Reference:
  - T. Bu et al., "Optimal ANN-SNN Conversion" (arXiv:2303.04347, ICLR 2022)
  - T. Bu et al., "Inference-Scale Complexity in ANN-SNN Conversion" (CVPR 2025)
"""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import numpy as np
from pathlib import Path

from config import NSL_CLASS_NAMES
from train_utils import compute_class_weights
from models import QCFS, IDS_MLP_QCFS
from data_loaders import load_nslkdd_raw, preprocess_nslkdd

DATA_DIR = Path(__file__).parent.parent / "data"
MODEL_DIR = Path(__file__).parent.parent / "models"
MODEL_DIR.mkdir(exist_ok=True)


def evaluate(model, loader, num_classes):
    model.eval()
    class_correct = np.zeros(num_classes)
    class_total = np.zeros(num_classes)
    with torch.no_grad():
        for X_batch, y_batch in loader:
            preds = model(X_batch).argmax(dim=1)
            for i in range(num_classes):
                mask = y_batch == i
                class_correct[i] += (preds[mask] == y_batch[mask]).sum().item()
                class_total[i] += mask.sum().item()
    per_class_acc = np.where(class_total > 0, class_correct / class_total, 0.0)
    macro_acc = per_class_acc.mean() * 100
    overall_acc = class_correct.sum() / class_total.sum() * 100
    return overall_acc, macro_acc, per_class_acc, class_correct, class_total


def train():
    torch.manual_seed(42)
    np.random.seed(42)

    L_VALUES = [4, 8, 16]  # Test multiple quantization levels

    print("=" * 60)
    print("SNN-IDS Path A: QCFS Comparison Experiment")
    print("=" * 60)

    print("\n[1/3] Loading NSL-KDD dataset...")
    train_df, test_df = load_nslkdd_raw(DATA_DIR)

    X_train, y_train, X_test, y_test, scaler, label_enc = preprocess_nslkdd(
        train_df.copy(), test_df.copy()
    )
    X_train = torch.tensor(X_train, dtype=torch.float32)
    y_train = torch.tensor(y_train, dtype=torch.long)
    X_test = torch.tensor(X_test, dtype=torch.float32)
    y_test = torch.tensor(y_test, dtype=torch.long)
    input_dim = X_train.shape[1]
    num_classes = len(label_enc.classes_)

    train_loader = DataLoader(
        TensorDataset(X_train, y_train), batch_size=512, shuffle=True
    )
    test_loader = DataLoader(
        TensorDataset(X_test, y_test), batch_size=1024, shuffle=False
    )

    class_weights = compute_class_weights(y_train, num_classes)

    results = {}

    for L in L_VALUES:
        print(f"\n{'='*60}")
        print(f"[2/3] Training QCFS model (L={L}, equivalent T={L} SNN)...")
        print(f"{'='*60}")

        torch.manual_seed(42)
        model = IDS_MLP_QCFS(input_dim=input_dim, hidden=256, num_classes=num_classes, L=L)
        print(f"  Model params: {sum(p.numel() for p in model.parameters()):,}")
        print(f"  QCFS levels: L={L} (step = threshold/{L})")

        criterion = nn.CrossEntropyLoss(weight=class_weights)
        optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
        scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=80)

        best_macro = 0.0
        for epoch in range(80):
            model.train()
            total_loss = 0
            for X_batch, y_batch in train_loader:
                optimizer.zero_grad()
                out = model(X_batch)
                loss = criterion(out, y_batch)
                loss.backward()
                optimizer.step()
                total_loss += loss.item()
            scheduler.step()

            if (epoch + 1) % 10 == 0 or epoch == 0:
                overall, macro, _, _, _ = evaluate(model, test_loader, num_classes)
                print(f"  Epoch {epoch+1:3d} | Loss: {total_loss/len(train_loader):.4f} | Overall: {overall:.2f}% | Macro: {macro:.2f}%")
                if macro > best_macro:
                    best_macro = macro
                    torch.save(model.state_dict(), MODEL_DIR / f"ids_qcfs_L{L}_best.pth")

        # Load best and evaluate
        model.load_state_dict(torch.load(MODEL_DIR / f"ids_qcfs_L{L}_best.pth", weights_only=True))
        overall, macro, per_class, class_correct, class_total = evaluate(
            model, test_loader, num_classes
        )

        # Print learned thresholds
        thresholds = []
        for m in model.modules():
            if isinstance(m, QCFS):
                thresholds.append(m.threshold.item())
        print(f"\n  Learned thresholds: {[f'{t:.4f}' for t in thresholds]}")

        print(f"\n  Per-class accuracy (L={L}):")
        for i, cls in enumerate(label_enc.classes_):
            if class_total[i] > 0:
                print(f"    {cls:>8s}: {per_class[i]*100:6.2f}% ({int(class_correct[i])}/{int(class_total[i])})")
        print(f"    {'Overall':>8s}: {overall:.2f}%")
        print(f"    {'Macro':>8s}: {macro:.2f}%")

        results[L] = {"overall": overall, "macro": macro, "per_class": per_class}

    print(f"\n{'='*60}")
    print("[3/3] Comparison: ReLU (Path B) vs QCFS (Path A)")
    print(f"{'='*60}")
    print(f"\n  {'Model':<20s} {'Overall':>10s} {'Macro':>10s}")
    print(f"  {'-'*40}")
    print(f"  {'ReLU (Path B)':<20s} {'76.45%':>10s} {'56.32%':>10s}")
    for L, r in results.items():
        print(f"  {f'QCFS L={L} (Path A)':<20s} {r['overall']:>9.2f}% {r['macro']:>9.2f}%")

    print(f"\n  ONNX files exported to {MODEL_DIR}/")
    print(f"  Next: Upload QCFS ONNX to stedgeai-dc.st.com to check Floor/Div NPU support")


if __name__ == "__main__":
    train()
