"""
Export baseline models (LogReg, MLP 64-64, MLP 128-64) to ONNX + INT8 PTQ.
Retrains with seed 0 and exports for each dataset.

Usage:
    python src/export_baselines_onnx.py
"""

import torch
import torch.nn as nn
import numpy as np
import onnx
from pathlib import Path
from onnxruntime.quantization import quantize_static, QuantType, CalibrationMethod

from models import fuse_bn, FusedFlexMLP
from quantize_utils import CalibrationDataReader

BASE_DIR = Path(__file__).parent.parent
MODEL_DIR = BASE_DIR / "models"
MODEL_DIR.mkdir(exist_ok=True)

# Import from experiment_baselines
import sys
sys.path.insert(0, str(Path(__file__).parent))
from experiment_baselines import (
    FlexMLP, MODEL_CONFIGS, load_nslkdd, load_unsw,
    compute_class_weights, set_seed, DEVICE
)

import warnings
warnings.filterwarnings("ignore", message=".*NVIDIA GB10.*")


def train_and_export(config_name, dataset_name, X_train, y_train, num_classes,
                     class_weights, input_dim, seed=0, epochs=80):
    """Train model with seed 0, fuse BN, export ONNX + INT8."""
    cfg = MODEL_CONFIGS[config_name]
    hidden = cfg["hidden_layers"]

    print(f"\n  [{config_name}] Training on {dataset_name} (seed={seed})...")
    set_seed(seed)

    model = FlexMLP(input_dim, hidden, num_classes).to(DEVICE)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    criterion = nn.CrossEntropyLoss(weight=class_weights.to(DEVICE))

    loader = torch.utils.data.DataLoader(
        torch.utils.data.TensorDataset(X_train, y_train),
        batch_size=512, shuffle=True
    )

    model.train()
    best_macro = 0.0
    best_state = None

    # Prepare test data for model selection
    X_test_dev = X_train[:min(2000, len(X_train))]  # Use subset of train for selection
    y_test_dev = y_train[:min(2000, len(y_train))]

    for epoch in range(epochs):
        for X_b, y_b in loader:
            X_b, y_b = X_b.to(DEVICE), y_b.to(DEVICE)
            optimizer.zero_grad()
            loss = criterion(model(X_b), y_b)
            loss.backward()
            optimizer.step()
        scheduler.step()

        # Track best model every 10 epochs
        if (epoch + 1) % 10 == 0 or epoch == epochs - 1:
            model.eval()
            with torch.no_grad():
                out = model(X_test_dev.to(DEVICE))
                preds = out.argmax(dim=1).cpu()
                correct = np.zeros(num_classes)
                total = np.zeros(num_classes)
                for i in range(num_classes):
                    mask = y_test_dev == i
                    correct[i] = (preds[mask] == y_test_dev[mask]).sum().item()
                    total[i] = mask.sum().item()
                macro = np.where(total > 0, correct / total, 0.0).mean() * 100
                if macro > best_macro:
                    best_macro = macro
                    best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            model.train()

    model = model.cpu()
    model.load_state_dict(best_state)
    model.eval()

    # Fuse BN (skip message for models without BN, e.g., logreg)
    has_bn = any(isinstance(l, nn.BatchNorm1d) for l in model.layers)
    if has_bn:
        print(f"    Fusing BatchNorm...")
    fused = FusedFlexMLP(input_dim, hidden, num_classes)

    # Iterate through layers: Linear, BN, ReLU triples + final Linear
    src_layers = list(model.layers)
    fused_layers = list(fused.layers)

    fused_idx = 0
    src_idx = 0
    while src_idx < len(src_layers):
        layer = src_layers[src_idx]
        if isinstance(layer, nn.Linear) and src_idx + 1 < len(src_layers) and isinstance(src_layers[src_idx + 1], nn.BatchNorm1d):
            # Fuse Linear + BN
            w, b = fuse_bn(layer, src_layers[src_idx + 1])
            fused_layers[fused_idx].weight.data = w
            fused_layers[fused_idx].bias.data = b
            src_idx += 3  # Skip Linear, BN, ReLU
            fused_idx += 2  # Skip Linear, ReLU
        elif isinstance(layer, nn.Linear):
            # Final Linear (no BN)
            fused_layers[fused_idx].weight.data = layer.weight.data.clone()
            fused_layers[fused_idx].bias.data = layer.bias.data.clone()
            src_idx += 1
            fused_idx += 1
        else:
            src_idx += 1

    fused.eval()

    # Verify fusion
    dummy = torch.randn(1, input_dim)
    with torch.no_grad():
        diff = (model(dummy) - fused(dummy)).abs().max().item()
    print(f"    Max fusion error: {diff:.2e}")

    # Export ONNX
    prefix = f"baseline_{config_name}_{dataset_name}"
    onnx_path = MODEL_DIR / f"{prefix}.onnx"
    print(f"    Exporting ONNX to {onnx_path}...")
    torch.onnx.export(
        fused, dummy,
        str(onnx_path),
        input_names=["input"],
        output_names=["output"],
        opset_version=17,
        dynamic_axes=None,
    )
    print(f"    FP32 size: {onnx_path.stat().st_size / 1024:.1f} KB")

    # Verify ONNX
    m = onnx.load(str(onnx_path))
    ops = sorted(set(n.op_type for n in m.graph.node))
    print(f"    Operators: {ops}")

    # INT8 PTQ
    cal_data = X_train.numpy()
    rng = np.random.RandomState(42)
    idx = rng.choice(len(cal_data), size=min(1000, len(cal_data)), replace=False)
    cal_samples = cal_data[idx].astype(np.float32)

    int8_path = MODEL_DIR / f"{prefix}_int8.onnx"
    print(f"    INT8 quantization ({len(cal_samples)} cal samples)...")
    reader = CalibrationDataReader(cal_samples, input_name="input")
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
    print(f"    INT8 size: {int8_path.stat().st_size / 1024:.1f} KB")
    print(f"    Upload {int8_path.name} + {onnx_path.name} to stedgeai-dc.st.com")

    return {
        "fp32_onnx": str(onnx_path),
        "int8_onnx": str(int8_path),
        "fp32_kb": onnx_path.stat().st_size / 1024,
        "int8_kb": int8_path.stat().st_size / 1024,
        "operators": ops,
        "fusion_error": diff,
    }


