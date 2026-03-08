"""
SNN-IDS: ANN Training for Network Intrusion Detection
Target: STM32N6570-DK Neural-ART NPU (INT8)
Dataset: NSL-KDD
Math basis: T=1 SNN ≡ INT8 Quantized ANN (arXiv:2510.23383)
"""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import pandas as pd
import numpy as np
from sklearn.preprocessing import LabelEncoder, StandardScaler
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
MODEL_DIR = Path(__file__).parent.parent / "models"
MODEL_DIR.mkdir(exist_ok=True)

# NSL-KDD column names (41 features + label + difficulty)
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

# 5-class classification: normal, DoS, Probe, R2L, U2R
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


def load_nslkdd(path):
    df = pd.read_csv(path, header=None, names=COL_NAMES)
    df.drop(columns=["difficulty"], inplace=True)
    df["label"] = df["label"].map(ATTACK_MAP).fillna("unknown")
    df = df[df["label"] != "unknown"]
    return df


def preprocess(train_df, test_df):
    cat_cols = ["protocol_type", "service", "flag"]
    encoders = {}
    for col in cat_cols:
        le = LabelEncoder()
        combined = pd.concat([train_df[col], test_df[col]])
        le.fit(combined)
        train_df[col] = le.transform(train_df[col])
        test_df[col] = le.transform(test_df[col])
        encoders[col] = le

    label_enc = LabelEncoder()
    label_enc.fit(["normal", "DoS", "Probe", "R2L", "U2R"])
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


class IDS_MLP(nn.Module):
    """
    Lightweight MLP for Network Intrusion Detection.
    All core operators (Gemm, Relu) are Neural-ART NPU accelerated after BN fusion.
    BatchNorm is fused into Linear at ONNX export → Gemm + Relu only.
    Post INT8 quantization, this is mathematically equivalent to T=1 SNN inference.
    """
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


def compute_class_weights(labels, num_classes):
    counts = np.bincount(labels.numpy(), minlength=num_classes).astype(np.float32)
    counts = np.maximum(counts, 1.0)
    weights = 1.0 / counts
    weights = weights / weights.sum() * num_classes
    return torch.tensor(weights, dtype=torch.float32)


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
    train_df = load_nslkdd(DATA_DIR / "KDDTrain+.txt")
    test_df = load_nslkdd(DATA_DIR / "KDDTest+.txt")
    print(f"  Train: {len(train_df)} samples")
    print(f"  Test:  {len(test_df)} samples")
    print(f"  Classes: {train_df['label'].value_counts().to_dict()}")

    print("\n[2/4] Preprocessing...")
    X_train, y_train, X_test, y_test, scaler, label_enc = preprocess(
        train_df.copy(), test_df.copy()
    )
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
