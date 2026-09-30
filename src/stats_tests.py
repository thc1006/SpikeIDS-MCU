"""
Statistical testing framework for GLOBECOM 2026 submission.

Provides:
- wilcoxon_signed_rank: paired non-parametric test with effect size
- bootstrap_ci: percentile bootstrap 95% CI for mean
- cohen_d: paired Cohen's d (d_z)
- holm_bonferroni: FWE control for confirmatory hypotheses (primary)
- benjamini_hochberg: FDR control for exploratory hypotheses (secondary)
- run_full_analysis: orchestrator that reads a multi-seed results JSON and
  writes stats_tests.json with all p-values + effect sizes + corrections
- tost_paired / tost_wilcoxon: paired TOST equivalence tests (v4) with
  delta_min, power (normal approx + Monte Carlo) and required-n helpers;
  run_equivalence_analysis orchestrates them with Holm-Bonferroni

Design notes
------------
Holm-Bonferroni is used for the confirmatory hypotheses because it strictly
dominates vanilla Bonferroni (Holm 1979) while preserving FWE. Benjamini-
Hochberg is used only for exploratory per-class analysis where the number
of hypotheses (e.g., 15 classes in CICIDS2017) makes FWE control too
conservative to detect real effects.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, Iterable, Tuple

import numpy as np
from scipy import stats


# ── Paired Wilcoxon signed-rank ───────────────────────────────────────

def wilcoxon_signed_rank(
    x: Iterable[float],
    y: Iterable[float],
    name_x: str = "x",
    name_y: str = "y",
) -> dict:
    """Paired Wilcoxon signed-rank test with Cohen's d_z effect size.

    Returns a dict with:
      statistic, p_value, effect_size, direction, n_pairs,
      mean_x, mean_y, mean_diff, name_x, name_y
    """
    x = np.asarray(list(x), dtype=float)
    y = np.asarray(list(y), dtype=float)
    if x.shape != y.shape:
        raise ValueError(f"x and y must have equal length ({x.shape} vs {y.shape})")

    n = int(x.size)
    diff = x - y

    # If all differences are exactly zero, scipy raises; handle gracefully.
    if np.all(diff == 0):
        return {
            "statistic": 0.0,
            "p_value": 1.0,
            "effect_size": 0.0,
            "direction": "tie",
            "n_pairs": n,
            "mean_x": float(np.mean(x)),
            "mean_y": float(np.mean(y)),
            "mean_diff": 0.0,
            "name_x": name_x,
            "name_y": name_y,
        }

    try:
        stat, p = stats.wilcoxon(x, y, zero_method="wilcox",
                                  alternative="two-sided", method="auto")
    except ValueError:
        stat, p = float("nan"), float("nan")

    effect = cohen_d(x, y)
    if np.mean(diff) > 0:
        direction = f"{name_x}>{name_y}"
    elif np.mean(diff) < 0:
        direction = f"{name_x}<{name_y}"
    else:
        direction = "tie"

    return {
        "statistic": float(stat),
        "p_value": float(p),
        "effect_size": float(effect),
        "direction": direction,
        "n_pairs": n,
        "mean_x": float(np.mean(x)),
        "mean_y": float(np.mean(y)),
        "mean_diff": float(np.mean(diff)),
        "name_x": name_x,
        "name_y": name_y,
    }


# ── Bootstrap CI ──────────────────────────────────────────────────────

def bootstrap_ci(
    values: Iterable[float],
    confidence: float = 0.95,
    n_boot: int = 10_000,
    seed: int = 0,
) -> Tuple[float, float]:
    """Percentile bootstrap CI for the mean of *values*."""
    values = np.asarray(list(values), dtype=float)
    n = values.size
    if n == 0:
        return (float("nan"), float("nan"))
    # Degenerate case: zero variance
    if np.all(values == values[0]):
        v = float(values[0])
        return (v, v)

    rng = np.random.default_rng(seed)
    # Use numpy.random.Generator.integers — fast, deterministic
    idx = rng.integers(0, n, size=(n_boot, n))
    means = values[idx].mean(axis=1)
    alpha = 1.0 - confidence
    lo = float(np.percentile(means, 100 * alpha / 2))
    hi = float(np.percentile(means, 100 * (1 - alpha / 2)))
    return (lo, hi)


# ── Paired Cohen's d_z ────────────────────────────────────────────────

def cohen_d(x: Iterable[float], y: Iterable[float]) -> float:
    """Paired Cohen's d_z = mean(diff) / std(diff, ddof=1)."""
    x = np.asarray(list(x), dtype=float)
    y = np.asarray(list(y), dtype=float)
    diff = x - y
    if diff.size < 2:
        return float("nan")
    sd = float(np.std(diff, ddof=1))
    if sd == 0.0:
        return 0.0
    return float(np.mean(diff) / sd)


