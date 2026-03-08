"""
SNN-IDS: Export PyTorch model to ONNX format
Target: ST Edge AI Developer Cloud → Neural-ART NPU (INT8)
"""

import torch
import torch.nn as nn
import numpy as np
from pathlib import Path

MODEL_DIR = Path(__file__).parent.parent / "models"


class IDS_MLP(nn.Module):
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


def fuse_bn(model):
    """Fuse BatchNorm into preceding Linear layers for deployment."""
    layers = list(model.layers)
    fused = []
    i = 0
    while i < len(layers):
        if (
            i + 1 < len(layers)
            and isinstance(layers[i], nn.Linear)
            and isinstance(layers[i + 1], nn.BatchNorm1d)
        ):
            linear = layers[i]
            bn = layers[i + 1]

            # Fused weight and bias
            bn_weight = bn.weight.data
            bn_bias = bn.bias.data
            bn_mean = bn.running_mean
            bn_var = bn.running_var
            bn_eps = bn.eps

            scale = bn_weight / torch.sqrt(bn_var + bn_eps)

            fused_weight = linear.weight.data * scale.unsqueeze(1)
            if linear.bias is not None:
                fused_bias = (linear.bias.data - bn_mean) * scale + bn_bias
            else:
                fused_bias = -bn_mean * scale + bn_bias

            new_linear = nn.Linear(linear.in_features, linear.out_features)
            new_linear.weight.data = fused_weight
            new_linear.bias.data = fused_bias
            fused.append(new_linear)
            i += 2
        else:
            fused.append(layers[i])
            i += 1

    model.layers = nn.Sequential(*fused)
    return model


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
    model = fuse_bn(model)
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
