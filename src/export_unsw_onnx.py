"""
Export UNSW-NB15 ReLU MLP to ONNX + INT8 PTQ.
Uses the best model from seed 0 saved by experiment_unsw.py.

Usage:
    python src/export_unsw_onnx.py
"""

import torch
import torch.nn as nn
import numpy as np
import pandas as pd
import onnx
from pathlib import Path
from sklearn.preprocessing import LabelEncoder, StandardScaler
from onnxruntime.quantization import quantize_static, QuantType, CalibrationMethod

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
MODEL_DIR = BASE_DIR / "models"


class IDS_MLP(nn.Module):
    def __init__(self, input_dim=34, hidden=256, num_classes=10):
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


def fuse_bn(linear, bn):
    """Fuse BatchNorm into Linear layer."""
    w = linear.weight.data
    b = linear.bias.data if linear.bias is not None else torch.zeros(w.shape[0])
    mean = bn.running_mean
    var = bn.running_var
    gamma = bn.weight.data
    beta = bn.bias.data
    eps = bn.eps

    std = torch.sqrt(var + eps)
    fused_w = w * (gamma / std).unsqueeze(1)
    fused_b = (b - mean) * gamma / std + beta
    return fused_w, fused_b


class IDS_MLP_Fused(nn.Module):
    def __init__(self, input_dim=34, hidden=256, num_classes=10):
        super().__init__()
        self.fc1 = nn.Linear(input_dim, hidden)
        self.relu1 = nn.ReLU()
        self.fc2 = nn.Linear(hidden, hidden)
        self.relu2 = nn.ReLU()
        self.fc3 = nn.Linear(hidden, hidden // 2)
        self.relu3 = nn.ReLU()
        self.fc4 = nn.Linear(hidden // 2, num_classes)

    def forward(self, x):
        x = self.relu1(self.fc1(x))
        x = self.relu2(self.fc2(x))
        x = self.relu3(self.fc3(x))
        return self.fc4(x)


class CalibrationDataReader:
    def __init__(self, data, input_name="input"):
        self.data = data
        self.idx = 0
        self.input_name = input_name

    def get_next(self):
        if self.idx >= len(self.data):
            return None
        sample = self.data[self.idx:self.idx + 1]
        self.idx += 1
        return {self.input_name: sample}

    def rewind(self):
        self.idx = 0


def main():
    print("=" * 60)
    print("UNSW-NB15: ONNX Export + INT8 PTQ")
    print("=" * 60)

    # Load saved model
    pth_path = MODEL_DIR / "unsw_relu_best.pth"
    if not pth_path.exists():
        print(f"ERROR: {pth_path} not found. Run experiment_unsw.py first.")
        return

    state = torch.load(pth_path, weights_only=True)

    # Create model and load weights
    input_dim = 34
    num_classes = 10
    model = IDS_MLP(input_dim=input_dim, hidden=256, num_classes=num_classes)
    model.load_state_dict(state)
    model.eval()

    # Fuse BN
    print("\n[1] Fusing BatchNorm into Linear layers...")
    fused = IDS_MLP_Fused(input_dim=input_dim, hidden=256, num_classes=num_classes)

    layers_bn = model.layers
    w1, b1 = fuse_bn(layers_bn[0], layers_bn[1])
    w2, b2 = fuse_bn(layers_bn[3], layers_bn[4])
    w3, b3 = fuse_bn(layers_bn[6], layers_bn[7])
    w4, b4 = layers_bn[9].weight.data, layers_bn[9].bias.data

    fused.fc1.weight.data, fused.fc1.bias.data = w1, b1
    fused.fc2.weight.data, fused.fc2.bias.data = w2, b2
    fused.fc3.weight.data, fused.fc3.bias.data = w3, b3
    fused.fc4.weight.data, fused.fc4.bias.data = w4, b4
    fused.eval()

    # Verify
    dummy = torch.randn(1, input_dim)
    with torch.no_grad():
        out_orig = model(dummy)
        out_fused = fused(dummy)
    diff = (out_orig - out_fused).abs().max().item()
    print(f"  Max fusion error: {diff:.2e}")

    # Export ONNX
    onnx_path = MODEL_DIR / "unsw_model.onnx"
    print(f"\n[2] Exporting ONNX to {onnx_path}...")
    torch.onnx.export(
        fused, dummy,
        str(onnx_path),
        input_names=["input"],
        output_names=["output"],
        opset_version=17,
        dynamic_axes=None,
    )
    print(f"  Size: {onnx_path.stat().st_size / 1024:.1f} KB")

    # Verify ONNX ops
    m = onnx.load(str(onnx_path))
    ops = sorted(set(n.op_type for n in m.graph.node))
    print(f"  Operators: {ops}")

    # Load calibration data (must match experiment_unsw.py preprocessing)
    print("\n[3] Loading calibration data...")
    train_df = pd.read_parquet(DATA_DIR / "UNSW_NB15_training-set.parquet")
    test_df = pd.read_parquet(DATA_DIR / "UNSW_NB15_testing-set.parquet")
    for col in ["id"]:
        if col in train_df.columns:
            train_df = train_df.drop(columns=[col])
            test_df = test_df.drop(columns=[col])
    train_df = train_df.drop(columns=["attack_cat", "label"])
    test_df = test_df.drop(columns=["attack_cat", "label"])

    # Fit LabelEncoder on concat(train, test) to match training pipeline
    cat_cols = train_df.select_dtypes(include=["object", "category"]).columns.tolist()
    for col in cat_cols:
        le = LabelEncoder()
        combined = pd.concat([train_df[col].astype(str), test_df[col].astype(str)])
        le.fit(combined)
        train_df[col] = le.transform(train_df[col].astype(str))

    X_train = train_df.values.astype(np.float32)
    X_train = np.nan_to_num(X_train, nan=0.0, posinf=1e6, neginf=-1e6)
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)

    rng = np.random.RandomState(42)
    idx = rng.choice(len(X_train), size=1000, replace=False)
    cal_data = X_train[idx].astype(np.float32)
    print(f"  Calibration samples: {len(cal_data)}")

    # INT8 PTQ
    int8_path = MODEL_DIR / "unsw_model_int8.onnx"
    print(f"\n[4] INT8 quantization...")
    reader = CalibrationDataReader(cal_data, input_name="input")
    quantize_static(
        model_input=str(onnx_path),
        model_output=str(int8_path),
        calibration_data_reader=reader,
        quant_format=QuantType.QInt8,
        calibrate_method=CalibrationMethod.MinMax,
        per_channel=False,
        weight_type=QuantType.QInt8,
        activation_type=QuantType.QInt8,
    )
    print(f"  INT8 size: {int8_path.stat().st_size / 1024:.1f} KB")
    print(f"  FP32 size: {onnx_path.stat().st_size / 1024:.1f} KB")

    int8_m = onnx.load(str(int8_path))
    int8_ops = sorted(set(n.op_type for n in int8_m.graph.node))
    print(f"  INT8 operators: {int8_ops}")

    print(f"\n  Upload {int8_path.name} to stedgeai-dc.st.com for NPU benchmark.")
    print(f"  Also upload {onnx_path.name} for FP32 comparison.")
    print("  Done.")


if __name__ == "__main__":
    main()