# ── Holm-Bonferroni (confirmatory, FWE control) ───────────────────────

def holm_bonferroni(
    p_values: Dict[str, float],
    alpha: float = 0.05,
) -> Dict[str, Tuple[float, float, bool]]:
    """Holm-Bonferroni step-down for FWE control.

    Returns {name: (p_raw, p_corrected, reject_H0)}.
    Corrected p is clipped to [0, 1] and is non-decreasing in raw-p order.
    """
    names = list(p_values.keys())
    raws = np.array([p_values[n] for n in names], dtype=float)
    m = len(names)
    order = np.argsort(raws)

    adj = np.empty(m, dtype=float)
    running_max = 0.0
    for rank, idx in enumerate(order):
        scale = m - rank  # step-down weights
        p_adj = raws[idx] * scale
        running_max = max(running_max, p_adj)  # enforce monotonicity
        adj[idx] = min(1.0, running_max)

    result: Dict[str, Tuple[float, float, bool]] = {}
    for name, raw, p_adj in zip(names, raws, adj):
        result[name] = (float(raw), float(p_adj), bool(p_adj <= alpha))
    return result


# ── Benjamini-Hochberg (exploratory, FDR control) ────────────────────

def benjamini_hochberg(
    p_values: Dict[str, float],
    alpha: float = 0.05,
) -> Dict[str, Tuple[float, float, bool]]:
    """Benjamini-Hochberg step-up for FDR control.

    Returns {name: (p_raw, p_adjusted, reject_H0)}.
    """
    names = list(p_values.keys())
    raws = np.array([p_values[n] for n in names], dtype=float)
    m = len(names)
    order = np.argsort(raws)

    # BH adjusted p: p_(i) * m / i, enforced monotone from the top down.
    adj_sorted = np.empty(m, dtype=float)
    running_min = 1.0
    for rank in range(m - 1, -1, -1):
        i = rank + 1  # 1-based rank
        p_adj = raws[order[rank]] * m / i
        running_min = min(running_min, p_adj)
        adj_sorted[rank] = min(1.0, running_min)

    adj = np.empty(m, dtype=float)
    for rank, idx in enumerate(order):
        adj[idx] = adj_sorted[rank]

    result: Dict[str, Tuple[float, float, bool]] = {}
    for name, raw, p_adj in zip(names, raws, adj):
        result[name] = (float(raw), float(p_adj), bool(p_adj <= alpha))
    return result


# ── Orchestrator: read multi-seed JSON, run the 5 key comparisons ────

# Metric keys inside per_seed entries
_METRICS = ("overall_acc", "macro_acc", "macro_f1", "macro_precision",
            "macro_recall", "mcc")


def _extract(per_seed_list, key):
    return np.array([float(r[key]) for r in per_seed_list], dtype=float)


