"""Paired-seed statistics with explicit estimands, fixed families, and finite JSON.

All differences are LEFT (ReLU) minus RIGHT (QCFS/CNN), in percentage points.
Zero observed variance is NOT treated as infinite inferential certainty.
TOST mean inference and signed-rank location inference are not interchangeable.
"""
from __future__ import annotations
import math
import numpy as np
from scipy import stats, integrate
from contracts import require


def vector(values):
    a = np.asarray(values, dtype=np.float64)
    require(a.ndim == 1 and len(a) > 0 and np.isfinite(a).all(), "Expected nonempty finite 1D observations")
    return a


def differences(x, y):
    x, y = vector(x), vector(y)
    require(x.shape == y.shape, "Paired observations differ in shape")
    with np.errstate(over="ignore",invalid="ignore"):
        d=x-y
    require(np.isfinite(d).all(),"Non-finite paired differences (overflow)")
    return d


def validate_alpha(alpha):
    require(math.isfinite(alpha) and 0 < alpha < .5, "alpha must be finite and in (0,0.5)")


def exact_signed_rank(d, alternative="two-sided", decimals=12):
    """Exact conditional sign-flip distribution; zero discard; tied average ranks.

    Floating differences are rounded at a DECLARED resolution before ranking.
    All rank sums and counts use integer arithmetic. Not Monte Carlo.
    Assumes independent, symmetric differences under the location null.
    """
    require(alternative in ("two-sided", "greater", "less"), "Unknown alternative")
    d = np.round(vector(d), decimals=decimals)
    absolute_nonzero = np.abs(d[d != 0])
    _, tie_counts = np.unique(absolute_nonzero, return_counts=True)
    tie_groups = sorted((int(count) for count in tie_counts if count > 1), reverse=True)
    z = d[d != 0]; n = len(z)
    require(n <= 100, "Exact DP supports <=100 nonzero pairs")
    if n == 0:
        return {"statistic": 0., "p": 1., "n_nonzero": 0,
                "n_zero": int(len(d)), "absolute_rank_tie_group_sizes": [],
                "rank_biserial": 0., "method": "exact_conditional_sign_flip",
                "zero_method": "wilcox_discard_after_declared_rounding",
                "tie_method": "average_ranks", "round_decimals": decimals}
    ranks = np.rint(2*stats.rankdata(np.abs(z), method="average")).astype(int)
    total = int(ranks.sum()); counts = [0]*(total+1); counts[0] = 1; reached = 0
    for rank in ranks:
        r = int(rank)
        for j in range(reached, -1, -1): counts[j+r] += counts[j]
        reached += r
    positive = int(ranks[z>0].sum())
    p_less = sum(counts[:positive+1])/(1 << n)
    p_greater = sum(counts[positive:])/(1 << n)
    p = min(1., 2*min(p_less, p_greater)) if alternative == "two-sided" else (p_less if alternative == "less" else p_greater)
    return {"statistic": min(positive, total-positive)/2 if alternative == "two-sided" else positive/2,
            "p": float(p), "n_nonzero": n, "n_zero": int(len(d)-n),
            "absolute_rank_tie_group_sizes": tie_groups,
            "rank_biserial": (2*positive-total)/total,
            "method": "exact_conditional_sign_flip",
            "zero_method": "wilcox_discard_after_declared_rounding",
            "tie_method": "average_ranks", "round_decimals": decimals}


def hodges_lehmann_pseudomedian(d, decimals=12):
    """One-sample Hodges--Lehmann estimate from all Walsh averages.

    The declared rounding matches the signed-rank test's numerical identity.
    This is a location estimate under the same symmetry interpretation, not a
    sample mean and not a dataset-resampling estimand.
    """
    rounded = np.round(vector(d), decimals=decimals)
    upper = np.triu_indices(len(rounded))
    walsh = (rounded[upper[0]] + rounded[upper[1]]) / 2.0
    require(np.isfinite(walsh).all(), "Non-finite Walsh average")
    return float(np.median(walsh))


def wilcoxon_pair(x, y):
    d = differences(x, y); n = len(d)
    sd = (0. if np.ptp(d) == 0 else float(d.std(ddof=1))) if n > 1 else None
    dz = float(d.mean()/sd) if sd is not None and sd > 0 else None
    signed_rank = exact_signed_rank(d)
    return {**signed_rank, "n": n, "mean_diff": float(d.mean()),
            "median_diff": float(np.median(d)),
            "hodges_lehmann_pseudomedian_diff":
                hodges_lehmann_pseudomedian(d, signed_rank["round_decimals"]),
            "dz": dz, "dz_status": "defined" if dz is not None else "undefined_zero_or_insufficient_variance",
            "test_estimand": "symmetric paired-difference location/pseudomedian",
            "symmetry_assumption":
                "paired seed differences are independent and symmetric about the tested location",
            "mean_diff_role": "descriptive only; the signed-rank p-value does not test the mean",
            "differences": d.tolist()}


def holm(pvalues: dict[str, float | None], alpha=.05):
    validate_alpha(alpha)
    names = list(pvalues)
    require(len(names) > 0, "Empty hypothesis family")
    # Undefined tests REMAIN in the declared family with conservative control p=1.
    ps = {k: 1. if v is None else float(v) for k, v in pvalues.items()}
    require(all(math.isfinite(v) and 0 <= v <= 1 for v in ps.values()), "Invalid p value in Holm family")
    result, previous = {}, 0.
    for i, name in enumerate(sorted(names, key=lambda n: (ps[n], n))):
        adjusted = min(1., max(previous, ps[name]*(len(names)-i))); previous = adjusted
        result[name] = {"p_raw": pvalues[name], "p_adj": adjusted, "reject": pvalues[name] is not None and adjusted < alpha,
                        "family_size": len(names), "undefined_test_retained": pvalues[name] is None}
    return {name: result[name] for name in names}


