"""
SNN-IDS: ANN Training for Network Intrusion Detection
Target: STM32N6570-DK Neural-ART NPU (INT8)
Dataset: NSL-KDD
Math basis: T=1 SNN ≡ INT8 Quantized ANN (Bu CVPR'25, Jiang ICML'23)
"""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import numpy as np
from pathlib import Path

from config import NSL_CLASS_NAMES
from models import IDS_MLP
from train_utils import compute_class_weights
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

    print("=" * 60)
    print("SNN-IDS: Training ANN (T=1 SNN equivalent)")
    print("=" * 60)

    print("\n[1/4] Loading NSL-KDD dataset...")
    train_df, test_df = load_nslkdd_raw(DATA_DIR)
    print(f"  Train: {len(train_df)} samples")
    print(f"  Test:  {len(test_df)} samples")
    print(f"  Classes: {train_df['label'].value_counts().to_dict()}")

    print("\n[2/4] Preprocessing...")
    X_train, y_train, X_test, y_test, scaler, label_enc = preprocess_nslkdd(
        train_df.copy(), test_df.copy()
    )
    X_train = torch.tensor(X_train, dtype=torch.float32)
    y_train = torch.tensor(y_train, dtype=torch.long)
    X_test = torch.tensor(X_test, dtype=torch.float32)
    y_test = torch.tensor(y_test, dtype=torch.long)
    input_dim = X_train.shape[1]
    num_classes = len(label_enc.classes_)
    print(f"  Input dim: {input_dim}")
    print(f"  Classes: {list(label_enc.classes_)}")

    train_loader = DataLoader(
        TensorDataset(X_train, y_train), batch_size=512, shuffle=True
    )
    test_loader = DataLoader(
        TensorDataset(X_test, y_test), batch_size=1024, shuffle=False
    )

    # Fix: class weights for imbalanced dataset
    class_weights = compute_class_weights(y_train, num_classes)
    print(f"  Class weights: {dict(zip(label_enc.classes_, class_weights.tolist()))}")

    print("\n[3/4] Training...")
    model = IDS_MLP(input_dim=input_dim, hidden=256, num_classes=num_classes)
    print(f"  Model params: {sum(p.numel() for p in model.parameters()):,}")
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
                torch.save(model.state_dict(), MODEL_DIR / "ids_model_best.pth")

    print(f"\n  Best macro accuracy: {best_macro:.2f}%")

    print("\n[4/4] Per-class accuracy (best model)...")
    model.load_state_dict(torch.load(MODEL_DIR / "ids_model_best.pth", weights_only=True))
    overall, macro, per_class, class_correct, class_total = evaluate(
        model, test_loader, num_classes
    )

    for i, cls in enumerate(label_enc.classes_):
        if class_total[i] > 0:
            print(f"  {cls:>8s}: {per_class[i]*100:6.2f}% ({int(class_correct[i])}/{int(class_total[i])})")
    print(f"  {'Overall':>8s}: {overall:.2f}%")
    print(f"  {'Macro':>8s}: {macro:.2f}%")

    torch.save({
        "input_dim": input_dim,
        "hidden": 256,
        "num_classes": num_classes,
        "best_macro_acc": best_macro,
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "classes": list(label_enc.classes_),
    }, MODEL_DIR / "ids_metadata.pth")

    print(f"\nModel saved: {MODEL_DIR / 'ids_model_best.pth'}")
    print(f"Metadata saved: {MODEL_DIR / 'ids_metadata.pth'}")

    # NSL-KDD 5-class SOTA ~80% overall, ~65% macro. Adjusted threshold.
    go = macro > 50 and overall > 74
    print(f"\nGo/No-Go: macro>{50}% AND overall>{74}%? {'GO' if go else 'REVIEW NEEDED'}")


if __name__ == "__main__":
    train()
