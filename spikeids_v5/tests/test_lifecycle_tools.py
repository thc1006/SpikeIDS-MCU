"""Adversarial tests for export acceptance, bundling, and reversible archival gates."""

from __future__ import annotations

import copy
import hashlib
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "spikeids_v5"))

from contracts import (  # noqa: E402
    ContractError,
    check_seal,
    json_bytes,
    load_json,
    seal,
    sha256,
    write_json,
)

from metrics import aggregate  # noqa: E402
from tools import (  # noqa: E402
    archive_pre_v5,
    package_v5_artifacts,
    run_v5_exports,
    v5_retention,
    verify_v5_neural,
    verify_v5_tree,
)

JOBS = package_v5_artifacts.JOBS


def test_independent_metric_oracle_known_binary_case() -> None:
    y_true = np.array([0, 0, 1, 1], dtype=np.int64)
    y_pred = np.array([0, 1, 1, 1], dtype=np.int64)
    probabilities = np.array([
        [0.9, 0.1], [0.2, 0.8], [0.4, 0.6], [0.1, 0.9],
    ], dtype=np.float64)
    result = verify_v5_neural.metric_oracle(
        y_true, y_pred, probabilities, ["normal", "attack"]
    )
    assert result["confusion_matrix"] == [[1, 1], [0, 2]]
    assert result["overall_acc"] == pytest.approx(75.0)
    assert result["macro_precision"] == pytest.approx(100 * (1 + 2 / 3) / 2)
    assert result["macro_recall"] == pytest.approx(75.0)
    assert result["macro_f1"] == pytest.approx(100 * (2 / 3 + 0.8) / 2)
    assert result["mcc"] == pytest.approx(1 / np.sqrt(3))
    assert result["roc_auc_macro"] == pytest.approx(0.75)
    assert result["per_class"]["normal"]["fpr"] == pytest.approx(0.0)
    assert result["per_class"]["attack"]["fpr"] == pytest.approx(0.5)

    invalid = probabilities.copy()
    invalid[0] = [0.9, 0.2]
    with pytest.raises(Exception, match="metric inputs are invalid"):
        verify_v5_neural.metric_oracle(
            y_true, y_pred, invalid, ["normal", "attack"]
        )


@pytest.mark.parametrize(
    ("values", "expected_two_sided", "expected_greater", "expected_less"),
    [
        ([1.0, 2.0, 3.0], 0.25, 0.125, 1.0),
        ([1.0, 1.0, 2.0, -2.0], 0.75, 0.375, 0.75),
        ([1.0, -1.0, 2.0, -2.0, 0.0], 1.0, 0.625, 0.625),
    ],
)
def test_signed_rank_oracle_exactly_enumerates_ties_and_zeros(
        values: list[float], expected_two_sided: float,
        expected_greater: float, expected_less: float) -> None:
    vector = np.asarray(values)
    assert verify_v5_neural.signed_rank_oracle(vector)["p"] == expected_two_sided
    assert verify_v5_neural.signed_rank_oracle(vector, "greater")["p"] == expected_greater
    assert verify_v5_neural.signed_rank_oracle(vector, "less")["p"] == expected_less


def test_signed_rank_oracle_exposes_independent_estimand_diagnostics() -> None:
    values = np.asarray([0.0, 1.0, -1.0, 1.0, 3.0])
    result = verify_v5_neural.signed_rank_oracle(values)
    assert result["n_zero"] == 1
    assert result["absolute_rank_tie_group_sizes"] == [3]
    assert result["zero_method"] == "wilcox_discard_after_declared_rounding"
    assert result["tie_method"] == "average_ranks"
    assert result["round_decimals"] == 12
    rounded = np.round(values, decimals=12)
    row, column = np.triu_indices(len(rounded))
    assert verify_v5_neural.hodges_lehmann_oracle(values) == pytest.approx(
        np.median((rounded[row] + rounded[column]) / 2.0)
    )


@pytest.mark.parametrize(
    "argv",
    [
        [sys.executable, str(ROOT / "tools/verify_v5_neural.py")],
        [sys.executable, str(ROOT / "tools/verify_v5_neural.py"),
         "--run-dir", "/tmp/a", "--run-dir", "/tmp/b"],
        [sys.executable, str(ROOT / "tools/run_v5_exports.py"),
         "--run-dir", "/tmp/a", "--output-root", "/tmp/b",
         "--paper-dir", "/tmp/c", "--validation-samples", "999"],
    ],
)
def test_tool_provenance_rejects_missing_duplicate_or_changed_logical_args(
        argv: list[str]) -> None:
    tool = Path(argv[1])
    packages = (
        run_v5_exports.EXPORT_RUNNER_PACKAGES
        if tool.name == "run_v5_exports.py"
        else verify_v5_neural.NEURAL_VERIFIER_PACKAGES
    )
    with pytest.raises(Exception):
        verify_v5_neural.tool_provenance(tool, argv, packages, cwd=ROOT)


def test_tool_provenance_rejects_wrong_canonical_output() -> None:
    tool = ROOT / "tools/verify_v5_neural.py"
    run_dir = ROOT / "synthetic-run"
    provenance = verify_v5_neural.tool_provenance(
        tool,
        [sys.executable, str(tool), "--run-dir", str(run_dir),
         "--output", str(run_dir / "wrong.json")],
        verify_v5_neural.NEURAL_VERIFIER_PACKAGES,
        cwd=ROOT,
    )
    with pytest.raises(Exception, match="canonical invocation differs"):
        verify_v5_neural.validate_tool_provenance(
            provenance, tool, verify_v5_neural.NEURAL_VERIFIER_PACKAGES,
            {"run_dir": str(run_dir.resolve()),
             "output": str((run_dir / "independent_verification.json").resolve())},
        )


def test_package_snapshot_rejects_hardlink_and_copy_race(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"validated bytes")
    alias = tmp_path / "alias.bin"
    os.link(source, alias)
    with pytest.raises(Exception, match="Hardlinked source is forbidden"):
        package_v5_artifacts.snapshot_regular_file(source)
    alias.unlink()

    expected = package_v5_artifacts.snapshot_regular_file(source)
    original_copy = shutil.copy2

    def mutate_after_copy(src: Path, dst: Path) -> str:
        result = original_copy(src, dst)
        Path(src).write_bytes(b"changed after validation")
        return str(result)

    monkeypatch.setattr(package_v5_artifacts.shutil, "copy2", mutate_after_copy)
    with pytest.raises(Exception, match="changed during copy"):
        package_v5_artifacts.copy_snapshot(
            source, tmp_path / "destination.bin", expected
        )


def test_signed_rank_oracle_matches_scipy_exhaustive_small_cases() -> None:
    rng = np.random.default_rng(20260921)
    method = stats.PermutationMethod(n_resamples=np.inf)
    for _ in range(12):
        values = rng.integers(-3, 4, size=8).astype(np.float64)
        nonzero = values[values != 0]
        if not len(nonzero):
            continue
        for alternative in ("two-sided", "greater", "less"):
            expected = stats.wilcoxon(
                nonzero, alternative=alternative, method=method
            ).pvalue
            actual = verify_v5_neural.signed_rank_oracle(
                values, alternative
            )["p"]
            assert actual == expected


def test_holm_oracle_uses_strict_alpha_boundary_and_retains_undefined() -> None:
    result = verify_v5_neural.holm_oracle(
        {"boundary": 0.025, "undefined": None}, 0.05
    )
    assert result["boundary"]["p_adj"] == pytest.approx(0.05)
    assert result["boundary"]["reject"] is False
    assert result["undefined"]["p_adj"] == 1.0
    assert result["undefined"]["reject"] is False


def test_independent_aggregate_oracle_handles_singleton_and_detects_tamper() -> None:
    y_true = np.array([0, 0, 1, 1], dtype=np.int64)
    y_pred = np.array([0, 1, 1, 1], dtype=np.int64)
    probabilities = np.array([
        [0.9, 0.1], [0.2, 0.8], [0.4, 0.6], [0.1, 0.9],
    ], dtype=np.float64)
    row = verify_v5_neural.metric_oracle(
        y_true, y_pred, probabilities, ["normal", "attack"]
    )
    row["seed"] = 0
    stored = aggregate([row], ["normal", "attack"])
    verify_v5_neural.compare_aggregate(
        stored, [row], ["normal", "attack"], "singleton"
    )

    changed = copy.deepcopy(stored)
    changed["confusion_matrix_mean"][0][0] += 1
    with pytest.raises(Exception, match="confusion-matrix mean differs"):
        verify_v5_neural.compare_aggregate(
            changed, [row], ["normal", "attack"], "tampered"
        )