def run_full_analysis(
    input_path: str,
    output_path: str | None = None,
    alpha: float = 0.05,
) -> dict:
    """Run paired Wilcoxon + Holm-Bonferroni on the primary comparisons.

    Input: a JSON file produced by experiment_multiseed.py (or a dict with
    the same structure). Expects top-level keys "relu" and "qcfs_L4", each
    with {"per_seed": [metrics, metrics, ...]}.

    Output: dict with per-metric Wilcoxon results, Holm-Bonferroni correction
    over the *overall_acc* and *macro_f1* comparisons (primary confirmatory
    set), and per-seed means ± 95% bootstrap CI.
    """
    in_path = Path(input_path)
    data = json.loads(in_path.read_text())

    summary: dict = {
        "source": str(in_path),
        "alpha": alpha,
        "comparisons": {},
        "bootstrap_ci": {},
    }

    if "relu" in data and "qcfs_L4" in data:
        relu_seeds = data["relu"]["per_seed"]
        qcfs_seeds = data["qcfs_L4"]["per_seed"]

        p_values_primary: Dict[str, float] = {}
        for metric in _METRICS:
            try:
                x = _extract(relu_seeds, metric)
                y = _extract(qcfs_seeds, metric)
            except KeyError:
                continue
            w = wilcoxon_signed_rank(x, y, "ReLU", "QCFS_L4")
            summary["comparisons"][metric] = w
            summary["bootstrap_ci"][metric] = {
                "ReLU": bootstrap_ci(x),
                "QCFS_L4": bootstrap_ci(y),
            }
            if metric in ("overall_acc", "macro_f1"):
                p_values_primary[metric] = w["p_value"]

        summary["holm_bonferroni_primary"] = {
            k: {"p_raw": v[0], "p_corrected": v[1], "reject_H0": v[2]}
            for k, v in holm_bonferroni(p_values_primary, alpha=alpha).items()
        }

    # Per-class exploratory (BH-FDR) — only if both sides are present.
    if "relu" in data and "qcfs_L4" in data:
        relu_agg = data.get("relu", {}).get("aggregate", {}).get("per_class", {})
        qcfs_agg = data.get("qcfs_L4", {}).get("aggregate", {}).get("per_class", {})
        if relu_agg and qcfs_agg:
            # per-class macro_f1 means at the aggregate level → approximate exploratory BH
            per_class_p: Dict[str, float] = {}
            for cls in relu_agg.keys():
                if cls not in qcfs_agg:
                    continue
                r = _extract_per_class(data["relu"]["per_seed"], cls, "f1")
                q = _extract_per_class(data["qcfs_L4"]["per_seed"], cls, "f1")
                if r is None or q is None:
                    continue
                w = wilcoxon_signed_rank(r, q, "ReLU", "QCFS_L4")
                per_class_p[cls] = w["p_value"]
            if per_class_p:
                summary["benjamini_hochberg_per_class_f1"] = {
                    k: {"p_raw": v[0], "p_adjusted": v[1], "reject_H0": v[2]}
                    for k, v in benjamini_hochberg(per_class_p, alpha=alpha).items()
                }

    if output_path:
        Path(output_path).write_text(json.dumps(summary, indent=2))

    return summary


def _extract_per_class(per_seed, cls, metric):
    try:
        return np.array([float(r["per_class"][cls][metric]) for r in per_seed],
                         dtype=float)
    except (KeyError, TypeError):
        return None


# ── TOST equivalence testing (v4) ────────────────────────────────────
#
# A non-significant Wilcoxon/t-test does NOT support equivalence
# (absence of evidence != evidence of absence). Equivalence needs a
# pre-specified margin delta and two one-sided tests (Schuirmann 1987):
#   H01: mu_d <= -delta   vs  H11: mu_d > -delta
#   H02: mu_d >= +delta   vs  H12: mu_d < +delta
# Rejecting both at alpha declares |mu_d| < delta, equivalently the
# (1 - 2*alpha) CI of mu_d lies inside (-delta, +delta).

def tost_paired(
    x: Iterable[float],
    y: Iterable[float],
    delta: float,
    alpha: float = 0.05,
) -> dict:
    """Parametric paired TOST on d = x - y with margin +/-delta.

    Returns p_lower, p_upper, p_tost = max(p_lower, p_upper), the
    (1-2*alpha) CI of the mean difference, the decision, and delta_min:
    the smallest margin at which these data would declare equivalence
    (= max(|ci_lo|, |ci_hi|)). delta_min is the honest headline number —
    it says how tight an equivalence the data support instead of a
    pass/fail at one margin.
    """
    if delta <= 0:
        raise ValueError("delta must be positive")
    x = np.asarray(list(x), dtype=float)
    y = np.asarray(list(y), dtype=float)
    if x.shape != y.shape:
        raise ValueError(f"x and y must have equal length ({x.shape} vs {y.shape})")
    d = x - y
    n = int(d.size)
    base = {"test": "tost_t", "delta": float(delta), "alpha": float(alpha), "n": n}
    if n < 2:
        return {**base, "mean_diff": float(d.mean()) if n else float("nan"),
                "sd_diff": float("nan"), "ci": [float("nan"), float("nan")],
                "p_lower": float("nan"), "p_upper": float("nan"),
                "p_tost": float("nan"), "equivalent": False,
                "delta_min": float("nan"), "note": "insufficient pairs"}

    mean_d = float(d.mean())
    sd_d = float(d.std(ddof=1))
    if sd_d == 0.0:
        eq = abs(mean_d) < delta
        return {**base, "mean_diff": mean_d, "sd_diff": 0.0,
                "ci": [mean_d, mean_d],
                "p_lower": 0.0 if mean_d > -delta else 1.0,
                "p_upper": 0.0 if mean_d < delta else 1.0,
                "p_tost": 0.0 if eq else 1.0, "equivalent": bool(eq),
                "delta_min": abs(mean_d), "note": "degenerate variance"}

    se = sd_d / math.sqrt(n)
    df = n - 1
    p_lower = float(stats.t.sf((mean_d + delta) / se, df))   # H01: mu <= -delta
    p_upper = float(stats.t.cdf((mean_d - delta) / se, df))  # H02: mu >= +delta
    ci_lo, ci_hi = stats.t.interval(1.0 - 2.0 * alpha, df, loc=mean_d, scale=se)
    p_tost = max(p_lower, p_upper)
    return {**base, "mean_diff": mean_d, "sd_diff": sd_d,
            "ci": [float(ci_lo), float(ci_hi)],
            "p_lower": p_lower, "p_upper": p_upper, "p_tost": float(p_tost),
            "equivalent": bool(p_tost < alpha),
            "delta_min": float(max(abs(ci_lo), abs(ci_hi)))}


