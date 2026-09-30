#!/usr/bin/env python3
"""Independent per-payload scientific diagnosis for explicit export continuation.

Original plan/checkpoint/selection seals remain unchanged. The caller explicitly
routes one retained or fresh payload directory; no fake plan.output_root, legacy
acceptance oracle, worker, retry, test inference or phase/publication approval.
Only audit_dir is written. Model/freezer primitives are shared frozen code;
comparisons and quantization recipe replay are independently implemented here.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "spikeids_v5")]
import numpy as np
import onnx
import onnxruntime as ort
import torch
from contracts import check_seal, digest, json_bytes, load_json, require, seal
from evidence import load_fit
from experiment_all import load_checkpoint, tree_digest
from models import build, freeze_for_export
from tools import continue_v5_data_phase as records
from tools import continue_v5_research as lifecycle
from tools import export_v5_runtime as runtime
from tools import export_v5_build_identity as identity

SELF = Path(__file__).resolve()
JOBS = tuple((d, m) for d in ("nslkdd", "unsw", "cicids2017", "iot23")
             for m in (("relu", "qcfs") if d == "iot23" else ("relu", "qcfs", "cnn")))
KEYS = tuple((d, m, q) for d, m in JOBS for q in ("fp32", "qdq"))
SCOPE = "only these validation vectors, not every possible input"
REASONS = {
    "freeze": "BN folding/freezing changed outputs beyond the predeclared gate; inspect boundary activations",
    "fp32_parity": "ONNX numerical parity gate failed",
    "qdq_parity": "QDQ validation disagreement gate failed",
}
CHECK_NAMES = ("freeze_check", "onnx_check", "quantization_check")
RECIPE = {"quant_format": "QDQ", "activation_type": "QInt8", "weight_type": "QInt8",
          "per_channel": True, "reduce_range": False, "calibrate_method": "MinMax",
          "op_types_to_quantize": ["Gemm", "MatMul", "Conv"], "nodes_to_quantize": [],
          "nodes_to_exclude": [], "use_external_data_format": False,
          "calibration_providers": ["CPUExecutionProvider"], "extra_options": {},
          "unspecified_behavior": "bound to the recorded ONNX Runtime version and source"}


def source_paths():
    # The old runtime is used only for its same-FD sealed JSON integrity reader.
    return sorted({SELF, *identity.source_paths(), runtime.SELF})


def fixed_protocol():
    return {
        "deployment_seed": 0, "fold_bn": True, "opset": 17, "export_batch": 1,
        "fp32_atol": 1e-6, "fp32_rtol": 1e-5, "fp32_max_prediction_disagreement": 0.0,
        "int8_max_prediction_disagreement": 0.01, "validation_samples": 1024, "calibration_samples": 1000,
        "row_selection": {"generator": "numpy.random.default_rng(0); PCG64", "order": ["validation", "fit"],
            "replace": False, "indices": "ascending sorted choice indices", "validation_partition": "validation",
            "calibration_partition": "fit", "insufficient_rows": "fail; never silently truncate"},
        "qdq_recipe": RECIPE,
        "runtime": {"provider": "CPUExecutionProvider", "intra_op_threads": 1, "inter_op_threads": 1,
            "execution_mode": "ORT_SEQUENTIAL", "graph_optimization_level": "ORT_ENABLE_BASIC",
            "torch_deterministic_algorithms": True, "torch_float32_matmul_precision": "highest"},
        "retry_policy": "one registered matrix per neural run; failed artifacts retained",
    }


def equal(left, right):
    return json_bytes(left) == json_bytes(right)


def new_record(path, body):
    """Publish exclusively, then bind parsed content and hash from the same FD."""
    path = Path(path)
    expected = seal(body)
    records.write_new(path, expected)
    actual, pin = runtime._record(path)
    require(equal(actual, expected), "Published audit record differs from intended typed content")
    records.assert_snapshots({str(path): pin}, full=False)
    return pin


def assert_audit_inventory(root, pins):
    """Derive the permitted tree only from already captured commitments."""
    root = Path(root)
    require(all(Path(p).is_relative_to(root) and Path(p) != root for p in pins), "Foreign audit commitment")
    files = sorted(str(Path(p).relative_to(root)) for p in pins)
    directories = {"."}
    for name in files:
        directories.update(str(parent) for parent in Path(name).parents)
    lifecycle.assert_boundary({"root": str(root), "files": files,
        "directories": sorted(directories), "pins": pins}, full=False)


def array_digest(value):
    value = np.ascontiguousarray(value)
    hasher = hashlib.sha256(json_bytes({"shape": list(value.shape), "dtype": value.dtype.str}))
    hasher.update(memoryview(value).cast("B"))
    return hasher.hexdigest()


def numerical_check(reference, actual):
    """Own elementwise tolerance formula and integer argmax-disagreement count.

    FP32 subtraction/tolerance follows NumPy allclose's asymmetric second-array
    rule; maximum absolute error separately uses float64 differences, as declared
    by the recorded diagnostic. No producer compare_logits is called.
    """
    a, b = np.asarray(reference), np.asarray(actual)
    require(a.dtype == b.dtype == np.float32 and a.shape == b.shape and
            a.ndim == 2 and a.shape[0] == 1024 and a.shape[1] >= 2 and
            np.isfinite(a).all() and np.isfinite(b).all(), "Invalid audit logits")
    close = np.less_equal(np.abs(a - b), 1e-6 + 1e-5 * np.abs(b))
    count = int(np.count_nonzero(np.argmax(a, axis=1) != np.argmax(b, axis=1)))
    diagnostic = {"allclose": bool(close.all()),
                  "max_abs_error": float(np.max(np.abs(a.astype(np.float64) - b.astype(np.float64)))),
                  "prediction_disagreement_fraction": count / 1024,
                  "vectors_checked": 1024, "scope": SCOPE}
    return {"diagnostic": diagnostic, "prediction_disagreement_count": count,
            "reference_logits_sha256": array_digest(a), "actual_logits_sha256": array_digest(b)}


def selections(cache):
    rng = np.random.default_rng(0)
    selected, arrays = {}, {}
    for partition, count in (("validation", 1024), ("fit", 1000)):
        x = np.load(cache / f"x_{partition}.npy", allow_pickle=False, mmap_mode="r")
        ids = np.load(cache / f"ids_{partition}.npy", allow_pickle=False, mmap_mode="r")
        require(x.dtype == np.float32 and x.ndim == 2 and ids.ndim == 1 and
                len(x) == len(ids) and len(x) >= count, "Insufficient/malformed fixed audit rows")
        indices = np.sort(rng.choice(len(ids), count, replace=False))
        values = np.asarray(x[indices], dtype=np.float32)
        require(np.isfinite(values).all(), "Non-finite fixed audit rows")
        selected[partition] = {"partition": partition, "indices": indices.tolist(),
            "row_ids": ids[indices].tolist(), "ids_sha256": array_digest(ids[indices]),
            "x_sha256": array_digest(values)}
        arrays[partition] = values
    return selected, arrays


def checkpoint_model(run, neural, job, metadata):
    result = load_fit(run / "results" / f"{job['id']}.json", job, neural)
    checkpoint = run / "results" / job["id"] / "runs" / f"{job['model']}_seed_0.pt"
    state = load_checkpoint(checkpoint, result["fingerprint"])
    p = result["protocol"]
    model = build(job["model"], len(metadata["features"]), len(metadata["class_names"]),
                  p["hidden"], p["levels"], p["qcfs_formula"])
    model.load_state_dict(state["best_model"], strict=True)
    model.eval()
    require(tree_digest(model.state_dict()) == state["fit_result"]["best_state_sha256"],
            "Audit selected checkpoint state differs")
    return model


def infer_onnx(path, vectors):
    graph = onnx.load(path, load_external_data=False)
    require(all(not value.external_data for value in graph.graph.initializer), "External ONNX tensors forbidden")
    onnx.checker.check_model(graph)
    require([(op.domain, op.version) for op in graph.opset_import] == [("", 17)], "Unexpected ONNX opset")
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
    require([i.name for i in session.get_inputs()] == ["input"] and
            [i.name for i in session.get_outputs()] == ["logits"] and
            session.get_inputs()[0].type == "tensor(float)" and
            session.get_inputs()[0].shape == [1, vectors.shape[1]], "Unexpected ONNX IO contract")
    logits = np.concatenate([session.run(["logits"], {"input": row[None]})[0] for row in vectors])
    return logits, sorted({node.op_type for node in graph.graph.node})


def rebuild_qdq(output, audit, fit):
    from onnxruntime.quantization import (CalibrationDataReader, CalibrationMethod,
                                          QuantFormat, QuantType, quantize_static)
    require(fit.dtype == np.float32 and len(fit) == 1000, "Wrong fixed calibration budget")
    class Reader(CalibrationDataReader):
        def __init__(self): self.position = 0
        def get_next(self):
            if self.position == 1000: return None
            value = fit[self.position:self.position + 1]
            self.position += 1
            return {"input": value}
    target, log = audit / "model_qdq_rebuilt.onnx", audit / "qdq_rebuild.log"
    require(not target.exists() and not log.exists(), "No audit reconstruction retry")
    with log.open("x") as stream:
        try:
            stream.write(json.dumps({"recipe": RECIPE, "fit_rows": 1000}, sort_keys=True) + "\n")
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                quantize_static(str(output / "model_fp32.onnx"), str(target), Reader(),
                    quant_format=QuantFormat.QDQ, activation_type=QuantType.QInt8, weight_type=QuantType.QInt8,
                    per_channel=True, reduce_range=False, calibrate_method=CalibrationMethod.MinMax,
                    op_types_to_quantize=["Gemm", "MatMul", "Conv"], nodes_to_quantize=[], nodes_to_exclude=[],
                    use_external_data_format=False, calibration_providers=["CPUExecutionProvider"], extra_options={})
        finally:
            stream.flush(); os.fsync(stream.fileno())
    return {str(path): lifecycle.snapshot(path) for path in (target, log)}


def check_policy(policy, neural, export, job, mode, metadata, checkpoint_sha, best_sha):
    expected = {"schema": 5, "source_plan_sha256": neural["content_sha256"],
        "checkpoint_sha256": checkpoint_sha, "best_model_sha256": best_sha,
        "data_fingerprint": job["data_fingerprint"], "preprocessor_sha256": metadata["preprocessor_sha256"],
        "deployment_seed": 0, "fold_bn": True, "int8": mode == "qdq", "atol": 1e-6, "rtol": 1e-5,
        "board_atol": 1e-6, "board_rtol": 1e-5, "int8_max_disagreement": 0.01 if mode == "qdq" else None,
        "validation_samples": 1024, "calibration_samples": 1000, "opset": 17, "export_batch": 1,
        "onnx": onnx.__version__, "onnxruntime": ort.__version__, "torch": str(torch.__version__),
        "export_plan_sha256": export["content_sha256"], "qdq_recipe": RECIPE,
        "npu_placement": "UNVERIFIED; vendor mapping report and on-board parity required"}
    require(equal(policy, seal(expected)), "Raw export policy differs from fixed independent audit contract")


def validate_payload(*, neural_run, neural_plan, original_export_plan, row,
                     payload_dir, audit_dir, build_identity):
    """Confirm the declared payload outcome; caller owns full matrix/lifecycle."""
    run, neural, export = Path(neural_run), neural_plan, original_export_plan
    audit, output = Path(audit_dir), Path(payload_dir)
    require(isinstance(row, dict) and set(row) == {"dataset", "model", "mode", "passed", "return_code"},
            "Payload row must contain exactly the five declared identity/outcome fields")
    require(run.is_absolute() and run.resolve() == run and output.is_absolute() and output.resolve() == output,
            "Explicit canonical neural and payload paths required")
    check_seal(neural); check_seal(export)
    require(export["run_dir"] == str(run) and export["source_plan_sha256"] == neural["content_sha256"] and
            equal(neural.get("seeds"), list(range(20))) and neural.get("protocol_role") == "planned_benchmark",
            "Wrong original full neural/export plan binding")
    require(tuple((a.get("dataset"), a.get("model"), a.get("mode")) for a in export["attempts"]) == KEYS,
            "Original export plan must retain the ordered fixed 22 attempts")
    require(equal(export["protocol"], fixed_protocol()), "Original frozen export policy differs")
    original_plan_path = Path(export["output_root"]) / "export_plan.json"
    require(original_plan_path.is_absolute() and original_plan_path.resolve() == original_plan_path,
            "Original plan path must remain its genuine canonical registered path")
    identity_pins = identity.validate_build_identity(build_identity)
    identity.validate_distribution_versions(export["tool_provenance"]["packages"], build_identity)

    dataset, arm, mode = (row[k] for k in ("dataset", "model", "mode"))
    require((dataset, arm, mode) in KEYS and type(row["passed"]) is bool and
            type(row["return_code"]) is int and row["return_code"] == (0 if row["passed"] else 1),
            "Unclassified or noncanonical numerical audit row")
    matches = [j for j in neural["jobs"] if (j["dataset"], j["model"]) == (dataset, arm)]
    require(len(matches) == 1 and type(neural["deployment_seed"]) is int and neural["deployment_seed"] == 0,
            "Audit must reconstruct unique primary seed zero")
    job = matches[0]; cache = Path(job["cache"])
    checkpoint = run / "results" / job["id"] / "runs" / f"{arm}_seed_0.pt"
    before = lifecycle.artifact_boundary(output)
    paths = [*source_paths(), original_plan_path, run / "plan.json", checkpoint,
             run / "results" / f"{job['id']}.json", cache / "metadata.json",
             cache / "preprocessing.json", *[cache / f"{name}.npy" for name in
             ("x_validation", "ids_validation", "x_fit", "ids_fit")]]
    pins = {str(p): lifecycle.snapshot(p) for p in paths}
    lifecycle.merge_pins(pins, before["pins"])
    require(equal(load_json(original_plan_path), export) and equal(load_json(run / "plan.json"), neural),
            "Provided original plan differs from its retained bytes")
    original_inputs = {record["path"]: record for record in export["inputs"]}
    for path in [checkpoint, run / "results" / f"{job['id']}.json", cache / "metadata.json",
                 cache / "preprocessing.json", *[cache / f"{name}.npy" for name in
                 ("x_validation", "ids_validation", "x_fit", "ids_fit")]]:
        require(str(path) in original_inputs and pins[str(path)]["sha256"] == original_inputs[str(path)]["sha256"],
                "Scientific input differs from original pre-attempt export commitment")

    audit = records.new_path(Path(audit))
    for forbidden in (run, output, cache, Path(export["output_root"])):
        records.nonoverlap([audit, forbidden])
    require(all(not Path(path).is_relative_to(audit) for path in pins), "Audit overlaps a scientific source/input")
    audit.mkdir()
    produced = {}
    try:
        metadata = load_json(cache / "metadata.json"); check_seal(metadata)
        require(export["datasets"][dataset]["cache"] == str(cache) and
                export["datasets"][dataset]["metadata_sha256"] == pins[str(cache / "metadata.json")]["sha256"],
                "Original dataset metadata/cache binding differs")
        require(metadata["data_fingerprint"] == job["data_fingerprint"], "Prepared dataset identity differs")
        selection, arrays = selections(cache)
        require(equal(selection, export["datasets"][dataset]["selection"]), "Frozen row selection differs")
        attempt = next(a for a in export["attempts"] if (a["dataset"], a["model"], a["mode"]) == (dataset, arm, mode))
        require(attempt["checkpoint_sha256"] == pins[str(checkpoint)]["sha256"], "Frozen primary checkpoint differs")
        policy = load_json(output / "export_policy.json"); check_seal(policy)
        identity.validate_policy_versions(policy, build_identity, provenance_packages=export["tool_provenance"]["packages"])
        model = checkpoint_model(run, neural, job, metadata)
        best_sha = tree_digest(model.state_dict())
        require(best_sha == attempt["best_state_sha256"], "Not the independently selected neural state")
        check_policy(policy, neural, export, job, mode, metadata, pins[str(checkpoint)]["sha256"], best_sha)
        vectors = arrays["validation"]
        torch.set_num_threads(1); torch.use_deterministic_algorithms(True, warn_only=False)
        torch.set_float32_matmul_precision("highest")
        frozen = freeze_for_export(model, fold_bn=True)
        with torch.inference_mode():
            original = np.concatenate([model(torch.from_numpy(row[None])).numpy() for row in vectors])
            folded = np.concatenate([frozen(torch.from_numpy(row[None])).numpy() for row in vectors])
        comparisons = {"freeze_check": numerical_check(original, folded)}
        filename = "export_report.json" if row["passed"] else "FAILED.json"
        report = load_json(output / filename); check_seal(report)
        failure_stage = None if row["passed"] else report.get("stage")
        require(row["passed"] or failure_stage in REASONS, "Only retained numerical negatives may be audited")
        fp32_logits = qdq_logits = None; operators = {}
        if row["passed"] or failure_stage in ("fp32_parity", "qdq_parity"):
            fp32_logits, operators["fp32"] = infer_onnx(output / "model_fp32.onnx", vectors)
            comparisons["onnx_check"] = numerical_check(original, fp32_logits)
        if (row["passed"] and mode == "qdq") or failure_stage == "qdq_parity":
            require(mode == "qdq", "QDQ failure in FP32 arm")
            qdq_logits, operators["qdq"] = infer_onnx(output / "model_qdq_int8.onnx", vectors)
            comparisons["quantization_check"] = numerical_check(fp32_logits, qdq_logits)
            produced = rebuild_qdq(output, audit, arrays["fit"])
            require(produced[str(audit / "model_qdq_rebuilt.onnx")]["sha256"] ==
                    pins[str(output / "model_qdq_int8.onnx")]["sha256"], "Fixed QDQ recipe graph differs")
        diagnostic = {key: value["diagnostic"] for key, value in comparisons.items()}
        computed = {"schema": 1, "kind": "export_continuation_payload_numerical_recomputation",
                    "dataset": dataset, "model": arm, "mode": mode,
                    "comparisons": comparisons, "selection": selection, "operators": operators,
                    "expected_original_passed": row["passed"], "retained_failure_stage": failure_stage,
                    "recipe_rebuild": dict(produced), "validation_reexposure": True,
                    "original_export_plan_sha256": export["content_sha256"],
                    "payload_dir": str(output), "diagnosis_only": True,
                    "build_identity_sha256": digest(build_identity),
                    "installed_build_files": identity_pins,
                    "new_export_attempts": 0, "new_failure_replays": 0, "test_vectors_read": 0}
        produced[str(audit / "recomputed.json")] = new_record(audit / "recomputed.json", computed)
        if row["passed"]:
            require("FAILED.json" not in before["files"] and report.get("status") ==
                    "validated_on_sampled_validation_vectors", "Contradictory retained success")
            for key, actual in diagnostic.items():
                require(equal(report.get(key), actual), f"Recomputed success diagnostic differs: {key}")
            require((mode == "qdq") == ("quantization_check" in report), "Wrong success mode diagnostics")
            for key in ("board_validated", "energy_measured", "npu_placement_verified"):
                require(report.get(key) is False, "Unprovided physical evidence claim")
            require(report.get("policy_sha256") == digest({k: v for k, v in policy.items() if k != "content_sha256"}) and
                    report.get("checkpoint_sha256") == pins[str(checkpoint)]["sha256"] and
                    report.get("source_plan_sha256") == neural["content_sha256"] and
                    report.get("export_plan_sha256") == export["content_sha256"] and
                    report.get("data_fingerprint") == job["data_fingerprint"] and
                    report.get("preprocessor_sha256") == metadata["preprocessor_sha256"], "Success report identity differs")
            payloads = {"export_policy.json", "model_fp32.onnx", "validation_vectors.npz",
                        "calibration_rows.json", "preprocessing.json"}
            if mode == "qdq": payloads.add("model_qdq_int8.onnx")
            require(set(before["files"]) - {"runner_validation.json"} == payloads | {"export_report.json"} and
                    equal(report.get("files_sha256"), {name: pins[str(output / name)]["sha256"] for name in payloads}),
                    "Success payload inventory differs")
            for name, key, kind in (("model_fp32.onnx", "graph_sha256", "fp32"),
                                    *(([("model_qdq_int8.onnx", "quantized_graph_sha256", "qdq")]) if mode == "qdq" else [])):
                require(report.get(key) == pins[str(output / name)]["sha256"] and
                        equal(report.get(f"{kind}_operators"), operators[kind]), "Graph inventory differs")
            require(report.get("reference_kind") == ("qdq_int8_onnx" if mode == "qdq" else "fp32_onnx"),
                    "Wrong stored reference role")
            with np.load(output / "validation_vectors.npz", allow_pickle=False) as stored:
                expected = {"x": vectors, "original_logits": original,
                            "reference_logits": qdq_logits if mode == "qdq" else fp32_logits,
                            "validation_row_ids": np.load(cache / "ids_validation.npy", allow_pickle=False,
                                mmap_mode="r")[selection["validation"]["indices"]]}
                require(set(stored.files) == set(expected), "Wrong vector archive fields")
                for key, value in expected.items():
                    require(stored[key].dtype == value.dtype and np.array_equal(stored[key], value),
                            f"Stored vector array differs: {key}")
            require(equal(load_json(output / "calibration_rows.json"), {"partition": "fit",
                    "row_ids": selection["fit"]["row_ids"], "ids_sha256": selection["fit"]["ids_sha256"]}) and
                    pins[str(output / "preprocessing.json")]["sha256"] == pins[str(cache / "preprocessing.json")]["sha256"],
                    "Calibration or preprocessing payload differs")
        else:
            fail_key = dict(zip(REASONS, CHECK_NAMES))[failure_stage]
            require("export_report.json" not in before["files"] and report.get("publication_gate") is False and
                    report.get("status") == "failed" and
                    report.get("reason") == f"ContractError: {REASONS[failure_stage]}" and
                    report.get("checkpoint_sha256") == pins[str(checkpoint)]["sha256"] and
                    report.get("source_plan_sha256") == neural["content_sha256"] and
                    report.get("export_plan_sha256") == export["content_sha256"] and
                    equal(report.get("diagnostics"), diagnostic), "Retained negative diagnostics or identity differ")
            partial = {"export_policy.json"}
            if failure_stage in ("fp32_parity", "qdq_parity"): partial.add("model_fp32.onnx")
            if failure_stage == "qdq_parity": partial.add("model_qdq_int8.onnx")
            require(set(before["files"]) - {"runner_validation.json", "FAILED.json"} == partial and
                    equal(report.get("partial_files_sha256"), {name: pins[str(output / name)]["sha256"] for name in partial}),
                    "Negative partial-graph inventory differs")
        for name, measurement in comparisons.items():
            value = measurement["diagnostic"]
            passed = (measurement["prediction_disagreement_count"] / 1024 <= 0.01 if name == "quantization_check"
                      else value["allclose"] and measurement["prediction_disagreement_count"] == 0)
            require(passed is (row["passed"] or name != fail_key), "Recomputed numerical gate decision differs")
        require(equal(identity.validate_build_identity(build_identity), identity_pins),
                "Build identity changed during numerical diagnosis")
        identity.validate_distribution_versions(export["tool_provenance"]["packages"], build_identity)
        records.assert_snapshots({**pins, **produced})
        lifecycle.assert_boundary(before, full=False)
        assert_audit_inventory(audit, produced)
        produced[str(audit / "accepted.json")] = new_record(audit / "accepted.json", {**computed, "passed": True,
                   "source_sha256": pins[str(SELF)]["sha256"], "input_pins": pins, "generated_pins": dict(produced)})
        require(equal(identity.validate_build_identity(build_identity), identity_pins),
                "Build identity changed during diagnosis publication")
        records.assert_snapshots({**pins, **produced}, full=False)
        assert_audit_inventory(audit, produced)
        return {"dataset": dataset, "model": arm, "mode": mode, "passed": True,
                "original_parity_passed": row["passed"], "comparisons": comparisons,
                "diagnosis_only": True, "negative_stage": failure_stage,
                "original_export_plan_sha256": export["content_sha256"], "payload_dir": str(output),
                "source_sha256": pins[str(SELF)]["sha256"], "build_identity_sha256": digest(build_identity),
                "installed_build_files": identity_pins,
                "inputs": pins, "artifacts": produced}
    except BaseException as exc:
        new_record(audit / "FAILED.json", {"schema": 1, "kind": "export_continuation_payload_diagnosis_failure",
                   "passed": False, "error": repr(exc), "automatic_retry": False})
        raise
