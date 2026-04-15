"""
Unit tests for src/stats_tests.py (Phase 3 GLOBECOM uplift).

Contracts:
- wilcoxon_signed_rank(x, y, name_x, name_y) → dict with
  {statistic, p_value, effect_size, direction, n_pairs}
- bootstrap_ci(values, confidence=0.95, n_boot=10000) → (lo, hi)
- holm_bonferroni(p_values_dict) → {name: (p_raw, p_corrected, reject_H0)}
- cohen_d(x, y) → float (paired)
- benjamini_hochberg(p_values_dict, alpha=0.05) → {name: (p_raw, p_bh, reject_H0)}
- run_full_analysis(results_json_path) → dict (writes JSON, returns summary)

All tests are RED until Phase 3 lands src/stats_tests.py.
"""

import json
import math
import numpy as np
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ── Imports deferred to allow red-state collection ────────────────────

def _import():
    import stats_tests as st
    return st


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def paired_identical():
    x = np.array([78.1, 78.5, 78.9, 79.0, 78.3, 78.7, 79.1, 78.6, 78.8, 78.4])
    y = x.copy()
    return x, y


@pytest.fixture
def paired_dominant():
    """x strictly >= y, difference ~1.0."""
    rng = np.random.default_rng(0)
    y = 77.0 + rng.normal(0, 0.5, size=20)
    x = y + 1.0 + rng.normal(0, 0.1, size=20)
    return x, y


@pytest.fixture
def paired_small_n():
    x = np.array([1.0, 2.0, 3.0])
    y = np.array([1.1, 1.9, 3.2])
    return x, y


# ── Wilcoxon signed-rank ──────────────────────────────────────────────

def test_wilcoxon_returns_required_keys(paired_dominant):
    st = _import()
    x, y = paired_dominant
    result = st.wilcoxon_signed_rank(x, y, "ReLU", "QCFS")
    for key in ("statistic", "p_value", "effect_size", "direction", "n_pairs"):
        assert key in result, f"missing key: {key}"


def test_wilcoxon_rejects_mismatched_lengths():
    st = _import()
    with pytest.raises((ValueError, AssertionError)):
        st.wilcoxon_signed_rank([1, 2, 3], [1, 2], "a", "b")


def test_wilcoxon_detects_dominance(paired_dominant):
    st = _import()
    x, y = paired_dominant
    result = st.wilcoxon_signed_rank(x, y, "ReLU", "QCFS")
    assert result["p_value"] < 0.05
    assert result["direction"] in ("ReLU>QCFS", "x>y", "greater")


def test_wilcoxon_identical_inputs_high_p(paired_identical):
    st = _import()
    x, y = paired_identical
    result = st.wilcoxon_signed_rank(x, y, "A", "B")
    assert result["p_value"] >= 0.05 or math.isnan(result["p_value"])
    assert abs(result["effect_size"]) < 1e-6 or math.isnan(result["effect_size"])


def test_wilcoxon_n_pairs_matches_input(paired_dominant):
    st = _import()
    x, y = paired_dominant
    result = st.wilcoxon_signed_rank(x, y, "A", "B")
    assert result["n_pairs"] == len(x)


# ── Bootstrap CI ──────────────────────────────────────────────────────

def test_bootstrap_ci_contains_mean(paired_dominant):
    st = _import()
    x, _ = paired_dominant
    lo, hi = st.bootstrap_ci(x, confidence=0.95, n_boot=2000)
    assert lo < np.mean(x) < hi


def test_bootstrap_ci_shrinks_with_large_n():
    st = _import()
    rng = np.random.default_rng(1)
    small = rng.normal(0, 1, size=20)
    large = rng.normal(0, 1, size=500)
    lo_s, hi_s = st.bootstrap_ci(small, n_boot=2000)
    lo_l, hi_l = st.bootstrap_ci(large, n_boot=2000)
    assert (hi_l - lo_l) < (hi_s - lo_s)


def test_bootstrap_ci_95pct_default():
    st = _import()
    x = np.array([1.0] * 30)  # zero variance
    lo, hi = st.bootstrap_ci(x)
    assert lo == pytest.approx(1.0, abs=1e-6)
    assert hi == pytest.approx(1.0, abs=1e-6)


# ── Cohen's d (paired) ────────────────────────────────────────────────

def test_cohen_d_zero_for_identical(paired_identical):
    st = _import()
    x, y = paired_identical
    d = st.cohen_d(x, y)
    assert abs(d) < 1e-9