def hodges_lehmann(d: Iterable[float]) -> float:
    """Hodges-Lehmann one-sample estimator: median of the Walsh averages
    (d_i + d_j) / 2 over i <= j."""
    d = np.asarray(list(d), dtype=float)
    if d.size == 0:
        return float("nan")
    i, j = np.triu_indices(d.size)
    return float(np.median((d[i] + d[j]) / 2.0))


def tost_wilcoxon(
    x: Iterable[float],
    y: Iterable[float],
    delta: float,
    alpha: float = 0.05,
) -> dict:
    """Non-parametric paired TOST: two one-sided Wilcoxon signed-rank tests
    on the shifted differences d + delta (alternative 'greater') and
    d - delta (alternative 'less'). Matches the v3 choice of a signed-rank
    test for the difference hypotheses; use it when normality of d is
    doubtful. The exact one-sided p-value floor is 2**-n, so n <= 4 can
    never declare equivalence and n = 5 only when all five shifted
    differences share a sign — small arms are power-limited by construction.
    """
    if delta <= 0:
        raise ValueError("delta must be positive")
    x = np.asarray(list(x), dtype=float)
    y = np.asarray(list(y), dtype=float)
    if x.shape != y.shape:
        raise ValueError(f"x and y must have equal length ({x.shape} vs {y.shape})")
    d = x - y
    n = int(d.size)
    base = {"test": "tost_wilcoxon", "delta": float(delta),
            "alpha": float(alpha), "n": n,
            "median_diff": float(np.median(d)) if n else float("nan"),
            # Hodges-Lehmann pseudo-median: the location the signed-rank
            # bounds actually apply to (TOSTER::wilcox_TOST convention).
            "hodges_lehmann": hodges_lehmann(d) if n else float("nan")}
    if n < 2:
        return {**base, "p_lower": float("nan"), "p_upper": float("nan"),
                "p_tost": float("nan"), "equivalent": False, "note": "insufficient pairs"}

    def _one_sided(values, alternative):
        if np.all(values == 0):
            return 1.0  # nothing to rank: cannot reject
        try:
            return float(stats.wilcoxon(values, zero_method="wilcox",
                                        alternative=alternative).pvalue)
        except ValueError:
            return float("nan")

    p_lower = _one_sided(d + delta, "greater")  # rejects median_d <= -delta
    p_upper = _one_sided(d - delta, "less")     # rejects median_d >= +delta
    p_tost = max(p_lower, p_upper)
    return {**base, "p_lower": p_lower, "p_upper": p_upper,
            "p_tost": float(p_tost),
            "equivalent": bool(not math.isnan(p_tost) and p_tost < alpha)}


def tost_power_normal(
    n: int,
    sd_diff: float,
    delta: float,
    alpha: float = 0.05,
    true_diff: float = 0.0,
) -> float:
    """Known-variance normal approximation to paired-TOST power
    (Julious 2004): P(both one-sided tests reject | true mean = true_diff)."""
    if n < 2 or sd_diff <= 0 or delta <= 0:
        return 0.0
    se = sd_diff / math.sqrt(n)
    z = stats.norm.ppf(1.0 - alpha)
    upper = stats.norm.cdf((delta - true_diff) / se - z)
    lower = stats.norm.cdf((-delta - true_diff) / se + z)
    return float(max(0.0, upper - lower))


