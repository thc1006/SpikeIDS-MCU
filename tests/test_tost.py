"""Tests for the v4 TOST equivalence helpers in src/stats_tests.py.

Covers: decision <-> CI consistency, delta_min semantics, degenerate and
insufficient inputs, the non-parametric variant, power monotonicity, the
agreement between the normal approximation and Monte-Carlo power, and the
orchestrator's Holm family.
"""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stats_tests import (  # noqa: E402
    run_equivalence_analysis,
    tost_paired,
    tost_power_mc,
    tost_power_normal,
    tost_required_n,
    tost_wilcoxon,
)


def _arms(n=20, sd=0.5, shift=0.0, seed=0):
    rng = np.random.default_rng(seed)
    x = 80.0 + rng.normal(0.0, 1.0, n)
    y = x - shift + rng.normal(0.0, sd, n)
    return x, y


def test_tost_t_passes_when_arms_are_equivalent():
    x, y = _arms(n=20, sd=0.3, shift=0.0)
    r = tost_paired(x, y, delta=1.0)
    assert r["equivalent"] is True
    assert r["p_tost"] < 0.05
    assert -1.0 < r["ci"][0] and r["ci"][1] < 1.0


def test_tost_t_fails_when_difference_exceeds_margin():
    x, y = _arms(n=20, sd=0.3, shift=2.0)
    r = tost_paired(x, y, delta=1.0)
    assert r["equivalent"] is False
    assert r["p_tost"] > 0.5


def test_decision_matches_ci_inclusion():
    """TOST at alpha rejects both sides iff the (1-2alpha) CI is inside (-d, d)."""
    for seed in range(15):
        x, y = _arms(n=8, sd=0.8, shift=0.4, seed=seed)
        r = tost_paired(x, y, delta=1.0, alpha=0.05)
        inside = (-1.0 < r["ci"][0]) and (r["ci"][1] < 1.0)
        assert r["equivalent"] == inside


def test_delta_min_is_the_smallest_passing_margin():
    x, y = _arms(n=12, sd=0.6, shift=0.3, seed=3)
    r = tost_paired(x, y, delta=1.0)
    dm = r["delta_min"]
    assert tost_paired(x, y, delta=dm * 1.001)["equivalent"] is True
    assert tost_paired(x, y, delta=dm * 0.999)["equivalent"] is False


def test_zero_difference_is_equivalent_at_any_margin():
    x = np.array([70.0, 71.0, 72.5, 69.0, 73.0])
    r = tost_paired(x, x.copy(), delta=0.01)
    assert r["equivalent"] is True
    assert r["note"] == "degenerate variance"
    assert r["delta_min"] == 0.0


def test_insufficient_pairs_and_bad_delta():
    r = tost_paired([1.0], [1.5], delta=1.0)
    assert r["equivalent"] is False and r["note"] == "insufficient pairs"
    with pytest.raises(ValueError):
        tost_paired([1.0, 2.0], [1.0, 2.0], delta=0.0)
    with pytest.raises(ValueError):
        tost_paired([1.0, 2.0], [1.0], delta=1.0)


def test_wilcoxon_tost_agrees_on_clear_cases():
    x, y = _arms(n=20, sd=0.3, shift=0.0, seed=1)
    assert tost_wilcoxon(x, y, delta=1.0)["equivalent"] is True
    x, y = _arms(n=20, sd=0.3, shift=2.5, seed=1)
    assert tost_wilcoxon(x, y, delta=1.0)["equivalent"] is False


def test_wilcoxon_tost_is_power_limited_below_five_pairs():
    """The exact one-sided signed-rank p floor is 2**-n: with n = 4 the
    best attainable p is 0.0625, so equivalence can never be declared even
    for identical-looking arms; with n = 5 it can (p = 1/32)."""
    x, y = _arms(n=4, sd=0.05, shift=0.0, seed=2)
    r = tost_wilcoxon(x, y, delta=1.0)
    assert r["equivalent"] is False
    assert r["p_tost"] == pytest.approx(0.0625)
    x, y = _arms(n=5, sd=0.05, shift=0.0, seed=2)
    assert tost_wilcoxon(x, y, delta=1.0)["p_tost"] == pytest.approx(1 / 32)


def test_power_increases_with_n_and_margin():
    p10 = tost_power_normal(10, sd_diff=1.0, delta=1.0)
    p40 = tost_power_normal(40, sd_diff=1.0, delta=1.0)
    p40_wide = tost_power_normal(40, sd_diff=1.0, delta=2.0)
    assert p10 < p40 < p40_wide <= 1.0


def test_required_n_matches_power_function():
    n = tost_required_n(sd_diff=1.0, delta=1.0, power=0.8)
    assert tost_power_normal(n, 1.0, 1.0) >= 0.8
    assert tost_power_normal(n - 1, 1.0, 1.0) < 0.8
    assert tost_required_n(sd_diff=1.0, delta=1.0, true_diff=1.0) > 100_000


def test_monte_carlo_power_tracks_normal_approximation():
    """With the variance estimated, MC power sits a little below the
    known-variance approximation for small n and converges for large n."""
    for n in (10, 30):
        approx = tost_power_normal(n, sd_diff=1.0, delta=1.0)
        mc = tost_power_mc(n, sd_diff=1.0, delta=1.0, n_sim=40_000, seed=7)
        assert abs(mc - approx) < 0.08, (n, mc, approx)


def test_orchestrator_holm_family_and_sensitivity():
    xa, ya = _arms(n=20, sd=0.3, shift=0.0, seed=4)
    xb, yb = _arms(n=20, sd=0.3, shift=3.0, seed=5)
    out = run_equivalence_analysis({"a": (xa, ya), "b": (xb, yb)}, delta=1.0)
    holm = out["holm_bonferroni_tost_t"]
    assert holm["a"]["equivalent"] is True
    assert holm["b"]["equivalent"] is False
    assert holm["a"]["p_corrected"] >= holm["a"]["p_raw"]
    assert out["sensitivity"]["a"]["0.5"] is True
    assert out["sensitivity"]["b"]["3"] is False
    assert out["pairs"]["a"]["required_n"]["power_0.80"] >= 2
    assert 0.0 <= out["pairs"]["a"]["power_at_n"]["monte_carlo"] <= 1.0
