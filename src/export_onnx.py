"""
SNN-IDS: Export PyTorch model to ONNX format
Target: ST Edge AI Developer Cloud → Neural-ART NPU (INT8)
"""

import torch
import numpy as np
from pathlib import Path

from models import IDS_MLP, fuse_bn_model

MODEL_DIR = Path(__file__).parent.parent / "models"


def export():
    metadata = torch.load(MODEL_DIR / "ids_metadata.pth", weights_only=False)
    input_dim = metadata["input_dim"]
    hidden = metadata["hidden"]
    num_classes = metadata["num_classes"]

    print(f"Model config: input={input_dim}, hidden={hidden}, classes={num_classes}")
    print(f"Classes: {metadata['classes']}")
    print(f"Best macro accuracy: {metadata['best_macro_acc']:.2f}%")

    model = IDS_MLP(input_dim=input_dim, hidden=hidden, num_classes=num_classes)
    model.load_state_dict(
        torch.load(MODEL_DIR / "ids_model_best.pth", weights_only=True)
    )
    model.eval()

    # Fuse BatchNorm into Linear for cleaner ONNX graph
    model = fuse_bn_model(model)
    print("BatchNorm fused into Linear layers")

    # Verify fused model produces same output
    dummy = torch.randn(1, input_dim)
    with torch.no_grad():
        out = model(dummy)
    print(f"Output shape: {out.shape}")

    # Export to ONNX
    onnx_path = MODEL_DIR / "ids_model.onnx"
    torch.onnx.export(
        model,
        dummy,
        str(onnx_path),
        input_names=["input"],
        output_names=["output"],
        dynamic_axes=None,  # Fixed batch=1 for NPU
        opset_version=17,
    )
    print(f"\nONNX exported: {onnx_path}")
    print(f"File size: {onnx_path.stat().st_size / 1024:.1f} KB")

    # Validate ONNX model
    import onnx
    onnx_model = onnx.load(str(onnx_path))
    onnx.checker.check_model(onnx_model)
    print("ONNX validation: PASSED")

    # Print operator list (for Neural-ART compatibility check)
    ops = set()
    for node in onnx_model.graph.node:
        ops.add(node.op_type)
    print(f"ONNX operators: {sorted(ops)}")
    print("\nNeural-ART compatibility:")
    npu_supported = {"Gemm", "MatMul", "Relu", "Add"}
    for op in sorted(ops):
        supported = op in npu_supported
        print(f"  {op}: {'NPU' if supported else 'CPU fallback'}")

    # Run ONNX Runtime inference to verify
    import onnxruntime as ort
    sess = ort.InferenceSession(str(onnx_path))
    ort_out = sess.run(None, {"input": dummy.numpy()})
    diff = np.abs(out.numpy() - ort_out[0]).max()
    print(f"\nPyTorch vs ONNX max diff: {diff:.8f}")
    assert diff < 1e-5, f"Output mismatch: {diff}"
    print("Numerical verification: PASSED")


if __name__ == "__main__":
    export()
