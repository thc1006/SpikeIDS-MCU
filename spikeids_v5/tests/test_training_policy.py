"""Adversarial checks for fit-only weighting and fixed-budget selection."""
from __future__ import annotations

import numpy as np
import pytest
import torch

import experiment_all as runner
import models


def test_prepared_weights_use_post_final_dedup_model_fit_labels(prepared) -> None:
    args = runner.parser().parse_args([
        "--dataset", "nslkdd", "--cache", str(prepared / "nslkdd"),
        "--output", "unused.json", "--model", "relu", "--device", "cpu",
    ])
    data = runner.prepare_data(args)
    expected = np.bincount(data.y_fit.numpy(), minlength=len(data.names)).tolist()
    assert data.weighting["fit_class_counts"] == expected
    assert data.weighting["source"] == "fit labels only"


def test_sqrt_inverse_weights_are_fit_only_and_exact() -> None:
    y_fit = np.array([0] * 4 + [1] * 16 + [2] * 64, dtype=np.int64)
    weights, policy = runner.class_weight_policy(
        y_fit, ["rare", "middle", "common"], "sqrt_inverse_fit_only_v1")
    expected = 1.0 / np.sqrt(np.array([4, 16, 64], dtype=np.float64))
    expected = np.asarray(expected / expected.sum() * 3, dtype=np.float32)
    assert np.array_equal(weights, expected)
    assert policy["fit_class_counts"] == [4, 16, 64]
    assert weights.max() / weights.min() == pytest.approx(4.0)

    # No validation/test value can enter this API.  Permuting fit labels keeps
    # counts and evidence exact; changing one fit label changes both.
    permuted, same = runner.class_weight_policy(
        y_fit[::-1], ["rare", "middle", "common"], "sqrt_inverse_fit_only_v1")
    assert np.array_equal(permuted, weights)
    assert same == policy
    changed = y_fit.copy(); changed[0] = 1
    altered, altered_policy = runner.class_weight_policy(
        changed, ["rare", "middle", "common"], "sqrt_inverse_fit_only_v1")
    assert not np.array_equal(altered, weights)
    assert altered_policy["weights_sha256"] != policy["weights_sha256"]


@pytest.mark.parametrize("scheme", [
    "sqrt_inverse_fit_only_v1", "unweighted_fit_only_v1",
    "inverse_fit_only_legacy_v1",
])
def test_weight_schemes_are_finite_positive_normalized(scheme: str) -> None:
    w, policy = runner.class_weight_policy(
        np.array([0, 0, 1, 2, 2, 2], dtype=np.int64), ["a", "b", "c"], scheme)
    assert w.dtype == np.float32
    assert np.isfinite(w).all() and (w > 0).all()
    assert float(w.sum()) == pytest.approx(3.0, abs=2e-7)
    assert policy["source"] == "fit labels only"
    with pytest.raises(Exception):
        runner.class_weight_policy(np.array([0, 0], dtype=np.int64), ["a", "b"], scheme)


def test_fixed_final_epoch_ignores_better_earlier_validation(
        prepared, tmp_path, monkeypatch) -> None:
    args = runner.parser().parse_args([
        "--dataset", "nslkdd", "--cache", str(prepared / "nslkdd"),
        "--output", str(tmp_path / "unused.json"), "--model", "relu",
        "--epochs", "3", "--batch-size", "16", "--hidden", "16",
        "--seeds", "0", "--device", "cpu", "--eval-every", "1",
        "--checkpoint-every", "1", "--threads", "1",
        "--checkpoint-policy", "fixed_final_epoch_v1",
        "--loss-weighting", "sqrt_inverse_fit_only_v1",
    ])
    runner.validate_args(args)
    data = runner.prepare_data(args)
    scores = iter([99.0, 1.0, 2.0])
    monkeypatch.setattr(runner, "validation_score",
                        lambda *_args, **_kwargs: next(scores))
    result = runner.train_one(
        "relu", 0, data, models, args, torch.device("cpu"), "fixed-final",
        tmp_path / "fixed.pt")
    assert result["best_epoch"] == 3
    assert result["best_validation_macro_recall_pct"] == 2.0
    assert [row["validation_macro_recall_pct"] for row in result["history"]] == [99.0, 1.0, 2.0]


def test_legacy_selector_is_explicit_not_default(prepared, tmp_path, monkeypatch) -> None:
    args = runner.parser().parse_args([
        "--dataset", "nslkdd", "--cache", str(prepared / "nslkdd"),
        "--output", str(tmp_path / "unused.json"), "--model", "relu",
        "--epochs", "3", "--batch-size", "16", "--hidden", "16",
        "--seeds", "0", "--device", "cpu", "--eval-every", "1",
        "--checkpoint-every", "1", "--threads", "1",
        "--checkpoint-policy", "best_validation_macro_recall_legacy_v1",
    ])
    runner.validate_args(args)
    data = runner.prepare_data(args)
    scores = iter([99.0, 1.0, 2.0])
    monkeypatch.setattr(runner, "validation_score",
                        lambda *_args, **_kwargs: next(scores))
    result = runner.train_one(
        "relu", 0, data, models, args, torch.device("cpu"), "legacy",
        tmp_path / "legacy.pt")
    assert result["best_epoch"] == 1
    assert runner.parser().parse_args([
        "--dataset", "nslkdd", "--cache", "c", "--output", "x.json",
        "--model", "relu",
    ]).checkpoint_policy == "fixed_final_epoch_v1"