def tost_paired(x, y, delta, alpha=.05):
    validate_alpha(alpha)
    require(math.isfinite(delta) and delta > 0, "Equivalence margin must be finite and positive")
    d = differences(x, y); n = len(d); mean = float(d.mean())
    sd = (0. if np.ptp(d) == 0 else float(d.std(ddof=1))) if n > 1 else None
    base = {"n": n, "delta": delta, "alpha": alpha, "mean_diff": mean, "sd_diff": sd,
            "estimand": "mean paired seed difference", "confidence_level": 1-2*alpha}
    if sd is None or sd == 0:
        return {**base, "status": "undefined_sampling_variance", "p_lower": None, "p_upper": None,
                "p_tost": None, "ci": None, "equivalent": False, "delta_min_infimum": None,
                "note": "Identical observed differences do not establish a known zero population variance."}
    se = sd/math.sqrt(n)
    p_lower = float(stats.t.sf((mean+delta)/se, n-1))
    p_upper = float(stats.t.cdf((mean-delta)/se, n-1))
    half = float(stats.t.ppf(1-alpha, n-1)*se)
    ci = [mean-half, mean+half]
    return {**base, "status": "defined", "p_lower": p_lower, "p_upper": p_upper, "p_tost": max(p_lower,p_upper),
            "ci": ci, "equivalent": max(p_lower,p_upper) < alpha,
            "delta_min_infimum": max(abs(v) for v in ci),
            "delta_min_scope": "uncorrected sensitivity diagnostic; passing requires STRICTLY greater margin; not a new preregistered bound"}


def tost_wilcoxon(x, y, delta, alpha=.05):
    validate_alpha(alpha)
    require(math.isfinite(delta) and delta > 0, "Invalid equivalence margin")
    d = differences(x,y)
    lower = exact_signed_rank(d+delta, "greater")
    upper = exact_signed_rank(d-delta, "less")
    a = lower["p"]
    b = upper["p"]
    return {"p_lower": a, "p_upper": b, "p_tost": max(a,b), "equivalent": max(a,b) < alpha,
            "estimand": "symmetric location/pseudomedian, NOT generally the mean",
            "symmetry_assumption":
                "paired seed differences are independent and symmetric about the location",
            "zero_method": "wilcox_discard_after_declared_rounding",
            "tie_method": "average_ranks",
            "lower_n_nonzero": lower["n_nonzero"],
            "upper_n_nonzero": upper["n_nonzero"],
            "role": "prespecified robustness analysis; no test-selection switching"}


def bootstrap_mean(values, seed=0, n_boot=10000, confidence=.95, block=1024):
    a = vector(values)
    require(type(n_boot) is int and n_boot > 0 and 0 < confidence < 1 and block > 0, "Invalid bootstrap configuration")
    rng = np.random.default_rng(seed); means = np.empty(n_boot)
    for start in range(0,n_boot,block):
        stop = min(n_boot,start+block)
        means[start:stop] = a[rng.integers(0,len(a),size=(stop-start,len(a)))].mean(1)
    lo = (1-confidence)/2
    return np.quantile(means,[lo,1-lo],method="linear").tolist()


def tost_power_normal_model(n, sigma, delta, alpha=.05, true_difference=0.):
    """Deterministic quadrature for the paired t-TOST rejection probability.

    Normal IID differences with externally assumed sigma and true mean. Integrates
    over the chi-square sampling distribution of variance and independent mean.
    'Numerically integrated under a model' does NOT mean distribution-free power.
    """
    validate_alpha(alpha)
    require(type(n) is int and n >= 2 and all(math.isfinite(v) for v in (sigma,delta,true_difference))
            and sigma > 0 and delta > 0, "Invalid power assumptions")
    df=n-1; tc=stats.t.ppf(1-alpha,df); se=sigma/math.sqrt(n)
    vmax=df*(delta/(tc*se))**2
    pmax=float(stats.chi2.cdf(vmax,df))
    def conditional(u):
        v=stats.chi2.ppf(u,df)
        half=tc*se*math.sqrt(v/df)
        return max(0.,float(stats.norm.cdf((delta-half-true_difference)/se)-
                           stats.norm.cdf((-delta+half-true_difference)/se)))
    probability,error=integrate.quad(conditional,0.,pmax,epsabs=1e-8,epsrel=1e-7,limit=150)
    return {"power": min(1.,max(0.,float(probability))), "integration_error_estimate": float(error),
            "n": n, "sigma_assumed": sigma, "true_difference_assumed": true_difference,
            "method": "normal_model_variance_integrated_t_TOST", "multiplicity": "individual test; not familywise power"}


def required_n(sigma,delta,alpha=.05,power=.8,true_difference=0.,n_max=100000):
    require(0 < power < 1 and type(n_max) is int and n_max >= 2, "Invalid required-n target")
    # Restrict planning to the interior alternative where monotone bracketing applies.
    require(abs(true_difference) < delta, "Power planning requires a true mean strictly inside the equivalence region")
    def value(n): return tost_power_normal_model(n,sigma,delta,alpha,true_difference)["power"]
    if value(2) >= power: return 2
    low,high=2,4
    while high<n_max and value(high)<power: low,high=high,min(n_max,high*2)
    if value(high)<power: return None
    while high-low>1:
        mid=(low+high)//2
        if value(mid)>=power: high=mid
        else: low=mid
    return high
