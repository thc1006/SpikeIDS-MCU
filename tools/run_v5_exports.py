#!/usr/bin/env python3
"""Run the predeclared seed-0 FP32 and QDQ export matrix without fail-open loops."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import onnx
import torch

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "spikeids_v5"
sys.path.insert(0, str(PACKAGE))

from contracts import (
    check_seal,
    digest,
    json_bytes,
    load_json,
    require,
    seal,
    sha256,
    write_json,
    write_text,
)
from evidence import load_fit, read_plan
from experiment_all import load_checkpoint, tree_digest

from models import build
from tools.verify_v5_neural import (
    NEURAL_VERIFIER_PACKAGES,
    tool_provenance,
    validate_tool_provenance,
)

JOBS = (
    ("nslkdd", "relu"),
    ("nslkdd", "qcfs"),
    ("nslkdd", "cnn"),
    ("unsw", "relu"),
    ("unsw", "qcfs"),
    ("unsw", "cnn"),
    ("cicids2017", "relu"),
    ("cicids2017", "qcfs"),
    ("cicids2017", "cnn"),
    ("iot23", "relu"),
    ("iot23", "qcfs"),
)
EXPORT_RUNNER_PACKAGES = ("numpy", "onnx", "onnxruntime", "torch")


def fixed_export_protocol() -> dict:
    """The policy is fixed in code; no observed export can select these values."""
    return {
        "deployment_seed": 0, "fold_bn": True, "opset": 17, "export_batch": 1,
        "fp32_atol": 1e-6, "fp32_rtol": 1e-5,
        "fp32_max_prediction_disagreement": 0.0,
        "int8_max_prediction_disagreement": 0.01,
        "validation_samples": 1024, "calibration_samples": 1000,
        "row_selection": {
            "generator": "numpy.random.default_rng(0); PCG64",
            "order": ["validation", "fit"], "replace": False,
            "indices": "ascending sorted choice indices",
            "validation_partition": "validation", "calibration_partition": "fit",
            "insufficient_rows": "fail; never silently truncate",
        },
        "qdq_recipe": {
            "quant_format": "QDQ", "activation_type": "QInt8",
            "weight_type": "QInt8", "per_channel": True,
            "reduce_range": False, "calibrate_method": "MinMax",
            "op_types_to_quantize": ["Gemm", "MatMul", "Conv"],
            "nodes_to_quantize": [], "nodes_to_exclude": [],
            "use_external_data_format": False,
            "calibration_providers": ["CPUExecutionProvider"],
            "extra_options": {},
            "unspecified_behavior": "bound to the recorded ONNX Runtime version and source",
        },
        "runtime": {
            "provider": "CPUExecutionProvider", "intra_op_threads": 1,
            "inter_op_threads": 1, "execution_mode": "ORT_SEQUENTIAL",
            "graph_optimization_level": "ORT_ENABLE_BASIC",
            "torch_deterministic_algorithms": True,
            "torch_float32_matmul_precision": "highest",
        },
        "retry_policy": "one registered matrix per neural run; failed artifacts retained",
    }


def _regular_file(path: Path) -> Path:
    path = Path(path).absolute()
    require(path.is_file() and not path.is_symlink() and
            not any(parent.is_symlink() for parent in path.parents) and
            path.stat().st_nlink == 1,
            f"Export input must be a regular, unaliased file: {path}")
    return path


def _file_stat(path: Path) -> dict:
    stat = _regular_file(path).stat()
    return {"device": stat.st_dev, "inode": stat.st_ino, "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns}


def _binding(path: Path) -> dict:
    path = _regular_file(path)
    before = _file_stat(path)
    value = {"path": str(path), "sha256": sha256(path), "stat": before}
    require(_file_stat(path) == before, f"Export input changed while hashing: {path}")
    return value


def _check_binding(value: dict, *, rehash: bool) -> None:
    require(isinstance(value, dict) and set(value) == {"path", "sha256", "stat"},
            "Malformed export input binding")
    path = _regular_file(Path(value["path"]))
    require(_file_stat(path) == value["stat"], f"Frozen export input changed: {path}")
    if rehash:
        require(sha256(path) == value["sha256"], f"Frozen export input bytes changed: {path}")
        require(_file_stat(path) == value["stat"], f"Export input raced its hash: {path}")


def _source_paths() -> list[Path]:
    return [*sorted(PACKAGE.glob("*.py")), Path(__file__).resolve(),
            ROOT / "tools/verify_v5_neural.py", PACKAGE / "EXPORT_PROTOCOL.md"]


def validate_prior_exposure(path: Path, neural_plan: dict) -> dict:
    """Disclose known history without treating a local declaration as preregistration."""
    value = load_json(_regular_file(path))
    check_seal(value)
    require(value.get("schema") == 1 and
            value.get("kind") == "spikeids_v5_export_prior_exposure" and
            value.get("source_plan_sha256") == neural_plan["content_sha256"],
            "Prior export exposure disclosure belongs to another plan")
    require(isinstance(value.get("known_exposures"), list) and
            isinstance(value.get("declaration"), str) and
            bool(value["declaration"].strip()) and
            value.get("complete_history_independently_verified") is False and
            value.get("local_freeze_is_external_preregistration") is False,
            "Prior exposure requires an explicit declaration and honest limitations")
    for exposure in value["known_exposures"]:
        require(isinstance(exposure, dict) and
                set(exposure) == {"description", "evidence_path", "evidence_sha256"} and
                isinstance(exposure["description"], str) and exposure["description"].strip(),
                "Malformed known export exposure")
        evidence = _regular_file(Path(exposure["evidence_path"]))
        require(sha256(evidence) == exposure["evidence_sha256"],
                "Prior export exposure evidence is missing or changed")
    return value


def _row_selection(job: dict) -> dict:
    cache = Path(job["cache"])
    rng = np.random.default_rng(0)
    result = {}
    for split, count in (("validation", 1024), ("fit", 1000)):
        ids = np.load(cache / f"ids_{split}.npy", mmap_mode="r", allow_pickle=False)
        x = np.load(cache / f"x_{split}.npy", mmap_mode="r", allow_pickle=False)
        require(ids.ndim == 1 and x.ndim == 2 and len(ids) == len(x) and len(ids) >= count,
                f"Insufficient or malformed export rows: {job['dataset']}/{split}")
        indices = np.sort(rng.choice(len(ids), count, replace=False))
        selected = np.asarray(x[indices], dtype=np.float32)
        require(np.isfinite(selected).all(), "Non-finite predeclared export input")
        result[split] = {"partition": split, "indices": indices.tolist(),
                         "row_ids": ids[indices].tolist(),
                         "ids_sha256": array_sha256(ids[indices]),
                         "x_sha256": array_sha256(selected)}
    return result


def build_export_plan(run_dir: Path, output_root: Path, neural_plan: dict,
                      runner_provenance: dict) -> dict:
    """Resolve every policy/input before any exporter subprocess may start."""
    run_dir, output_root = Path(run_dir).resolve(), Path(output_root).resolve()
    require(neural_plan.get("protocol_role") == "planned_benchmark" and
            neural_plan.get("seeds") == list(range(20)) and
            neural_plan.get("deployment_seed") == 0,
            "Export requires the fixed full 20-seed formal neural plan")
    validate_tool_provenance(runner_provenance, Path(__file__), EXPORT_RUNNER_PACKAGES)
    inputs: dict[str, dict] = {}

    def bind(path: Path) -> dict:
        record = _binding(path)
        inputs[record["path"]] = record
        return record

    neural_binding = bind(run_dir / "plan.json")
    require(load_json(run_dir / "plan.json") == neural_plan, "Neural plan differs on disk")
    for name in ("verification_fit.json", "verification_evaluate.json"):
        record = bind(run_dir / name)
        gate = load_json(Path(record["path"]))
        check_seal(gate)
        require(gate.get("passed") is True and
                gate.get("plan_sha256") == neural_plan["content_sha256"],
                f"Full neural barrier must pass before export: {name}")
    independent_binding = bind(run_dir / "independent_verification.json")
    independent = load_json(Path(independent_binding["path"]))
    check_seal(independent)
    require(independent.get("kind") == "independent_formal_neural_and_statistics_verification"
            and independent.get("passed") is True and
            independent.get("plan_sha256") == neural_plan["content_sha256"] and
            independent.get("prediction_artifacts_checked") == 440 and
            independent.get("checkpoints_checked") == 440,
            "Export requires independently verified 440 predictions and checkpoints")
    validate_tool_provenance(independent.get("tool_provenance"),
                             ROOT / "tools/verify_v5_neural.py", NEURAL_VERIFIER_PACKAGES,
                             {"run_dir": str(run_dir),
                              "output": str(run_dir / "independent_verification.json")})
    for name in ("verification_fit.json", "verification_evaluate.json"):
        require(independent.get(name.removesuffix(".json") + "_sha256") ==
                inputs[str(run_dir / name)]["sha256"], "Independent neural barrier is stale")
    exposure_path = run_dir / "export_prior_exposure.json"
    exposure_binding = bind(exposure_path)
    exposure = validate_prior_exposure(exposure_path, neural_plan)
    for row in exposure["known_exposures"]:
        bind(Path(row["evidence_path"]))
    selections, attempts = {}, []
    for dataset, model in JOBS:
        matches = [job for job in neural_plan["jobs"]
                   if job["dataset"] == dataset and job["model"] == model]
        require(len(matches) == 1, "Neural export arm is missing or duplicated")
        job = matches[0]
        if dataset not in selections:
            cache = Path(job["cache"])
            metadata_binding = bind(cache / "metadata.json")
            metadata = load_json(cache / "metadata.json")
            check_seal(metadata)
            require(metadata["data_fingerprint"] == job["data_fingerprint"],
                    "Export cache differs from frozen neural plan")
            for name, expected_sha in metadata["files_sha256"].items():
                require(Path(name).name == name, "Cache inventory has a non-local filename")
                require(bind(cache / name)["sha256"] == expected_sha,
                        "Export cache inventory differs from prepared metadata")
            selections[dataset] = {
                "cache": str(cache.resolve()), "data_fingerprint": job["data_fingerprint"],
                "metadata_sha256": metadata_binding["sha256"],
                "selection": _row_selection(job),
            }
        require(selections[dataset]["cache"] == str(Path(job["cache"]).resolve()) and
                selections[dataset]["data_fingerprint"] == job["data_fingerprint"],
                "Arms of one dataset must use the identical prepared cache")
        checkpoint = run_dir / "results" / job["id"] / "runs" / f"{model}_seed_0.pt"
        checkpoint_binding = bind(checkpoint)
        selected = independent["checkpoints"][job["id"]]["results"]["0"]
        require(selected["path"] == checkpoint.relative_to(run_dir).as_posix() and
                selected["artifact_sha256"] == checkpoint_binding["sha256"],
                "Selected export checkpoint differs from independent neural evidence")
        for execution in ("results", "replicas"):
            bind(run_dir / execution / f"{job['id']}.json")
            bind(run_dir / execution / job["id"] / "manifest.json")
        for mode in ("fp32", "qdq"):
            attempts.append({"dataset": dataset, "model": model, "mode": mode,
                             "output_dir": f"{dataset}/{model}/{mode}",
                             "checkpoint_sha256": checkpoint_binding["sha256"],
                             "best_state_sha256": selected["best_state_sha256"],
                             "data_fingerprint": job["data_fingerprint"]})
    sources = [_binding(path) for path in _source_paths()]
    result = seal({
        "schema": 1, "kind": "spikeids_v5_export_plan",
        "source_plan_sha256": neural_plan["content_sha256"],
        "source_plan": neural_binding, "run_dir": str(run_dir),
        "output_root": str(output_root), "protocol": fixed_export_protocol(),
        "attempts": attempts, "datasets": selections,
        "inputs": [inputs[name] for name in sorted(inputs)], "sources": sources,
        "tool_provenance": runner_provenance,
        "python_executable_sha256": sha256(Path(sys.executable).resolve()),
        "independent_neural_verification": independent_binding,
        "prior_exposure": {"binding": exposure_binding, "declaration": exposure},
        "claim_scope": "sampled CPU ONNX Runtime parity; no NPU, board, latency, or energy claim",
        "chronology_limit": "Local pre-attempt freeze is not an external timestamp or proof of unseen history",
    })
    for binding in [*result["inputs"], *sources]:
        _check_binding(binding, rehash=False)
    return result


def _write_once(path: Path, value: dict) -> None:
    """Never replace an earlier registration or a frozen plan, even after failure."""
    with Path(path).open("xb") as stream:
        stream.write(json_bytes(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def register_export_plan(output_root: Path, export_plan: dict) -> Path:
    check_seal(export_plan)
    require(str(Path(output_root).resolve()) == export_plan["output_root"],
            "Frozen export output root differs")
    output_root.mkdir(parents=True, exist_ok=False)
    path = output_root / "export_plan.json"
    _write_once(path, export_plan)
    _write_once(Path(export_plan["run_dir"]) / "export_registration.json", seal({
        "schema": 1, "kind": "spikeids_v5_export_registration",
        "source_plan_sha256": export_plan["source_plan_sha256"],
        "export_plan_path": str(path.resolve()),
        "export_plan_sha256": export_plan["content_sha256"],
        "export_plan_file_sha256": sha256(path),
    }))
    return path


def load_export_plan(export_root: Path, neural_plan: dict, *, rehash: bool = True) -> dict:
    """Consumer and pre/post-attempt gate; source/policy mutations always fail closed."""
    path = _regular_file(Path(export_root) / "export_plan.json")
    plan = load_json(path)
    check_seal(plan)
    require(plan.get("schema") == 1 and plan.get("kind") == "spikeids_v5_export_plan" and
            plan.get("source_plan_sha256") == neural_plan["content_sha256"] and
            plan.get("output_root") == str(Path(export_root).resolve()) and
            plan.get("protocol") == fixed_export_protocol(),
            "Frozen export plan identity or fixed policy differs")
    expected_attempts = [(d, m, mode) for d, m in JOBS for mode in ("fp32", "qdq")]
    require([(a.get("dataset"), a.get("model"), a.get("mode"))
             for a in plan.get("attempts", [])] == expected_attempts,
            "Frozen export plan changed the ordered 22-attempt matrix")
    sources = plan.get("sources", [])
    require([s.get("path") for s in sources] == [str(p.resolve()) for p in _source_paths()],
            "Frozen export source inventory changed")
    for binding in sources:
        _check_binding(binding, rehash=True)
    for binding in plan["inputs"]:
        _check_binding(binding, rehash=rehash)
    validate_tool_provenance(plan["tool_provenance"], Path(__file__), EXPORT_RUNNER_PACKAGES)
    require(plan["python_executable_sha256"] == sha256(Path(sys.executable).resolve()),
            "Python runtime changed after export freeze")
    registration = load_json(_regular_file(Path(plan["run_dir"]) / "export_registration.json"))
    check_seal(registration)
    require(registration == seal({
        "schema": 1, "kind": "spikeids_v5_export_registration",
        "source_plan_sha256": neural_plan["content_sha256"],
        "export_plan_path": str(path.resolve()),
        "export_plan_sha256": plan["content_sha256"],
        "export_plan_file_sha256": sha256(path),
    }), "Export registration differs; reruns cannot replace or reseal the frozen plan")
    stored_neural = load_json(Path(plan["source_plan"]["path"]))
    check_seal(stored_neural)
    require(stored_neural["content_sha256"] == neural_plan["content_sha256"] and
            Path(plan["source_plan"]["path"]) == Path(plan["run_dir"]) / "plan.json",
            "Export plan is not bound to its canonical neural plan")
    if rehash:
        require(build_export_plan(Path(plan["run_dir"]), Path(export_root), stored_neural,
                                  plan["tool_provenance"]) == plan,
                "Export plan differs from independent policy/input reconstruction")
    return plan


def exporter_invocation(run_dir: Path, output_dir: Path, dataset: str,
                        model: str, mode: str, validation_samples: int,
                        calibration_samples: int,
                        int8_max_disagreement: float, *,
                        export_plan_path: Path | None = None) -> list[str]:
    """Build the one canonical exporter subprocess argv recorded in evidence."""
    command = [
        sys.executable,
        str(PACKAGE / "export_verified.py"),
        "--run-dir", str(run_dir),
        "--dataset", dataset,
        "--model", model,
        "--output-dir", str(output_dir),
        "--export-plan", str(export_plan_path or output_dir.parents[2] / "export_plan.json"),
        "--fold-bn",
        "--validation-samples", str(validation_samples),
        "--calibration-samples", str(calibration_samples),
        "--atol", "1e-6",
        "--rtol", "1e-5",
    ]
    if mode == "qdq":
        command.extend(("--int8", "--int8-max-disagreement",
                        str(int8_max_disagreement)))
    return command


def output_files_sha256(output_dir: Path) -> dict[str, str]:
    """Inventory every exporter-created file except the runner evidence itself."""
    result = {}
    for path in sorted(output_dir.iterdir()):
        require(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1,
                f"Unexpected non-file/symlink in export output: {path}")
        if path.name != "runner_validation.json":
            result[path.name] = sha256(path)
    return result


def scientific_failure(output_dir: Path, export_plan: dict, dataset: str,
                       model: str, mode: str, return_code: int) -> dict:
    """Only a persisted numerical gate violation is a scientific export failure."""
    require(type(return_code) is int and return_code == 1,
            "Killed/transient/infrastructure subprocess failures are not scientific outcomes")
    failure_path = _regular_file(output_dir / "FAILED.json")
    failure = load_json(failure_path)
    check_seal(failure)
    attempt = next(row for row in export_plan["attempts"]
                   if (row["dataset"], row["model"], row["mode"]) == (dataset, model, mode))
    require(failure.get("schema") == 1 and failure.get("status") == "failed" and
            failure.get("publication_gate") is False and
            failure.get("source_plan_sha256") == export_plan["source_plan_sha256"] and
            failure.get("export_plan_sha256") == export_plan["content_sha256"] and
            failure.get("checkpoint_sha256") == attempt["checkpoint_sha256"],
            "Failure scientific identity differs from the registered attempt")
    stage = failure.get("stage")
    stages = {
        "freeze": ("freeze_check", "BN folding/freezing changed outputs beyond the predeclared gate; inspect boundary activations"),
        "fp32_parity": ("onnx_check", "ONNX numerical parity gate failed"),
        "qdq_parity": ("quantization_check", "QDQ validation disagreement gate failed"),
    }
    require(stage in stages and (stage != "qdq_parity" or mode == "qdq"),
            "Infrastructure/unclassified exporter failure is not a scientific gate result")
    check_name, reason = stages[stage]
    require(failure.get("reason") == f"ContractError: {reason}",
            "Failure is not the declared numerical gate violation")
    diagnostics = failure.get("diagnostics", {})
    ordered = ["freeze_check", "onnx_check", "quantization_check"]
    require(isinstance(diagnostics, dict) and
            set(diagnostics) == set(ordered[:ordered.index(check_name) + 1]),
            "Failure lacks the complete preceding numerical diagnostics")
    for name, check in diagnostics.items():
        require(isinstance(check, dict) and type(check.get("allclose")) is bool and
                check.get("vectors_checked") == 1024 and
                type(check.get("max_abs_error")) in (int, float) and
                np.isfinite(check["max_abs_error"]) and check["max_abs_error"] >= 0 and
                type(check.get("prediction_disagreement_fraction")) in (int, float) and
                np.isfinite(check["prediction_disagreement_fraction"]) and
                0 <= check["prediction_disagreement_fraction"] <= 1,
                "Failure contains malformed/non-finite numerical diagnostics")
        passed = (check["prediction_disagreement_fraction"] <= 0.01 if
                  name == "quantization_check" else
                  check["allclose"] and check["prediction_disagreement_fraction"] == 0)
        require(passed is (name != check_name),
                "Recorded failure does not reproduce the fixed numerical gate decision")
    partial = output_files_sha256(output_dir)
    partial.pop("FAILED.json")
    expected_partial = {"export_policy.json"}
    if stage in ("fp32_parity", "qdq_parity"):
        expected_partial.add("model_fp32.onnx")
    if stage == "qdq_parity":
        expected_partial.add("model_qdq_int8.onnx")
    require(failure.get("partial_files_sha256") == partial and
            set(partial) == expected_partial,
            "Scientific failure partial payload inventory differs")
    policy = load_json(output_dir / "export_policy.json")
    check_seal(policy)
    require(policy.get("export_plan_sha256") == export_plan["content_sha256"] and
            policy.get("checkpoint_sha256") == attempt["checkpoint_sha256"] and
            policy.get("qdq_recipe") == fixed_export_protocol()["qdq_recipe"],
            "Failed attempt used another policy/checkpoint/recipe")
    return failure


def replay_scientific_failure(run_dir: Path, export_root: Path, export_plan: dict,
                              row: dict) -> dict:
    """Replay a failure in isolation, checking identity, exact diagnostics and payloads."""
    dataset, model, mode = (row[name] for name in ("dataset", "model", "mode"))
    output_dir = export_root / row["output_dir"]
    original = scientific_failure(output_dir, export_plan, dataset, model, mode,
                                  row["return_code"])
    original_inventory = output_files_sha256(output_dir)
    with tempfile.TemporaryDirectory(prefix=".export-scientific-replay-",
                                     dir=export_root.parent) as directory:
        replay_output = Path(directory) / "output"
        command = exporter_invocation(run_dir, replay_output, dataset, model, mode,
                                      1024, 1000, 0.01,
                                      export_plan_path=export_root / "export_plan.json")
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                check=False, cwd=ROOT)
        require(result.returncode == row["return_code"],
                "Scientific failure replay passed or changed its return code")
        reproduced = scientific_failure(replay_output, export_plan, dataset, model,
                                        mode, result.returncode)
        require(reproduced == original and
                output_files_sha256(replay_output) == original_inventory,
                "Scientific failure replay changed identity, diagnostics, or payload bytes")
    require(output_files_sha256(output_dir) == original_inventory,
            "Original failed artifacts changed during replay")
    return {"kind": "exact_scientific_failure_replay", "passed": True,
            "export_plan_sha256": export_plan["content_sha256"],
            "failure_sha256": sha256(output_dir / "FAILED.json"),
            "output_files_sha256": original_inventory}


def _scientific_tex(value: float) -> str:
    """Format a finite nonnegative value without depending on TeX packages."""
    require(np.isfinite(value) and value >= 0.0, "Invalid export diagnostic")
    if value == 0.0:
        return "0"
    mantissa, exponent = f"{value:.3e}".split("e")
    return f"{mantissa}\\times 10^{{{int(exponent)}}}"


def validate_export_summary(export_root: Path, summary: dict, export_plan: dict) -> list[dict]:
    """Bind the manuscript-facing summary to the frozen policy and ordered matrix.

    A valid JSON seal establishes byte consistency, not the meaning of totals or
    thresholds. Recompute those values from the fixed plan before using them.
    Artifact bytes and numerical diagnostics are checked by the caller below.
    """
    check_seal(summary)
    require(summary.get("source_plan_sha256") == export_plan["source_plan_sha256"] and
            summary.get("export_plan_sha256") == export_plan["content_sha256"],
            "Export summary does not bind its pre-attempt plan")
    protocol = export_plan["protocol"]
    require(protocol == fixed_export_protocol(), "Export summary has an unsupported frozen policy")
    for key in ("deployment_seed", "fold_bn", "fp32_atol", "fp32_rtol",
                "fp32_max_prediction_disagreement", "int8_max_prediction_disagreement",
                "validation_samples", "calibration_samples"):
        require(type(summary.get(key)) is type(protocol[key]) and summary[key] == protocol[key],
                f"Export summary differs from frozen policy: {key}")
    require(summary.get("tool_provenance") == export_plan["tool_provenance"],
            "Export summary runner provenance differs from its frozen plan")
    attempts = summary.get("attempts")
    expected = [(dataset, model, mode) for dataset, model in JOBS for mode in ("fp32", "qdq")]
    require(isinstance(attempts, list) and len(attempts) == len(expected) and
            all(isinstance(row, dict) for row in attempts) and
            [(row.get("dataset"), row.get("model"), row.get("mode")) for row in attempts] == expected,
            "Export summary differs from the frozen ordered 22-attempt matrix")
    require([(row.get("dataset"), row.get("model"), row.get("mode"))
             for row in export_plan["attempts"]] == expected,
            "Frozen export plan differs from the ordered attempt matrix")
    for row, planned in zip(attempts, export_plan["attempts"]):
        dataset, model, mode = (row[key] for key in ("dataset", "model", "mode"))
        output = f"{dataset}/{model}/{mode}"
        require(planned.get("output_dir") == output and row.get("output_dir") == output and
                row.get("evidence") == f"{output}/runner_validation.json" and
                row.get("log") == f"logs/{dataset}_{model}_{mode}.log" and
                row.get("export_plan_sha256") == export_plan["content_sha256"],
                "Export attempt identity or canonical output/evidence/log path differs")
        require(type(row.get("passed")) is bool and type(row.get("return_code")) is int,
                "Export attempt decision and return code must be explicitly typed")
        require(row["return_code"] == (0 if row["passed"] else 1),
                "Infrastructure or inconsistent return codes cannot enter manuscript counts")
        require(type(row.get("elapsed_seconds")) in (int, float) and
                np.isfinite(row["elapsed_seconds"]) and row["elapsed_seconds"] >= 0,
                "Export attempt has an invalid elapsed time")
        for key in ("evidence_sha256", "log_sha256"):
            require(isinstance(row.get(key), str) and
                    re.fullmatch(r"[0-9a-f]{64}", row[key]) is not None,
                    f"Export attempt has an invalid digest: {key}")
    for mode in ("fp32", "qdq"):
        passed = sum(row["passed"] for row in attempts if row["mode"] == mode)
        for suffix, value in (("passed", passed), ("total", len(JOBS))):
            key = f"{mode}_{suffix}"
            require(type(summary.get(key)) is int and summary[key] == value,
                    f"Export summary count differs from the complete attempt matrix: {key}")
    require(type(summary.get("all_gates_passed")) is bool and
            summary["all_gates_passed"] == all(row["passed"] for row in attempts),
            "Export summary overall decision differs from its attempt matrix")
    return attempts


def expected_export_macros(export_root: Path, summary: dict) -> dict[str, str]:
    """Derive the manuscript view from sealed independent runner evidence."""
    export_root = Path(export_root)
    check_seal(summary)
    export_plan = load_export_plan(export_root, {"content_sha256": summary["source_plan_sha256"]})
    attempts = validate_export_summary(export_root, summary, export_plan)
    fp32_errors: list[float] = []
    qdq_disagreements: list[float] = []
    for row in attempts:
        evidence_path = _regular_file(export_root / row["evidence"])
        require(sha256(evidence_path) == row["evidence_sha256"],
                "Passing export evidence is missing or changed")
        require(sha256(_regular_file(export_root / row["log"])) == row["log_sha256"],
                "Export attempt log is missing or changed")
        evidence = load_json(evidence_path)
        check_seal(evidence)
        require(evidence.get("source_plan_sha256") == summary["source_plan_sha256"] and
                evidence.get("export_plan_sha256") == export_plan["content_sha256"] and
                evidence.get("dataset") == row["dataset"] and
                evidence.get("model") == row["model"] and
                evidence.get("mode") == row["mode"] and
                evidence.get("tool_provenance") == export_plan["tool_provenance"],
                "Export evidence identity/publication gate mismatch")
        inventory = output_files_sha256(export_root / row["output_dir"])
        require(evidence.get("output_files_sha256") == inventory,
                "Export runner evidence payload inventory is missing or changed")
        if not row.get("passed"):
            require(evidence.get("publication_gate") is False and
                    evidence.get("status") == "export_subprocess_failed" and
                    evidence.get("return_code") == row["return_code"] and
                    evidence.get("failure_classification") == "reproduced_scientific_gate",
                    "Infrastructure or unclassified failures cannot enter manuscript counts")
            failure = scientific_failure(export_root / row["output_dir"], export_plan,
                                         row["dataset"], row["model"], row["mode"],
                                         row["return_code"])
            replay = evidence.get("failure_replay", {})
            require(replay.get("kind") == "exact_scientific_failure_replay" and
                    replay.get("passed") is True and
                    replay.get("export_plan_sha256") == export_plan["content_sha256"] and
                    replay.get("failure_sha256") == sha256(export_root / row["output_dir"] / "FAILED.json") and
                    replay.get("output_files_sha256") == inventory and
                    failure["publication_gate"] is False,
                    "Failed export has no exact scientific failure replay")
            continue
        require(evidence.get("publication_gate") is True and
                evidence.get("status") == "independently_validated",
                "Passing export has a closed publication gate")
        fp32 = evidence.get("fp32_check", {})
        require(fp32.get("allclose") is True and
                fp32.get("prediction_disagreement_fraction") == 0.0 and
                fp32.get("vectors_checked") == summary["validation_samples"],
                "Passing export lacks the declared independent FP32 gate")
        fp32_error = float(fp32["max_abs_error"])
        require(np.isfinite(fp32_error) and fp32_error >= 0.0,
                "Passing export has an invalid FP32 error")
        fp32_errors.append(fp32_error)
        if row["mode"] == "qdq":
            qdq = evidence.get("qdq_check", {})
            require(qdq.get("vectors_checked") == summary["validation_samples"] and
                    float(qdq.get("prediction_disagreement_fraction", 2.0)) <=
                    summary["int8_max_prediction_disagreement"],
                    "Passing QDQ export lacks the declared independent gate")
            qdq_disagreement = float(qdq["prediction_disagreement_fraction"])
            require(np.isfinite(qdq_disagreement) and 0.0 <= qdq_disagreement <= 1.0,
                    "Passing QDQ export has an invalid disagreement rate")
            qdq_disagreements.append(qdq_disagreement)
    require(len(fp32_errors) == summary["fp32_passed"] + summary["qdq_passed"],
            "Export pass counts and independent evidence disagree")
    require(len(qdq_disagreements) == summary["qdq_passed"],
            "QDQ pass count and independent evidence disagree")
    worst_qdq = (f"{100.0 * max(qdq_disagreements):.3f}"
                 if qdq_disagreements else r"\text{n/a}")
    worst_fp32 = _scientific_tex(max(fp32_errors)) if fp32_errors else r"\text{n/a}"
    return {
        "vExportFpPassed": str(summary["fp32_passed"]),
        "vExportFpTotal": str(summary["fp32_total"]),
        "vExportQdqPassed": str(summary["qdq_passed"]),
        "vExportQdqTotal": str(summary["qdq_total"]),
        "vExportValidationVectors": str(summary["validation_samples"]),
        "vExportCalibrationRows": str(summary["calibration_samples"]),
        "vExportQdqLimitPct":
            f"{100.0 * summary['int8_max_prediction_disagreement']:.2f}",
        "vExportFpWorstAbsError": worst_fp32,
        "vExportQdqWorstPassedDisagreementPct": worst_qdq,
    }


def export_macro_text(values: dict[str, str]) -> str:
    lines = [
        "% Generated from the sealed version-5 export matrix. Do not hand-edit.",
        "% These are sampled ONNX Runtime gates, not NPU or physical-board evidence.",
    ]
    for name, value in sorted(values.items()):
        require(name.isalpha(), "Export LaTeX macro names must contain letters only")
        lines.append(f"\\newcommand{{\\{name}}}{{\\ensuremath{{{value}}}}}")
    return "\n".join(lines) + "\n"


def emit_export_macros(export_root: Path, paper_dir: Path, plan: dict,
                       summary_path: Path, runner_provenance: dict | None = None) -> None:
    """Atomically emit a paper view bound to the exact sealed export summary."""
    paper_dir = Path(paper_dir).resolve()
    require((paper_dir / "main.tex").is_file(),
            "Paper directory must contain main.tex before export macro emission")
    summary = load_json(summary_path)
    check_seal(summary)
    require(summary.get("source_plan_sha256") == plan["content_sha256"],
            "Export summary belongs to another training plan")
    macro_path = paper_dir / "export_macros_v5.tex"
    write_text(macro_path, export_macro_text(expected_export_macros(export_root, summary)))
    provenance_body = {
        "schema": 1,
        "kind": "spikeids_v5_export_paper_macros",
        "plan_sha256": plan["content_sha256"],
        "export_summary_sha256": sha256(summary_path),
        "export_plan_sha256": summary["export_plan_sha256"],
        "macro_sha256": sha256(macro_path),
    }
    if runner_provenance is not None:
        provenance_body["tool_provenance"] = runner_provenance
    provenance = seal(provenance_body)
    write_json(paper_dir / "export_macros_v5.provenance.json", provenance)


def compare_logits(reference: np.ndarray, actual: np.ndarray, atol: float, rtol: float) -> dict:
    """Independently compare two output tensors; do not trust exporter summaries."""
    reference = np.asarray(reference)
    actual = np.asarray(actual)
    require(reference.shape == actual.shape and reference.ndim == 2 and len(reference) > 0,
            "Independent ONNX check found an invalid logit shape")
    require(np.isfinite(reference).all() and np.isfinite(actual).all(),
            "Independent ONNX check found non-finite logits")
    return {
        "allclose": bool(np.allclose(reference, actual, atol=atol, rtol=rtol)),
        "max_abs_error": float(np.max(np.abs(reference.astype(np.float64) - actual))),
        "prediction_disagreement_fraction": float(
            np.mean(reference.argmax(axis=1) != actual.argmax(axis=1))
        ),
        "vectors_checked": len(reference),
    }


def array_sha256(value: np.ndarray) -> str:
    """Match the semantic ndarray digest used by the frozen exporter."""
    value = np.ascontiguousarray(value)
    hasher = hashlib.sha256(json_bytes({"shape": list(value.shape), "dtype": value.dtype.str}))
    hasher.update(memoryview(value).cast("B"))
    return hasher.hexdigest()


def evaluate_onnx(path: Path, vectors: np.ndarray) -> np.ndarray:
    """Evaluate the fixed-batch graph with a new, deterministic CPU ORT session."""
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    session = ort.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    require([item.name for item in session.get_inputs()] == ["input"],
            "Exported ONNX input contract changed")
    require([item.name for item in session.get_outputs()] == ["logits"],
            "Exported ONNX output contract changed")
    return np.concatenate([
        session.run(["logits"], {"input": row[None]})[0] for row in vectors
    ])


def validate_attempt(
    *, run_dir: Path, output_dir: Path, plan: dict, dataset: str, model: str,
    mode: str, validation_samples: int, calibration_samples: int,
    int8_max_disagreement: float,
) -> dict:
    """Validate files, provenance, sampled rows, and ONNX outputs from first principles."""
    export_plan = load_export_plan(output_dir.parents[2], plan, rehash=False)
    require(export_plan["run_dir"] == str(Path(run_dir).resolve()),
            "Export attempt uses another neural run")
    require(validation_samples == 1024 and calibration_samples == 1000 and
            int8_max_disagreement == 0.01 and (dataset, model) in JOBS and
            mode in ("fp32", "qdq"), "Attempt parameters differ from the frozen matrix")
    job = next(job for job in plan["jobs"]
               if job["dataset"] == dataset and job["model"] == model)
    report_path = output_dir / "export_report.json"
    report = load_json(report_path)
    check_seal(report)
    policy = load_json(output_dir / "export_policy.json")
    check_seal(policy)

    expected_policy = {
        "source_plan_sha256": plan["content_sha256"],
        "deployment_seed": 0,
        "fold_bn": True,
        "int8": mode == "qdq",
        "atol": 1e-6,
        "rtol": 1e-5,
        "int8_max_disagreement": int8_max_disagreement if mode == "qdq" else None,
        "validation_samples": validation_samples,
        "calibration_samples": calibration_samples,
        "opset": 17,
        "export_batch": 1,
        "data_fingerprint": job["data_fingerprint"],
        "export_plan_sha256": export_plan["content_sha256"],
        "qdq_recipe": fixed_export_protocol()["qdq_recipe"],
        **{name: export_plan["tool_provenance"]["packages"][name]
           for name in ("onnx", "onnxruntime", "torch")},
    }
    for key, expected in expected_policy.items():
        require(policy.get(key) == expected, f"Export policy mismatch: {key}")
    checkpoint = (run_dir / "results" / job["id"] / "runs" /
                  f"{model}_seed_{plan['deployment_seed']}.pt")
    require(policy.get("checkpoint_sha256") == sha256(checkpoint),
            "Export policy is not bound to the selected checkpoint")
    require(report.get("checkpoint_sha256") == policy["checkpoint_sha256"],
            "Export report checkpoint differs from its policy")
    require(report.get("policy_sha256") == digest(
        {key: value for key, value in policy.items() if key != "content_sha256"}
    ), "Export report is not bound to its sealed policy")
    require(report.get("source_plan_sha256") == plan["content_sha256"],
            "Export report refers to another training plan")
    require(report.get("export_plan_sha256") == export_plan["content_sha256"],
            "Export report refers to another pre-attempt export plan")
    require(report.get("data_fingerprint") == job["data_fingerprint"],
            "Export report refers to another prepared dataset")
    require(report.get("board_validated") is False and
            report.get("energy_measured") is False and
            report.get("npu_placement_verified") is False,
            "Software export must not claim unprovided physical evidence")
    require((mode == "qdq") == ("quantization_check" in report),
            "Export report mode does not match the requested mode")

    expected_files = {
        "export_policy.json", "validation_vectors.npz", "preprocessing.json",
        "calibration_rows.json", "model_fp32.onnx",
    }
    if mode == "qdq":
        expected_files.add("model_qdq_int8.onnx")
    require(set(report.get("files_sha256", {})) == expected_files,
            "Export report has a missing or unexpected hashed payload")
    require(set(output_files_sha256(output_dir)) == expected_files | {"export_report.json"},
            "Export attempt has an unplanned output file")
    for name, expected_hash in report["files_sha256"].items():
        require(sha256(output_dir / name) == expected_hash,
                f"Export payload hash mismatch: {name}")
    require(report.get("graph_sha256") == sha256(output_dir / "model_fp32.onnx"),
            "FP32 graph hash mismatch")
    if mode == "qdq":
        require(report.get("quantized_graph_sha256") ==
                sha256(output_dir / "model_qdq_int8.onnx"), "QDQ graph hash mismatch")

    cache = Path(job["cache"])
    cache_metadata = load_json(cache / "metadata.json")
    check_seal(cache_metadata)
    require(cache_metadata["data_fingerprint"] == job["data_fingerprint"],
            "Frozen plan cache fingerprint mismatch")
    require(policy.get("preprocessor_sha256") == cache_metadata["preprocessor_sha256"] and
            report.get("preprocessor_sha256") == cache_metadata["preprocessor_sha256"],
            "Export preprocessor identity mismatch")
    require(sha256(output_dir / "preprocessing.json") ==
            sha256(cache / "preprocessing.json"), "Exported preprocessing file changed")

    rng = np.random.default_rng(0)
    ids_validation = np.load(cache / "ids_validation.npy", mmap_mode="r", allow_pickle=False)
    ids_fit = np.load(cache / "ids_fit.npy", mmap_mode="r", allow_pickle=False)
    validation_indices = np.sort(rng.choice(
        len(ids_validation), validation_samples, replace=False
    ))
    calibration_indices = np.sort(rng.choice(
        len(ids_fit), calibration_samples, replace=False
    ))
    selection = export_plan["datasets"][dataset]["selection"]
    require(selection["validation"]["indices"] == validation_indices.tolist() and
            selection["fit"]["indices"] == calibration_indices.tolist(),
            "Export row selection differs from its frozen plan")
    with np.load(output_dir / "validation_vectors.npz", allow_pickle=False) as vectors_file:
        require(set(vectors_file.files) == {
            "x", "reference_logits", "original_logits", "validation_row_ids"
        }, "Validation-vector archive has unexpected fields")
        vectors = np.asarray(vectors_file["x"])
        reference_logits = np.asarray(vectors_file["reference_logits"])
        original_logits = np.asarray(vectors_file["original_logits"])
        validation_row_ids = np.asarray(vectors_file["validation_row_ids"])
    expected_vectors = np.asarray(
        np.load(cache / "x_validation.npy", mmap_mode="r", allow_pickle=False)[validation_indices],
        dtype=np.float32,
    )
    require(vectors.dtype == np.float32 and vectors.shape == expected_vectors.shape and
            np.array_equal(vectors, expected_vectors) and
            array_sha256(vectors) == selection["validation"]["x_sha256"],
            "Export vectors differ from the predeclared validation rows")
    require(np.array_equal(validation_row_ids, ids_validation[validation_indices]),
            "Export validation row IDs differ from the predeclared rows")
    calibration = load_json(output_dir / "calibration_rows.json")
    require(calibration.get("partition") == "fit" and
            calibration.get("row_ids") == ids_fit[calibration_indices].tolist() and
            calibration.get("ids_sha256") == array_sha256(ids_fit[calibration_indices]),
            "QDQ calibration record differs from the predeclared fit rows")

    result_path = run_dir / "results" / f"{job['id']}.json"
    result = load_fit(result_path, job, plan)
    state = load_checkpoint(checkpoint, result["fingerprint"])
    protocol = result["protocol"]
    checkpoint_model = build(
        model, len(cache_metadata["features"]), len(cache_metadata["class_names"]),
        protocol["hidden"], protocol["levels"], protocol["qcfs_formula"],
    )
    checkpoint_model.load_state_dict(state["best_model"], strict=True)
    checkpoint_model.eval()
    require(tree_digest(checkpoint_model.state_dict()) ==
            state["fit_result"]["best_state_sha256"] == policy.get("best_model_sha256"),
            "Export policy/checkpoint selected-state binding differs")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True, warn_only=False)
    torch.set_float32_matmul_precision("highest")
    with torch.inference_mode():
        checkpoint_logits = np.concatenate([
            checkpoint_model(torch.from_numpy(row[None])).numpy() for row in vectors
        ])
    checkpoint_check = compare_logits(checkpoint_logits, original_logits, 0.0, 0.0)
    require(checkpoint_check["allclose"] and
            checkpoint_check["prediction_disagreement_fraction"] == 0.0,
            "Stored PyTorch logits do not exactly match the selected checkpoint")

    fp32_graph = onnx.load(output_dir / "model_fp32.onnx")
    onnx.checker.check_model(fp32_graph)
    fp32_operators = sorted({node.op_type for node in fp32_graph.graph.node})
    require(fp32_operators == report.get("fp32_operators") and
            not ({"QuantizeLinear", "DequantizeLinear"} & set(fp32_operators)) and
            (mode == "qdq" or report.get("reference_kind") == "fp32_onnx"),
            "FP32 ONNX structure differs from its report or contains QDQ operators")

    fp32_logits = evaluate_onnx(output_dir / "model_fp32.onnx", vectors)
    fp32_check = compare_logits(checkpoint_logits, fp32_logits, 1e-6, 1e-5)
    require(fp32_check["allclose"] and
            fp32_check["prediction_disagreement_fraction"] == 0.0,
            "Independent FP32 ONNX parity gate failed")
    for key in ("allclose", "max_abs_error", "prediction_disagreement_fraction",
                "vectors_checked"):
        require(report.get("onnx_check", {}).get(key) == fp32_check[key],
                f"Raw and independent FP32 checks differ: {key}")
    qdq_check = None
    qdq_operators = None
    qdq_int8_initializer_count = None
    deployed_logits = fp32_logits
    if mode == "qdq":
        qdq_graph = onnx.load(output_dir / "model_qdq_int8.onnx")
        onnx.checker.check_model(qdq_graph)
        qdq_operators = sorted({node.op_type for node in qdq_graph.graph.node})
        qdq_int8_initializer_count = sum(
            initializer.data_type in (onnx.TensorProto.INT8, onnx.TensorProto.UINT8)
            for initializer in qdq_graph.graph.initializer
        )
        require({"QuantizeLinear", "DequantizeLinear"}.issubset(qdq_operators) and
                qdq_int8_initializer_count > 0 and
                qdq_operators == report.get("qdq_operators") and
                report.get("reference_kind") == "qdq_int8_onnx",
                "QDQ graph lacks independently verified Q/DQ structure or INT8 tensors")
        qdq_logits = evaluate_onnx(output_dir / "model_qdq_int8.onnx", vectors)
        qdq_check = compare_logits(fp32_logits, qdq_logits, 1e-6, 1e-5)
        require(qdq_check["prediction_disagreement_fraction"] <= int8_max_disagreement,
                "Independent QDQ prediction-disagreement gate failed")
        for key in ("allclose", "max_abs_error", "prediction_disagreement_fraction",
                    "vectors_checked"):
            require(report.get("quantization_check", {}).get(key) == qdq_check[key],
                    f"Raw and independent QDQ checks differ: {key}")
        deployed_logits = qdq_logits
    require(np.array_equal(reference_logits, deployed_logits),
            "Stored deployed reference logits differ from independent ORT evaluation")

    return {
        "schema": 1,
        "status": "independently_validated",
        "publication_gate": True,
        "source_plan_sha256": plan["content_sha256"],
        "export_plan_sha256": export_plan["content_sha256"],
        "dataset": dataset,
        "model": model,
        "mode": mode,
        "checkpoint_sha256": policy["checkpoint_sha256"],
        "export_report_sha256": sha256(report_path),
        "validation_vectors_sha256": sha256(output_dir / "validation_vectors.npz"),
        "checkpoint_logits_sha256": array_sha256(checkpoint_logits),
        "checkpoint_check": checkpoint_check,
        "fp32_check": fp32_check,
        "qdq_check": qdq_check,
        "fp32_operators": fp32_operators,
        "qdq_operators": qdq_operators,
        "qdq_int8_initializer_count": qdq_int8_initializer_count,
        "acceptance_basis": "independent recomputation; raw export report consistency checked",
        "scope": "independent CPU ONNX Runtime parity on the fixed sampled validation rows",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--paper-dir", required=True, type=Path)
    parser.add_argument("--int8-max-disagreement", type=float, default=0.01)
    parser.add_argument("--validation-samples", type=int, default=1024)
    parser.add_argument("--calibration-samples", type=int, default=1000)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    output_root = args.output_root.resolve()
    runner_provenance = tool_provenance(
        Path(__file__), [sys.executable, *sys.argv], EXPORT_RUNNER_PACKAGES
    )
    require(args.int8_max_disagreement == 0.01,
            "The fixed protocol requires QDQ disagreement <= 0.01; do not tune it after inspection")
    require(args.validation_samples == 1024 and args.calibration_samples == 1000,
            "The fixed export sample counts are 1024 validation and 1000 fit calibration rows")
    plan = read_plan(run_dir)
    require(plan.get("protocol_role") == "planned_benchmark" and
            plan.get("seeds") == list(range(20)),
            "Only the full planned 20-seed benchmark may feed the formal export matrix")
    verification = load_json(run_dir / "verification_evaluate.json")
    check_seal(verification)
    require(verification.get("passed") is True and
            verification.get("plan_sha256") == plan["content_sha256"],
            "The complete primary/replica fit and evaluation barrier must pass before export")
    require(plan.get("deployment_seed") == 0, "The fixed deployment checkpoint is seed 0")

    require(not (run_dir / "export_registration.json").exists(),
            "This neural run already registered an export matrix; retain its outcomes")
    export_plan = build_export_plan(run_dir, output_root, plan, runner_provenance)
    export_plan_path = register_export_plan(output_root, export_plan)
    require(load_export_plan(output_root, plan) == export_plan,
            "Export plan changed before attempt 1")
    logs = output_root / "logs"
    logs.mkdir()
    attempts = []
    for dataset, model in JOBS:
        for mode in ("fp32", "qdq"):
            require(load_export_plan(output_root, plan, rehash=False) == export_plan,
                    "Frozen export inputs changed before an attempt")
            output_dir = output_root / dataset / model / mode
            output_dir.parent.mkdir(parents=True, exist_ok=True)
            command = exporter_invocation(
                run_dir, output_dir, dataset, model, mode,
                args.validation_samples, args.calibration_samples,
                args.int8_max_disagreement,
                export_plan_path=export_plan_path,
            )
            log_path = logs / f"{dataset}_{model}_{mode}.log"
            started = time.perf_counter()
            with log_path.open("w", encoding="utf-8") as stream:
                result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                        check=False, cwd=ROOT)
            elapsed = time.perf_counter() - started
            require(load_export_plan(output_root, plan, rehash=False) == export_plan,
                    "Frozen export inputs changed during an attempt")
            report_path = output_dir / "export_report.json"
            failure_path = output_dir / "FAILED.json"
            runner_evidence = output_dir / "runner_validation.json"
            passed = result.returncode == 0 and report_path.is_file() and not failure_path.exists()
            if passed:
                try:
                    validation = validate_attempt(
                        run_dir=run_dir,
                        output_dir=output_dir,
                        plan=plan,
                        dataset=dataset,
                        model=model,
                        mode=mode,
                        validation_samples=args.validation_samples,
                        calibration_samples=args.calibration_samples,
                        int8_max_disagreement=args.int8_max_disagreement,
                    )
                    write_json(runner_evidence, seal({
                        **validation,
                        "tool_provenance": runner_provenance,
                        "exporter_invocation": command,
                        "output_files_sha256": output_files_sha256(output_dir),
                    }))
                except Exception as exc:  # noqa: BLE001 -- persist every independent-validation failure
                    passed = False
                    write_json(runner_evidence, seal({
                        "status": "runner_validation_failed",
                        "reason": f"{type(exc).__name__}: {exc}",
                        "source_plan_sha256": plan["content_sha256"],
                        "export_plan_sha256": export_plan["content_sha256"],
                        "dataset": dataset,
                        "model": model,
                        "mode": mode,
                        "publication_gate": False,
                        "tool_provenance": runner_provenance,
                        "exporter_invocation": command,
                        "output_files_sha256": output_files_sha256(output_dir),
                    }))
            if not runner_evidence.exists():
                if not output_dir.exists():
                    output_dir.mkdir(parents=True)
                failure_sha256 = sha256(failure_path) if failure_path.is_file() else None
                failure_replay = None
                failure_classification = "infrastructure_or_unclassified"
                failure_replay_error = None
                try:
                    failure_replay = replay_scientific_failure(run_dir, output_root, export_plan, {
                        "dataset": dataset, "model": model, "mode": mode,
                        "output_dir": output_dir.relative_to(output_root).as_posix(),
                        "return_code": result.returncode,
                    })
                    failure_classification = "reproduced_scientific_gate"
                except Exception as exc:  # noqa: BLE001 -- unclassified failures must remain unpublished
                    failure_replay_error = f"{type(exc).__name__}: {exc}"
                write_json(runner_evidence, seal({
                    "status": "export_subprocess_failed",
                    "return_code": result.returncode,
                    "source_plan_sha256": plan["content_sha256"],
                    "export_plan_sha256": export_plan["content_sha256"],
                    "dataset": dataset,
                    "model": model,
                    "mode": mode,
                    "failure_file": failure_path.name if failure_path.is_file() else None,
                    "failure_file_sha256": failure_sha256,
                    "failure_classification": failure_classification,
                    "failure_replay": failure_replay,
                    "failure_replay_error": failure_replay_error,
                    "publication_gate": False,
                    "tool_provenance": runner_provenance,
                    "exporter_invocation": command,
                    "output_files_sha256": output_files_sha256(output_dir),
                }))
            evidence = runner_evidence
            attempts.append({
                "dataset": dataset,
                "model": model,
                "mode": mode,
                "export_plan_sha256": export_plan["content_sha256"],
                "passed": passed,
                "return_code": result.returncode,
                "elapsed_seconds": elapsed,
                "output_dir": output_dir.relative_to(output_root).as_posix(),
                "evidence": evidence.relative_to(output_root).as_posix(),
                "evidence_sha256": sha256(evidence),
                "log": log_path.relative_to(output_root).as_posix(),
                "log_sha256": sha256(log_path),
            })
            print(f"{dataset}/{model}/{mode}: {'PASS' if passed else 'FAIL'} ({elapsed:.1f}s)",
                  flush=True)

    fp32_passed = sum(row["passed"] for row in attempts if row["mode"] == "fp32")
    qdq_passed = sum(row["passed"] for row in attempts if row["mode"] == "qdq")
    report = {
        "source_plan_sha256": plan["content_sha256"],
        "export_plan_sha256": export_plan["content_sha256"],
        "deployment_seed": 0,
        "fold_bn": True,
        "fp32_atol": 1e-6,
        "fp32_rtol": 1e-5,
        "fp32_max_prediction_disagreement": 0.0,
        "int8_max_prediction_disagreement": args.int8_max_disagreement,
        "validation_samples": args.validation_samples,
        "calibration_samples": args.calibration_samples,
        "attempts": attempts,
        "fp32_passed": fp32_passed,
        "fp32_total": len(JOBS),
        "qdq_passed": qdq_passed,
        "qdq_total": len(JOBS),
        "all_gates_passed": fp32_passed == qdq_passed == len(JOBS),
        "scope": "sampled ONNX Runtime parity; not vendor-NPU placement, board parity, latency, or energy",
        "acceptance_evidence": "sealed independent runner_validation.json; raw exporter checks must match independent recomputation",
        "tool_provenance": runner_provenance,
    }
    summary_path = output_root / "summary.json"
    write_json(summary_path, seal(report))
    emit_export_macros(
        output_root, args.paper_dir, plan, summary_path, runner_provenance
    )
    print(f"FP32 {fp32_passed}/{len(JOBS)}; QDQ {qdq_passed}/{len(JOBS)}", flush=True)
    return 0 if report["all_gates_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