def tost_power_mc(
    n: int,
    sd_diff: float,
    delta: float,
    alpha: float = 0.05,
    true_diff: float = 0.0,
    n_sim: int = 20_000,
    seed: int = 0,
) -> float:
    """Monte-Carlo power of the parametric paired TOST with the variance
    estimated per sample (i.e., the test actually run). Used to check the
    normal approximation and to size seed counts."""
    if n < 2 or sd_diff <= 0 or delta <= 0:
        return 0.0
    rng = np.random.default_rng(seed)
    d = rng.normal(true_diff, sd_diff, size=(n_sim, n))
    mean = d.mean(axis=1)
    se = d.std(axis=1, ddof=1) / math.sqrt(n)
    tcrit = stats.t.ppf(1.0 - alpha, n - 1)
    reject_lower = (mean + delta) / se > tcrit
    reject_upper = (mean - delta) / se < -tcrit
    return float(np.mean(reject_lower & reject_upper))


def tost_required_n(
    sd_diff: float,
    delta: float,
    alpha: float = 0.05,
    power: float = 0.8,
    true_diff: float = 0.0,
    n_max: int = 100_000,
) -> int:
    """Smallest paired sample size whose approximate TOST power reaches
    *power* at margin delta. Returns n_max + 1 when unattainable (e.g.
    |true_diff| >= delta)."""
    if abs(true_diff) >= delta:
        return n_max + 1
    for n in range(2, n_max + 1):
        if tost_power_normal(n, sd_diff, delta, alpha, true_diff) >= power:
            return n
    return n_max + 1


def run_equivalence_analysis(
    pairs: Dict[str, Tuple[Iterable[float], Iterable[float]]],
    delta: float,
    alpha: float = 0.05,
    deltas_sensitivity: Iterable[float] = (0.5, 1.0, 2.0, 3.0),
    powers: Iterable[float] = (0.8, 0.9),
) -> dict:
    """Run parametric + non-parametric TOST on named paired arms, apply
    Holm-Bonferroni across the parametric p_tost values (one family of
    equivalence claims), and report delta_min, a margin sensitivity sweep,
    and the seed count needed to reach the requested power at *delta*."""
    out: dict = {"delta": float(delta), "alpha": float(alpha),
                 "pairs": {}, "sensitivity": {}}
    p_family: Dict[str, float] = {}
    for name, (x, y) in pairs.items():
        x = np.asarray(list(x), dtype=float)
        y = np.asarray(list(y), dtype=float)
        t_res = tost_paired(x, y, delta, alpha)
        w_res = tost_wilcoxon(x, y, delta, alpha)
        d = x - y
        # Shapiro-Wilk on the differences: when it fails, read the
        # Wilcoxon TOST rather than the t-based one.
        sw_p = float(stats.shapiro(d).pvalue) if d.size >= 3 and d.std() > 0 else float("nan")
        entry = {"tost_t": t_res, "tost_wilcoxon": w_res, "normality_shapiro_p": sw_p}
        if not math.isnan(t_res.get("sd_diff", float("nan"))) and t_res["sd_diff"] > 0:
            entry["required_n"] = {
                f"power_{p:.2f}": tost_required_n(t_res["sd_diff"], delta, alpha, p)
                for p in powers}
            entry["power_at_n"] = {
                "normal_approx": tost_power_normal(t_res["n"], t_res["sd_diff"], delta, alpha),
                "monte_carlo": tost_power_mc(t_res["n"], t_res["sd_diff"], delta, alpha),
            }
        out["pairs"][name] = entry
        if not math.isnan(t_res["p_tost"]):
            p_family[name] = t_res["p_tost"]
        out["sensitivity"][name] = {
            f"{dd:g}": bool(tost_paired(x, y, dd, alpha)["equivalent"])
            for dd in deltas_sensitivity}
    if p_family:
        out["holm_bonferroni_tost_t"] = {
            k: {"p_raw": v[0], "p_corrected": v[1], "equivalent": v[2]}
            for k, v in holm_bonferroni(p_family, alpha=alpha).items()}
    return out


# ── CLI ───────────────────────────────────────────────────────────────

def _main():
    import argparse
    ap = argparse.ArgumentParser(description="Statistical testing for SNN-IDS")
    ap.add_argument("--input", required=True, help="multiseed results JSON")
    ap.add_argument("--output", default=None, help="stats_tests.json output")
    ap.add_argument("--alpha", type=float, default=0.05)
    args = ap.parse_args()
    out = args.output or str(Path(args.input).with_name("stats_tests.json"))
    result = run_full_analysis(args.input, out, alpha=args.alpha)
    print(f"Wrote {out}")
    for m, comp in result.get("comparisons", {}).items():
        print(f"  {m}: p={comp['p_value']:.4f} d_z={comp['effect_size']:.3f} {comp['direction']}")


if __name__ == "__main__":
    _main()