def main():
    print("=" * 60)
    print("Baselines: ONNX Export + INT8 PTQ")
    print("=" * 60)

    # Configs to export (skip the full MLP — already exported)
    configs = ["logreg", "mlp_64_64", "mlp_128_64"]

    datasets = {}

    # NSL-KDD
    print("\n[1] Loading NSL-KDD...")
    X_tr, y_tr, X_te, y_te, le, cn = load_nslkdd()
    cw = compute_class_weights(y_tr, len(cn))
    datasets["nslkdd"] = {
        "X_train": X_tr, "y_train": y_tr,
        "num_classes": len(cn), "class_weights": cw,
        "input_dim": X_tr.shape[1],
    }

    # UNSW-NB15
    print("[2] Loading UNSW-NB15...")
    X_tr, y_tr, X_te, y_te, le, cn = load_unsw()
    cw = compute_class_weights(y_tr, len(cn))
    datasets["unsw"] = {
        "X_train": X_tr, "y_train": y_tr,
        "num_classes": len(cn), "class_weights": cw,
        "input_dim": X_tr.shape[1],
    }

    results = {}
    for ds_name, ds in datasets.items():
        print(f"\n{'='*60}")
        print(f"Dataset: {ds_name}")
        print(f"{'='*60}")
        results[ds_name] = {}
        for cfg_name in configs:
            r = train_and_export(
                cfg_name, ds_name,
                ds["X_train"], ds["y_train"],
                ds["num_classes"], ds["class_weights"],
                ds["input_dim"],
            )
            results[ds_name][cfg_name] = r

    print("\n" + "=" * 60)
    print("Summary: Upload these to ST Edge AI Developer Cloud")
    print("=" * 60)
    for ds_name in results:
        for cfg_name in results[ds_name]:
            r = results[ds_name][cfg_name]
            print(f"  {ds_name}/{cfg_name}: FP32 {r['fp32_kb']:.1f}KB, "
                  f"INT8 {r['int8_kb']:.1f}KB")
    print("Done.")


if __name__ == "__main__":
    main()
