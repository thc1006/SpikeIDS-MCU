"""
Unit tests for Phase 5: NPU-deployable CNN baseline (GLOBECOM uplift).

Contracts (src/experiment_cnn_baseline.py, src/models.py::TinyCNN_IDS):
- TinyCNN_IDS uses Conv2d (1×K) only, NEVER Conv1d (Neural-ART does NOT confirm Conv1d)
- Input reshape: (B, F) → (B, 1, 1, F)
- Kernel width ≤ 6, kernel height ≤ 3 (Neural-ART HW limits)
- Param count < 30K
- ONNX export contains only NPU-safe ops: {Conv, Relu, Gemm, Reshape, Flatten, MatMul, Add}
- INT8 quant drop < 3 pp macro F1
- Runs 100 samples through onnxruntime without error

All tests are RED until Phase 5 lands.
"""

import sys
import json
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import torch
import torch.nn as nn


# ── Model structural tests ────────────────────────────────────────────

def test_tinycnn_ids_importable():
    from models import TinyCNN_IDS  # noqa
    assert TinyCNN_IDS is not None


def test_tinycnn_uses_conv2d_not_conv1d():
    from models import TinyCNN_IDS
    model = TinyCNN_IDS(input_dim=41, num_classes=5)
    # Forbid Conv1d anywhere — Neural-ART only confirms Conv2d
    for m in model.modules():
        assert not isinstance(m, nn.Conv1d), \
            f"Conv1d found at {type(m).__name__}; Neural-ART requires Conv2d"
    conv2ds = [m for m in model.modules() if isinstance(m, nn.Conv2d)]
    assert len(conv2ds) >= 1, "Expected at least one Conv2d layer"


def test_tinycnn_kernel_within_neural_art_limits():
    """Neural-ART: kernel width ≤ 6, height ≤ 3 (stride=1)."""
    from models import TinyCNN_IDS
    model = TinyCNN_IDS(input_dim=41, num_classes=5)
    for m in model.modules():
        if isinstance(m, nn.Conv2d):
            kh, kw = m.kernel_size
            assert kh <= 3, f"kernel height {kh} exceeds Neural-ART limit 3"
            assert kw <= 6, f"kernel width {kw} exceeds Neural-ART limit 6"


def test_tinycnn_input_reshape_to_4d():
    """Forward pass must accept (B, F) and internally reshape to 4D."""
    from models import TinyCNN_IDS
    model = TinyCNN_IDS(input_dim=41, num_classes=5)
    model.eval()
    x = torch.randn(4, 41)
    out = model(x)
    assert out.shape == (4, 5)


def test_tinycnn_param_count_under_30k():
    from models import TinyCNN_IDS
    model = TinyCNN_IDS(input_dim=41, num_classes=5)
    n = sum(p.numel() for p in model.parameters())
    assert n < 30_000, f"param count {n} exceeds 30K budget"


def test_tinycnn_handles_multiple_input_dims():
    from models import TinyCNN_IDS
    for dim in (41, 43, 69):  # NSL-KDD, UNSW, CICIDS
        model = TinyCNN_IDS(input_dim=dim, num_classes=5)
        x = torch.randn(2, dim)
        out = model(x)
        assert out.shape == (2, 5)


# ── ONNX export / operator safety ─────────────────────────────────────

NPU_SAFE_OPS = {
    "Conv", "Relu", "Gemm", "MatMul", "Add", "Reshape", "Flatten",
    "Transpose", "Constant", "Identity", "Unsqueeze", "Shape", "Gather",
    "Concat",
}


def test_tinycnn_onnx_export_has_only_safe_ops(tmp_path):
    from models import TinyCNN_IDS
    import onnx

    model = TinyCNN_IDS(input_dim=41, num_classes=5)
    model.eval()
    dummy = torch.randn(1, 41)
    onnx_path = tmp_path / "tinycnn.onnx"
    torch.onnx.export(
        model, dummy, str(onnx_path),
        input_names=["x"], output_names=["logits"],
        opset_version=13,
    )
    m = onnx.load(str(onnx_path))
    ops = {node.op_type for node in m.graph.node}
    forbidden = {"Conv1d", "LSTM", "GRU", "Attention", "ScaledDotProductAttention"}
    assert not (ops & forbidden), f"forbidden ops: {ops & forbidden}"
    extras = ops - NPU_SAFE_OPS
    assert not extras, f"ops outside NPU-safe set: {extras}"


# ── Experiment runner contract ────────────────────────────────────────

def test_experiment_cnn_baseline_importable():
    import experiment_cnn_baseline as exp  # noqa
    assert hasattr(exp, "main")


def test_cnn_results_json_schema_after_run():
    results_path = Path(__file__).parent.parent / "results" / "cnn_baseline.json"
    if not results_path.exists():
        pytest.skip("Phase 5 experiment not yet run")
    data = json.loads(results_path.read_text())
    # Expected top-level keys
    for ds in ("nslkdd", "unsw", "cicids2017"):
        assert ds in data, f"missing dataset {ds}"
        assert "per_seed" in data[ds]
        assert len(data[ds]["per_seed"]) >= 3  # at least 3 seeds
        assert "aggregate" in data[ds]
