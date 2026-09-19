"""
Export trained QCFS models to ONNX.
Freezes learned thresholds into fixed constants to avoid PyTorch ONNX export issues.
"""

import argparse
import torch
import torch.nn as nn
import numpy as np
from pathlib import Path
from models import QCFS, QCFSFrozen, IDS_MLP_QCFS, IDS_MLP_QCFS_Frozen, fuse_bn_to_linear

MODEL_DIR = Path(__file__).parent.parent / "models"


def freeze_model(model, L):
    """Convert trained QCFS model to export-friendly frozen version."""
    layers = list(model.layers)
    frozen_layers = []
    i = 0
    while i < len(layers):
        if (i + 1 < len(layers)
            and isinstance(layers[i], nn.Linear)
            and isinstance(layers[i + 1], nn.BatchNorm1d)):
            # Fuse BN into Linear
            fused = fuse_bn_to_linear(layers[i], layers[i + 1])
            frozen_layers.append(fused)
            i += 2
        elif isinstance(layers[i], QCFS):
            # Freeze QCFS with learned threshold
            threshold = layers[i].threshold.item()
            L_val = layers[i].L.item()
            step = threshold / L_val
            frozen_layers.append(QCFSFrozen(step=step, L=L_val))
            i += 1
        else:
            frozen_layers.append(layers[i])
            i += 1

    return IDS_MLP_QCFS_Frozen(frozen_layers)


def export_single(L, input_dim=41, num_classes=5, prefix="ids_qcfs"):
    model_path = MODEL_DIR / f"{prefix}_L{L}_best.pth"
    if not model_path.exists():
        print(f"  Skipping L={L}: {model_path} not found")
        return False

    print(f"\n{'='*50}")
    print(f"Exporting QCFS L={L} (d={input_dim}, C={num_classes}) from {model_path.name}")
    print(f"{'='*50}")

    # Load trained model
    model = IDS_MLP_QCFS(input_dim=input_dim, hidden=256, num_classes=num_classes, L=L)
    model.load_state_dict(torch.load(model_path, weights_only=True))
    model.eval()

    # Print learned thresholds
    for idx, m in enumerate(model.modules()):
        if isinstance(m, QCFS):
            print(f"  QCFS layer threshold: {m.threshold.item():.4f}, step: {m.threshold.item()/L:.6f}")

    # Freeze for export
    frozen = freeze_model(model, L)
    frozen.eval()

    # Verify outputs match
    dummy = torch.randn(1, input_dim)
    with torch.no_grad():
        out_orig = model(dummy)
        out_frozen = frozen(dummy)
    diff = (out_orig - out_frozen).abs().max().item()
    print(f"  Original vs Frozen max diff: {diff:.8f}")
    assert diff < 1e-4, f"Output mismatch: {diff}"

    # Export to ONNX
    onnx_path = MODEL_DIR / f"ids_qcfs_L{L}.onnx"
    torch.onnx.export(
        frozen,
        dummy,
        str(onnx_path),
        input_names=["input"],
        output_names=["output"],
        dynamic_axes=None,
        opset_version=17,
    )
    print(f"  ONNX exported: {onnx_path} ({onnx_path.stat().st_size / 1024:.1f} KB)")

    # Analyze operators
    import onnx
    onnx_model = onnx.load(str(onnx_path))
    onnx.checker.check_model(onnx_model)
    ops = set()
    for node in onnx_model.graph.node:
        ops.add(node.op_type)
    print(f"  ONNX operators: {sorted(ops)}")

    npu_confirmed = {"Gemm", "MatMul", "Relu", "Add", "Clip", "Mul",
                     "QuantizeLinear", "DequantizeLinear"}
    npu_uncertain = {"Floor", "Div"}
    print(f"  Neural-ART NPU compatibility:")
    for op in sorted(ops):
        if op in npu_confirmed:
            status = "NPU (confirmed)"
        elif op in npu_uncertain:
            status = "UNCERTAIN → may CPU fallback"
        else:
            status = "unknown"
        print(f"    {op}: {status}")

    # Verify with ONNX Runtime
    import onnxruntime as ort
    sess = ort.InferenceSession(str(onnx_path))
    ort_out = sess.run(None, {"input": dummy.numpy()})
    ort_diff = np.abs(out_frozen.numpy() - ort_out[0]).max()
    print(f"  PyTorch vs ONNX Runtime max diff: {ort_diff:.8f}")

    return True


def main():
    ap = argparse.ArgumentParser(description="Export trained QCFS models to ONNX.")
    ap.add_argument("--input-dim", type=int, default=41,
                    help="feature dim (41=NSL-KDD, 13=IoT-23, 34=UNSW, 69=CICIDS)")
    ap.add_argument("--classes", type=int, default=5, help="number of output classes")
    ap.add_argument("--prefix", default="ids_qcfs",
                    help="weight file prefix; reads <prefix>_L{L}_best.pth (e.g. iot23_qcfs)")
    ap.add_argument("--L", type=int, nargs="+", default=[4, 8, 16], help="QCFS L values to export")
    a = ap.parse_args()

    print("=" * 60)
    print(f"SNN-IDS: Export QCFS Models to ONNX (d={a.input_dim}, C={a.classes})")
    print("=" * 60)

    exported = []
    for L in a.L:
        if export_single(L, input_dim=a.input_dim, num_classes=a.classes, prefix=a.prefix):
            exported.append(L)

    if exported:
        print(f"\n{'='*60}")
        print("Summary")
        print(f"{'='*60}")
        print(f"  Exported L values: {exported}")
        print(f"  Next: compile with the local ST Edge AI Core toolchain")
        print(f"        (stedgeai generate --target stm32n6 [--st-neural-art ...])")
        print(f"  Goal: confirm the Floor operator falls back to CPU (SW epochs)")
    else:
        print("\nNo QCFS models found. Run train_qcfs.py first.")


if __name__ == "__main__":
    main()
