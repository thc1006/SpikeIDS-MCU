"""v4: ReLU vs QCFS (T=1 SNN) equivalence with paired TOST on all four datasets.

Why this exists: v3 argued "statistically indistinguishable" from
non-significant Wilcoxon tests, which is not evidence of equivalence.
This script re-analyses the same per-seed result files with two one-sided
tests at a pre-specified margin, reports the smallest margin each dataset
actually supports (delta_min), and sizes the seed counts needed for a
conclusive test.

Arms are paired by seed order (first n seeds of the longer arm), exactly
as scripts/run_globecom_stats.py did. Differences are ReLU - QCFS in
percentage points, so positive = ReLU higher.

Usage:
    uv run scripts/run_v4_equivalence.py [--delta 1.0] [--alpha 0.05]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_globecom_stats import _load, _metric, _per_seed_list  # noqa: E402
from stats_tests import run_equivalence_analysis  # noqa: E402

R = ROOT / "results"
METRICS = ("overall_acc", "macro_f1")

# Training batch size is not recorded in the result JSONs; it is fixed in the
# experiment scripts (DataLoader(..., batch_size=N, shuffle=True)). Keep this
# table in sync with src/ — tests/test_v4_equivalence.py greps the scripts.
TRAIN_BATCH = {
    "nslkdd": {"relu": ("experiment_multiseed.py", 512), "qcfs": ("experiment_multiseed.py", 512)},
    "unsw": {"relu": ("experiment_unsw.py", 512), "qcfs": ("experiment_unsw_qcfs.py", 512)},
    "cicids2017": {"relu": ("experiment_cicids2017.py", 512), "qcfs": ("experiment_cicids_qcfs.py", 512)},
    "iot23": {"relu": ("experiment_iot23.py", 1024), "qcfs": ("experiment_iot23_qcfs.py", 1024)},
}


def pair_validity(ds: str, relu_meta: dict, qcfs_meta: dict) -> dict:
    """A paired ReLU-vs-QCFS test is only meaningful if both arms were trained
    under the same budget. Compare epochs (from the JSONs) and batch size
    (from TRAIN_BATCH) and list every mismatch as a confound."""
    confounds = []
    er, eq = relu_meta.get("epochs"), qcfs_meta.get("epochs")
    if er != eq:
        confounds.append(f"epochs {er} vs {eq}")
    br, bq = TRAIN_BATCH[ds]["relu"][1], TRAIN_BATCH[ds]["qcfs"][1]
    if br != bq:
        confounds.append(f"batch_size {br} vs {bq}")
    for key in ("n_train", "n_test"):
        if relu_meta.get(key) != qcfs_meta.get(key):
            confounds.append(f"{key} {relu_meta.get(key)} vs {qcfs_meta.get(key)}")
    return {"valid": not confounds, "confounds": confounds}


def load_arms() -> dict[str, dict]:
    """Return {dataset: {relu, qcfs, n, validity}} with per-seed lists,
    the paired count, and the training-budget validity check."""
    nsl = _load(R / "multiseed_20.json")
    files = {
        "nslkdd": (nsl, "relu", nsl, "qcfs_L4"),
        "unsw": (_load(R / "unsw_multiseed_20.json"), None,
                 _load(R / "unsw_qcfs_multiseed.json"), "qcfs"),
        "cicids2017": (_load(R / "cicids2017_multiseed_experiment.json"), "relu",
                       _load(R / "cicids_qcfs_multiseed.json"), "qcfs"),
        "iot23": ((_load(R / "iot23_multiseed_v4.json") if (R / "iot23_multiseed_v4.json").exists()
                   else _load(R / "iot23_multiseed.json")), None,
                  (_load(R / "iot23_qcfs_multiseed_v4.json") if (R / "iot23_qcfs_multiseed_v4.json").exists()
                   else _load(R / "iot23_qcfs_multiseed.json")), "qcfs"),
    }
    arms = {}
    for ds, (rd, rk, qd, qk) in files.items():
        r, q = _per_seed_list(rd, rk), _per_seed_list(qd, qk)
        n = min(len(r), len(q))
        if rd.get("seeds", list(range(len(r))))[:n] != qd.get("seeds", list(range(len(q))))[:n]:
            raise ValueError(f"{ds}: seed sequences differ, cannot pair by order")
        arms[ds] = {"relu": r, "qcfs": q, "n": n, "validity": pair_validity(ds, rd, qd)}
    return arms


def build_pairs(arms, valid_only: bool):
    pairs = {}
    for ds, a in arms.items():
        if valid_only and not a["validity"]["valid"]:
            continue
        for m in METRICS:
            pairs[f"{ds}:{m}"] = (_metric(a["relu"], m, limit=a["n"]),
                                  _metric(a["qcfs"], m, limit=a["n"]))
    return pairs


def to_markdown(report: dict, arms) -> str:
    d = report["delta"]
    lines = [
        f"# ReLU vs QCFS (T=1 SNN) equivalence — paired TOST, margin ±{d:g} pp, α = {report['alpha']}",
        "",
        "Primary test: parametric paired TOST (Schuirmann 1987; Lakens 2017) on",
        "d = ReLU − QCFS in percentage points (positive = ReLU higher); it passes",
        "iff the 90 % t-CI of the mean difference lies inside (−δ, +δ). The",
        "Wilcoxon TOST (two one-sided signed-rank tests, TOSTER::wilcox_TOST",
        "convention, bounds on the Hodges-Lehmann pseudo-median) is a robustness",
        "check only. δ = 1 pp was pre-specified in the GLOBECOM 2026 submission.",
        "Holm-Bonferroni runs over one family = all valid dataset×metric",
        "equivalence claims (IUT + Holm strongly controls FWER).",
        "δ_min = smallest margin these data would pass at (uncorrected).",
        "n★ = seeds needed for 80 % / 90 % power at δ if the true difference is 0.",
        "",
        "SW p = Shapiro-Wilk normality of the differences (< 0.05 ⇒ prefer the Wilcoxon column).",
        "",
        "| Dataset | Metric | n | ReLU | QCFS | mean diff | 90 % CI | SW p | p_TOST (t) | p_TOST (W) | Holm eq.@δ | δ_min | n★ 80/90 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---:|---:|",
    ]
    for name, e in report["pairs"].items():
        ds, m = name.split(":")
        t = e["tost_t"]; w = e["tost_wilcoxon"]
        a = arms[ds]
        mr = _metric(a["relu"], m, limit=a["n"]).mean(); mq = _metric(a["qcfs"], m, limit=a["n"]).mean()
        holm = report.get("holm_bonferroni_tost_t", {}).get(name)
        holm_txt = (f"{'✅' if holm['equivalent'] else '❌'} ({holm['p_corrected']:.3f})"
                    if holm else "⚠️ excluded")
        req = e.get("required_n", {})
        flag = "" if a["validity"]["valid"] else " ⚠️"
        lines.append(
            f"| {ds}{flag} | {m} | {t['n']} | {mr:.2f} | {mq:.2f} | {t['mean_diff']:+.2f} | "
            f"[{t['ci'][0]:+.2f}, {t['ci'][1]:+.2f}] | {e['normality_shapiro_p']:.3f} | "
            f"{t['p_tost']:.3f} | {w['p_tost']:.3f} | "
            f"{holm_txt} | ±{t['delta_min']:.2f} | {req.get('power_0.80', '–')}/{req.get('power_0.90', '–')} |"
        )
    bad = {ds: a["validity"]["confounds"] for ds, a in arms.items() if not a["validity"]["valid"]}
    if bad:
        lines.append("")
        for ds, c in bad.items():
            lines.append(f"⚠️ **{ds}: pair is confounded — {', '.join(c)} — shown for reference, "
                         f"excluded from the Holm family; no equivalence or difference claim is valid "
                         f"until both arms are re-run under the same training budget.**")
    lines += ["", "## Margin sensitivity (parametric TOST, uncorrected)", "",
              "| Pair | " + " | ".join(f"δ={k}" for k in next(iter(report["sensitivity"].values())).keys()) + " |",
              "|---|" + "---|" * len(next(iter(report["sensitivity"].values())))]
    for name, sens in report["sensitivity"].items():
        lines.append(f"| {name} | " + " | ".join("✅" if v else "❌" for v in sens.values()) + " |")
    lines += ["", "Seed pairing uses the recorded seed lists (identical prefixes, 0, 1, 2, …).",
              "The test split is fixed per dataset (official split or random_state=42), so",
              "seed-to-seed variance reflects initialisation and shuffling only; the",
              "inference is about this split, not about resampling the data.",
              "n★ is a plug-in estimate using the observed SD of the differences."]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--delta", type=float, default=1.0, help="equivalence margin in pp")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--out", default=str(R / "equivalence_v4"))
    args = ap.parse_args()

    arms = load_arms()
    # Holm family = valid pairs only; confounded pairs are analysed for
    # reference and merged in afterwards, flagged.
    report = run_equivalence_analysis(build_pairs(arms, valid_only=True),
                                      delta=args.delta, alpha=args.alpha)
    extra = run_equivalence_analysis(build_pairs(arms, valid_only=False),
                                     delta=args.delta, alpha=args.alpha)
    for name in extra["pairs"]:
        if name not in report["pairs"]:
            report["pairs"][name] = extra["pairs"][name]
            report["sensitivity"][name] = extra["sensitivity"][name]
    report["seed_pairing"] = {ds: {"n_relu": len(a["relu"]), "n_qcfs": len(a["qcfs"]),
                                   "n_paired": a["n"], **a["validity"]}
                              for ds, a in arms.items()}
    report["difference_sign"] = "ReLU - QCFS (pp)"

    Path(args.out + ".json").write_text(json.dumps(report, indent=2))
    md = to_markdown(report, arms)
    Path(args.out + ".md").write_text(md)
    print(md)
    print(f"Wrote {args.out}.json and {args.out}.md")


if __name__ == "__main__":
    main()
