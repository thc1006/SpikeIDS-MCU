"""
Export CICIDS2017 ReLU MLP to ONNX + INT8 PTQ.
Uses the best model from seed 0 saved by experiment_cicids2017.py.

Usage:
    python src/export_cicids_onnx.py
    python src/export_cicids_onnx.py --grouped   # 7-class version
"""

import argparse
import torch
import numpy as np
import pandas as pd
import onnx
from pathlib import Path
from sklearn.preprocessing import LabelEncoder, StandardScaler
from onnxruntime.quantization import quantize_static, QuantType, CalibrationMethod

from models import IDS_MLP, IDS_MLP_Fused, fuse_bn
from quantize_utils import CalibrationDataReader

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
CICIDS_DIR = DATA_DIR / "cicids2017"
MODEL_DIR = BASE_DIR / "models"


def load_cicids_train_data(grouped=False):
    """Load CICIDS2017 training data for calibration.

    Replicates the exact preprocessing from experiment_cicids2017.py:
    train_test_split(random_state=42) then scaler fit on train only.
    """
    from experiment_cicids2017 import load_cicids2017
    from sklearn.model_selection import train_test_split

    df, labels = load_cicids2017(grouped=grouped)

    # Drop non-numeric
    non_numeric = df.select_dtypes(exclude=[np.number]).columns.tolist()
    if non_numeric:
        df = df.drop(columns=non_numeric)

    X = df.values.astype(np.float32)
    X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

    # Replicate the same train/test split as the experiment
    X_train, _, _, _ = train_test_split(
        X, labels, test_size=0.2, random_state=42, stratify=labels
    )

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)

    return X_train, df.shape[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grouped", action="store_true")
    args = parser.parse_args()

    suffix = "_grouped" if args.grouped else ""
    label_mode = "7-class grouped" if args.grouped else "15-class"

    print("=" * 60)
    print(f"CICIDS2017: ONNX Export + INT8 PTQ ({label_mode})")
    print("=" * 60)

    # Load saved model (experiment always saves as cicids_relu_best.pth)
    pth_path = MODEL_DIR / "cicids_relu_best.pth"
    if not pth_path.exists():
        print(f"ERROR: {pth_path} not found. Run experiment_cicids2017.py first.")
        return

    state = torch.load(pth_path, weights_only=True)

    # Infer dimensions from state dict
    input_dim = state['layers.0.weight'].shape[1]
    num_classes = state['layers.9.weight'].shape[0]
    print(f"  Input dim: {input_dim}, Classes: {num_classes}")

    # Create model and load weights
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
    onnx_path = MODEL_DIR / f"cicids_model{suffix}.onnx"
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

    # Verify ONNX
    m = onnx.load(str(onnx_path))
    onnx.checker.check_model(m)
    ops = sorted(set(n.op_type for n in m.graph.node))
    print(f"  Operators: {ops}")
    print(f"  ONNX checker: OK")

    # Load calibration data
    print("\n[3] Loading calibration data...")
    X_train, _ = load_cicids_train_data(grouped=args.grouped)

    rng = np.random.RandomState(42)
    idx = rng.choice(len(X_train), size=min(1000, len(X_train)), replace=False)
    cal_data = X_train[idx].astype(np.float32)
    print(f"  Calibration samples: {len(cal_data)}")

    # INT8 PTQ
    int8_path = MODEL_DIR / f"cicids_model{suffix}_int8.onnx"
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
