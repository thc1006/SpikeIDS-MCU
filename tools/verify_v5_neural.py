#!/usr/bin/env python3
"""Independent sklearn/SciPy/statsmodels oracle for the formal neural suite.

This verifier deliberately does not call the v5 metric or statistical helper
functions. It first requires the sealed primary/replica barrier, then reads
every saved prediction artifact and recomputes the reported quantities with
external libraries. The resulting report is sealed and is required by the
final artifact bundle.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import math
import platform
import sys
from collections.abc import Mapping
from pathlib import Path

import numpy as np
from scipy import stats
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    matthews_corrcoef,
    precision_recall_fscore_support,
    roc_auc_score,
)
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.weightstats import ttost_paired

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "spikeids_v5"
sys.path.insert(0, str(PACKAGE))

from contracts import (  # noqa: E402
    ARMS,
    DATASETS,
    METRICS,
    check_seal,
    load_json,
    require,
    seal,
    sha256,
    write_json,
)
from evidence import verified_suite  # noqa: E402

SCALARS = (
    "overall_acc", "macro_acc", "balanced_acc", "macro_precision",
    "macro_recall", "macro_f1", "weighted_precision", "weighted_recall",
    "weighted_f1", "mcc", "roc_auc_macro", "roc_auc_weighted",
)
PER_CLASS = ("accuracy", "precision", "recall", "f1", "fpr", "fnr")
TOOL_PROVENANCE_SCHEMA = 1
NEURAL_VERIFIER_PACKAGES = (
    "numpy", "scikit-learn", "scipy", "statsmodels",
)


def _parse_exact_options(argv: list[str], value_options: set[str],
                         boolean_options: set[str]) -> dict[str, str | bool]:
    require(len(argv) >= 2, "Tool invocation omits Python or script argv")
    parsed: dict[str, str | bool] = {}
    index = 2
    while index < len(argv):
        option = argv[index]
        require(option in value_options | boolean_options,
                f"Unsupported tool invocation option: {option}")
        require(option not in parsed, f"Duplicate tool invocation option: {option}")
        if option in boolean_options:
            parsed[option] = True
            index += 1
        else:
            require(index + 1 < len(argv), f"Missing value for invocation option: {option}")
            parsed[option] = argv[index + 1]
            index += 2
    return parsed


def canonical_tool_invocation(tool_path: Path, invocation: list[str],
                              cwd: Path) -> dict:
    """Strictly parse one lifecycle-tool argv into canonical logical fields."""
    name = Path(tool_path).name
    specifications = {
        "verify_v5_neural.py": (
            {"--run-dir", "--output"}, set(), {"--run-dir"}
        ),
        "verify_v5_tree.py": (
            {"--tree-run-dir", "--neural-run-dir", "--output"}, set(),
            {"--tree-run-dir", "--neural-run-dir"}
        ),
        "run_v5_exports.py": (
            {"--run-dir", "--output-root", "--paper-dir",
             "--int8-max-disagreement", "--validation-samples",
             "--calibration-samples"},
            set(), {"--run-dir", "--output-root", "--paper-dir"},
        ),
        "package_v5_artifacts.py": (
            {"--run-dir", "--tree-run-dir", "--export-root", "--data-audit",
             "--data-acceptance", "--paper-dir", "--paper-build", "--artifact-root"},
            set(), {"--run-dir", "--tree-run-dir", "--export-root", "--data-audit",
                    "--data-acceptance", "--paper-dir", "--paper-build", "--artifact-root"},
        ),
        "archive_pre_v5.py": (
            {"--formal-run", "--bundle"}, {"--execute"},
            {"--formal-run", "--bundle"},
        ),
    }
    require(name in specifications, f"Unsupported lifecycle tool: {name}")
    value_options, boolean_options, required = specifications[name]
    parsed = _parse_exact_options(invocation, value_options, boolean_options)
    require(required.issubset(parsed),
            f"Tool invocation omits required options: {sorted(required - set(parsed))}")

    def resolved(option: str) -> str:
        value = parsed[option]
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"Invalid path option: {option}")
        path = Path(value)
        if not path.is_absolute():
            path = cwd / path
        return str(path.resolve())

    if name == "verify_v5_neural.py":
        run_dir = Path(resolved("--run-dir"))
        output = (resolved("--output") if "--output" in parsed else
                  str((run_dir / "independent_verification.json").resolve()))
        return {"run_dir": str(run_dir), "output": output}
    if name == "verify_v5_tree.py":
        run_dir = Path(resolved("--tree-run-dir"))
        output = (resolved("--output") if "--output" in parsed else
                  str((run_dir / "independent_verification.json").resolve()))
        return {"tree_run_dir": str(run_dir),
                "neural_run_dir": resolved("--neural-run-dir"), "output": output}
    if name == "run_v5_exports.py":
        disagreement = float(parsed.get("--int8-max-disagreement", "0.01"))
        validation = int(parsed.get("--validation-samples", "1024"))
        calibration = int(parsed.get("--calibration-samples", "1000"))
        require(disagreement == 0.01 and validation == 1024 and calibration == 1000,
                "Export runner invocation changed a fixed protocol value")
        return {
            "run_dir": resolved("--run-dir"),
            "output_root": resolved("--output-root"),
            "paper_dir": resolved("--paper-dir"),
            "int8_max_disagreement": disagreement,
            "validation_samples": validation,
            "calibration_samples": calibration,
        }
    if name == "package_v5_artifacts.py":
        return {
            option.removeprefix("--").replace("-", "_"): resolved(option)
            for option in sorted(required)
        }
    return {
        "formal_run": resolved("--formal-run"),
        "bundle": resolved("--bundle"),
        "execute": parsed.get("--execute") is True,
    }


def tool_provenance(tool_path: Path, invocation: list[str],
                    packages: tuple[str, ...], *, cwd: Path | None = None) -> dict:
    """Record the exact executable source, invocation, and relevant runtime stack."""
    tool_path = Path(tool_path)
    require(tool_path.is_file() and not tool_path.is_symlink(),
            f"Provenance tool is missing or symlinked: {tool_path}")
    resolved = tool_path.resolve()
    try:
        relative = resolved.relative_to(ROOT).as_posix()
    except ValueError:
        relative = str(resolved)
    require(isinstance(invocation, list) and len(invocation) >= 2 and
            all(isinstance(item, str) and item for item in invocation),
            "Tool provenance requires a non-empty exact argv")
    package_names = tuple(packages)
    require(len(package_names) == len(set(package_names)) and
            all(isinstance(name, str) and name for name in package_names),
            "Tool provenance package names are invalid")
    resolved_cwd = (Path.cwd() if cwd is None else Path(cwd)).resolve()
    return {
        "schema": TOOL_PROVENANCE_SCHEMA,
        "tool": {
            "path": relative,
            "source_sha256": sha256(resolved),
        },
        "invocation": {
            "argv": list(invocation),
            "cwd": str(resolved_cwd),
            "parsed": canonical_tool_invocation(resolved, invocation, resolved_cwd),
        },
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "version_full": sys.version,
            "executable": str(Path(sys.executable).resolve()),
        },
        "platform": {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "packages": {
            name: importlib.metadata.version(name) for name in package_names
        },
    }


def validate_tool_provenance(value: object, tool_path: Path,
                             packages: tuple[str, ...],
                             expected_invocation: dict | None = None) -> None:
    """Fail closed unless provenance matches the current exact tool/runtime bytes."""
    if not isinstance(value, dict):
        require(False, "Tool provenance is missing or malformed")
        return
    provenance = value
    invocation = provenance.get("invocation")
    if (not isinstance(invocation, dict) or
            set(invocation) != {"argv", "cwd", "parsed"} or
            not isinstance(invocation.get("argv"), list) or
            not isinstance(invocation.get("cwd"), str) or
            not isinstance(invocation.get("parsed"), dict)):
        require(False, "Tool provenance invocation is missing or malformed")
        return
    argv = invocation["argv"]
    cwd = Path(invocation["cwd"])
    expected = tool_provenance(tool_path, argv, packages, cwd=cwd)
    require(provenance == expected,
            f"Tool provenance differs from current exact source/runtime: {tool_path.name}")
    require(Path(argv[0]).resolve() == Path(expected["python"]["executable"]),
            "Tool provenance invocation used another Python executable")
    invoked_tool = Path(argv[1])
    if not invoked_tool.is_absolute():
        invoked_tool = cwd / invoked_tool
    require(invoked_tool.resolve() == Path(tool_path).resolve(),
            "Tool provenance invocation refers to another tool path")
    if expected_invocation is not None:
        require(invocation["parsed"] == expected_invocation,
                "Tool provenance canonical invocation differs from expected paths/flags")


def close(actual: float | None, expected: float | None, label: str,
          atol: float = 1e-10) -> None:
    require((actual is None) == (expected is None), f"{label}: definedness differs")
    if actual is not None and expected is not None:
        require(math.isfinite(float(actual)) and math.isfinite(float(expected)) and
                abs(float(actual) - float(expected)) <= atol,
                f"{label}: {actual} differs from independent value {expected}")


def immutable_file_snapshot(path: Path) -> dict:
    """Bind identity and bytes so semantic validation cannot race later hashing."""
    path = Path(path)
    metadata = path.lstat()
    require(path.is_file() and not path.is_symlink() and metadata.st_nlink == 1,
            f"Evidence input is not an independent regular file: {path}")
    return {
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "nlink": metadata.st_nlink,
        "size": metadata.st_size,
        "sha256": sha256(path),
    }


def metric_oracle(y_true: np.ndarray, y_pred: np.ndarray,
                  probability: np.ndarray, class_names: list[str]) -> dict:
    """Recompute all stored metrics using sklearn plus direct class rates."""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    probability = np.asarray(probability)
    classes = len(class_names)
    labels = list(range(classes))
    require(classes >= 2 and len(set(class_names)) == classes and
            all(isinstance(name, str) for name in class_names),
            "Independent metric oracle received invalid class names")
    require(y_true.ndim == y_pred.ndim == 1 and len(y_true) > 0 and
            y_true.shape == y_pred.shape and
            probability.shape == (len(y_true), classes),
            "Independent metric oracle received malformed arrays")
    require(y_true.dtype.kind in "iu" and y_pred.dtype.kind in "iu" and
            probability.dtype.kind == "f" and np.isfinite(probability).all() and
            ((y_true >= 0) & (y_true < classes)).all() and
            ((y_pred >= 0) & (y_pred < classes)).all() and
            (probability >= 0).all() and (probability <= 1).all() and
            np.allclose(probability.sum(axis=1), 1.0, atol=1e-6, rtol=1e-5),
            "Independent metric inputs are invalid")
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average=None, zero_division=0,
    )
    macro = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="macro", zero_division=0,
    )
    weighted = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="weighted", zero_division=0,
    )
    result = {
        "overall_acc": 100.0 * float(accuracy_score(y_true, y_pred)),
        "macro_acc": 100.0 * float(np.mean(recall)),
        "balanced_acc": 100.0 * float(balanced_accuracy_score(y_true, y_pred)),
        "macro_precision": 100.0 * float(macro[0]),
        "macro_recall": 100.0 * float(macro[1]),
        "macro_f1": 100.0 * float(macro[2]),
        "weighted_precision": 100.0 * float(weighted[0]),
        "weighted_recall": 100.0 * float(weighted[1]),
        "weighted_f1": 100.0 * float(weighted[2]),
        "mcc": float(matthews_corrcoef(y_true, y_pred)),
        "roc_auc_macro": None,
        "roc_auc_weighted": None,
        "confusion_matrix": cm.tolist(),
        "per_class": {},
    }
    require(np.all(support > 0), "Formal test partition lacks a declared class")
    if classes == 2:
        auc = float(roc_auc_score(y_true, probability[:, 1]))
        result["roc_auc_macro"] = auc
        result["roc_auc_weighted"] = auc
    else:
        result["roc_auc_macro"] = float(roc_auc_score(
            y_true, probability, labels=labels, multi_class="ovr", average="macro"
        ))
        result["roc_auc_weighted"] = float(roc_auc_score(
            y_true, probability, labels=labels, multi_class="ovr", average="weighted"
        ))
    total = len(y_true)
    predicted = cm.sum(axis=0)
    true_positive = np.diag(cm)
    for index, name in enumerate(class_names):
        negatives = total - int(support[index])
        result["per_class"][name] = {
            "accuracy": 100.0 * float(recall[index]),
            "precision": 100.0 * float(precision[index]),
            "recall": 100.0 * float(recall[index]),
            "f1": 100.0 * float(f1[index]),
            "fpr": float((predicted[index] - true_positive[index]) / negatives),
            "fnr": float((support[index] - true_positive[index]) / support[index]),
        }
    return result


def compare_metric_record(stored: dict, independent: dict, identity: str) -> None:
    require(stored.get("confusion_matrix") == independent["confusion_matrix"],
            f"{identity}: confusion matrix differs from sklearn")
    for name in SCALARS:
        close(stored.get(name), independent[name], f"{identity}/{name}")
    require(set(stored.get("per_class", {})) == set(independent["per_class"]),
            f"{identity}: per-class keys differ")
    for class_name, values in independent["per_class"].items():
        for metric in PER_CLASS:
            close(stored["per_class"][class_name].get(metric), values[metric],
                  f"{identity}/{class_name}/{metric}")


def compare_aggregate(stored: dict, rows: list[dict], class_names: list[str],
                      identity: str) -> None:
    def compare_summary(block: dict, values: np.ndarray, label: str) -> None:
        require(values.ndim == 1 and len(values) > 0 and np.isfinite(values).all(),
                f"{label}: independent values are malformed")
        close(block.get("mean"), float(np.mean(values)), f"{label}/mean")
        expected_std = (float(np.std(values, ddof=1))
                        if len(values) > 1 else None)
        close(block.get("std"), expected_std, f"{label}/std")
        require(block.get("n_valid") == len(values) == block.get("n_total"),
                f"{label}: aggregate count differs")
        stored_values = block.get("values")
        if not isinstance(stored_values, list):
            raise RuntimeError(f"{label}: aggregate values missing or malformed")
        require(len(stored_values) == len(values),
                f"{label}: aggregate values have the wrong length")
        for index, value in enumerate(values):
            close(stored_values[index], float(value), f"{label}/values/{index}")

    for metric in SCALARS:
        values = np.asarray([row[metric] for row in rows], dtype=np.float64)
        compare_summary(stored[metric], values, f"{identity}/{metric}")
    for class_name in class_names:
        for metric in PER_CLASS:
            values = np.asarray(
                [row["per_class"][class_name][metric] for row in rows],
                dtype=np.float64,
            )
            compare_summary(stored["per_class"][class_name][metric], values,
                            f"{identity}/{class_name}/{metric}")
    matrices = np.asarray([row["confusion_matrix"] for row in rows], dtype=np.float64)
    mean = np.asarray(stored.get("confusion_matrix_mean"), dtype=np.float64)
    std_value = stored.get("confusion_matrix_std")
    require(mean.shape == matrices.shape[1:] and
            np.allclose(mean, matrices.mean(axis=0), atol=1e-10, rtol=0),
            f"{identity}: aggregate confusion-matrix mean differs")
    if len(matrices) == 1:
        require(std_value is None,
                f"{identity}: singleton confusion-matrix std must be undefined")
    else:
        std = np.asarray(std_value, dtype=np.float64)
        require(std.shape == matrices.shape[1:] and
                np.allclose(std, matrices.std(axis=0, ddof=1), atol=1e-10, rtol=0),
            f"{identity}: aggregate confusion matrices differ")


def signed_rank_oracle(differences: np.ndarray,
                       alternative: str = "two-sided") -> dict:
    """Exhaustively enumerate sign assignments, independent of the v5 DP."""
    require(alternative in ("two-sided", "greater", "less"),
            "Invalid signed-rank alternative")
    rounded = np.round(np.asarray(differences, dtype=np.float64), decimals=12)
    require(rounded.ndim == 1 and np.isfinite(rounded).all(),
            "Signed-rank oracle requires a finite vector")
    nonzero = rounded[rounded != 0]
    _, tie_counts = np.unique(np.abs(nonzero), return_counts=True)
    tie_groups = sorted(
        (int(count) for count in tie_counts if count > 1), reverse=True
    )
    if not len(nonzero):
        return {"p": 1.0, "statistic": 0.0, "n_nonzero": 0,
                "n_zero": len(rounded), "absolute_rank_tie_group_sizes": [],
                "rank_biserial": 0.0,
                "zero_method": "wilcox_discard_after_declared_rounding",
                "tie_method": "average_ranks", "round_decimals": 12}
    require(len(nonzero) <= 24,
            "Exhaustive signed-rank oracle is restricted to at most 24 pairs")
    doubled_ranks = np.rint(
        2 * stats.rankdata(np.abs(nonzero), method="average")
    ).astype(np.int64)
    total_rank = int(doubled_ranks.sum())
    observed = int(doubled_ranks[nonzero > 0].sum())
    less_equal = 0
    greater_equal = 0
    assignments = 1 << len(nonzero)
    shifts = np.arange(len(nonzero), dtype=np.uint64)
    for start in range(0, assignments, 65536):
        stop = min(assignments, start + 65536)
        masks = np.arange(start, stop, dtype=np.uint64)[:, None]
        positive = ((masks >> shifts) & 1).astype(np.int64, copy=False)
        rank_sums = positive @ doubled_ranks
        less_equal += int(np.count_nonzero(rank_sums <= observed))
        greater_equal += int(np.count_nonzero(rank_sums >= observed))
    p_less = less_equal / assignments
    p_greater = greater_equal / assignments
    if alternative == "two-sided":
        pvalue = min(1.0, 2 * min(p_less, p_greater))
        statistic = min(observed, total_rank - observed) / 2
    else:
        pvalue = p_less if alternative == "less" else p_greater
        statistic = observed / 2
    return {
        "p": float(pvalue),
        "statistic": float(statistic),
        "n_nonzero": len(nonzero),
        "n_zero": len(rounded) - len(nonzero),
        "absolute_rank_tie_group_sizes": tie_groups,
        "rank_biserial": float((2 * observed - total_rank) / total_rank),
        "zero_method": "wilcox_discard_after_declared_rounding",
        "tie_method": "average_ranks",
        "round_decimals": 12,
    }


def exact_signed_rank_oracle(differences: np.ndarray) -> float:
    return float(signed_rank_oracle(differences)["p"])


def hodges_lehmann_oracle(differences: np.ndarray) -> float:
    """Independently compute the one-sample Walsh-average pseudomedian."""
    rounded = np.round(np.asarray(differences, dtype=np.float64), decimals=12)
    require(rounded.ndim == 1 and len(rounded) > 0 and np.isfinite(rounded).all(),
            "Hodges-Lehmann oracle requires a nonempty finite vector")
    row, column = np.triu_indices(len(rounded))
    walsh = (rounded[row] + rounded[column]) / 2.0
    require(np.isfinite(walsh).all(), "Hodges-Lehmann Walsh averages overflowed")
    return float(np.median(walsh))


def holm_oracle(pvalues: Mapping[str, float | None], alpha: float) -> dict[str, dict]:
    names = list(pvalues)
    numeric = []
    for name in names:
        value = pvalues[name]
        numeric.append(1.0 if value is None else float(value))
    _, adjusted, _, _ = multipletests(numeric, alpha=alpha, method="holm")
    return {
        name: {"p_adj": float(adjusted[index]),
               "reject": bool(pvalues[name] is not None and adjusted[index] < alpha)}
        for index, name in enumerate(names)
    }


def bootstrap_mean_oracle(values: np.ndarray) -> list[float]:
    """Independently reproduce the prespecified 10,000-resample mean interval."""
    values = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(0)
    means = np.empty(10_000, dtype=np.float64)
    for start in range(0, len(means), 1024):
        stop = min(len(means), start + 1024)
        indices = rng.integers(0, len(values), size=(stop - start, len(values)))
        means[start:stop] = values[indices].mean(axis=1)
    return np.quantile(means, [0.025, 0.975], method="linear").tolist()


def verify_statistics(run_dir: Path, plan: dict, primary: dict[tuple[str, str], dict]) -> dict:
    difference_path = run_dir / "stats_report_globecom.json"
    equivalence_path = run_dir / "equivalence_v5.json"
    difference_snapshot = immutable_file_snapshot(difference_path)
    equivalence_snapshot = immutable_file_snapshot(equivalence_path)
    difference = load_json(difference_path); check_seal(difference)
    equivalence = load_json(equivalence_path); check_seal(equivalence)
    require(difference.get("plan_sha256") == equivalence.get("plan_sha256") ==
            plan["content_sha256"], "Statistical reports refer to another plan")

    raw_difference: dict[str, float] = {}
    for dataset in DATASETS:
        left_rows = {row["seed"]: row for row in primary[(dataset, "relu")]["per_seed"]}
        for arm in ARMS[dataset]:
            if arm == "relu":
                continue
            right_rows = {row["seed"]: row for row in primary[(dataset, arm)]["per_seed"]}
            for metric in METRICS:
                key = f"{dataset}:relu_vs_{arm}:{metric}"
                values = np.asarray([
                    left_rows[seed][metric] - right_rows[seed][metric]
                    for seed in plan["seeds"]
                ], dtype=np.float64)
                signed_rank = signed_rank_oracle(values)
                pvalue = float(signed_rank["p"])
                reported = difference["comparisons"][key]
                left = np.asarray(
                    [left_rows[seed][metric] for seed in plan["seeds"]],
                    dtype=np.float64,
                )
                right = np.asarray(
                    [right_rows[seed][metric] for seed in plan["seeds"]],
                    dtype=np.float64,
                )
                require(reported.get("paired_seeds") == plan["seeds"] and
                        reported.get("n") == len(values) and
                        reported.get("n_nonzero") == signed_rank["n_nonzero"] and
                        reported.get("n_zero") == signed_rank["n_zero"] and
                        reported.get("absolute_rank_tie_group_sizes") ==
                        signed_rank["absolute_rank_tie_group_sizes"] and
                        reported.get("zero_method") == signed_rank["zero_method"] and
                        reported.get("tie_method") == signed_rank["tie_method"] and
                        reported.get("round_decimals") == signed_rank["round_decimals"],
                        f"difference/{key}: pairing or sample count differs")
                close(reported.get("left_mean"), float(np.mean(left)),
                      f"difference/{key}/left_mean", atol=1e-12)
                close(reported.get("right_mean"), float(np.mean(right)),
                      f"difference/{key}/right_mean", atol=1e-12)
                close(reported.get("mean_diff"), float(np.mean(values)),
                      f"difference/{key}/mean", atol=1e-12)
                close(reported.get("median_diff"), float(np.median(values)),
                      f"difference/{key}/median", atol=1e-12)
                close(reported.get("hodges_lehmann_pseudomedian_diff"),
                      hodges_lehmann_oracle(values),
                      f"difference/{key}/hodges_lehmann", atol=1e-12)
                close(reported.get("statistic"), signed_rank["statistic"],
                      f"difference/{key}/statistic", atol=1e-14)
                close(reported.get("rank_biserial"), signed_rank["rank_biserial"],
                      f"difference/{key}/rank_biserial", atol=1e-14)
                close(reported.get("p"), pvalue, f"difference/{key}/p", atol=1e-14)
                close(reported.get("p_raw"), pvalue,
                      f"difference/{key}/p_raw", atol=1e-14)
                stored_differences = np.asarray(reported.get("differences"),
                                                dtype=np.float64)
                require(stored_differences.shape == values.shape and
                        np.array_equal(stored_differences, values),
                        f"difference/{key}: paired differences differ")
                require(reported.get("test_estimand") ==
                        "symmetric paired-difference location/pseudomedian" and
                        reported.get("symmetry_assumption") ==
                        "paired seed differences are independent and symmetric about the tested location" and
                        reported.get("mean_diff_role") ==
                        "descriptive only; the signed-rank p-value does not test the mean",
                        f"difference/{key}: signed-rank estimand/assumption differs")
                stored_ci = np.asarray(
                    reported.get("paired_difference_bootstrap_95ci"),
                    dtype=np.float64,
                )
                independent_ci = np.asarray(bootstrap_mean_oracle(values))
                require(stored_ci.shape == (2,) and
                        np.allclose(stored_ci, independent_ci, atol=1e-12, rtol=0),
                        f"difference/{key}: bootstrap interval differs")
                raw_difference[key] = pvalue
    require(list(raw_difference) == plan["difference_family"],
            "Independent difference family order/identity differs")
    adjusted_difference = holm_oracle(raw_difference, plan["alpha"])
    for key, oracle in adjusted_difference.items():
        reported = difference["comparisons"][key]
        close(reported.get("p_adj"), oracle["p_adj"],
              f"difference/{key}/holm", atol=1e-14)
        require(reported.get("reject") is oracle["reject"] and
                reported.get("family_size") == len(raw_difference) and
                reported.get("undefined_test_retained") is False,
                f"difference/{key}: Holm decision differs")

    raw_equivalence: dict[str, float | None] = {}
    raw_robust_equivalence: dict[str, float] = {}
    for dataset in DATASETS:
        left_rows = {row["seed"]: row for row in primary[(dataset, "relu")]["per_seed"]}
        right_rows = {row["seed"]: row for row in primary[(dataset, "qcfs")]["per_seed"]}
        for metric in METRICS:
            key = f"{dataset}:{metric}"
            left = np.asarray([left_rows[seed][metric] for seed in plan["seeds"]])
            right = np.asarray([right_rows[seed][metric] for seed in plan["seeds"]])
            differences = left - right
            reported = equivalence["pairs"][key]["tost_t"]
            require(equivalence["pairs"][key].get("paired_seeds") == plan["seeds"] and
                    reported.get("n") == len(differences),
                    f"equivalence/{key}: pairing or sample count differs")
            close(reported.get("mean_diff"), float(np.mean(differences)),
                  f"equivalence/{key}/mean", atol=1e-12)
            close(reported.get("delta"), float(plan["equivalence_margin_pp"]),
                  f"equivalence/{key}/margin", atol=0)
            close(reported.get("alpha"), float(plan["alpha"]),
                  f"equivalence/{key}/alpha", atol=0)
            close(reported.get("confidence_level"), 1 - 2 * float(plan["alpha"]),
                  f"equivalence/{key}/confidence", atol=1e-15)
            if np.ptp(differences) == 0:
                require(reported.get("p_tost") is None and
                        reported.get("status") == "undefined_sampling_variance" and
                        reported.get("sd_diff") == 0.0 and
                        reported.get("ci") is None and
                        reported.get("equivalent") is False and
                        reported.get("delta_min_infimum") is None,
                        f"equivalence/{key}: degenerate variance was not retained")
                equivalence_pvalue: float | None = None
            else:
                tost_pvalue, lower, upper = ttost_paired(
                    left, right, -plan["equivalence_margin_pp"],
                    plan["equivalence_margin_pp"],
                )
                equivalence_pvalue = float(tost_pvalue)
                sd = float(np.std(differences, ddof=1))
                half = float(stats.t.ppf(1 - plan["alpha"], len(differences) - 1) *
                             sd / math.sqrt(len(differences)))
                ci = [float(np.mean(differences)) - half,
                      float(np.mean(differences)) + half]
                close(reported.get("sd_diff"), sd,
                      f"equivalence/{key}/sd", atol=1e-12)
                require(reported.get("status") == "defined",
                        f"equivalence/{key}: defined TOST marked undefined")
                close(reported.get("p_tost"), equivalence_pvalue,
                      f"equivalence/{key}/p", atol=1e-14)
                close(reported.get("p_lower"), float(lower[1]),
                      f"equivalence/{key}/lower", atol=1e-14)
                close(reported.get("p_upper"), float(upper[1]),
                      f"equivalence/{key}/upper", atol=1e-14)
                stored_ci = reported.get("ci")
                require(isinstance(stored_ci, list) and len(stored_ci) == 2,
                        f"equivalence/{key}: individual CI missing")
                for index in range(2):
                    close(stored_ci[index], ci[index],
                          f"equivalence/{key}/ci/{index}", atol=1e-12)
                close(reported.get("delta_min_infimum"),
                      max(abs(value) for value in ci),
                      f"equivalence/{key}/delta_min", atol=1e-12)
                require(reported.get("equivalent") is
                        (equivalence_pvalue < plan["alpha"]),
                        f"equivalence/{key}: raw TOST decision differs")
            robust = equivalence["pairs"][key]["tost_signed_rank_robustness"]
            robust_lower_result = signed_rank_oracle(
                differences + plan["equivalence_margin_pp"], "greater"
            )
            robust_upper_result = signed_rank_oracle(
                differences - plan["equivalence_margin_pp"], "less"
            )
            robust_lower = robust_lower_result["p"]
            robust_upper = robust_upper_result["p"]
            robust_p = max(float(robust_lower), float(robust_upper))
            close(robust.get("p_lower"), float(robust_lower),
                  f"equivalence/{key}/robust_lower", atol=1e-14)
            close(robust.get("p_upper"), float(robust_upper),
                  f"equivalence/{key}/robust_upper", atol=1e-14)
            close(robust.get("p_tost"), robust_p,
                  f"equivalence/{key}/robust_tost", atol=1e-14)
            require(robust.get("equivalent") is (robust_p < plan["alpha"]),
                    f"equivalence/{key}: robust TOST decision differs")
            require(
                robust.get("estimand") ==
                "symmetric location/pseudomedian, NOT generally the mean" and
                robust.get("symmetry_assumption") ==
                "paired seed differences are independent and symmetric about the location" and
                robust.get("zero_method") ==
                "wilcox_discard_after_declared_rounding" and
                robust.get("tie_method") == "average_ranks" and
                robust.get("lower_n_nonzero") ==
                robust_lower_result["n_nonzero"] and
                robust.get("upper_n_nonzero") ==
                robust_upper_result["n_nonzero"] and
                robust.get("role") ==
                "prespecified robustness analysis; no test-selection switching",
                f"equivalence/{key}: robust TOST diagnostics/estimand differ",
            )
            raw_equivalence[key] = equivalence_pvalue
            raw_robust_equivalence[key] = robust_p
    require(list(raw_equivalence) == plan["equivalence_family"],
            "Independent equivalence family order/identity differs")
    adjusted_equivalence = holm_oracle(raw_equivalence, plan["alpha"])
    require(list(raw_robust_equivalence) == plan["equivalence_family"],
            "Independent robust equivalence family order/identity differs")
    adjusted_robust = holm_oracle(raw_robust_equivalence, plan["alpha"])
    for key, oracle in adjusted_equivalence.items():
        reported = equivalence["pairs"][key]
        close(reported["holm"].get("p_adj"), oracle["p_adj"],
              f"equivalence/{key}/holm", atol=1e-14)
        require(reported.get("equivalent_familywise") is oracle["reject"] and
                reported["holm"].get("family_size") == len(raw_equivalence) and
                reported["holm"].get("undefined_test_retained") is
                (raw_equivalence[key] is None),
                f"equivalence/{key}: Holm decision differs")
        robust = adjusted_robust[key]
        reported_robust = reported.get("signed_rank_robustness_holm", {})
        close(reported_robust.get("p_raw"), raw_robust_equivalence[key],
              f"equivalence/{key}/robust_holm_raw", atol=1e-14)
        close(reported_robust.get("p_adj"), robust["p_adj"],
              f"equivalence/{key}/robust_holm", atol=1e-14)
        require(
            reported_robust.get("reject") is robust["reject"] and
            reported_robust.get("family_size") == len(raw_robust_equivalence) and
            reported_robust.get("undefined_test_retained") is False and
            reported.get("equivalent_familywise_signed_rank_robustness") is
            robust["reject"] and
            reported.get("primary_robustness_discordant") is
            (oracle["reject"] != robust["reject"]),
            f"equivalence/{key}: robust Holm/discordance decision differs",
        )

    require(
        difference.get("primary_test_estimand") ==
        "symmetric paired-difference location/pseudomedian" and
        difference.get("assumption") ==
        "independent paired seed differences symmetric about the tested location" and
        difference.get("zero_rule") ==
        "discard exact zeros after 12-decimal declared rounding" and
        difference.get("tie_rule") ==
        "average absolute ranks; exact conditional sign enumeration",
        "Difference report changes its signed-rank estimand or numerical rules",
    )
    require(
        equivalence.get("primary_estimand") ==
        "mean paired seed difference via paired t-TOST" and
        equivalence.get("robustness_estimand") ==
        "symmetric paired-difference location/pseudomedian via signed-rank TOST" and
        equivalence.get("robustness_family_definition") ==
        "the same eight hypotheses, Holm-adjusted separately as a robustness family",
        "Equivalence report changes its primary/robust estimands or family",
    )
    require(immutable_file_snapshot(difference_path) == difference_snapshot and
            immutable_file_snapshot(equivalence_path) == equivalence_snapshot,
            "Statistical report changed during independent verification")

    return {
        "difference_report_sha256": difference_snapshot["sha256"],
        "equivalence_report_sha256": equivalence_snapshot["sha256"],
        "difference_hypotheses": len(raw_difference),
        "equivalence_hypotheses": len(raw_equivalence),
        "difference_oracle":
            "SciPy average ranks plus NumPy exhaustive sign enumeration and statsmodels Holm",
        "equivalence_oracle":
            "statsmodels paired TOST, exhaustive signed-rank robustness, separate statsmodels Holm families, and primary-robust decision comparison",
    }


def verify(run_dir: Path) -> dict:
    run_dir = run_dir.resolve()
    preliminary_plan = load_json(run_dir / "plan.json")
    check_seal(preliminary_plan)
    checkpoint_snapshots: dict[Path, dict] = {}
    for job in preliminary_plan.get("jobs", []):
        for execution in ("results", "replicas"):
            for seed in preliminary_plan.get("seeds", []):
                checkpoint = (run_dir / execution / job["id"] / "runs" /
                              f"{job['model']}_seed_{seed}.pt")
                checkpoint_snapshots[checkpoint] = immutable_file_snapshot(checkpoint)
    plan, primary = verified_suite(run_dir)
    require(plan == preliminary_plan,
            "Formal plan changed during independent verification")
    require(plan.get("protocol_role") == "planned_benchmark" and
            plan.get("seeds") == list(range(20)),
            "Only the fixed full formal neural plan may pass this verifier")
    execution_digests: dict[str, dict] = {}
    checkpoint_evidence: dict[str, dict] = {}
    artifacts_checked = 0
    checkpoints_checked = 0
    for job in plan["jobs"]:
        execution_digests[job["id"]] = {}
        checkpoint_evidence[job["id"]] = {}
        for execution in ("results", "replicas"):
            result_path = run_dir / execution / f"{job['id']}.json"
            record = load_json(result_path); check_seal(record)
            fit_by_seed = {row["seed"]: row for row in record["fit_runs"]}
            checkpoint_evidence[job["id"]][execution] = {}
            independent_rows = []
            for row in record["per_seed"]:
                fit_row = fit_by_seed[row["seed"]]
                checkpoint = (result_path.with_suffix("") / "runs" /
                              f"{record['kind']}_seed_{row['seed']}.pt")
                require(checkpoint.is_file() and not checkpoint.is_symlink(),
                        f"Missing/symlinked neural checkpoint: {checkpoint}")
                snapshot = immutable_file_snapshot(checkpoint)
                require(snapshot == checkpoint_snapshots.get(checkpoint),
                        f"Neural checkpoint changed during semantic verification: {checkpoint}")
                checkpoint_evidence[job["id"]][execution][str(row["seed"])] = {
                    "path": checkpoint.relative_to(run_dir).as_posix(),
                    "artifact_sha256": snapshot["sha256"],
                    "best_state_sha256": fit_row["best_state_sha256"],
                    "final_state_sha256": fit_row["final_state_sha256"],
                }
                checkpoints_checked += 1
                artifact = result_path.with_suffix("") / "runs" / row["artifact"]["filename"]
                require(artifact.is_file() and not artifact.is_symlink(),
                        f"Missing/symlinked prediction artifact: {artifact}")
                with np.load(artifact, allow_pickle=False) as arrays:
                    independent = metric_oracle(
                        arrays["y_true"], arrays["y_pred"], arrays["probabilities"],
                        record["class_names"],
                    )
                identity = f"{execution}/{job['id']}/seed={row['seed']}"
                compare_metric_record(row, independent, identity)
                independent["seed"] = row["seed"]
                independent_rows.append(independent)
                artifacts_checked += 1
            independent_rows.sort(key=lambda item: item["seed"])
            compare_aggregate(record["aggregate"], independent_rows,
                              record["class_names"], f"{execution}/{job['id']}")
            execution_digests[job["id"]][execution] = record["scientific_digest"]
        require(execution_digests[job["id"]]["results"] ==
                execution_digests[job["id"]]["replicas"],
                f"Primary/replica digest differs: {job['id']}")
    require(artifacts_checked == 2 * len(plan["jobs"]) * len(plan["seeds"]),
            "Independent neural verifier did not inspect all 440 artifacts")
    require(checkpoints_checked == 2 * len(plan["jobs"]) * len(plan["seeds"]),
            "Independent neural verifier did not bind all 440 checkpoints")
    statistics = verify_statistics(run_dir, plan, primary)
    return {
        "schema": 1,
        "kind": "independent_formal_neural_and_statistics_verification",
        "passed": True,
        "plan_sha256": plan["content_sha256"],
        "verification_fit_sha256": sha256(run_dir / "verification_fit.json"),
        "verification_evaluate_sha256": sha256(run_dir / "verification_evaluate.json"),
        "prediction_artifacts_checked": artifacts_checked,
        "checkpoints_checked": checkpoints_checked,
        "checkpoints": checkpoint_evidence,
        "executions_checked": 2 * len(plan["jobs"]),
        "metric_oracle": "sklearn metrics plus direct per-class rates",
        "execution_scientific_digests": execution_digests,
        "statistics": statistics,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    output = args.output.resolve() if args.output else run_dir / "independent_verification.json"
    require(output.parent == run_dir,
            "Independent neural verification output must be a direct child of the run directory")
    provenance = tool_provenance(
        Path(__file__), [sys.executable, *sys.argv], NEURAL_VERIFIER_PACKAGES
    )
    value = seal({**verify(run_dir), "tool_provenance": provenance})
    if output.exists():
        existing = load_json(output); check_seal(existing)
        require(existing == value,
                "Existing independent neural verification differs; use a fresh formal run")
    else:
        write_json(output, value)
    print(f"INDEPENDENT NEURAL/STATISTICS VERIFICATION PASSED: {output}")


if __name__ == "__main__":
    main()
