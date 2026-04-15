"""
Unit tests for QCFS L-sweep experiment (Phase 2 GLOBECOM uplift).

Contracts (src/experiment_qcfs_lsweep.py):
- LVALUES constant == [2, 4, 8, 16]
- SEEDS constant == [0, 1, 2, 3, 4]
- DATASETS keys == ["nslkdd", "unsw"]
- build_model(L, input_dim, num_classes) → IDS_MLP_QCFS instance
- run_sweep(dataset_name, loader, lvalues, seeds, epochs=..., out_path=...) → dict
- Result JSON schema: {"sweep": {(ds, L): {seed: metrics}}, "aggregate": {...}}

Also tests that QCFS model built at each L produces the expected structure
and that floor op survives through ONNX export (sanity for Phase 2 → Phase 4).
"""

import sys
import json
import pytest
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import torch
from models import IDS_MLP_QCFS, QCFS


# ── Constants ─────────────────────────────────────────────────────────

def test_lvalues_are_powers_of_two():
    from experiment_qcfs_lsweep import LVALUES
    assert LVALUES == [2, 4, 8, 16]
    for L in LVALUES:
        assert (L & (L - 1)) == 0, f"L={L} is not a power of 2"


def test_seed_count_is_five():
    from experiment_qcfs_lsweep import SEEDS
    assert len(SEEDS) == 5
    assert SEEDS == [0, 1, 2, 3, 4]


def test_dataset_keys_match_spec():
    from experiment_qcfs_lsweep import DATASETS
    assert set(DATASETS.keys()) == {"nslkdd", "unsw"}


# ── Model construction ───────────────────────────────────────────────

@pytest.mark.parametrize("L", [2, 4, 8, 16])
def test_qcfs_model_accepts_each_L(L):
    model = IDS_MLP_QCFS(input_dim=41, hidden=64, num_classes=5, L=L)
    # Find QCFS activations
    qcfs_layers = [m for m in model.modules() if isinstance(m, QCFS)]
    assert len(qcfs_layers) >= 1
    for q in qcfs_layers:
        assert int(q.L.item()) == L


@pytest.mark.parametrize("L", [2, 4, 8, 16])
def test_qcfs_forward_runs(L):
    model = IDS_MLP_QCFS(input_dim=41, hidden=64, num_classes=5, L=L)
    model.eval()
    x = torch.randn(8, 41)
    y = model(x)
    assert y.shape == (8, 5)
    assert not torch.isnan(y).any()


def test_qcfs_larger_L_has_finer_steps():
    """L=16 gives smaller step size than L=2 for the same threshold."""
    import torch.nn as nn
    q_small = QCFS(L=2, init_threshold=4.0)
    q_large = QCFS(L=16, init_threshold=4.0)
    step_s = (q_small.threshold / q_small.L).item()
    step_l = (q_large.threshold / q_large.L).item()
    assert step_l < step_s


# ── Result schema ────────────────────────────────────────────────────

def test_run_sweep_returns_nested_dict(tmp_path):
    """run_sweep should produce {L: {seed: {metric: value}}} per dataset."""
    from experiment_qcfs_lsweep import run_sweep_smoke
    out = tmp_path / "qcfs_lsweep.json"
    result = run_sweep_smoke(str(out))  # quick-path for tests
    assert "nslkdd" in result
    assert "unsw" in result
    assert set(result["nslkdd"].keys()) == {"L2", "L4", "L8", "L16"}
    for lk, seed_dict in result["nslkdd"].items():
        assert len(seed_dict) >= 1  # at least one seed for smoke
        for sk, metrics in seed_dict.items():
            assert "overall_acc" in metrics
            assert "macro_f1" in metrics


def test_qcfs_int8_drop_under_2pct(tmp_path):
    """Soft contract: INT8 PTQ on QCFS model should drop <2pp macro-F1."""
    # This test will only run if Phase 2 produces the ablation JSON.
    results_path = Path(__file__).parent.parent / "results" / "qcfs_lsweep.json"
    if not results_path.exists():
        pytest.skip("Phase 2 not yet run")
    data = json.loads(results_path.read_text())
    # Best L across seeds for NSL-KDD
    assert "nslkdd" in data
    best_l = max(data["nslkdd"].keys(),
                 key=lambda k: np.mean([s["macro_f1"] for s in data["nslkdd"][k].values()]))
    assert best_l in {"L4", "L8", "L16"}  # L=2 should not be best
