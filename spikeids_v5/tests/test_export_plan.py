"""Adversarial pre-attempt export policy and exact scientific-failure replay tests."""

from __future__ import annotations

import copy
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "spikeids_v5"))

from contracts import ContractError, load_json, seal, sha256, write_json

from tools import run_v5_exports as exports


@pytest.fixture
def frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Tiny artifacts with real selection/seals; provenance mocking is explicit."""
    run = tmp_path / "run"
    run.mkdir()
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    protocol = tmp_path / "protocol.md"
    protocol.write_text("Fixed synthetic protocol.\n", encoding="utf-8")
    monkeypatch.setattr(exports, "_source_paths", lambda: [source, protocol])
    monkeypatch.setattr(exports, "validate_tool_provenance", lambda *_a, **_k: None)
    jobs = []
    caches = {}
    for dataset, model in exports.JOBS:
        if dataset not in caches:
            cache = tmp_path / dataset
            cache.mkdir()
            arrays = {
                "ids_fit.npy": np.arange(1100, dtype=np.int64),
                "ids_validation.npy": np.arange(1100, 2200, dtype=np.int64),
                "x_fit.npy": np.arange(2200, dtype=np.float32).reshape(1100, 2),
                "x_validation.npy": np.arange(2200, 4400, dtype=np.float32).reshape(1100, 2),
            }
            for name, array in arrays.items():
                np.save(cache / name, array)
            write_json(cache / "preprocessing.json", {"synthetic": True})
            inventory = {path.name: sha256(path) for path in cache.iterdir()}
            write_json(cache / "metadata.json", seal({
                "data_fingerprint": dataset, "files_sha256": inventory,
            }))
            caches[dataset] = cache
        jobs.append({"id": f"{dataset}_{model}", "dataset": dataset, "model": model,
                     "cache": str(caches[dataset]), "data_fingerprint": dataset})
    plan = seal({"protocol_role": "planned_benchmark", "seeds": list(range(20)),
                 "deployment_seed": 0, "jobs": jobs})
    write_json(run / "plan.json", plan)
    for name in ("verification_fit.json", "verification_evaluate.json"):
        write_json(run / name, seal({"passed": True, "plan_sha256": plan["content_sha256"]}))
    checkpoints = {}
    for job in jobs:
        for execution in ("results", "replicas"):
            write_json(run / execution / f"{job['id']}.json", seal({"synthetic": True}))
            write_json(run / execution / job["id"] / "manifest.json", seal({"synthetic": True}))
        checkpoint = run / "results" / job["id"] / "runs" / f"{job['model']}_seed_0.pt"
        checkpoint.parent.mkdir()
        checkpoint.write_bytes(job["id"].encode())
        checkpoints[job["id"]] = {"results": {"0": {
            "path": checkpoint.relative_to(run).as_posix(),
            "artifact_sha256": sha256(checkpoint), "best_state_sha256": "b" * 64,
        }}}
    write_json(run / "independent_verification.json", seal({
        "kind": "independent_formal_neural_and_statistics_verification", "passed": True,
        "plan_sha256": plan["content_sha256"], "prediction_artifacts_checked": 440,
        "checkpoints_checked": 440, "checkpoints": checkpoints, "tool_provenance": {},
        "verification_fit_sha256": sha256(run / "verification_fit.json"),
        "verification_evaluate_sha256": sha256(run / "verification_evaluate.json"),
    }))
    write_json(run / "export_prior_exposure.json", seal({
        "schema": 1, "kind": "spikeids_v5_export_prior_exposure",
        "source_plan_sha256": plan["content_sha256"], "known_exposures": [],
        "declaration": "Synthetic fixture; this is not a formal exposure declaration.",
        "complete_history_independently_verified": False,
        "local_freeze_is_external_preregistration": False,
    }))
    output = tmp_path / "exports"
    export_plan = exports.build_export_plan(run, output, plan, {})
    exports.register_export_plan(output, export_plan)
    return {"run": run, "output": output, "neural": plan, "plan": export_plan,
            "source": source, "caches": caches}


def _reseal(path: Path, value: dict) -> None:
    value = {key: item for key, item in value.items() if key != "content_sha256"}
    write_json(path, seal(value))


def test_complete_matrix_frozen_before_any_attempt(frozen: dict) -> None:
    plan = exports.load_export_plan(frozen["output"], frozen["neural"])
    assert len(plan["attempts"]) == 22
    assert not (frozen["output"] / "nslkdd").exists()
    assert plan["protocol"]["qdq_recipe"]["calibrate_method"] == "MinMax"
    assert plan["protocol"]["row_selection"]["calibration_partition"] == "fit"
    for dataset in plan["datasets"].values():
        assert len(dataset["selection"]["validation"]["indices"]) == 1024
        assert len(dataset["selection"]["fit"]["indices"]) == 1000
        assert set(dataset["selection"]["fit"]["row_ids"]) <= set(range(1100))
    assert exports.load_export_plan(frozen["output"], frozen["neural"], rehash=False) == plan


@pytest.mark.parametrize("mutation", ["source", "cache", "checkpoint", "gate", "disclosure"])
def test_post_freeze_input_mutation_rejected_even_without_rehash(frozen: dict, mutation: str) -> None:
    paths = {
        "source": frozen["source"],
        "cache": frozen["caches"]["nslkdd"] / "x_fit.npy",
        "checkpoint": frozen["run"] / "results/nslkdd_relu/runs/relu_seed_0.pt",
        "gate": frozen["run"] / "verification_evaluate.json",
        "disclosure": frozen["run"] / "export_prior_exposure.json",
    }
    path = paths[mutation]
    old = path.stat()
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(data)
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    with pytest.raises(Exception, match="changed"):
        exports.load_export_plan(frozen["output"], frozen["neural"], rehash=False)


@pytest.mark.parametrize("mutation", ["threshold", "recipe", "matrix", "samples", "selection"])
def test_resealed_policy_or_row_mutation_cannot_replace_registration(frozen: dict, mutation: str) -> None:
    path = frozen["output"] / "export_plan.json"
    plan = load_json(path)
    if mutation == "threshold":
        plan["protocol"]["int8_max_prediction_disagreement"] = 1.0
    elif mutation == "recipe":
        plan["protocol"]["qdq_recipe"]["activation_type"] = "QUInt8"
    elif mutation == "matrix":
        plan["attempts"].pop()
    elif mutation == "samples":
        plan["protocol"]["calibration_samples"] = 10
    else:
        plan["datasets"]["nslkdd"]["selection"]["fit"]["row_ids"][0] = 99999
    _reseal(path, plan)
    with pytest.raises(Exception, match="policy|matrix|registration"):
        exports.load_export_plan(frozen["output"], frozen["neural"])


def test_coordinated_registration_reseal_still_reconstructs_selection(frozen: dict) -> None:
    path = frozen["output"] / "export_plan.json"
    plan = load_json(path)
    plan["datasets"]["nslkdd"]["selection"]["fit"]["indices"][0] = 99999
    _reseal(path, plan)
    registration_path = frozen["run"] / "export_registration.json"
    registration = load_json(registration_path)
    registration["export_plan_sha256"] = load_json(path)["content_sha256"]
    registration["export_plan_file_sha256"] = sha256(path)
    _reseal(registration_path, registration)
    with pytest.raises(Exception, match="reconstruction"):
        exports.load_export_plan(frozen["output"], frozen["neural"])


def test_only_one_matrix_can_register_per_neural_run(frozen: dict) -> None:
    other = frozen["output"].parent / "second-attempt"
    second = exports.build_export_plan(frozen["run"], other, frozen["neural"], {})
    original_registration = (frozen["run"] / "export_registration.json").read_bytes()
    with pytest.raises(FileExistsError):
        exports.register_export_plan(other, second)
    assert (frozen["run"] / "export_registration.json").read_bytes() == original_registration
    assert exports.load_export_plan(frozen["output"], frozen["neural"]) == frozen["plan"]


def test_aliasing_bound_input_is_rejected(frozen: dict) -> None:
    os.link(frozen["source"], frozen["source"].with_name("alias.py"))
    with pytest.raises(Exception, match="unaliased"):
        exports.load_export_plan(frozen["output"], frozen["neural"])


def test_insufficient_rows_never_silently_truncated(frozen: dict) -> None:
    cache = frozen["caches"]["nslkdd"]
    np.save(cache / "ids_validation.npy", np.arange(100, dtype=np.int64))
    with pytest.raises(Exception, match="Insufficient or malformed"):
        exports._row_selection({"dataset": "nslkdd", "cache": str(cache)})


def _failed_attempt(frozen: dict) -> tuple[dict, dict, Path]:
    plan = frozen["plan"]
    output = frozen["output"] / "nslkdd/relu/qdq"
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = next(a["checkpoint_sha256"] for a in plan["attempts"]
                      if a["dataset"] == "nslkdd" and a["model"] == "relu")
    write_json(output / "export_policy.json", seal({
        "export_plan_sha256": plan["content_sha256"], "checkpoint_sha256": checkpoint,
        "qdq_recipe": exports.fixed_export_protocol()["qdq_recipe"],
    }))
    (output / "model_fp32.onnx").write_bytes(b"synthetic-fp32-graph")
    (output / "model_qdq_int8.onnx").write_bytes(b"synthetic-qdq-graph")
    okay = {"allclose": True, "max_abs_error": 0.0,
            "prediction_disagreement_fraction": 0.0, "vectors_checked": 1024}
    diagnostic = {**okay, "allclose": False, "max_abs_error": 0.2,
                  "prediction_disagreement_fraction": 20 / 1024}
    failure = seal({
        "schema": 1, "status": "failed", "stage": "qdq_parity", "publication_gate": False,
        "reason": "ContractError: QDQ validation disagreement gate failed",
        "source_plan_sha256": plan["source_plan_sha256"],
        "export_plan_sha256": plan["content_sha256"], "checkpoint_sha256": checkpoint,
        "diagnostics": {"freeze_check": okay, "onnx_check": okay,
                        "quantization_check": diagnostic},
        "partial_files_sha256": exports.output_files_sha256(output),
    })
    write_json(output / "FAILED.json", failure)
    row = {"dataset": "nslkdd", "model": "relu", "mode": "qdq",
           "return_code": 1, "output_dir": "nslkdd/relu/qdq"}
    return row, failure, output


@pytest.mark.parametrize("mutation", ["oom", "disk", "identity", "passing", "prior_gate", "payload", "extra_payload"])
def test_failure_cannot_masquerade_as_scientific_qdq_outcome(frozen: dict, mutation: str) -> None:
    row, failure, output = _failed_attempt(frozen)
    assert exports.scientific_failure(output, frozen["plan"], "nslkdd", "relu", "qdq", 1) == failure
    if mutation == "oom":
        row["return_code"] = -9
    elif mutation == "disk":
        failure["reason"] = "OSError: No space left on device"
    elif mutation == "identity":
        failure["checkpoint_sha256"] = "a" * 64
    elif mutation == "passing":
        failure["diagnostics"]["quantization_check"]["prediction_disagreement_fraction"] = 0.0
    elif mutation == "prior_gate":
        failure["diagnostics"]["onnx_check"]["allclose"] = False
    elif mutation == "extra_payload":
        (output / "core").write_bytes(b"unplanned")
        failure["partial_files_sha256"]["core"] = sha256(output / "core")
    else:
        (output / "model_qdq_int8.onnx").write_bytes(b"changed")
    _reseal(output / "FAILED.json", failure)
    with pytest.raises(ContractError):
        exports.scientific_failure(output, frozen["plan"], "nslkdd", "relu", "qdq", row["return_code"])


@pytest.mark.parametrize("mutation", [None, "succeeds", "diagnostic", "payload", "infra"])
def test_failure_replay_requires_exact_scientific_diagnostics_and_payloads(
        frozen: dict, monkeypatch: pytest.MonkeyPatch, mutation: str | None) -> None:
    row, failure, output = _failed_attempt(frozen)
    original = {path.name: path.read_bytes() for path in output.iterdir()}

    def replay(argv: list[str], **_kwargs) -> subprocess.CompletedProcess:
        assert Path(argv[argv.index("--export-plan") + 1]) == frozen["output"] / "export_plan.json"
        target = Path(argv[argv.index("--output-dir") + 1])
        assert target != output
        target.mkdir()
        for name, data in original.items():
            (target / name).write_bytes(data)
        if mutation == "diagnostic":
            altered = copy.deepcopy(failure)
            altered["diagnostics"]["quantization_check"]["prediction_disagreement_fraction"] = 30 / 1024
            _reseal(target / "FAILED.json", altered)
        if mutation == "payload":
            (target / "model_qdq_int8.onnx").write_bytes(b"different-graph")
            altered = copy.deepcopy(failure)
            altered["partial_files_sha256"]["model_qdq_int8.onnx"] = sha256(target / "model_qdq_int8.onnx")
            _reseal(target / "FAILED.json", altered)
        if mutation == "infra":
            altered = copy.deepcopy(failure)
            altered["stage"] = "payload_write"
            altered["reason"] = "OSError: disk full"
            _reseal(target / "FAILED.json", altered)
        return subprocess.CompletedProcess(argv, 0 if mutation == "succeeds" else 1)

    monkeypatch.setattr(exports.subprocess, "run", replay)
    if mutation is None:
        result = exports.replay_scientific_failure(frozen["run"], frozen["output"], frozen["plan"], row)
        assert result["passed"] is True
    else:
        with pytest.raises(Exception, match="replay|Infrastructure"):
            exports.replay_scientific_failure(frozen["run"], frozen["output"], frozen["plan"], row)
    assert original == {path.name: path.read_bytes() for path in output.iterdir()}
    assert not list(frozen["output"].parent.glob(".export-scientific-replay-*"))


def _publication_summary(frozen: dict) -> dict:
    """Synthetic prevalidated runner records isolate the summary consumer contract."""
    attempts = []
    protocol = exports.fixed_export_protocol()
    (frozen["output"] / "logs").mkdir(exist_ok=True)
    for dataset, model in exports.JOBS:
        for mode in ("fp32", "qdq"):
            relative = f"{dataset}/{model}/{mode}"
            output = frozen["output"] / relative
            output.mkdir(parents=True, exist_ok=True)
            evidence_path = output / "runner_validation.json"
            write_json(evidence_path, seal({
                "source_plan_sha256": frozen["neural"]["content_sha256"],
                "export_plan_sha256": frozen["plan"]["content_sha256"],
                "dataset": dataset, "model": model, "mode": mode,
                "status": "independently_validated", "publication_gate": True,
                "tool_provenance": {}, "output_files_sha256": {},
                "fp32_check": {"allclose": True, "prediction_disagreement_fraction": 0.,
                               "vectors_checked": 1024, "max_abs_error": 0.},
                "qdq_check": {"prediction_disagreement_fraction": 0., "vectors_checked": 1024},
            }))
            log_relative = f"logs/{dataset}_{model}_{mode}.log"
            log = frozen["output"] / log_relative
            log.write_text("Synthetic prevalidated attempt; not a research result.\n")
            attempts.append({
                "dataset": dataset, "model": model, "mode": mode, "passed": True,
                "export_plan_sha256": frozen["plan"]["content_sha256"],
                "return_code": 0, "elapsed_seconds": 1., "output_dir": relative,
                "evidence": f"{relative}/runner_validation.json",
                "evidence_sha256": sha256(evidence_path),
                "log": log_relative, "log_sha256": sha256(log),
            })
    return seal({
        "source_plan_sha256": frozen["neural"]["content_sha256"],
        "export_plan_sha256": frozen["plan"]["content_sha256"],
        **{key: protocol[key] for key in (
            "deployment_seed", "fold_bn", "fp32_atol", "fp32_rtol",
            "fp32_max_prediction_disagreement", "int8_max_prediction_disagreement",
            "validation_samples", "calibration_samples")},
        "tool_provenance": {}, "attempts": attempts, "fp32_passed": 11,
        "qdq_passed": 11, "fp32_total": 11, "qdq_total": 11, "all_gates_passed": True,
    })


def _seal_modified(value: dict) -> dict:
    return seal({key: item for key, item in value.items() if key != "content_sha256"})


def test_publication_summary_uses_frozen_policy_and_complete_counts(frozen: dict) -> None:
    macros = exports.expected_export_macros(frozen["output"], _publication_summary(frozen))
    assert macros["vExportFpTotal"] == macros["vExportQdqTotal"] == "11"
    assert macros["vExportCalibrationRows"] == "1000"
    assert macros["vExportQdqLimitPct"] == "1.00"


@pytest.mark.parametrize("key,value", [
    ("deployment_seed", 1), ("deployment_seed", False), ("fold_bn", 1),
    ("fp32_atol", 1.), ("fp32_rtol", 1.), ("fp32_max_prediction_disagreement", .5),
    ("validation_samples", 7), ("calibration_samples", 7),
    ("int8_max_prediction_disagreement", .99), ("fp32_total", 1), ("qdq_total", 999),
    ("fp32_total", 11.), ("fp32_passed", 10), ("qdq_passed", 0),
    ("all_gates_passed", 1), ("all_gates_passed", False), ("tool_provenance", {"wrong": True}),
])
def test_resealed_publication_scalar_cannot_override_frozen_plan(frozen: dict, key, value) -> None:
    summary = _publication_summary(frozen)
    summary[key] = value
    with pytest.raises(ContractError):
        exports.expected_export_macros(frozen["output"], _seal_modified(summary))


@pytest.mark.parametrize("key,value", [
    ("passed", "true"), ("passed", 1), ("return_code", False), ("return_code", 1),
    ("export_plan_sha256", "wrong"), ("output_dir", "../elsewhere"),
    ("evidence", "nslkdd/relu/qdq/runner_validation.json"),
    ("log", "logs/nslkdd_relu_qdq.log"), ("evidence_sha256", "wrong"),
    ("log_sha256", "wrong"), ("elapsed_seconds", -1.), ("elapsed_seconds", True),
])
def test_resealed_attempt_identity_type_and_path_mutations_rejected(frozen: dict, key, value) -> None:
    summary = _publication_summary(frozen)
    summary["attempts"][0][key] = value
    with pytest.raises(ContractError):
        exports.expected_export_macros(frozen["output"], _seal_modified(summary))


def test_resealed_publication_attempt_reordering_rejected(frozen: dict) -> None:
    summary = _publication_summary(frozen)
    summary["attempts"][:2] = summary["attempts"][1::-1]
    with pytest.raises(ContractError, match="ordered"):
        exports.expected_export_macros(frozen["output"], _seal_modified(summary))


@pytest.mark.parametrize("mutation", ["log", "evidence_alias", "payload", "status", "provenance"])
def test_publication_checks_bound_artifacts_not_just_summary_seal(frozen: dict, mutation: str) -> None:
    summary = _publication_summary(frozen)
    row = summary["attempts"][0]
    evidence_path = frozen["output"] / row["evidence"]
    if mutation == "log":
        (frozen["output"] / row["log"]).write_text("changed log\n")
    elif mutation == "evidence_alias":
        os.link(evidence_path, frozen["output"] / "outside-alias.json")
    elif mutation == "payload":
        (evidence_path.parent / "unrecorded.bin").write_bytes(b"changed payload")
    else:
        evidence = load_json(evidence_path)
        evidence["status" if mutation == "status" else "tool_provenance"] = "wrong"
        _reseal(evidence_path, evidence)
        row["evidence_sha256"] = sha256(evidence_path)
    with pytest.raises(ContractError):
        exports.expected_export_macros(frozen["output"], _seal_modified(summary))


def test_publication_rejects_unclassified_failure(frozen: dict) -> None:
    summary = _publication_summary(frozen)
    row, _failure, output = _failed_attempt(frozen)
    evidence = seal({"source_plan_sha256": frozen["neural"]["content_sha256"],
                     "export_plan_sha256": frozen["plan"]["content_sha256"],
                     "dataset": "nslkdd", "model": "relu", "mode": "qdq",
                     "status": "export_subprocess_failed", "publication_gate": False,
                     "return_code": 1, "tool_provenance": {},
                     "output_files_sha256": exports.output_files_sha256(output),
                     "failure_classification": "infrastructure_or_unclassified"})
    write_json(output / "runner_validation.json", evidence)
    attempt = next(a for a in summary["attempts"] if a["output_dir"] == row["output_dir"])
    attempt.update(passed=False, return_code=1, evidence_sha256=sha256(output / "runner_validation.json"))
    summary.update(qdq_passed=10, all_gates_passed=False)
    with pytest.raises(Exception, match="Infrastructure or unclassified"):
        exports.expected_export_macros(frozen["output"], _seal_modified(summary))


@pytest.mark.parametrize("replay_inventory_mutation", [False, True])
def test_publication_preserves_complete_mixed_scientific_outcomes(
        frozen: dict, replay_inventory_mutation: bool) -> None:
    summary = _publication_summary(frozen)
    row, _failure, output = _failed_attempt(frozen)
    inventory = exports.output_files_sha256(output)
    # This consumer test supplies a synthetic completed replay record; the
    # separate replay tests above actually call the replay subprocess API.
    replay = {"kind": "exact_scientific_failure_replay", "passed": True,
              "export_plan_sha256": frozen["plan"]["content_sha256"],
              "failure_sha256": sha256(output / "FAILED.json"),
              "output_files_sha256": {} if replay_inventory_mutation else inventory}
    write_json(output / "runner_validation.json", seal({
        "source_plan_sha256": frozen["neural"]["content_sha256"],
        "export_plan_sha256": frozen["plan"]["content_sha256"],
        "dataset": "nslkdd", "model": "relu", "mode": "qdq",
        "status": "export_subprocess_failed", "publication_gate": False,
        "return_code": 1, "tool_provenance": {}, "output_files_sha256": inventory,
        "failure_classification": "reproduced_scientific_gate", "failure_replay": replay,
    }))
    attempt = next(a for a in summary["attempts"] if a["output_dir"] == row["output_dir"])
    attempt.update(passed=False, return_code=1, evidence_sha256=sha256(output / "runner_validation.json"))
    summary.update(qdq_passed=10, all_gates_passed=False)
    if replay_inventory_mutation:
        with pytest.raises(ContractError, match="replay"):
            exports.expected_export_macros(frozen["output"], _seal_modified(summary))
    else:
        macros = exports.expected_export_macros(frozen["output"], _seal_modified(summary))
        assert macros["vExportQdqPassed"] == "10" and macros["vExportQdqTotal"] == "11"
        assert macros["vExportFpPassed"] == "11"


def test_real_onnx_export_and_structured_failure_preserve_frozen_policy(
        frozen: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Actual ONNX export/ORT execution; only the already-tested checkpoint loader is substituted."""
    candidate = Path(os.environ.get("SPIKEIDS_EXPORTER_UNDER_TEST",
                                    str(ROOT / "spikeids_v5/export_verified.py")))
    spec = importlib.util.spec_from_file_location("export_plan_candidate", candidate)
    assert spec is not None and spec.loader is not None
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    assert exporter.QDQ_RECIPE == exports.fixed_export_protocol()["qdq_recipe"]
    job = frozen["neural"]["jobs"][0]
    cache = frozen["caches"]["nslkdd"]
    arrays = {name: np.load(cache / f"{name}.npy", allow_pickle=False)
              for name in ("x_fit", "x_validation", "ids_fit", "ids_validation")}
    arrays.update(y_fit=np.zeros(1100, dtype=np.int64),
                  y_validation=np.zeros(1100, dtype=np.int64))
    model = torch.nn.Linear(2, 2, bias=False).eval()
    with torch.no_grad():
        model.weight.copy_(torch.eye(2))
    checkpoint = frozen["run"] / "results/nslkdd_relu/runs/relu_seed_0.pt"
    metadata = {"data_fingerprint": "nslkdd", "preprocessor_sha256": "p" * 64}
    monkeypatch.setattr(exporter, "checkpoint_context", lambda *_args:
                        (frozen["neural"], job, {}, metadata, arrays, model, checkpoint))
    fp32_output = frozen["output"] / "nslkdd/relu/fp32"
    argv = exports.exporter_invocation(frozen["run"], fp32_output, "nslkdd", "relu", "fp32",
                                       1024, 1000, 0.01)
    monkeypatch.setattr(sys, "argv", argv[1:])
    exporter.main()
    fp32_report = load_json(fp32_output / "export_report.json")
    assert fp32_report["export_plan_sha256"] == frozen["plan"]["content_sha256"]
    assert fp32_report["onnx_check"]["allclose"] is True

    # Keep real graph generation and ORT, but inject a known reproducible numerical
    # disagreement at its output boundary to exercise the actual failure writer.
    import onnxruntime as ort

    real_session = ort.InferenceSession

    class ChangedQdqSession:
        def __init__(self, path, **kwargs):
            self.session = real_session(path, **kwargs)
            self.changed = str(path).endswith("model_qdq_int8.onnx")

        def run(self, names, values):
            result = self.session.run(names, values)
            if self.changed:
                result[0] = result[0][:, ::-1].copy()
            return result

        def __getattr__(self, name):
            return getattr(self.session, name)

    monkeypatch.setattr(ort, "InferenceSession", ChangedQdqSession)
    qdq_output = frozen["output"] / "nslkdd/relu/qdq"
    argv = exports.exporter_invocation(frozen["run"], qdq_output, "nslkdd", "relu", "qdq",
                                       1024, 1000, 0.01)
    monkeypatch.setattr(sys, "argv", argv[1:])
    with pytest.raises(Exception, match="QDQ validation disagreement gate failed"):
        exporter.main()
    failure = exports.scientific_failure(qdq_output, frozen["plan"], "nslkdd", "relu", "qdq", 1)
    assert failure["stage"] == "qdq_parity"
    assert failure["diagnostics"]["quantization_check"]["prediction_disagreement_fraction"] > 0.01
    assert failure["partial_files_sha256"]["model_qdq_int8.onnx"] == sha256(qdq_output / "model_qdq_int8.onnx")

    def actual_replay(argv, **_kwargs):
        monkeypatch.setattr(sys, "argv", argv[1:])
        try:
            exporter.main()
        except ContractError as exc:
            assert str(exc) == "QDQ validation disagreement gate failed"
            return subprocess.CompletedProcess(argv, 1)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(exports.subprocess, "run", actual_replay)
    replay = exports.replay_scientific_failure(frozen["run"], frozen["output"], frozen["plan"], {
        "dataset": "nslkdd", "model": "relu", "mode": "qdq", "return_code": 1,
        "output_dir": "nslkdd/relu/qdq",
    })
    assert replay["passed"] is True