def test_tree_oracle_rejects_hyperparameter_and_onnx_matrix_drift(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = {
        "content_sha256": "a" * 64,
        "random_forest_seeds": list(range(20)),
        "xgboost_seeds": [0],
        "deployment_seed": 0,
        "threads": 16,
        "datasets": {"nslkdd": {}, "unsw": {}},
        "hyperparameters": {
            "random_forest": {
                "n_estimators": 100, "max_depth": 20,
                "class_weight": "balanced",
            },
            "xgboost": {
                "n_estimators": 100, "max_depth": 6, "learning_rate": 0.1,
                "tree_method": "hist", "subsample": 1.0,
                "colsample_bytree": 1.0,
                "sample_weight": "inverse fit-class frequency",
            },
        },
    }
    report = {"rf_onnx": [
        {"dataset": "nslkdd"}, {"dataset": "unsw"},
    ]}
    monkeypatch.setattr(
        verify_v5_tree, "load_verified_tree_suite", lambda _path: (plan, report)
    )
    changed = copy.deepcopy(plan)
    changed["hyperparameters"]["xgboost"]["max_depth"] = 7
    monkeypatch.setattr(
        verify_v5_tree, "load_verified_tree_suite", lambda _path: (changed, report)
    )
    with pytest.raises(Exception, match="hyperparameters differ"):
        verify_v5_tree.verify(tmp_path)

    duplicate = {"rf_onnx": [
        {"dataset": "nslkdd"}, {"dataset": "nslkdd"},
    ]}
    monkeypatch.setattr(
        verify_v5_tree, "load_verified_tree_suite", lambda _path: (plan, duplicate)
    )
    with pytest.raises(Exception, match="exactly one row"):
        verify_v5_tree.verify(tmp_path)


def test_independent_logit_comparison_detects_prediction_change() -> None:
    reference = np.array([[2.0, 1.0], [0.0, 3.0]], dtype=np.float32)
    identical = run_v5_exports.compare_logits(reference, reference.copy(), 1e-6, 1e-5)
    assert identical["allclose"] is True
    assert identical["prediction_disagreement_fraction"] == 0.0

    changed = reference.copy()
    changed[0] = [0.0, 4.0]
    disagreement = run_v5_exports.compare_logits(reference, changed, 1e-6, 1e-5)
    assert disagreement["allclose"] is False
    assert disagreement["prediction_disagreement_fraction"] == 0.5


def _failure_payload(output: Path, export_plan: dict, dataset: str, model: str,
                     mode: str) -> dict:
    checkpoint = next(row["checkpoint_sha256"] for row in export_plan["attempts"]
                      if (row["dataset"], row["model"], row["mode"]) == (dataset, model, mode))
    write_json(output / "export_policy.json", seal({
        "export_plan_sha256": export_plan["content_sha256"],
        "checkpoint_sha256": checkpoint,
        "qdq_recipe": run_v5_exports.fixed_export_protocol()["qdq_recipe"],
    }))
    write_json(output / "FAILED.json", seal({
        "schema": 1, "status": "failed", "publication_gate": False,
        "source_plan_sha256": export_plan["source_plan_sha256"],
        "export_plan_sha256": export_plan["content_sha256"],
        "checkpoint_sha256": checkpoint, "stage": "freeze",
        "reason": "ContractError: BN folding/freezing changed outputs beyond the predeclared gate; inspect boundary activations",
        "diagnostics": {"freeze_check": {"allclose": False, "vectors_checked": 1024,
                        "max_abs_error": 1.0, "prediction_disagreement_fraction": 0.1}},
        "partial_files_sha256": {"export_policy.json": sha256(output / "export_policy.json")},
    }))
    inventory = run_v5_exports.output_files_sha256(output)
    return {
        "return_code": 1, "failure_file": "FAILED.json",
        "failure_file_sha256": sha256(output / "FAILED.json"),
        "failure_classification": "reproduced_scientific_gate", "failure_replay_error": None,
        "failure_replay": {"kind": "exact_scientific_failure_replay", "passed": True,
                           "export_plan_sha256": export_plan["content_sha256"],
                           "failure_sha256": sha256(output / "FAILED.json"),
                           "output_files_sha256": inventory},
    }


def _make_export_matrix(root: Path, plan_sha256: str, monkeypatch) -> dict:
    formal = root / "formal"
    paper = root / "paper"
    runner_provenance = verify_v5_neural.tool_provenance(
        ROOT / "tools/run_v5_exports.py",
        [sys.executable, str(ROOT / "tools/run_v5_exports.py"),
         "--run-dir", str(formal), "--output-root", str(root),
         "--paper-dir", str(paper)],
        run_v5_exports.EXPORT_RUNNER_PACKAGES,
        cwd=ROOT,
    )
    export_plan = seal({
        "source_plan_sha256": plan_sha256, "tool_provenance": runner_provenance,
        "protocol": run_v5_exports.fixed_export_protocol(),
        "run_dir": str(formal.resolve()),
        "attempts": [{"dataset": d, "model": m, "mode": q, "output_dir": f"{d}/{m}/{q}",
                      "checkpoint_sha256": "c" * 64}
                     for d, m in JOBS for q in ("fp32", "qdq")],
    })
    # This unit fixture isolates matrix validation; full archive fixtures below
    # exercise the actual plan/registration gate without replacing validators.
    monkeypatch.setattr(package_v5_artifacts, "load_export_plan", lambda *_a, **_k: export_plan)
    monkeypatch.setattr(run_v5_exports, "load_export_plan", lambda *_a, **_k: export_plan)
    attempts = []
    for dataset, model in JOBS:
        for mode in ("fp32", "qdq"):
            output_dir = root / dataset / model / mode
            output_dir.mkdir(parents=True)
            log = root / "logs" / f"{dataset}_{model}_{mode}.log"
            log.parent.mkdir(exist_ok=True)
            log.write_text("synthetic test log\n", encoding="utf-8")
            passed = mode == "fp32"
            evidence_path = output_dir / "runner_validation.json"
            if passed:
                payload_names = {
                    "export_policy.json", "validation_vectors.npz", "preprocessing.json",
                    "calibration_rows.json", "model_fp32.onnx",
                }
                for name in payload_names:
                    (output_dir / name).write_bytes(f"{dataset}/{model}/{name}".encode())
                report_path = output_dir / "export_report.json"
                write_json(report_path, seal({
                    "export_plan_sha256": export_plan["content_sha256"],
                    "files_sha256": {
                        name: sha256(output_dir / name) for name in sorted(payload_names)
                    }
                }))
                evidence = {
                    "status": "independently_validated",
                    "publication_gate": True,
                    "source_plan_sha256": plan_sha256,
                    "dataset": dataset,
                    "model": model,
                    "mode": mode,
                    "export_report_sha256": sha256(report_path),
                    "checkpoint_logits_sha256": "c" * 64,
                    "checkpoint_check": {
                        "allclose": True,
                        "max_abs_error": 0.0,
                        "prediction_disagreement_fraction": 0.0,
                        "vectors_checked": 1024,
                    },
                    "fp32_check": {
                        "allclose": True,
                        "max_abs_error": 1.25e-6,
                        "prediction_disagreement_fraction": 0.0,
                        "vectors_checked": 1024,
                    },
                    "qdq_check": None,
                    "fp32_operators": ["Gemm"],
                    "qdq_operators": None,
                    "qdq_int8_initializer_count": None,
                    "acceptance_basis":
                        "independent recomputation; raw export report consistency checked",
                    "tool_provenance": runner_provenance,
                    "exporter_invocation": ["synthetic test exporter"],
                }
                return_code = 0
            else:
                evidence = {
                    "status": "export_subprocess_failed",
                    "publication_gate": False,
                    "source_plan_sha256": plan_sha256,
                    "dataset": dataset,
                    "model": model,
                    "mode": mode,
                    "tool_provenance": runner_provenance,
                    "exporter_invocation": ["synthetic test exporter"],
                }
                evidence.update(_failure_payload(output_dir, export_plan, dataset, model, mode))
                return_code = 1
            evidence["export_plan_sha256"] = export_plan["content_sha256"]
            evidence["output_files_sha256"] = {
                path.name: sha256(path)
                for path in sorted(output_dir.iterdir()) if path.is_file()
            }
            write_json(evidence_path, seal(evidence))
            relative_dir = f"{dataset}/{model}/{mode}"
            attempts.append({
                "export_plan_sha256": export_plan["content_sha256"],
                "dataset": dataset,
                "model": model,
                "mode": mode,
                "passed": passed,
                "return_code": return_code,
                "elapsed_seconds": 1.0,
                "output_dir": relative_dir,
                "evidence": f"{relative_dir}/runner_validation.json",
                "evidence_sha256": sha256(evidence_path),
                "log": f"logs/{dataset}_{model}_{mode}.log",
                "log_sha256": sha256(log),
            })
    summary = {
        "export_plan_sha256": export_plan["content_sha256"],
        "source_plan_sha256": plan_sha256,
        "deployment_seed": 0,
        "fold_bn": True,
        "fp32_atol": 1e-6,
        "fp32_rtol": 1e-5,
        "fp32_max_prediction_disagreement": 0.0,
        "int8_max_prediction_disagreement": 0.01,
        "validation_samples": 1024,
        "calibration_samples": 1000,
        "attempts": attempts,
        "fp32_passed": len(JOBS),
        "fp32_total": len(JOBS),
        "qdq_passed": 0,
        "qdq_total": len(JOBS),
        "all_gates_passed": False,
        "tool_provenance": runner_provenance,
    }
    write_json(root / "summary.json", seal(summary))
    return summary


def test_export_matrix_rejects_post_validation_tamper(tmp_path: Path, monkeypatch) -> None:
    plan = {"content_sha256": "a" * 64}
    _make_export_matrix(tmp_path, plan["content_sha256"], monkeypatch)
    checked = package_v5_artifacts.validate_export_matrix(tmp_path, plan)
    assert checked["fp32_passed"] == len(JOBS)

    tampered = tmp_path / "nslkdd" / "relu" / "fp32" / "model_fp32.onnx"
    tampered.write_bytes(b"changed after runner validation")
    with pytest.raises(Exception, match="incomplete or changed"):
        package_v5_artifacts.validate_export_matrix(tmp_path, plan)


@pytest.mark.parametrize("mutation", ["summary_policy", "summary_count", "row_plan", "infra", "passing_failure"])
def test_package_matrix_rejects_resealed_false_export_claims(tmp_path, monkeypatch, mutation):
    plan = {"content_sha256": "a" * 64}
    _make_export_matrix(tmp_path, plan["content_sha256"], monkeypatch)
    summary = load_json(tmp_path / "summary.json")
    summary.pop("content_sha256")
    row = summary["attempts"][1]
    if mutation == "summary_policy":
        summary["int8_max_prediction_disagreement"] = 0.99
    elif mutation == "summary_count":
        summary["qdq_total"] = 999
    elif mutation == "row_plan":
        row["export_plan_sha256"] = "f" * 64
    else:
        evidence_path = tmp_path / row["evidence"]
        evidence = load_json(evidence_path)
        evidence.pop("content_sha256")
        if mutation == "infra":
            evidence["failure_classification"] = "infrastructure_or_unclassified"
        else:
            failure_path = tmp_path / row["output_dir"] / "FAILED.json"
            failure = load_json(failure_path)
            failure.pop("content_sha256")
            failure["diagnostics"]["freeze_check"].update(
                allclose=True, max_abs_error=0.0, prediction_disagreement_fraction=0.0)
            write_json(failure_path, seal(failure))
            evidence["output_files_sha256"]["FAILED.json"] = sha256(failure_path)
        write_json(evidence_path, seal(evidence))
        row["evidence_sha256"] = sha256(evidence_path)
    write_json(tmp_path / "summary.json", seal(summary))
    with pytest.raises(ContractError):
        package_v5_artifacts.validate_export_matrix(tmp_path, plan)


def test_tree_verifier_provenance_requires_neural_run_dir(tmp_path):
    tool = ROOT / "tools/verify_v5_tree.py"
    with pytest.raises(Exception, match="required"):
        verify_v5_neural.canonical_tool_invocation(
            tool, [sys.executable, str(tool), "--tree-run-dir", str(tmp_path)], ROOT)
    command = [sys.executable, str(tool), "--tree-run-dir", str(tmp_path / "tree"),
               "--neural-run-dir", str(tmp_path / "neural")]
    expected = {"tree_run_dir": str(tmp_path / "tree"),
                "neural_run_dir": str(tmp_path / "neural"),
                "output": str(tmp_path / "tree/independent_verification.json")}
    assert verify_v5_neural.canonical_tool_invocation(tool, command, ROOT) == expected
    assert archive_pre_v5._canonical_lifecycle_invocation(tool.name, command, str(ROOT)) == expected


def test_package_replays_export_validation_and_rejects_stale_failure(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "only" / "relu" / "fp32"
    output.mkdir(parents=True)
    evidence_path = output / "runner_validation.json"
    formal = tmp_path / "formal"
    runner_provenance = verify_v5_neural.tool_provenance(
        ROOT / "tools/run_v5_exports.py",
        [sys.executable, str(ROOT / "tools/run_v5_exports.py"),
         "--run-dir", str(formal), "--output-root", str(tmp_path),
         "--paper-dir", str(tmp_path / "paper")],
        run_v5_exports.EXPORT_RUNNER_PACKAGES,
        cwd=ROOT,
    )
    command = run_v5_exports.exporter_invocation(
        formal, output, "only", "relu", "fp32", 1024, 1000, 0.01
    )
    validation = {
        "status": "independently_validated",
        "publication_gate": True,
        "source_plan_sha256": "a" * 64,
        "dataset": "only",
        "model": "relu",
        "mode": "fp32",
        "output_files_sha256": {},
    }
    write_json(evidence_path, seal({
        **validation,
        "tool_provenance": runner_provenance,
        "exporter_invocation": command,
    }))
    summary = {"tool_provenance": runner_provenance, "attempts": [{
        "dataset": "only", "model": "relu", "mode": "fp32",
        "passed": True, "return_code": 0, "output_dir": "only/relu/fp32",
        "evidence": "only/relu/fp32/runner_validation.json",
    }]}
    export_plan = {"content_sha256": "e" * 64}
    summary["export_plan_sha256"] = export_plan["content_sha256"]
    monkeypatch.setattr(package_v5_artifacts, "load_export_plan", lambda *_a, **_k: export_plan)
    monkeypatch.setattr(package_v5_artifacts, "validate_attempt",
                        lambda **_kwargs: validation)
    package_v5_artifacts.replay_export_matrix(
        formal, tmp_path, {"content_sha256": "a" * 64}, summary
    )

    failed = {
        "status": "runner_validation_failed",
        "reason": "RuntimeError: deterministic failure",
        "publication_gate": False,
        "source_plan_sha256": "a" * 64,
        "dataset": "only",
        "model": "relu",
        "mode": "fp32",
        "tool_provenance": runner_provenance,
        "exporter_invocation": command,
        "output_files_sha256": {},
    }
    write_json(evidence_path, seal(failed))
    summary["attempts"][0].update(passed=False, return_code=0)

    def fail_again(**_kwargs):
        raise RuntimeError("deterministic failure")

    monkeypatch.setattr(package_v5_artifacts, "validate_attempt", fail_again)
    with pytest.raises(Exception, match="Unclassified/infrastructure"):
        package_v5_artifacts.replay_export_matrix(
            formal, tmp_path, {"content_sha256": "a" * 64}, summary
        )


def test_infrastructure_failure_is_rejected_without_replay(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    formal = tmp_path / "formal"
    output_dir = tmp_path / "only/relu/fp32"
    output_dir.mkdir(parents=True)
    evidence_path = output_dir / "runner_validation.json"
    command = run_v5_exports.exporter_invocation(
        formal, output_dir, "only", "relu", "fp32", 1024, 1000, 0.01
    )
    evidence = seal({
        "status": "export_subprocess_failed",
        "return_code": 7,
        "source_plan_sha256": "a" * 64,
        "dataset": "only", "model": "relu", "mode": "fp32",
        "failure_file": None, "failure_file_sha256": None,
        "publication_gate": False,
        "exporter_invocation": command,
        "output_files_sha256": {},
    })
    write_json(evidence_path, evidence)
    original_bytes = evidence_path.read_bytes()
    summary = {"attempts": [{
        "dataset": "only", "model": "relu", "mode": "fp32",
        "passed": False, "return_code": 7,
        "output_dir": "only/relu/fp32",
        "evidence": "only/relu/fp32/runner_validation.json",
    }]}
    export_plan = {"content_sha256": "e" * 64}
    summary["export_plan_sha256"] = export_plan["content_sha256"]
    monkeypatch.setattr(package_v5_artifacts, "load_export_plan", lambda *_a, **_k: export_plan)
    def forbidden_replay(*args, **kwargs):
        pytest.fail("Infrastructure error must not be replayed as a scientific outcome")
    monkeypatch.setattr(package_v5_artifacts, "replay_scientific_failure", forbidden_replay)
    with pytest.raises(Exception, match="Unclassified/infrastructure"):
        package_v5_artifacts.replay_export_matrix(
            formal, tmp_path, {"content_sha256": "a" * 64}, summary
        )
    assert evidence_path.read_bytes() == original_bytes


def test_export_paper_macros_are_evidence_derived_and_sealed(tmp_path: Path, monkeypatch) -> None:
    plan = {"content_sha256": "a" * 64}
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text("test\n", encoding="utf-8")
    _make_export_matrix(tmp_path, plan["content_sha256"], monkeypatch)
    summary_path = tmp_path / "summary.json"
    summary = run_v5_exports.load_json(summary_path)

    values = run_v5_exports.expected_export_macros(tmp_path, summary)
    assert values["vExportFpPassed"] == str(len(JOBS))
    assert values["vExportQdqPassed"] == "0"
    assert values["vExportFpWorstAbsError"] == r"1.250\times 10^{-6}"
    assert values["vExportQdqWorstPassedDisagreementPct"] == r"\text{n/a}"

    run_v5_exports.emit_export_macros(tmp_path, paper, plan, summary_path)
    macro = paper / "export_macros_v5.tex"
    provenance = run_v5_exports.load_json(
        paper / "export_macros_v5.provenance.json"
    )
    run_v5_exports.check_seal(provenance)
    assert provenance["macro_sha256"] == sha256(macro)

    evidence = tmp_path / "nslkdd" / "relu" / "fp32" / "runner_validation.json"
    value = run_v5_exports.load_json(evidence)
    value["fp32_check"]["max_abs_error"] = 9.0
    write_json(evidence, value)
    with pytest.raises(Exception, match="missing or changed"):
        run_v5_exports.expected_export_macros(tmp_path, summary)


def test_data_audit_must_match_formal_cache(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    source_spec = {"dataset": "only", "revision": "fixed"}
    source_spec_path = tmp_path / "audit" / "source_specs" / "only.json"
    write_json(source_spec_path, source_spec)
    metadata = seal({
        "data_fingerprint": "d" * 64,
        "features": ["f0"],
        "class_names": ["normal", "attack"],
        "counts": {"fit": 6, "validation": 2, "test": 2},
        "raw_rows": 10,
        "partition": {"retained_rows": 10, "excluded_rows": 0},
        "raw_binding": {
            "source_spec": source_spec,
            "files": [{"path": "raw.csv", "role": "combined", "sha256": "b" * 64}],
        },
    })
    write_json(cache / "metadata.json", metadata)
    plan = {"jobs": [{
        "dataset": "only", "cache": str(cache), "data_fingerprint": "d" * 64,
    }]}
    audit = {"datasets": {"only": {
        "features": ["f0"],
        "classes": ["normal", "attack"],
        "rows": 10,
        "source_spec": "audit/source_specs/only.json",
        "source_spec_sha256": sha256(source_spec_path),
        "files": [{"path": "raw.csv", "role": "combined", "sha256": "b" * 64}],
    }}}
    original_jobs = package_v5_artifacts.JOBS
    original_package = package_v5_artifacts.PACKAGE
    package_v5_artifacts.JOBS = (("only", "relu"),)
    package_v5_artifacts.PACKAGE = tmp_path
    try:
        package_v5_artifacts.validate_audit_against_caches(audit, plan)
        audit["datasets"]["only"]["files"][0]["sha256"] = "c" * 64
        with pytest.raises(Exception, match="raw file binding mismatch"):
            package_v5_artifacts.validate_audit_against_caches(audit, plan)
    finally:
        package_v5_artifacts.JOBS = original_jobs
        package_v5_artifacts.PACKAGE = original_package


def test_archive_gate_rejects_bundle_payload_tamper(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    formal = tmp_path / "formal"
    formal.mkdir()
    plan = seal({
        "protocol_role": "planned_benchmark",
        "seeds": list(range(20)),
        "deployment_seed": 0,
    })
    write_json(formal / "plan.json", plan)
    verification = seal({"passed": True, "plan_sha256": plan["content_sha256"]})
    write_json(formal / "verification_evaluate.json", verification)
    formal_tree = tmp_path / "formal_tree"
    export_run = tmp_path / "export_run"
    formal_tree.mkdir()
    export_run.mkdir()

    bundle = tmp_path / plan["content_sha256"]
    payload = bundle / "payload" / "checkpoints" / "only" / "relu" / "seed_0.pt"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"verified model")
    live_payload = formal / "results/only_relu/runs/relu_seed_0.pt"
    live_payload.parent.mkdir(parents=True)
    shutil.copy2(payload, live_payload)
    result_path = bundle / "payload" / "evidence" / "neural" / "results" / "only_relu.json"
    write_json(result_path, seal({
        "dataset": "only",
        "kind": "relu",
        "data_fingerprint": "d" * 64,
        "fit_runs": [{
            "seed": 0,
            "best_state_sha256": "b" * 64,
            "final_state_sha256": "f" * 64,
            "best_epoch": 1,
        }],
    }))
    independent_path = (
        bundle / "payload/evidence/neural/independent_verification.json"
    )
    write_json(independent_path, seal({
        "checkpoints": {"only_relu": {"results": {"0": {
            "path": "results/only_relu/runs/relu_seed_0.pt",
            "artifact_sha256": archive_pre_v5.digest_file(payload),
            "best_state_sha256": "b" * 64,
            "final_state_sha256": "f" * 64,
        }}}},
    }))
    live_result_path = formal / "results/only_relu.json"
    live_independent_path = formal / "independent_verification.json"
    shutil.copy2(result_path, live_result_path)
    shutil.copy2(independent_path, live_independent_path)
    manifest = seal({
        "schema": 1,
        "kind": "spikeids_v5_plan_addressed_model_bundle",
        "plan_sha256": plan["content_sha256"],
        "formal_run": str(formal.resolve()),
        "formal_tree_run": str(formal_tree.resolve()),
        "export_run": str(export_run.resolve()),
        "selected_models": [{
            "dataset": "only",
            "model": "relu",
            "seed": 0,
            "checkpoint": "payload/checkpoints/only/relu/seed_0.pt",
                "checkpoint_sha256": archive_pre_v5.digest_file(payload),
                "best_state_sha256": "b" * 64,
                "final_state_sha256": "f" * 64,
            "best_epoch": 1,
            "data_fingerprint": "d" * 64,
        }],
        "files": [
            {
                "path": "payload/checkpoints/only/relu/seed_0.pt",
                "bytes": payload.stat().st_size,
                "sha256": archive_pre_v5.digest_file(payload),
                "source": str(live_payload),
            },
            {
                "path": "payload/evidence/neural/results/only_relu.json",
                "bytes": result_path.stat().st_size,
                "sha256": archive_pre_v5.digest_file(result_path),
                "source": str(live_result_path),
            },
            {
                "path": "payload/evidence/neural/independent_verification.json",
                "bytes": independent_path.stat().st_size,
                "sha256": archive_pre_v5.digest_file(independent_path),
                "source": str(live_independent_path),
            },
        ],
        "full_all_seed_evidence_in_formal_runs": True,
        "large_payload_intended_for_git": False,
    })
    archive_pre_v5.write_json(bundle / "BUNDLE_MANIFEST.json", manifest)
    original_jobs = archive_pre_v5.FORMAL_JOBS
    original_required = archive_pre_v5.REQUIRED_BUNDLE_PATHS
    archive_pre_v5.FORMAL_JOBS = (("only", "relu"),)
    archive_pre_v5.REQUIRED_BUNDLE_PATHS = frozenset({
        "payload/checkpoints/only/relu/seed_0.pt"
    })
    monkeypatch.setattr(archive_pre_v5, "validate_embedded_evidence",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(archive_pre_v5, "validate_bundled_lifecycle_provenance",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(archive_pre_v5, "validate_bundled_resource_evidence",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(archive_pre_v5, "validate_bundled_release_inputs",
                        lambda *_args, **_kwargs: None)
    try:
        hardlink = tmp_path / "checkpoint-hardlink.pt"
        os.link(payload, hardlink)
        with pytest.raises(RuntimeError, match="Missing or symlinked bundle file"):
            archive_pre_v5.validate_execution_gate(formal, bundle)
        hardlink.unlink()
        archive_pre_v5.validate_execution_gate(formal, bundle)
        incomplete_body = {
            key: value for key, value in manifest.items() if key != "content_sha256"
        }
        incomplete_body["selected_models"] = []
        archive_pre_v5.write_json(
            bundle / "BUNDLE_MANIFEST.json", seal(incomplete_body)
        )
        with pytest.raises(RuntimeError, match="exactly one checkpoint"):
            archive_pre_v5.validate_execution_gate(formal, bundle)
        archive_pre_v5.write_json(bundle / "BUNDLE_MANIFEST.json", manifest)
        payload.write_bytes(b"tampered model")
        with pytest.raises(RuntimeError, match="file changed"):
            archive_pre_v5.validate_execution_gate(formal, bundle)
    finally:
        archive_pre_v5.FORMAL_JOBS = original_jobs
        archive_pre_v5.REQUIRED_BUNDLE_PATHS = original_required


def test_archive_embedded_evidence_requires_exact_frozen_source(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    plan = seal({"sources": {"missing.py": "a" * 64}})
    plan_path = bundle / "payload" / "evidence" / "neural" / "plan.json"
    write_json(plan_path, plan)
    manifest = {"tree_plan_sha256": "t" * 64}
    inventory = {
        "payload/evidence/neural/plan.json": {
            "sha256": archive_pre_v5.digest_file(plan_path)
        }
    }
    with pytest.raises(RuntimeError, match="lacks exact frozen source"):
        archive_pre_v5.validate_embedded_evidence(
            bundle, manifest, plan, inventory
        )


def test_tool_report_rejects_single_byte_change(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    write_json(report, seal({"passed": True, "value": "unchanged"}))
    text = report.read_text(encoding="utf-8")
    report.write_text(text.replace("unchanged", "Xnchanged", 1), encoding="utf-8")
    with pytest.raises(Exception, match="Integrity failure"):
        check_seal(load_json(report))


@pytest.mark.parametrize("field", ["source_sha256", "package_version"])
def test_resealed_provenance_cannot_change_tool_or_version(field: str) -> None:
    tool = ROOT / "tools/verify_v5_neural.py"
    provenance = verify_v5_neural.tool_provenance(
        tool,
        [sys.executable, str(tool), "--run-dir", str(ROOT / "synthetic-run")],
        verify_v5_neural.NEURAL_VERIFIER_PACKAGES,
        cwd=ROOT,
    )
    verify_v5_neural.validate_tool_provenance(
        provenance, tool, verify_v5_neural.NEURAL_VERIFIER_PACKAGES
    )
    changed = copy.deepcopy(provenance)
    if field == "source_sha256":
        changed["tool"]["source_sha256"] = "0" * 64
    else:
        changed["packages"]["numpy"] = "forged-version"
    resealed = seal({"tool_provenance": changed})
    check_seal(resealed)
    with pytest.raises(Exception, match="differs from current exact source/runtime"):
        verify_v5_neural.validate_tool_provenance(
            changed, tool, verify_v5_neural.NEURAL_VERIFIER_PACKAGES
        )


def _make_bundled_lifecycle_tools(root: Path) -> tuple[dict, dict[str, dict]]:
    declared = {}
    auxiliary = {}
    inventory = {}
    for name in archive_pre_v5.LIFECYCLE_TOOL_PACKAGES:
        source = ROOT / "tools" / name
        relative = f"payload/source/tools/{name}"
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        digest = archive_pre_v5.digest_file(destination)
        declared[relative] = digest
        inventory[relative] = {"path": relative, "sha256": digest}
    for name in archive_pre_v5.AUXILIARY_TOOLS:
        source = ROOT / "tools" / name
        relative = f"payload/source/tools/{name}"
        destination = root / relative
        destination.write_bytes(source.read_bytes())
        auxiliary[relative] = sha256(destination)
        inventory[relative] = {"path": relative, "sha256": auxiliary[relative]}
    creator = verify_v5_neural.tool_provenance(
        ROOT / "tools/package_v5_artifacts.py",
        [sys.executable, str(ROOT / "tools/package_v5_artifacts.py"),
         "--run-dir", str(root / "formal"),
         "--tree-run-dir", str(root / "tree"),
         "--export-root", str(root / "exports"),
         "--data-audit", str(root / "audit.json"),
         "--data-acceptance", str(root / "data_acceptance.json"),
         "--paper-dir", str(root / "paper"),
         "--paper-build", str(root / "paper-build"),
         "--artifact-root", str(root / "artifacts")],
        package_v5_artifacts.PACKAGE_TOOL_PACKAGES,
        cwd=ROOT,
    )
    manifest = {
        "lifecycle_tools_sha256": declared,
        "auxiliary_tools_sha256": auxiliary,
        "creator_provenance": creator,
        "bundle_replay": package_v5_artifacts.ARCHIVE_REPLAY_BLOCKER,
    }
    return manifest, inventory


def _fixture_resource(formal: Path, plan: dict) -> None:
    rows = [{"boundary": boundary, "elapsed_seconds": elapsed,
             "host": {"vmstat": {"pswpin": 0, "pswpout": 0, "oom_kill": 0}},
             "processes": [{"pid": 1, "start_ticks": 1, "rss_bytes": 1024,
                            "cgroup": "/fixture.scope"}],
             "gpu": None,
             "cgroup": {"path": "/fixture.scope", "memory_max": 16 * 1024 ** 3,
                        "memory_current": 1024, "memory_peak": 2048,
                        "swap_max": 0, "swap_current": 0,
                        "events": {"oom": 0, "oom_kill": 0, "oom_group_kill": 0}}}
            for boundary, elapsed in (("baseline", 0.0), ("final", 0.1))]
    raw = formal / "resource_run_001.jsonl"
    raw.write_bytes(b"\n".join(json_bytes(row) for row in rows) + b"\n")
    write_json(formal / "resource_run_001.json", seal({
        "kind": "spikeids_v5_resource_telemetry", "action": "run",
        "plan_sha256": plan["content_sha256"], "completed": True, "telemetry_passed": True,
        "resource_limits": plan["resource_limits"],
        "raw_samples": {"path": raw.name, "sha256": sha256(raw)}, "samples": 2,
        "duration_seconds": 0.1, "interval_seconds": 1.0,
        "vmstat_delta": {"pswpin": 0, "pswpout": 0, "oom_kill": 0},
        "peak_process_tree_rss_bytes": 1024, "gpu_expected": False, "gpu_samples": 0,
        "sampling_errors": [], "resource_limit_violations": [], "foreign_gpu_pids": [],
        "foreign_gpu_process_identities": [],
    }))


def _fixture_export_plan(formal: Path, exports: Path, plan: dict,
                         provenance: dict) -> dict:
    exposure = seal({"schema": 1, "kind": "spikeids_v5_export_prior_exposure",
                     "source_plan_sha256": plan["content_sha256"], "known_exposures": [],
                     "declaration": "Synthetic test fixture, not research evidence.",
                     "complete_history_independently_verified": False,
                     "local_freeze_is_external_preregistration": False})
    write_json(formal / "export_prior_exposure.json", exposure)
    source = run_v5_exports._binding(formal / "plan.json")
    exposure_binding = run_v5_exports._binding(formal / "export_prior_exposure.json")
    export_plan = seal({
        "schema": 1, "kind": "spikeids_v5_export_plan", "source_plan_sha256": plan["content_sha256"],
        "source_plan": source, "run_dir": str(formal), "output_root": str(exports),
        "protocol": run_v5_exports.fixed_export_protocol(), "tool_provenance": provenance,
        "python_executable_sha256": sha256(Path(sys.executable).resolve()),
        "prior_exposure": {"binding": exposure_binding, "declaration": exposure},
        "inputs": [source, exposure_binding],
        "sources": [run_v5_exports._binding(path) for path in run_v5_exports._source_paths()],
        "attempts": [{"dataset": dataset, "model": model, "mode": mode,
                      "output_dir": f"{dataset}/{model}/{mode}", "checkpoint_sha256": "c" * 64}
                     for dataset, model in JOBS for mode in ("fp32", "qdq")],
    })
    write_json(exports / "export_plan.json", export_plan)
    write_json(formal / "export_registration.json", seal({
        "schema": 1, "kind": "spikeids_v5_export_registration",
        "source_plan_sha256": plan["content_sha256"],
        "export_plan_path": str(exports / "export_plan.json"),
        "export_plan_sha256": export_plan["content_sha256"],
        "export_plan_file_sha256": sha256(exports / "export_plan.json"),
    }))
    return export_plan


def _make_full_archive_gate_fixture(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    """Build the full 440/84/22 structural release fixture, using tiny dummy artifacts."""
    formal = tmp_path / "formal"
    tree = tmp_path / "tree"
    exports = tmp_path / "exports"
    paper = (ROOT / ".pytest_cache/lifecycle-paper" /
             hashlib.sha256(str(tmp_path).encode()).hexdigest())
    paper_build = tmp_path / "paper-build"
    artifacts = tmp_path / "artifacts"
    source_code = tmp_path / "source-code"
    for directory in (formal, tree, exports, paper, artifacts, source_code):
        directory.mkdir(parents=True)

    audit_source = source_code / "audit_data.py"
    loader_source = source_code / "data_loaders.py"
    audit_source.write_text("# frozen audit implementation\n", encoding="utf-8")
    loader_source.write_text("# frozen data loader\n", encoding="utf-8")
    audit_datasets = {}
    accepted_datasets = {}
    plan_jobs = []
    semantic_checks = {
        name: True for name in package_v5_artifacts.DATA_ACCEPTANCE_SEMANTIC_CHECKS
    }
    iot_provenance_path = ROOT / "spikeids_v5/audit/iot23_provenance.json"
    iot_provenance = load_json(iot_provenance_path)
    check_seal(iot_provenance)
    iot_spec_path = ROOT / "spikeids_v5/audit/source_specs/iot23.json"
    for index, dataset in enumerate(package_v5_artifacts.FORMAL_DATASETS):
        if dataset == "iot23":
            combined = iot_provenance["combined"]
            raw_files = [{
                "path": combined["path"], "role": "combined",
                "bytes": combined["bytes"], "sha256": combined["sha256"],
                "rows": combined["rows"],
            }]
            raw_rows = combined["rows"]
        else:
            raw_files = [{
                "path": f"raw/{dataset}.csv", "role": "combined",
                "bytes": 4, "sha256": f"{index + 1:x}" * 64, "rows": 4,
            }]
            raw_rows = 4
        audit_datasets[dataset] = {
            "rows": raw_rows,
            "features": ["f0"],
            "classes": ["normal", "attack"],
            "files": raw_files,
        }
        if dataset == "iot23":
            audit_datasets[dataset].update({
                "source_spec": "audit/source_specs/iot23.json",
                "source_spec_sha256": sha256(iot_spec_path),
            })
        data_fingerprint = f"{index + 5:x}" * 64
        metadata_body = {
            "dataset": dataset,
            "data_fingerprint": data_fingerprint,
            "raw_rows": raw_rows,
            "counts": {"fit": 1, "validation": 1, "test": 1},
            "features": ["f0"],
            "class_names": ["normal", "attack"],
            "files_sha256": {},
            "partition": {
                "retained_rows": 3,
                "excluded_rows": raw_rows - 3,
                "retained_pattern_fractions": {
                    "fit": 1 / 3, "validation": 1 / 3, "test": 1 / 3,
                },
            },
            "exact_model_input_group_leakage_excluded": True,
            "capture_device_time_group_generalization_established": False,
            "upstream_preprocessing_verified": False,
        }
        rebuilds = []
        for rebuild_name in ("first", "second"):
            root = tmp_path / "rebuilds" / dataset / rebuild_name
            root.mkdir(parents=True)
            payload = root / "cache.bin"
            payload.write_bytes(f"accepted/{dataset}".encode())
            metadata_body["files_sha256"] = {"cache.bin": sha256(payload)}
            write_json(root / "metadata.json", seal(metadata_body))
            rebuilds.append({
                "resolved_root": str(root.resolve()),
                "metadata_sha256": sha256(root / "metadata.json"),
                "data_fingerprint": data_fingerprint,
                "files_sha256": {"cache.bin": sha256(payload)},
            })
        plan_jobs.append({
            "dataset": dataset,
            "cache": rebuilds[0]["resolved_root"],
            "data_fingerprint": data_fingerprint,
        })
        accepted_datasets[dataset] = {
            "raw_files": raw_files,
            "rebuilds": rebuilds,
            "byte_identical_rebuilds": True,
            "semantic_checks": semantic_checks,
            "cache_counts": metadata_body["counts"],
            "features": metadata_body["features"],
            "classes": metadata_body["class_names"],
            "realized_pattern_fractions":
                metadata_body["partition"]["retained_pattern_fractions"],
        }
    audit_path = tmp_path / "audit.json"
    audit = seal({
        "raw_source_audit_passed": True,
        "data_acceptance_passed": False,
        "audit_implementation_sha256": sha256(audit_source),
        "data_loader_sha256": sha256(loader_source),
        "datasets": audit_datasets,
    })
    write_json(audit_path, audit)
    data_acceptance_path = tmp_path / "data_acceptance.json"
    write_json(data_acceptance_path, seal({
        "kind": "spikeids_v5_data_acceptance",
        "acceptance_schema": 1,
        "data_acceptance_passed": True,
        "two_distinct_fresh_roots": True,
        "byte_identical_rebuilds": True,
        "raw_audit": {
            "path": str(audit_path.resolve()),
            "sha256": sha256(audit_path),
            "content_sha256": audit["content_sha256"],
            "audit_implementation_sha256": sha256(audit_source),
            "raw_source_audit_passed": True,
        },
        "producer": {"path": str(loader_source.resolve()),
                     "sha256": sha256(loader_source)},
        "independent_verifier": {"path": str(audit_source.resolve()),
                                 "sha256": sha256(audit_source)},
        "upstream_provenance": {
            "path": str(iot_provenance_path.resolve()),
            "sha256": sha256(iot_provenance_path),
            "content_sha256": iot_provenance["content_sha256"],
            "comparison_passed": True,
        },
        "datasets": accepted_datasets,
        "limitations": {
            name: False for name in package_v5_artifacts.DATA_ACCEPTANCE_LIMITATIONS
        },
    }))
    environment = {"python": "test-runtime", "platform": "test-platform"}
    dataset_jobs = {job["dataset"]: job for job in plan_jobs}
    plan_jobs = [{**dataset_jobs[d], "id": f"{d}_{m}", "model": m,
                  "hyperparameters": {"device": "cpu", "seeds": list(range(20))}}
                 for d, m in JOBS]
    plan = seal({
        "schema": 5,
        "protocol_role": "planned_benchmark",
        "seeds": list(range(20)),
        "deployment_seed": 0,
        "environment": environment,
        "sources": {
            "audit_data.py": sha256(audit_source),
            "data_loaders.py": sha256(loader_source),
            "resource_evidence.py": sha256(ROOT / "spikeids_v5/resource_evidence.py"),
            "contracts.py": sha256(ROOT / "spikeids_v5/contracts.py"),
        },
        "resource_limits": {"maximum_process_tree_rss_bytes": 14 * 1024 ** 3,
                            "require_bounded_cgroup": True,
                            "maximum_cgroup_memory_bytes": 16 * 1024 ** 3,
                            "require_zero_swap_io": True, "require_zero_oom_kills": True},
        "jobs": plan_jobs,
    })
    write_json(formal / "plan.json", plan)
    write_json(formal / "environment.json", environment)
    _fixture_resource(formal, plan)
    verification_fit = seal({"passed": True, "plan_sha256": plan["content_sha256"]})
    verification_evaluate = seal({"passed": True, "plan_sha256": plan["content_sha256"]})
    write_json(formal / "verification_fit.json", verification_fit)
    write_json(formal / "verification_evaluate.json", verification_evaluate)
    stats_path = formal / "stats_report_globecom.json"
    equivalence_path = formal / "equivalence_v5.json"
    write_json(stats_path, seal({"kind": "difference"}))
    write_json(equivalence_path, seal({"kind": "equivalence"}))
    write_json(formal / "paper_numeric_check.json", seal({
        "numeric_consistency_passed": True,
        "strict_heuristic_scan_passed": True,
    }))

    best_digest, final_digest = "b" * 64, "f" * 64
    checkpoints = {}
    selected_models = []
    for job in plan_jobs:
        dataset, model, job_id = job["dataset"], job["model"], job["id"]
        checkpoints[job_id] = {}
        for execution in ("results", "replicas"):
            work = formal / execution / job_id
            (work / "runs").mkdir(parents=True)
            per_seed, fit_runs = [], []
            checkpoints[job_id][execution] = {}
            for seed in range(20):
                checkpoint = work / "runs" / f"{model}_seed_{seed}.pt"
                prediction = work / "runs" / f"{model}_seed_{seed}_predictions.npz"
                checkpoint.write_bytes(f"dummy checkpoint/{job_id}/{execution}/{seed}".encode())
                prediction.write_bytes(f"dummy predictions/{job_id}/{execution}/{seed}".encode())
                checkpoints[job_id][execution][str(seed)] = {
                    "path": checkpoint.relative_to(formal).as_posix(),
                    "artifact_sha256": sha256(checkpoint),
                    "best_state_sha256": best_digest, "final_state_sha256": final_digest,
                }
                per_seed.append({"seed": seed, "artifact": {
                    "filename": prediction.name, "sha256": sha256(prediction)}})
                fit_runs.append({"seed": seed, "best_epoch": 1,
                                 "best_state_sha256": best_digest,
                                 "final_state_sha256": final_digest})
            for filename in ("manifest.json", "fit_manifest.json", "fit_evidence.json"):
                write_json(work / filename, seal({"synthetic": True}))
            write_json(work.with_suffix(".json"), seal({
                "status": "complete", "dataset": dataset, "kind": model,
                "data_fingerprint": job["data_fingerprint"],
                "formal": {"plan_sha256": plan["content_sha256"]},
                "per_seed": per_seed, "fit_runs": fit_runs,
            }))
        checkpoint = formal / "results" / job_id / "runs" / f"{model}_seed_0.pt"
        selected_models.append({
            "dataset": dataset, "model": model, "seed": 0,
            "checkpoint": f"payload/checkpoints/{dataset}/{model}/seed_0.pt",
            "checkpoint_sha256": sha256(checkpoint),
            "best_state_sha256": best_digest, "final_state_sha256": final_digest,
            "best_epoch": 1, "data_fingerprint": job["data_fingerprint"],
        })
    (formal / "equivalence_v5.md").write_text("Synthetic equivalence report\\n")

    neural_provenance = verify_v5_neural.tool_provenance(
        ROOT / "tools/verify_v5_neural.py",
        [sys.executable, str(ROOT / "tools/verify_v5_neural.py"),
         "--run-dir", str(formal)],
        verify_v5_neural.NEURAL_VERIFIER_PACKAGES,
        cwd=ROOT,
    )
    neural_independent_path = formal / "independent_verification.json"
    write_json(neural_independent_path, seal({
        "kind": "independent_formal_neural_and_statistics_verification",
        "passed": True,
        "plan_sha256": plan["content_sha256"],
        "verification_fit_sha256": sha256(formal / "verification_fit.json"),
        "verification_evaluate_sha256": sha256(formal / "verification_evaluate.json"),
        "prediction_artifacts_checked": 440,
        "checkpoints_checked": 440,
        "executions_checked": 22,
        "checkpoints": checkpoints,
        "statistics": {
            "difference_report_sha256": sha256(stats_path),
            "equivalence_report_sha256": sha256(equivalence_path),
            "difference_hypotheses": 14,
            "equivalence_hypotheses": 8,
        },
        "tool_provenance": neural_provenance,
    }))

    neural_binding = {"path": str(formal / "plan.json"), "sha256": sha256(formal / "plan.json"),
                      "content_sha256": plan["content_sha256"]}
    acceptance_binding = {"path": str(data_acceptance_path), "sha256": sha256(data_acceptance_path),
                          "content_sha256": load_json(data_acceptance_path)["content_sha256"]}
    tree_plan = seal({"kind": "tree_baseline_plan", "deployment_seed": 0,
                      "neural_plan": neural_binding, "data_acceptance": acceptance_binding,
                      "random_forest_seeds": list(range(20)), "xgboost_seeds": [0],
                      "datasets": {"nslkdd": {}, "unsw": {}}})
    write_json(tree / "test_exposure.json", seal({"kind": "synthetic-test-exposure"}))
    write_json(tree / "plan.json", tree_plan)
    write_json(tree / "verification_fit.json", seal({"passed": True}))
    write_json(tree / "results.json", seal({"kind": "tree-results"}))
    tree_models: dict[str, dict] = {}
    rf_onnx = []
    for dataset in ("nslkdd", "unsw"):
        tree_models[dataset] = {}
        for kind in ("random_forest", "xgboost"):
            model_path = tree / f"primary/{dataset}/{kind}/seed_0.joblib"
            model_path.parent.mkdir(parents=True, exist_ok=True)
            model_path.write_bytes(f"{dataset}/{kind}".encode())
            tree_models[dataset][kind] = {}
            for seed in (range(20) if kind == "random_forest" else [0]):
                tree_models[dataset][kind][str(seed)] = {}
                for execution in ("primary", "replica"):
                    record_path = tree / f"{execution}/{dataset}/{kind}/seed_{seed}.json"
                    record_path.parent.mkdir(parents=True, exist_ok=True)
                    record_path.with_suffix(".joblib").write_bytes(model_path.read_bytes())
                    identity = {"execution_id": f"{len(list(tree.rglob('*.ledger.json'))) + 1:032x}",
                                "execution": execution, "record_path": str(record_path),
                                "artifact_path": str(record_path.with_suffix('.joblib'))}
                    ledger_path = record_path.with_suffix('.ledger.json')
                    ledger = seal({"ledger_kind": "tree_execution_ledger", "run_dir": str(tree),
                                   "execution_identity": identity})
                    write_json(ledger_path, ledger)
                    write_json(record_path, seal({
                        "execution_identity": identity,
                        "execution_ledger_sha256": sha256(ledger_path),
                        "execution_ledger_content_sha256": ledger["content_sha256"],
                    }))
                    tree_models[dataset][kind][str(seed)][execution] = {
                        "artifact": record_path.with_suffix(".joblib").relative_to(tree).as_posix(),
                        "artifact_sha256": sha256(record_path.with_suffix(".joblib")),
                        "record_sha256": sha256(record_path),
                        "execution_ledger_sha256": sha256(ledger_path),
                        "execution_identity": identity,
                    }
        onnx_path = tree / f"onnx/rf_{dataset}_seed_0.onnx"
        onnx_path.parent.mkdir(parents=True, exist_ok=True)
        onnx_path.write_bytes(f"onnx/{dataset}".encode())
        rf_onnx.append({
            "dataset": dataset,
            "onnx": f"onnx/{onnx_path.name}",
            "onnx_sha256": sha256(onnx_path),
        })
    tree_provenance = verify_v5_neural.tool_provenance(
        ROOT / "tools/verify_v5_tree.py",
        [sys.executable, str(ROOT / "tools/verify_v5_tree.py"),
         "--tree-run-dir", str(tree), "--neural-run-dir", str(formal)],
        verify_v5_tree.TREE_VERIFIER_PACKAGES,
        cwd=ROOT,
    )
    tree_independent_path = tree / "independent_verification.json"
    write_json(tree_independent_path, seal({
        "kind": "independent_formal_tree_verification",
        "passed": True,
        "tree_plan_sha256": tree_plan["content_sha256"],
        "tree_results_sha256": sha256(tree / "results.json"),
        "tree_fit_verification_sha256": sha256(tree / "verification_fit.json"),
        "neural_plan": neural_binding, "data_acceptance": acceptance_binding,
        "test_exposure_sha256": sha256(tree / "test_exposure.json"),
        "models": tree_models,
        "rf_onnx": rf_onnx,
        "tool_provenance": tree_provenance,
    }))

    runner_provenance = verify_v5_neural.tool_provenance(
        ROOT / "tools/run_v5_exports.py",
        [sys.executable, str(ROOT / "tools/run_v5_exports.py"),
         "--run-dir", str(formal), "--output-root", str(exports),
         "--paper-dir", str(paper)],
        run_v5_exports.EXPORT_RUNNER_PACKAGES,
        cwd=ROOT,
    )
    export_plan = _fixture_export_plan(formal, exports, plan, runner_provenance)
    attempts = []
    live_fp32_graph = exports / "nslkdd/relu/fp32/model_fp32.onnx"
    for dataset, model, mode in [(d, m, q) for d, m in JOBS for q in ("fp32", "qdq")]:
        output_dir = exports / f"{dataset}/{model}/{mode}"
        output_dir.mkdir(parents=True)
        log = exports / f"logs/{dataset}_{model}_{mode}.log"
        log.parent.mkdir(exist_ok=True)
        log.write_text(f"{mode} log\n", encoding="utf-8")
        passed = mode == "fp32"
        if passed:
            payload_names = {
                "export_policy.json", "validation_vectors.npz", "preprocessing.json",
                "calibration_rows.json", "model_fp32.onnx",
            }
            for name in payload_names:
                (output_dir / name).write_bytes(f"fp32/{name}".encode())
            report_path = output_dir / "export_report.json"
            write_json(report_path, seal({
                "export_plan_sha256": export_plan["content_sha256"],
                "files_sha256": {
                    name: sha256(output_dir / name) for name in sorted(payload_names)
                }
            }))
        failure_fields = {} if passed else _failure_payload(
            output_dir, export_plan, dataset, model, mode
        )
        output_files = {
            path.name: sha256(path)
            for path in sorted(output_dir.iterdir()) if path.is_file()
        }
        evidence_path = output_dir / "runner_validation.json"
        evidence = {
            "status": "independently_validated" if passed else "export_subprocess_failed",
            "export_plan_sha256": export_plan["content_sha256"],
            **failure_fields,
            "publication_gate": passed,
            "source_plan_sha256": plan["content_sha256"],
            "dataset": dataset,
            "model": model,
            "mode": mode,
            "tool_provenance": runner_provenance,
            "exporter_invocation": run_v5_exports.exporter_invocation(
                formal, output_dir, dataset, model, mode, 1024, 1000, 0.01
            ),
            "output_files_sha256": output_files,
        }
        if passed:
            evidence.update({
                "export_report_sha256": sha256(report_path),
                "checkpoint_check": {
                    "allclose": True, "max_abs_error": 0.0,
                    "prediction_disagreement_fraction": 0.0,
                    "vectors_checked": 1024,
                },
                "fp32_check": {
                    "allclose": True, "max_abs_error": 1e-7,
                    "prediction_disagreement_fraction": 0.0,
                    "vectors_checked": 1024,
                },
                "qdq_check": None,
                "qdq_operators": None,
                "qdq_int8_initializer_count": None,
            })
        else:
            evidence["return_code"] = 1
        write_json(evidence_path, seal(evidence))
        relative_dir = f"{dataset}/{model}/{mode}"
        attempts.append({
            "dataset": dataset, "model": model, "mode": mode,
            "export_plan_sha256": export_plan["content_sha256"],
            "elapsed_seconds": 1.0,
            "passed": passed, "return_code": 0 if passed else 1,
            "output_dir": relative_dir,
            "evidence": f"{relative_dir}/runner_validation.json",
            "evidence_sha256": sha256(evidence_path),
            "log": f"logs/{dataset}_{model}_{mode}.log",
            "log_sha256": sha256(log),
        })
    export_summary_path = exports / "summary.json"
    write_json(export_summary_path, seal({
        "export_plan_sha256": export_plan["content_sha256"],
        "source_plan_sha256": plan["content_sha256"],
        "deployment_seed": 0, "fold_bn": True,
        "fp32_atol": 1e-6, "fp32_rtol": 1e-5,
        "fp32_max_prediction_disagreement": 0.0,
        "fp32_passed": 11, "fp32_total": 11,
        "qdq_passed": 0, "qdq_total": 11,
        "all_gates_passed": False,
        "validation_samples": 1024,
        "calibration_samples": 1000,
        "int8_max_prediction_disagreement": 0.01,
        "attempts": attempts,
        "tool_provenance": runner_provenance,
    }))

    for name, body in (
        ("main.tex", b"\\documentclass{IEEEtran}\n\\input{result_macros_v5.tex}\n"
                     b"\\input{export_macros_v5.tex}\n\\begin{document}safe \\cite{x}"
                     b"\\bibliographystyle{IEEEtran}\\bibliography{references}\\end{document}\n"),
        ("references.bib", b"@article{x,title={Safe},author={A},journal={J},year={2026}}\n"),
        ("result_macros_v5.tex", b"% generated\n"),
        ("export_macros_v5.tex", b"% generated\n"),
    ):
        (paper / name).write_bytes(body)
    write_json(paper / "result_macros_v5.provenance.json", seal({
        "plan_sha256": plan["content_sha256"],
        "tree_plan_sha256": tree_plan["content_sha256"],
        "tree_result_sha256": sha256(tree / "results.json"),
        "macro_sha256": sha256(paper / "result_macros_v5.tex"),
    }))
    write_json(paper / "export_macros_v5.provenance.json", seal({
        "kind": "spikeids_v5_export_paper_macros",
        "export_plan_sha256": export_plan["content_sha256"],
        "plan_sha256": plan["content_sha256"],
        "export_summary_sha256": sha256(export_summary_path),
        "macro_sha256": sha256(paper / "export_macros_v5.tex"),
        "tool_provenance": runner_provenance,
    }))
    from tools import build_v5_paper, v5_retention
    from test_paper_build_tool import _make_toolchain
    fake_tools = _make_toolchain(tmp_path, {})
    # Keep the identical toolchain available through archive consumption. The
    # pytest fixture restores PATH only after every validator in this test runs.
    monkeypatch.setenv("PATH", str(fake_tools))
    build_v5_paper.build_paper(
        repo_root=ROOT, paper_dir=paper, output_dir=paper_build,
        plan_paths={"neural": formal / "plan.json", "tree": tree / "plan.json",
                    "export": exports / "export_plan.json"},
    )
    retention = v5_retention.build_retention(formal, tree, exports, {
        "neural": plan["content_sha256"], "tree": tree_plan["content_sha256"],
        "exports": export_plan["content_sha256"],
    })

    bundle = artifacts / plan["content_sha256"]
    bundle.mkdir()
    source_by_relative: dict[str, str] = {}

    def add(source: Path, relative: str) -> None:
        destination = bundle / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        source_by_relative[relative] = str(source.resolve())

    for relative, source in {
        "payload/evidence/neural/plan.json": formal / "plan.json",
        "payload/evidence/neural/environment.json": formal / "environment.json",
        "payload/evidence/neural/verification_fit.json": formal / "verification_fit.json",
        "payload/evidence/neural/verification_evaluate.json": formal / "verification_evaluate.json",
        "payload/evidence/neural/independent_verification.json": neural_independent_path,
        "payload/evidence/neural/stats_report_globecom.json": stats_path,
        "payload/evidence/neural/equivalence_v5.json": equivalence_path,
        "payload/evidence/neural/paper_numeric_check.json": formal / "paper_numeric_check.json",
        "payload/evidence/neural/export_registration.json": formal / "export_registration.json",
        "payload/evidence/neural/export_prior_exposure.json": formal / "export_prior_exposure.json",
        "payload/evidence/neural/resource_run_001.json": formal / "resource_run_001.json",
        "payload/evidence/neural/resource_run_001.jsonl": formal / "resource_run_001.jsonl",
        "payload/evidence/tree/plan.json": tree / "plan.json",
        "payload/evidence/tree/verification_fit.json": tree / "verification_fit.json",
        "payload/evidence/tree/results.json": tree / "results.json",
        "payload/evidence/tree/independent_verification.json": tree_independent_path,
        "payload/evidence/tree/test_exposure.json": tree / "test_exposure.json",
        "payload/evidence/exports/summary.json": export_summary_path,
        "payload/evidence/data/data_audit.json": audit_path,
        "payload/evidence/data/data_acceptance.json": data_acceptance_path,
        "payload/evidence/data/iot23_provenance.json": iot_provenance_path,
        "payload/evidence/data/source_specs/iot23.json": iot_spec_path,
        "payload/evidence/paper/main.tex": paper / "main.tex",
        "payload/evidence/paper/main.pdf": paper_build / "main.pdf",
        "payload/evidence/paper/result_macros_v5.tex": paper / "result_macros_v5.tex",
        "payload/evidence/paper/result_macros_v5.provenance.json":
            paper / "result_macros_v5.provenance.json",
        "payload/evidence/paper/export_macros_v5.tex": paper / "export_macros_v5.tex",
        "payload/evidence/paper/export_macros_v5.provenance.json":
            paper / "export_macros_v5.provenance.json",
        "payload/source/spikeids_v5/audit_data.py": audit_source,
        "payload/source/spikeids_v5/data_loaders.py": loader_source,
        "payload/source/spikeids_v5/resource_evidence.py": ROOT / "spikeids_v5/resource_evidence.py",
        "payload/source/spikeids_v5/contracts.py": ROOT / "spikeids_v5/contracts.py",
        "payload/source/data_acceptance/producer.py": loader_source,
        "payload/source/data_acceptance/independent_verifier.py": audit_source,
        "payload/source/data_acceptance/iot23_provenance_verifier.py":
            ROOT / "tools/verify_iot23_provenance.py",
        "payload/source/requirements.txt": ROOT / "requirements.txt",
    }.items():
        add(source, relative)
    for dataset in ("nslkdd", "unsw"):
        for kind in ("random_forest", "xgboost"):
            add(tree / f"primary/{dataset}/{kind}/seed_0.joblib",
                f"payload/tree_models/{dataset}/{kind}/seed_0.joblib")
        add(tree / f"onnx/rf_{dataset}_seed_0.onnx",
            f"payload/tree_models/{dataset}/random_forest/rf_{dataset}_seed_0.onnx")
    for execution in ("primary", "replica"):
        for source in (tree / execution).rglob("*.json"):
            add(source, f"payload/evidence/tree/{source.relative_to(tree).as_posix()}")
    for source in sorted(exports.rglob("*")):
        if source.is_file():
            add(source, f"payload/exports/{source.relative_to(exports).as_posix()}")
    for selected in selected_models:
        dataset, model = selected["dataset"], selected["model"]
        work = formal / "results" / f"{dataset}_{model}"
        add(work / "runs" / f"{model}_seed_0.pt", selected["checkpoint"])
        add(work.with_suffix(".json"), f"payload/evidence/neural/results/{dataset}_{model}.json")
    lifecycle = {}
    for name in archive_pre_v5.LIFECYCLE_TOOL_PACKAGES:
        relative = f"payload/source/tools/{name}"
        add(ROOT / "tools" / name, relative)
        lifecycle[relative] = sha256(bundle / relative)
    auxiliary = {}
    for name in archive_pre_v5.AUXILIARY_TOOLS:
        relative = f"payload/source/tools/{name}"
        add(ROOT / "tools" / name, relative)
        auxiliary[relative] = sha256(bundle / relative)
    for source in paper_build.rglob("*"):
        if source.is_file():
            add(source, f"payload/evidence/paper_build/{source.relative_to(paper_build).as_posix()}")
    write_json(bundle / "RETENTION_MANIFEST.json", retention)
    source_by_relative["RETENTION_MANIFEST.json"] = "generated full scientific artifact inventory"
    model_card_source = tmp_path / "MODEL_CARD.md"
    model_card_source.write_text("# Synthetic gate fixture\n", encoding="utf-8")
    add(model_card_source, "MODEL_CARD.md")

    creator = verify_v5_neural.tool_provenance(
        ROOT / "tools/package_v5_artifacts.py",
        [sys.executable, str(ROOT / "tools/package_v5_artifacts.py"),
         "--run-dir", str(formal), "--tree-run-dir", str(tree),
         "--export-root", str(exports), "--data-audit", str(audit_path),
         "--data-acceptance", str(data_acceptance_path),
         "--paper-dir", str(paper), "--paper-build", str(paper_build),
         "--artifact-root", str(artifacts)],
        package_v5_artifacts.PACKAGE_TOOL_PACKAGES,
        cwd=ROOT,
    )
    files = []
    for path in sorted(bundle.rglob("*")):
        if path.is_file():
            relative = path.relative_to(bundle).as_posix()
            files.append({
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "source": source_by_relative[relative],
            })
    manifest = seal({
        "schema": 1,
        "kind": "spikeids_v5_plan_addressed_model_bundle",
        "plan_sha256": plan["content_sha256"],
        "tree_plan_sha256": tree_plan["content_sha256"],
        "formal_run": str(formal.resolve()),
        "export_plan_sha256": export_plan["content_sha256"],
        "formal_tree_run": str(tree.resolve()),
        "export_run": str(exports.resolve()),
        "data_audit": str(audit_path.resolve()),
        "data_acceptance": str(data_acceptance_path.resolve()),
        "paper_dir": str(paper.resolve()),
        "paper_build": str(paper_build.resolve()),
        "artifact_root": str(artifacts.resolve()),
        "selected_models": selected_models,
        "creator_provenance": creator,
        "lifecycle_tools_sha256": lifecycle,
        "auxiliary_tools_sha256": auxiliary,
        "bundle_replay": package_v5_artifacts.ARCHIVE_REPLAY_BLOCKER,
        "files": files,
        "full_all_seed_evidence_in_formal_runs": True,
        "large_payload_intended_for_git": False,
    })
    archive_pre_v5.write_json(bundle / "BUNDLE_MANIFEST.json", manifest)
    return formal, bundle, live_fp32_graph


def test_full_archive_gate_replays_embedded_bindings_without_mocking(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    formal, bundle, live_graph = _make_full_archive_gate_fixture(tmp_path, monkeypatch)
    verification, manifest = archive_pre_v5.validate_execution_gate(formal, bundle)
    assert verification["passed"] is True
    assert len(manifest["selected_models"]) == 11

    live_graph.write_bytes(b"changed after bundle creation")
    with pytest.raises(RuntimeError, match="Live formal/tree/export source differs"):
        archive_pre_v5.validate_execution_gate(formal, bundle)


def test_archive_requires_unselected_replica_checkpoint_retention(tmp_path, monkeypatch):
    formal, bundle, _ = _make_full_archive_gate_fixture(tmp_path, monkeypatch)
    archive_pre_v5.validate_execution_gate(formal, bundle)
    missing = formal / "replicas/iot23_qcfs/runs/qcfs_seed_19.pt"
    missing.unlink()
    with pytest.raises(v5_retention.RetentionError, match="Retention"):
        archive_pre_v5.validate_execution_gate(formal, bundle)


def test_archive_uses_verified_build_pdf_not_touched_live_pdf(tmp_path, monkeypatch):
    formal, bundle, _ = _make_full_archive_gate_fixture(tmp_path, monkeypatch)
    manifest = load_json(bundle / "BUNDLE_MANIFEST.json")
    live_pdf = Path(manifest["paper_dir"]) / "main.pdf"
    live_pdf.write_bytes(b"%PDF-1.7\nwrong unrelated live PDF\n%%EOF\n")
    archive_pre_v5.validate_execution_gate(formal, bundle)
    built_pdf = Path(manifest["paper_build"]) / "main.pdf"
    built_pdf.write_bytes(b"%PDF-1.7\nreplacement built PDF\n%%EOF\n")
    with pytest.raises(RuntimeError, match="Live formal/tree/export source differs"):
        archive_pre_v5.validate_execution_gate(formal, bundle)


@pytest.mark.parametrize("mutation", ["registration", "policy", "exposure", "order"])
def test_archive_export_plan_rejects_resealed_contract_mutations(tmp_path, monkeypatch, mutation):
    formal, bundle, _ = _make_full_archive_gate_fixture(tmp_path, monkeypatch)
    manifest = load_json(bundle / "BUNDLE_MANIFEST.json")
    neural = load_json(formal / "plan.json")
    summary = load_json(bundle / "payload/exports/summary.json")
    archive_pre_v5.validate_bundled_export_plan(bundle, manifest, neural, summary)
    path = bundle / "payload/exports/export_plan.json"
    if mutation == "registration":
        path = bundle / "payload/evidence/neural/export_registration.json"
    elif mutation == "exposure":
        path = bundle / "payload/evidence/neural/export_prior_exposure.json"
    changed = load_json(path)
    changed.pop("content_sha256")
    if mutation == "registration":
        changed["export_plan_sha256"] = "0" * 64
    elif mutation == "exposure":
        changed["local_freeze_is_external_preregistration"] = True
    elif mutation == "policy":
        changed["protocol"]["int8_max_prediction_disagreement"] = 0.99
    else:
        changed["attempts"].reverse()
    write_json(path, seal(changed))
    with pytest.raises(RuntimeError):
        archive_pre_v5.validate_bundled_export_plan(bundle, manifest, neural, summary)


@pytest.mark.parametrize("mutation", ["counter", "missing_trace", "unbounded_scope"])
def test_archive_replays_resource_trace_not_only_sealed_summary(tmp_path, monkeypatch, mutation):
    formal, bundle, _ = _make_full_archive_gate_fixture(tmp_path, monkeypatch)
    plan = load_json(formal / "plan.json")
    archive_pre_v5.validate_bundled_resource_evidence(bundle, plan)
    report_path = bundle / "payload/evidence/neural/resource_run_001.json"
    raw = report_path.with_suffix(".jsonl")
    if mutation == "missing_trace":
        raw.unlink()
    else:
        import contracts
        rows = [contracts.loads_json(line) for line in raw.read_bytes().splitlines()]
        if mutation == "counter":
            rows[-1]["host"]["vmstat"]["pswpout"] = 1
        else:
            rows[-1]["cgroup"]["memory_max"] = "max"
        raw.write_bytes(b"\n".join(json_bytes(row) for row in rows) + b"\n")
        report = load_json(report_path)
        report.pop("content_sha256")
        report["raw_samples"]["sha256"] = sha256(raw)
        write_json(report_path, seal(report))
    with pytest.raises((ContractError, FileNotFoundError)):
        archive_pre_v5.validate_bundled_resource_evidence(bundle, plan)


def test_data_acceptance_rejects_resealed_semantic_failure(tmp_path: Path, monkeypatch) -> None:
    formal, bundle, _ = _make_full_archive_gate_fixture(tmp_path, monkeypatch)
    manifest = load_json(bundle / "BUNDLE_MANIFEST.json")
    audit_path = Path(manifest["data_audit"])
    acceptance_path = Path(manifest["data_acceptance"])
    plan = load_json(formal / "plan.json")
    audit = load_json(audit_path)
    package_v5_artifacts.validate_data_acceptance(
        acceptance_path, audit_path, audit, plan
    )

    changed = load_json(acceptance_path)
    changed.pop("content_sha256")
    changed["datasets"]["nslkdd"]["semantic_checks"]["finite_values"] = False
    write_json(acceptance_path, seal(changed))
    with pytest.raises(Exception, match="semantic checks are incomplete"):
        package_v5_artifacts.validate_data_acceptance(
            acceptance_path, audit_path, audit, plan
        )


def test_data_acceptance_rejects_resealed_iot_report_redirect(tmp_path: Path, monkeypatch) -> None:
    formal, bundle, _ = _make_full_archive_gate_fixture(tmp_path, monkeypatch)
    manifest = load_json(bundle / "BUNDLE_MANIFEST.json")
    audit_path = Path(manifest["data_audit"])
    acceptance_path = Path(manifest["data_acceptance"])
    redirected = tmp_path / "redirected" / "iot23_provenance.json"
    redirected.parent.mkdir()
    shutil.copy2(ROOT / "spikeids_v5/audit/iot23_provenance.json", redirected)
    acceptance = load_json(acceptance_path)
    acceptance.pop("content_sha256")
    acceptance["upstream_provenance"]["path"] = str(redirected.resolve())
    acceptance["upstream_provenance"]["sha256"] = sha256(redirected)
    write_json(acceptance_path, seal(acceptance))
    with pytest.raises(Exception, match="fixed formal path"):
        package_v5_artifacts.validate_data_acceptance(
            acceptance_path, audit_path, load_json(audit_path),
            load_json(formal / "plan.json"),
        )


def test_archive_rejects_export_payload_and_manifest_coordinated_reseal(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    formal, bundle, live_graph = _make_full_archive_gate_fixture(tmp_path, monkeypatch)
    bundled_graph = bundle / "payload/exports/nslkdd/relu/fp32/model_fp32.onnx"
    changed = b"coordinated tamper"
    bundled_graph.write_bytes(changed)
    live_graph.write_bytes(changed)
    manifest = load_json(bundle / "BUNDLE_MANIFEST.json")
    manifest.pop("content_sha256")
    row = next(item for item in manifest["files"]
               if item["path"] ==
               "payload/exports/nslkdd/relu/fp32/model_fp32.onnx")
    row["bytes"] = len(changed)
    row["sha256"] = sha256(bundled_graph)
    archive_pre_v5.write_json(bundle / "BUNDLE_MANIFEST.json", seal(manifest))
    with pytest.raises(v5_retention.RetentionError, match="Retention exact inventory or file bytes changed"):
        archive_pre_v5.validate_execution_gate(formal, bundle)


def test_archive_rejects_iot_report_acceptance_manifest_coordinated_reseal(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    formal, bundle, _ = _make_full_archive_gate_fixture(tmp_path, monkeypatch)
    bundled_report = bundle / package_v5_artifacts.IOT_PROVENANCE_REPORT_BUNDLE
    report = load_json(bundled_report)
    report.pop("content_sha256")
    report["semantic_comparison"]["values_equal"] = False
    report = seal(report)
    write_json(bundled_report, report)

    manifest = load_json(bundle / "BUNDLE_MANIFEST.json")
    acceptance_path = Path(manifest["data_acceptance"])
    acceptance = load_json(acceptance_path)
    acceptance.pop("content_sha256")
    acceptance["upstream_provenance"]["sha256"] = sha256(bundled_report)
    acceptance["upstream_provenance"]["content_sha256"] = report["content_sha256"]
    write_json(acceptance_path, seal(acceptance))
    bundled_acceptance = bundle / "payload/evidence/data/data_acceptance.json"
    shutil.copy2(acceptance_path, bundled_acceptance)

    manifest.pop("content_sha256")
    for relative, path in (
        (package_v5_artifacts.IOT_PROVENANCE_REPORT_BUNDLE, bundled_report),
        ("payload/evidence/data/data_acceptance.json", bundled_acceptance),
    ):
        row = next(item for item in manifest["files"] if item["path"] == relative)
        row["bytes"] = path.stat().st_size
        row["sha256"] = sha256(path)
    archive_pre_v5.write_json(bundle / "BUNDLE_MANIFEST.json", seal(manifest))
    with pytest.raises(RuntimeError, match="Live formal/tree/export source differs"):
        archive_pre_v5.validate_execution_gate(formal, bundle)


def test_archive_rejects_bundled_iot_verifier_manifest_reseal(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    formal, bundle, _ = _make_full_archive_gate_fixture(tmp_path, monkeypatch)
    relative = package_v5_artifacts.IOT_PROVENANCE_TOOL_BUNDLE
    bundled_tool = bundle / relative
    bundled_tool.write_bytes(bundled_tool.read_bytes() + b"\n# tampered\n")
    manifest = load_json(bundle / "BUNDLE_MANIFEST.json")
    manifest.pop("content_sha256")
    row = next(item for item in manifest["files"] if item["path"] == relative)
    row["bytes"] = bundled_tool.stat().st_size
    row["sha256"] = sha256(bundled_tool)
    archive_pre_v5.write_json(bundle / "BUNDLE_MANIFEST.json", seal(manifest))
    with pytest.raises(RuntimeError, match="Bundled IoT provenance verifier bytes differ"):
        archive_pre_v5.validate_execution_gate(formal, bundle)


def test_archive_rejects_resealed_live_source_redirection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    formal, bundle, live_graph = _make_full_archive_gate_fixture(tmp_path, monkeypatch)
    redirected = tmp_path / "redirected.onnx"
    shutil.copy2(live_graph, redirected)
    manifest = load_json(bundle / "BUNDLE_MANIFEST.json")
    manifest.pop("content_sha256")
    row = next(item for item in manifest["files"]
               if item["path"] ==
               "payload/exports/nslkdd/relu/fp32/model_fp32.onnx")
    row["source"] = str(redirected)
    archive_pre_v5.write_json(bundle / "BUNDLE_MANIFEST.json", seal(manifest))
    with pytest.raises(RuntimeError, match="Live formal/tree/export source differs"):
        archive_pre_v5.validate_execution_gate(formal, bundle)


def test_archive_rejects_missing_required_lifecycle_tool(tmp_path: Path) -> None:
    manifest, inventory = _make_bundled_lifecycle_tools(tmp_path)
    missing = tmp_path / "payload/source/tools/verify_v5_tree.py"
    missing.unlink()
    with pytest.raises(RuntimeError, match="missing or changed"):
        archive_pre_v5.validate_bundled_lifecycle_tools(
            tmp_path, manifest, inventory
        )


def test_archive_rejects_bundled_lifecycle_tool_byte_tamper(tmp_path: Path) -> None:
    manifest, inventory = _make_bundled_lifecycle_tools(tmp_path)
    tampered = tmp_path / "payload/source/tools/run_v5_exports.py"
    tampered.write_bytes(tampered.read_bytes() + b"\n# tampered\n")
    with pytest.raises(RuntimeError, match="missing or changed"):
        archive_pre_v5.validate_bundled_lifecycle_tools(
            tmp_path, manifest, inventory
        )


def test_archive_rejects_tool_tamper_after_inventory_reseal(tmp_path: Path) -> None:
    manifest, inventory = _make_bundled_lifecycle_tools(tmp_path)
    relative = "payload/source/tools/run_v5_exports.py"
    tampered = tmp_path / relative
    tampered.write_bytes(tampered.read_bytes() + b"\n# tampered and resealed\n")
    forged_sha256 = archive_pre_v5.digest_file(tampered)
    manifest["lifecycle_tools_sha256"][relative] = forged_sha256
    inventory[relative]["sha256"] = forged_sha256
    resealed = seal(manifest)
    check_seal(resealed)
    with pytest.raises(RuntimeError, match="not release-trusted"):
        archive_pre_v5.validate_bundled_lifecycle_tools(
            tmp_path, resealed, inventory
        )


def test_archive_rejects_resealed_creator_version_claim(tmp_path: Path) -> None:
    manifest, inventory = _make_bundled_lifecycle_tools(tmp_path)
    manifest["creator_provenance"]["packages"]["numpy"] = "forged-version"
    resealed = seal(manifest)
    check_seal(resealed)
    with pytest.raises(RuntimeError, match="package versions differ"):
        archive_pre_v5.validate_bundled_lifecycle_tools(
            tmp_path, resealed, inventory
        )


def test_archive_reparses_argv_and_rejects_resealed_duplicate_arg(
        tmp_path: Path) -> None:
    manifest, inventory = _make_bundled_lifecycle_tools(tmp_path)
    invocation = manifest["creator_provenance"]["invocation"]
    invocation["argv"].extend(("--run-dir", str(tmp_path / "forged")))
    resealed = seal(manifest)
    check_seal(resealed)
    with pytest.raises(RuntimeError, match="Duplicate lifecycle invocation option"):
        archive_pre_v5.validate_bundled_lifecycle_tools(
            tmp_path, resealed, inventory
        )