def test_cohen_d_positive_when_x_dominates(paired_dominant):
    st = _import()
    x, y = paired_dominant
    d = st.cohen_d(x, y)
    assert d > 0
    assert d > 0.5  # expect large effect


def test_cohen_d_symmetric_sign():
    st = _import()
    x = np.array([2.0, 3.0, 4.0, 5.0])
    y = np.array([1.0, 2.0, 3.0, 4.0])
    assert st.cohen_d(x, y) == pytest.approx(-st.cohen_d(y, x), abs=1e-9)


# ── Holm-Bonferroni ───────────────────────────────────────────────────

def test_holm_bonferroni_preserves_order():
    st = _import()
    pvals = {"a": 0.001, "b": 0.010, "c": 0.040, "d": 0.060}
    corrected = st.holm_bonferroni(pvals)
    # corrected p must be non-decreasing w.r.t. raw order
    order = sorted(pvals, key=lambda k: pvals[k])
    adj = [corrected[k][1] for k in order]
    assert all(adj[i] <= adj[i + 1] + 1e-12 for i in range(len(adj) - 1))


def test_holm_bonferroni_rejects_small_p():
    st = _import()
    pvals = {"a": 0.001, "b": 0.002, "c": 0.003}
    corrected = st.holm_bonferroni(pvals)
    assert all(corrected[k][2] for k in pvals)  # all rejected at α=0.05


def test_holm_bonferroni_accepts_large_p():
    st = _import()
    pvals = {"a": 0.40, "b": 0.50, "c": 0.60}
    corrected = st.holm_bonferroni(pvals)
    assert all(not corrected[k][2] for k in pvals)


def test_holm_bonferroni_stricter_than_bonferroni_tied():
    """Holm always dominates or ties vanilla Bonferroni."""
    st = _import()
    pvals = {"a": 0.01, "b": 0.02, "c": 0.03, "d": 0.04}
    m = len(pvals)
    holm = st.holm_bonferroni(pvals)
    for k, raw in pvals.items():
        p_holm = holm[k][1]
        p_bonf = min(1.0, raw * m)
        assert p_holm <= p_bonf + 1e-12


# ── Benjamini-Hochberg (secondary, for per-class exploratory) ─────────

def test_bh_returns_required_keys():
    st = _import()
    pvals = {"a": 0.01, "b": 0.02, "c": 0.03}
    result = st.benjamini_hochberg(pvals, alpha=0.05)
    for k in pvals:
        raw, adj, rej = result[k]
        assert raw == pvals[k]
        assert 0.0 <= adj <= 1.0
        assert isinstance(rej, (bool, np.bool_))


def test_bh_less_conservative_than_holm():
    """For uniform mid-range p-values, BH should reject at least as many as Holm."""
    st = _import()
    pvals = {f"c{i}": 0.01 + 0.001 * i for i in range(10)}
    holm = st.holm_bonferroni(pvals)
    bh = st.benjamini_hochberg(pvals, alpha=0.05)
    holm_rej = sum(1 for v in holm.values() if v[2])
    bh_rej = sum(1 for v in bh.values() if v[2])
    assert bh_rej >= holm_rej


# ── Full analysis runner ──────────────────────────────────────────────

def test_run_full_analysis_writes_json(tmp_path):
    """The orchestrator accepts a results dir and writes stats_tests.json."""
    st = _import()
    # Build a minimal fixture pair: 10 seeds, ReLU > QCFS on OA
    fake_results = {
        "relu": {"per_seed": [{"overall_acc": 78.0 + i * 0.1, "macro_f1": 59.0 + i * 0.1}
                                for i in range(10)]},
        "qcfs_L4": {"per_seed": [{"overall_acc": 77.0 + i * 0.1, "macro_f1": 57.0 + i * 0.1}
                                   for i in range(10)]},
    }
    in_path = tmp_path / "fake_multiseed.json"
    in_path.write_text(json.dumps(fake_results))
    out_path = tmp_path / "stats_tests.json"
    summary = st.run_full_analysis(str(in_path), str(out_path))
    assert out_path.exists()
    loaded = json.loads(out_path.read_text())
    assert "comparisons" in loaded or "holm_bonferroni" in loaded
    assert isinstance(summary, dict)


# ── Required fields sanity ────────────────────────────────────────────

def test_report_contains_all_required_fields(paired_dominant):
    st = _import()
    x, y = paired_dominant
    w = st.wilcoxon_signed_rank(x, y, "A", "B")
    # Check no required field is None/NaN for a well-conditioned input
    assert w["statistic"] is not None
    assert w["p_value"] is not None
    assert w["effect_size"] is not None
