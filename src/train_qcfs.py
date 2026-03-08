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
  - "Optimal ANN-SNN Conversion" (arXiv:2205.13055, ICML 2023)
  - "One Timestep is Enough" (arXiv:2510.23383, 2025)
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

# --- Reuse data loading from train.py ---
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


def load_nslkdd(path):
    df = pd.read_csv(path, header=None, names=COL_NAMES)
    df.drop(columns=["difficulty"], inplace=True)
    df["label"] = df["label"].map(ATTACK_MAP).fillna("unknown")
    df = df[df["label"] != "unknown"]
    return df


def preprocess(train_df, test_df):
    cat_cols = ["protocol_type", "service", "flag"]
    for col in cat_cols:
        le = LabelEncoder()
        combined = pd.concat([train_df[col], test_df[col]])
        le.fit(combined)
        train_df[col] = le.transform(train_df[col])
        test_df[col] = le.transform(test_df[col])

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


class FloorSTE(torch.autograd.Function):
    """Floor with Straight-Through Estimator gradient."""
    @staticmethod
    def forward(ctx, x):
        return torch.floor(x)

    @staticmethod
    def backward(ctx, grad_output):
        return grad_output  # STE: pass gradient through unchanged


class QCFS(nn.Module):
    """
    Quantization-Clip-Floor-Shift activation.
    QCFS(x) = floor( clip(x / step, 0, L) ) * step

    At T=1: equivalent to uniform INT quantization with L levels.
    The threshold (and thus step) is learnable.
    """
    def __init__(self, L=8, init_threshold=1.0):
        super().__init__()
        self.register_buffer("L", torch.tensor(float(L)))
        # Learnable threshold parameter (per-layer scalar)
        self.threshold = nn.Parameter(torch.tensor(float(init_threshold)))

    def forward(self, x):
        step = self.threshold / self.L
        # Clip to [0, L], then floor (with STE), then scale back
        x_scaled = x / (step + 1e-8)
        x_clipped = torch.clamp(x_scaled, 0.0, self.L.item())
        x_floored = FloorSTE.apply(x_clipped)
        return x_floored * step

    def extra_repr(self):
        return f"L={self.L}, threshold={self.threshold.item():.4f}"


class IDS_MLP_QCFS(nn.Module):
    """
    Same architecture as IDS_MLP but with QCFS activation instead of ReLU.
    ONNX operators: Linear(Gemm) + Div + Clip + Floor + Mul
    The question: will Floor and Div be NPU-mapped or CPU-fallback?
    """
    def __init__(self, input_dim=41, hidden=256, num_classes=5, L=8):
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

    L_VALUES = [4, 8, 16]  # Test multiple quantization levels

    print("=" * 60)
    print("SNN-IDS Path A: QCFS Comparison Experiment")
    print("=" * 60)

    print("\n[1/3] Loading NSL-KDD dataset...")
    train_df = load_nslkdd(DATA_DIR / "KDDTrain+.txt")
    test_df = load_nslkdd(DATA_DIR / "KDDTest+.txt")

    X_train, y_train, X_test, y_test, scaler, label_enc = preprocess(
        train_df.copy(), test_df.copy()
    )
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


def export_qcfs_onnx(model, input_dim, L):
    """Export QCFS model to ONNX (WITHOUT BN fusion, to preserve QCFS operators)."""
    model.eval()
    dummy = torch.randn(1, input_dim)

    onnx_path = MODEL_DIR / f"ids_qcfs_L{L}.onnx"
    torch.onnx.export(
        model,
        dummy,
        str(onnx_path),
        input_names=["input"],
        output_names=["output"],
        dynamic_axes=None,
        opset_version=17,
    )
    print(f"\n  ONNX exported: {onnx_path} ({onnx_path.stat().st_size / 1024:.1f} KB)")

    # Check operators
    import onnx
    onnx_model = onnx.load(str(onnx_path))
    onnx.checker.check_model(onnx_model)
    ops = set()
    for node in onnx_model.graph.node:
        ops.add(node.op_type)
    print(f"  ONNX operators: {sorted(ops)}")

    npu_supported = {"Gemm", "MatMul", "Relu", "Add", "Clip", "Mul", "BatchNormalization",
                     "QuantizeLinear", "DequantizeLinear"}
    npu_uncertain = {"Floor", "Div"}
    print(f"  Neural-ART compatibility:")
    for op in sorted(ops):
        if op in npu_supported:
            status = "NPU (confirmed)"
        elif op in npu_uncertain:
            status = "UNCERTAIN (may CPU fallback)"
        else:
            status = "unknown"
        print(f"    {op}: {status}")


if __name__ == "__main__":
    train()
