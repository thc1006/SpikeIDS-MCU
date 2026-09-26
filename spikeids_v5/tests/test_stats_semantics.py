"""Adversarial tests for statistical estimands and publication formatting."""

from __future__ import annotations

import numpy as np

from paper_contract import fmt_effect, fmt_p
from stats_tests import hodges_lehmann_pseudomedian, tost_wilcoxon, wilcoxon_pair


def test_signed_rank_report_does_not_claim_to_test_mean() -> None:
    left = [1.0, 2.0, 7.0, 9.0]
    right = [0.0, 3.0, 4.0, 8.0]
    report = wilcoxon_pair(left, right)
    differences = np.asarray(left) - np.asarray(right)
    walsh = sorted(
        (differences[i] + differences[j]) / 2.0
        for i in range(len(differences))
        for j in range(i, len(differences))
    )
    assert report["hodges_lehmann_pseudomedian_diff"] == np.median(walsh)
    assert "pseudomedian" in report["test_estimand"]
    assert report["mean_diff_role"].startswith("descriptive only")
    assert "symmetric" in report["symmetry_assumption"]


def test_signed_rank_records_zero_and_tie_rules() -> None:
    report = wilcoxon_pair([1.0, 2.0, 3.0, 4.0], [1.0, 1.0, 4.0, 3.0])
    assert report["n_zero"] == 1
    assert report["absolute_rank_tie_group_sizes"] == [3]
    assert report["zero_method"] == "wilcox_discard_after_declared_rounding"
    assert report["tie_method"] == "average_ranks"


def test_hodges_lehmann_uses_declared_rounding() -> None:
    values = [1.0 + 4e-13, 2.0 - 4e-13]
    assert hodges_lehmann_pseudomedian(values, decimals=12) == 1.5


def test_signed_rank_tost_exposes_robustness_estimand_and_rules() -> None:
    report = tost_wilcoxon([1.0, 2.0, 3.0], [0.9, 2.1, 2.9], delta=1.0)
    assert "pseudomedian" in report["estimand"]
    assert report["role"].startswith("prespecified robustness")
    assert report["zero_method"] == "wilcox_discard_after_declared_rounding"


def test_publication_p_values_preserve_alpha_boundary() -> None:
    below = fmt_p(0.0499999)
    above = fmt_p(0.0500001)
    assert below != above
    assert below == "0.0499999"
    assert above == "0.0500001"


def test_publication_numbers_do_not_round_tiny_effect_to_signed_zero() -> None:
    assert fmt_effect(0.0) == "0"
    assert fmt_effect(4e-12) != "+0"
    assert "10^{" in fmt_effect(-4e-12)
    assert fmt_p(1e-12) != "0"
