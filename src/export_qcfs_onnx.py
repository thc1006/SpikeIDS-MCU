"""
Export trained QCFS models to ONNX.
Freezes learned thresholds into fixed constants to avoid PyTorch ONNX export issues.
"""

import torch
import torch.nn as nn
import numpy as np
from pathlib import Path

MODEL_DIR = Path(__file__).parent.parent / "models"


class FloorSTE(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x):
        return torch.floor(x)

    @staticmethod
    def backward(ctx, grad_output):
        return grad_output


class QCFS(nn.Module):
    def __init__(self, L=8, init_threshold=1.0):
        super().__init__()
        self.register_buffer("L", torch.tensor(float(L)))
        self.threshold = nn.Parameter(torch.tensor(float(init_threshold)))

    def forward(self, x):
        step = self.threshold / self.L
        x_scaled = x / (step + 1e-8)
        x_clipped = torch.clamp(x_scaled, 0.0, self.L.item())
        x_floored = FloorSTE.apply(x_clipped)
        return x_floored * step


class QCFSFrozen(nn.Module):
    """QCFS with frozen (constant) threshold for clean ONNX export."""
    def __init__(self, step: float, L: float):
        super().__init__()
        self.register_buffer("step_val", torch.tensor(step))
        self.register_buffer("L_val", torch.tensor(L))
        self.register_buffer("inv_step", torch.tensor(1.0 / (step + 1e-8)))

    def forward(self, x):
        x_scaled = x * self.inv_step
        x_clipped = torch.clamp(x_scaled, 0.0, self.L_val)
        x_floored = torch.floor(x_clipped)
        return x_floored * self.step_val


class IDS_MLP_QCFS(nn.Module):
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


class IDS_MLP_QCFS_Frozen(nn.Module):
    """Export-only model with frozen QCFS and fused BatchNorm."""
    def __init__(self, layers_list):
        super().__init__()
        self.layers = nn.Sequential(*layers_list)

    def forward(self, x):
        return self.layers(x)


def fuse_bn_linear(linear, bn):
    """Fuse BatchNorm into preceding Linear layer."""
    scale = bn.weight.data / torch.sqrt(bn.running_var + bn.eps)
    fused_weight = linear.weight.data * scale.unsqueeze(1)
    if linear.bias is not None:
        fused_bias = (linear.bias.data - bn.running_mean) * scale + bn.bias.data
    else:
        fused_bias = -bn.running_mean * scale + bn.bias.data
    new_linear = nn.Linear(linear.in_features, linear.out_features)
    new_linear.weight.data = fused_weight
    new_linear.bias.data = fused_bias
    return new_linear


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
            fused = fuse_bn_linear(layers[i], layers[i + 1])
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


def export_single(L):
    model_path = MODEL_DIR / f"ids_qcfs_L{L}_best.pth"
    if not model_path.exists():
        print(f"  Skipping L={L}: {model_path} not found")
        return False

    print(f"\n{'='*50}")
    print(f"Exporting QCFS L={L}")
    print(f"{'='*50}")

    # Load trained model
    model = IDS_MLP_QCFS(input_dim=41, hidden=256, num_classes=5, L=L)
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
    dummy = torch.randn(1, 41)
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
    print("=" * 60)
    print("SNN-IDS: Export QCFS Models to ONNX")
    print("=" * 60)

    exported = []
    for L in [4, 8, 16]:
        if export_single(L):
            exported.append(L)

    if exported:
        print(f"\n{'='*60}")
        print("Summary")
        print(f"{'='*60}")
        print(f"  Exported L values: {exported}")
        print(f"  Next: Upload ids_qcfs_L*.onnx to stedgeai-dc.st.com")
        print(f"  Goal: Check if Floor operator is NPU-mapped or CPU-fallback")
        print(f"  Compare inference time vs ReLU model (0.4563 ms)")
    else:
        print("\nNo QCFS models found. Run train_qcfs.py first.")


if __name__ == "__main__":
    main()
