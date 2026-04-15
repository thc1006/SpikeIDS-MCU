"""Run the GLOBECOM statistical test battery.

Compares ReLU MLP vs. the NPU-eligible baselines (QCFS, TinyCNN, RF)
across all three datasets, applying Holm-Bonferroni FWE control per
dataset. Cross-file comparisons (20-seed ReLU vs. 5-seed TinyCNN) use
a paired test on the first 5 seeds only, since seeds were aligned.

Usage:
    python scripts/run_globecom_stats.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy import stats as sp

ROOT = Path(__file__).resolve().parent.parent
R = ROOT / "results"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _per_seed_list(data: dict, key: str | None = None) -> list[dict]:
    """Extract per-seed metric records, handling nested vs flat schemas."""
    if key and key in data:
        return data[key]["per_seed"]
    return data["per_seed"]


def _metric(per_seed: list[dict], metric: str, limit: int | None = None) -> np.ndarray:
    vals = [float(r[metric]) for r in per_seed]
    if limit is not None:
        vals = vals[:limit]
    return np.array(vals, dtype=float)


def wilcoxon_pair(x: np.ndarray, y: np.ndarray) -> dict:
    if len(x) != len(y):
        raise ValueError(f"length mismatch: {len(x)} vs {len(y)}")
    diff = x - y
    if np.all(diff == 0):
        return {"p": 1.0, "statistic": 0.0, "dz": 0.0, "mean_diff": 0.0, "n": len(x)}
    res = sp.wilcoxon(x, y, zero_method="wilcox", alternative="two-sided")
    sd = np.std(diff, ddof=1)
    dz = float(np.mean(diff) / sd) if sd > 0 else 0.0
    return {
        "p": float(res.pvalue),
        "statistic": float(res.statistic),
        "dz": dz,
        "mean_diff": float(np.mean(diff)),
        "n": int(len(x)),
    }


def holm_bonferroni(pvals: dict[str, float], alpha: float = 0.05) -> dict[str, dict]:
    """Returns {name: {p_raw, p_adj, reject}} after Holm-Bonferroni."""
    names = list(pvals.keys())
    raws = np.array([pvals[n] for n in names], dtype=float)
    m = len(raws)
    order = np.argsort(raws)

    adj_sorted = np.empty(m)
    running = 0.0
    for rank in range(m):
        i = rank + 1
        p_adj = raws[order[rank]] * (m - rank)
        running = max(running, p_adj)
        adj_sorted[rank] = min(1.0, running)

    out: dict[str, dict] = {}
    for rank, idx in enumerate(order):
        out[names[idx]] = {
            "p_raw": float(raws[idx]),
            "p_adj": float(adj_sorted[rank]),
            "reject": bool(adj_sorted[rank] <= alpha),
        }
    return out


def bootstrap_ci(vals: np.ndarray, n_boot: int = 10_000, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    n = len(vals)
    means = [float(np.mean(vals[rng.integers(0, n, size=n)])) for _ in range(n_boot)]
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)


def tost_paired(
    x: np.ndarray,
    y: np.ndarray,
    delta: float = 1.0,
    alpha: float = 0.05,
) -> dict:
    """Paired TOST for equivalence of mean difference within +/- delta.

    Returns p-values for lower/upper one-sided tests, 90% CI of mean diff,
    and a boolean equivalence decision.
    """
    if len(x) != len(y):
        raise ValueError(f"length mismatch: {len(x)} vs {len(y)}")
    if len(x) < 2:
        return {
            "delta": float(delta),
            "alpha": float(alpha),
            "n": int(len(x)),
            "mean_diff": float(np.mean(x - y)) if len(x) else 0.0,
            "ci90": [float("nan"), float("nan")],
            "p_lower": float("nan"),
            "p_upper": float("nan"),
            "p_tost": float("nan"),
            "equivalent": False,
            "note": "insufficient pairs",
        }

    d = x - y
    n = len(d)
    mean_diff = float(np.mean(d))
    sd = float(np.std(d, ddof=1))
    if sd == 0.0:
        ci90 = [mean_diff, mean_diff]
        equivalent = (-delta < mean_diff < delta)
        return {
            "delta": float(delta),
            "alpha": float(alpha),
            "n": int(n),
            "mean_diff": mean_diff,
            "ci90": ci90,
            "p_lower": 0.0 if mean_diff > -delta else 1.0,
            "p_upper": 0.0 if mean_diff < delta else 1.0,
            "p_tost": 0.0 if equivalent else 1.0,
            "equivalent": bool(equivalent),
            "note": "degenerate variance",
        }

    se = sd / np.sqrt(n)
    t_lower = (mean_diff + delta) / se  # H01: mu <= -delta
    p_lower = float(1.0 - sp.t.cdf(t_lower, df=n - 1))
    t_upper = (mean_diff - delta) / se  # H02: mu >= +delta
    p_upper = float(sp.t.cdf(t_upper, df=n - 1))

    ci_lo, ci_hi = sp.t.interval(0.90, df=n - 1, loc=mean_diff, scale=se)
    p_tost = max(p_lower, p_upper)
    equivalent = (p_lower < alpha) and (p_upper < alpha)
    return {
        "delta": float(delta),
        "alpha": float(alpha),
        "n": int(n),
        "mean_diff": mean_diff,
        "ci90": [float(ci_lo), float(ci_hi)],
        "p_lower": p_lower,
        "p_upper": p_upper,
        "p_tost": float(p_tost),
        "equivalent": bool(equivalent),
    }


def main() -> None:
    # ── Load result files ─────────────────────────────────────────────
    nsl_multi = _load(R / "multiseed_20.json")
    unsw_20 = _load(R / "unsw_multiseed_20.json")
    cnn = _load(R / "cnn_baseline_merged.json")
    cicids = _load(R / "cicids2017_multiseed_experiment.json")

    alpha = 0.05
    eq_delta_pp = 1.0
    report: dict = {
        "alpha": alpha,
        "equivalence_delta_pp": eq_delta_pp,
        "datasets": {},
    }

    # ── NSL-KDD comparisons ───────────────────────────────────────────
    nsl_relu = _per_seed_list(nsl_multi, "relu")
    nsl_qcfs = _per_seed_list(nsl_multi, "qcfs_L4")
    nsl_cnn_seeds = cnn["nslkdd"]["per_seed"]
    n_cnn = len(nsl_cnn_seeds)

    pairs = {
        "nslkdd_relu_vs_qcfs": (
            _metric(nsl_relu, "overall_acc"),
            _metric(nsl_qcfs, "overall_acc"),
        ),
        "nslkdd_relu_vs_cnn": (
            _metric(nsl_relu, "overall_acc", limit=n_cnn),
            _metric(nsl_cnn_seeds, "overall_acc"),
        ),
    }
    nsl_pvals = {k: wilcoxon_pair(x, y)["p"] for k, (x, y) in pairs.items()}
    nsl_adj = holm_bonferroni(nsl_pvals)
    report["datasets"]["nslkdd"] = {
        "comparisons": {
            k: {**wilcoxon_pair(*pairs[k]), **nsl_adj[k]}
            for k in pairs
        },
        "equivalence_tost": {
            "relu_vs_qcfs_overall_acc": tost_paired(
                _metric(nsl_relu, "overall_acc"),
                _metric(nsl_qcfs, "overall_acc"),
                delta=eq_delta_pp,
                alpha=alpha,
            ),
            "relu_vs_qcfs_macro_f1": tost_paired(
                _metric(nsl_relu, "macro_f1"),
                _metric(nsl_qcfs, "macro_f1"),
                delta=eq_delta_pp,
                alpha=alpha,
            ),
        },
        "bootstrap_ci": {
            "relu_overall_acc": bootstrap_ci(_metric(nsl_relu, "overall_acc")),
            "qcfs_overall_acc": bootstrap_ci(_metric(nsl_qcfs, "overall_acc")),
            "cnn_overall_acc": bootstrap_ci(_metric(nsl_cnn_seeds, "overall_acc")),
        },
    }

    # ── UNSW-NB15 comparisons ─────────────────────────────────────────
    unsw_relu = _per_seed_list(unsw_20)
    unsw_cnn_seeds = cnn["unsw"]["per_seed"]
    n_cnn_unsw = len(unsw_cnn_seeds)

    pairs_unsw = {
        "unsw_relu_vs_cnn": (
            _metric(unsw_relu, "overall_acc", limit=n_cnn_unsw),
            _metric(unsw_cnn_seeds, "overall_acc"),
        ),
    }

    # UNSW QCFS vs ReLU (if the qcfs multiseed file exists)
    unsw_qcfs_path = R / "unsw_qcfs_multiseed.json"
    if unsw_qcfs_path.exists():
        unsw_qcfs_data = _load(unsw_qcfs_path)
        unsw_qcfs_per_seed = _per_seed_list(unsw_qcfs_data, "qcfs")
        n_qcfs = len(unsw_qcfs_per_seed)
        pairs_unsw["unsw_relu_vs_qcfs"] = (
            _metric(unsw_relu, "overall_acc", limit=n_qcfs),
            _metric(unsw_qcfs_per_seed, "overall_acc"),
        )
    unsw_pvals = {k: wilcoxon_pair(x, y)["p"] for k, (x, y) in pairs_unsw.items()}
    unsw_adj = holm_bonferroni(unsw_pvals)
    unsw_ci = {
        "relu_overall_acc": bootstrap_ci(_metric(unsw_relu, "overall_acc")),
        "cnn_overall_acc": bootstrap_ci(_metric(unsw_cnn_seeds, "overall_acc")),
    }
    if unsw_qcfs_path.exists():
        unsw_ci["qcfs_overall_acc"] = bootstrap_ci(
            _metric(unsw_qcfs_per_seed, "overall_acc")
        )
    report["datasets"]["unsw"] = {
        "comparisons": {
            k: {**wilcoxon_pair(*pairs_unsw[k]), **unsw_adj[k]}
            for k in pairs_unsw
        },
        "equivalence_tost": {},
        "bootstrap_ci": unsw_ci,
    }
    if unsw_qcfs_path.exists():
        report["datasets"]["unsw"]["equivalence_tost"] = {
            "relu_vs_qcfs_overall_acc": tost_paired(
                _metric(unsw_relu, "overall_acc", limit=n_qcfs),
                _metric(unsw_qcfs_per_seed, "overall_acc"),
                delta=eq_delta_pp,
                alpha=alpha,
            ),
            "relu_vs_qcfs_macro_f1": tost_paired(
                _metric(unsw_relu, "macro_f1", limit=n_qcfs),
                _metric(unsw_qcfs_per_seed, "macro_f1"),
                delta=eq_delta_pp,
                alpha=alpha,
            ),
        }

    # ── CICIDS2017 ────────────────────────────────────────────────────
    cic_relu = _per_seed_list(cicids, "relu") if "relu" in cicids else cicids.get("per_seed")
    if cic_relu:
        cic_entry = {
            "n_seeds": len(cic_relu),
            "comparisons": {},
            "bootstrap_ci": {
                "relu_overall_acc": bootstrap_ci(_metric(cic_relu, "overall_acc")),
            },
        }
        pairs_cic: dict = {}
        cic_qcfs_path = R / "cicids_qcfs_multiseed.json"
        if cic_qcfs_path.exists():
            cic_qcfs_data = _load(cic_qcfs_path)
            cic_qcfs_seeds = _per_seed_list(cic_qcfs_data, "qcfs")
            n_cq = len(cic_qcfs_seeds)
            pairs_cic["cicids_relu_vs_qcfs"] = (
                _metric(cic_relu, "overall_acc", limit=n_cq),
                _metric(cic_qcfs_seeds, "overall_acc"),
            )
            cic_entry["bootstrap_ci"]["qcfs_overall_acc"] = bootstrap_ci(
                _metric(cic_qcfs_seeds, "overall_acc")
            )
        cic_tinycnn_path = R / "cnn_baseline_cicids.json"
        if cic_tinycnn_path.exists():
            cnn_extra = _load(cic_tinycnn_path)
            cic_tinycnn_seeds = (
                cnn_extra.get("cicids2017", {}).get("per_seed")
                or cnn_extra.get("per_seed")
            )
            if cic_tinycnn_seeds:
                n_ct = len(cic_tinycnn_seeds)
                pairs_cic["cicids_relu_vs_cnn"] = (
                    _metric(cic_relu, "overall_acc", limit=n_ct),
                    _metric(cic_tinycnn_seeds, "overall_acc"),
                )
                cic_entry["bootstrap_ci"]["cnn_overall_acc"] = bootstrap_ci(
                    _metric(cic_tinycnn_seeds, "overall_acc")
                )
        if pairs_cic:
            cic_pvals = {k: wilcoxon_pair(x, y)["p"] for k, (x, y) in pairs_cic.items()}
            cic_adj = holm_bonferroni(cic_pvals)
            cic_entry["comparisons"] = {
                k: {**wilcoxon_pair(*pairs_cic[k]), **cic_adj[k]}
                for k in pairs_cic
            }
            if "cicids_relu_vs_qcfs" in pairs_cic:
                cic_entry["equivalence_tost"] = {
                    "relu_vs_qcfs_overall_acc": tost_paired(
                        pairs_cic["cicids_relu_vs_qcfs"][0],
                        pairs_cic["cicids_relu_vs_qcfs"][1],
                        delta=eq_delta_pp,
                        alpha=alpha,
                    ),
                    "relu_vs_qcfs_macro_f1": tost_paired(
                        _metric(cic_relu, "macro_f1", limit=n_cq),
                        _metric(cic_qcfs_seeds, "macro_f1"),
                        delta=eq_delta_pp,
                        alpha=alpha,
                    ),
                }
        report["datasets"]["cicids2017"] = cic_entry

    # ── IoT-23 (ReLU vs QCFS equivalence + Wilcoxon) ──────────────────
    iot_relu_path = R / "iot23_multiseed.json"
    iot_qcfs_path = R / "iot23_qcfs_multiseed.json"
    if iot_relu_path.exists() and iot_qcfs_path.exists():
        iot_relu_data = _load(iot_relu_path)
        iot_qcfs_data = _load(iot_qcfs_path)
        iot_relu = _per_seed_list(iot_relu_data)
        iot_qcfs = _per_seed_list(iot_qcfs_data, "qcfs")
        n_iot = min(len(iot_relu), len(iot_qcfs))
        iot_pair = (
            _metric(iot_relu, "overall_acc", limit=n_iot),
            _metric(iot_qcfs, "overall_acc", limit=n_iot),
        )
        iot_w = wilcoxon_pair(*iot_pair)
        iot_w = {
            **iot_w,
            "p_raw": iot_w["p"],
            "p_adj": iot_w["p"],
            "reject": bool(iot_w["p"] <= alpha),
        }
        report["datasets"]["iot23"] = {
            "n_seeds_relu": int(len(iot_relu)),
            "n_seeds_qcfs": int(len(iot_qcfs)),
            "comparisons": {
                "iot23_relu_vs_qcfs": iot_w,
            },
            "equivalence_tost": {
                "relu_vs_qcfs_overall_acc": tost_paired(
                    _metric(iot_relu, "overall_acc", limit=n_iot),
                    _metric(iot_qcfs, "overall_acc", limit=n_iot),
                    delta=eq_delta_pp,
                    alpha=alpha,
                ),
                "relu_vs_qcfs_macro_f1": tost_paired(
                    _metric(iot_relu, "macro_f1", limit=n_iot),
                    _metric(iot_qcfs, "macro_f1", limit=n_iot),
                    delta=eq_delta_pp,
                    alpha=alpha,
                ),
            },
            "bootstrap_ci": {
                "relu_overall_acc": bootstrap_ci(_metric(iot_relu, "overall_acc")),
                "qcfs_overall_acc": bootstrap_ci(_metric(iot_qcfs, "overall_acc")),
            },
        }

    out_path = R / "stats_report_globecom.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"Wrote {out_path}")
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
