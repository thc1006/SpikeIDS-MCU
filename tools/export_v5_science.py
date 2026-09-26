#!/usr/bin/env python3
"""Additive, independently replayed freeze and fixed-QDQ-recipe acceptance.

No registry, plan, checkpoint, legacy source or exporter output is modified.
The caller owns registration resolution, frozen runtime/source/input identities,
one-shot process lifecycle, cgroup evidence and final whole-run publication.
Every call requires a new persistent audit directory; failures are retained.
Only declared validation and fit-calibration rows are read; never test vectors.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

import numpy as np
import torch

from tools import run_v5_exports as legacy
from contracts import check_seal, json_bytes, load_json, require, seal, sha256
from models import freeze_for_export

SELF = Path(__file__).resolve()


def policy() -> dict:
    return {"schema": 1, "kind": "independent_export_scientific_replay",
            "freeze": "reconstruct original and frozen checkpoint; batch1; exact typed raw-diagnostic comparison",
            "qdq": "rebuild from accepted FP32 graph and frozen fit rows; exact whole ONNX file bytes",
            "limitation": "identical graph bytes do not prove an unobserved historical API invocation; no all-integer or NPU claim",
            "scientific_policy": legacy.fixed_export_protocol(),
            "no_test_vectors": True, "automatic_retry": False}


def _fresh_audit(path: Path, forbidden: list[Path]) -> Path:
    path = Path(path).absolute()
    require(path == path.resolve() and not path.exists() and not path.is_symlink(),
            "Scientific replay requires a fresh canonical audit directory")
    for other in forbidden:
        other = Path(other).resolve()
        require(path != other and path not in other.parents and other not in path.parents,
                "Scientific replay audit must not overlap original scientific inputs/output")
    path.mkdir(parents=True, exist_ok=False)
    return path


def _write_new(path: Path, value: dict) -> None:
    with path.open("xb") as stream:
        stream.write(json_bytes(seal(value)) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _written_binding(path: Path, expected: dict) -> dict:
    binding = legacy._binding(path)
    require(json_bytes(load_json(path)) == json_bytes(seal(expected)), "Written scientific replay record differs")
    legacy._check_binding(binding, rehash=False)
    return binding


def _check_inputs(bindings: list[dict]) -> None:
    for binding in bindings:
        legacy._check_binding(binding, rehash=True)
    # Close the full hashing window with cheap inode/ctime/stat bookends.
    for binding in bindings:
        legacy._check_binding(binding, rehash=False)


def validate_attempt(*, audit_dir: Path, **kwargs) -> dict:
    """Preserve legacy acceptance fields, then strengthen freeze/recipe evidence.

    `kwargs` is the unchanged legacy validate_attempt keyword contract. A scoped
    external-registration adapter may replace legacy.load_export_plan; this
    function does not assume or rewrite where registration evidence is stored.
    """
    run, output = Path(kwargs["run_dir"]).resolve(), Path(kwargs["output_dir"]).resolve()
    neural, dataset, arm, mode = (kwargs[key] for key in ("plan", "dataset", "model", "mode"))
    job = next(job for job in neural["jobs"] if job["dataset"] == dataset and job["model"] == arm)
    cache = Path(job["cache"]).resolve()
    audit = _fresh_audit(audit_dir, [run, output, cache])
    stage = "legacy_independent_validation"
    try:
        require(type(kwargs["validation_samples"]) is int and kwargs["validation_samples"] == 1024 and
                type(kwargs["calibration_samples"]) is int and kwargs["calibration_samples"] == 1000 and
                type(kwargs["int8_max_disagreement"]) is float and kwargs["int8_max_disagreement"] == 0.01 and
                mode in ("fp32", "qdq"), "Scientific replay policy differs from the frozen protocol")
        paths = [SELF, output / "export_report.json", output / "export_policy.json",
                 output / "model_fp32.onnx", output / "validation_vectors.npz",
                 output / "calibration_rows.json", output / "preprocessing.json", cache / "metadata.json",
                 cache / "x_fit.npy", cache / "ids_fit.npy", cache / "x_validation.npy",
                 cache / "ids_validation.npy", run / "results" / f"{job['id']}.json",
                 run / "results" / job["id"] / "runs" / f"{arm}_seed_0.pt"]
        if mode == "qdq": paths.append(output / "model_qdq_int8.onnx")
        bindings = [legacy._binding(path) for path in paths]
        input_by_path = {value["path"]: value for value in bindings}
        audit_bindings = []
        accepted = legacy.validate_attempt(**kwargs)
        export_plan = legacy.load_export_plan(output.parents[2], neural, rehash=False)
        require(json_bytes(export_plan["protocol"]) == json_bytes(legacy.fixed_export_protocol()),
                "Scientific replay received a changed fixed export policy")
        selection = legacy._row_selection(job)
        require(json_bytes(selection) == json_bytes(export_plan["datasets"][dataset]["selection"]),
                "Independent scientific replay rows differ from frozen plan")
        report = load_json(output / "export_report.json"); check_seal(report)
        raw_policy = load_json(output / "export_policy.json"); check_seal(raw_policy)
        require(json_bytes(raw_policy.get("qdq_recipe")) == json_bytes(export_plan["protocol"]["qdq_recipe"]),
                "Scientific replay quantization policy differs")
        stage = "freeze_replay"
        result = legacy.load_fit(run / "results" / f"{job['id']}.json", job, neural)
        checkpoint = run / "results" / job["id"] / "runs" / f"{arm}_seed_0.pt"
        state = legacy.load_checkpoint(checkpoint, result["fingerprint"])
        metadata = load_json(cache / "metadata.json"); check_seal(metadata)
        protocol = result["protocol"]
        model = legacy.build(arm, len(metadata["features"]), len(metadata["class_names"]),
                             protocol["hidden"], protocol["levels"], protocol["qcfs_formula"])
        model.load_state_dict(state["best_model"], strict=True)
        model.eval()
        require(legacy.tree_digest(model.state_dict()) == state["fit_result"]["best_state_sha256"] ==
                raw_policy["best_model_sha256"], "Replayed freeze model is not the selected checkpoint")
        x = np.load(cache / "x_validation.npy", mmap_mode="r", allow_pickle=False)
        vectors = np.asarray(x[selection["validation"]["indices"]], dtype=np.float32)
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True, warn_only=False)
        torch.set_float32_matmul_precision("highest")
        frozen = freeze_for_export(model, fold_bn=True)
        with torch.inference_mode():
            original_logits = np.concatenate([model(torch.from_numpy(row[None])).numpy() for row in vectors])
            frozen_logits = np.concatenate([frozen(torch.from_numpy(row[None])).numpy() for row in vectors])
        freeze_check = {**legacy.compare_logits(original_logits, frozen_logits, 1e-6, 1e-5),
                        "scope": "only these validation vectors, not every possible input"}
        require(freeze_check["allclose"] is True and freeze_check["prediction_disagreement_fraction"] == 0.0,
                "Independent checkpoint freezing numerical gate failed")
        require(json_bytes(report.get("freeze_check")) == json_bytes(freeze_check),
                "Raw freeze diagnostic differs from independent numerical replay")
        freeze_record = {
            "schema": 1, "kind": "independent_checkpoint_freeze_replay", "passed": True,
            "export_plan_sha256": export_plan["content_sha256"], "dataset": dataset, "model": arm,
            "mode": mode, "checkpoint_sha256": sha256(checkpoint), "check": freeze_check,
            "original_logits_sha256": legacy.array_sha256(original_logits),
            "frozen_logits_sha256": legacy.array_sha256(frozen_logits),
            "validation_selection": selection["validation"]}
        _write_new(audit / "freeze_replay.json", freeze_record)
        audit_bindings.append(_written_binding(audit / "freeze_replay.json", freeze_record))

        replay = None
        if mode == "qdq":
            stage = "qdq_recipe_replay"
            from onnxruntime.quantization import (CalibrationDataReader, CalibrationMethod,
                                                  QuantFormat, QuantType, quantize_static)
            fit = np.load(cache / "x_fit.npy", mmap_mode="r", allow_pickle=False)
            indices = selection["fit"]["indices"]
            class Reader(CalibrationDataReader):
                def __init__(self): self.position = 0
                def get_next(self):
                    if self.position == len(indices): return None
                    index = indices[self.position]
                    self.position += 1
                    return {"input": np.asarray(fit[index:index + 1], dtype=np.float32)}
            rebuilt, log = audit / "model_qdq_rebuilt.onnx", audit / "qdq_recipe_replay.log"
            with log.open("x", encoding="utf-8") as stream:
                try:
                    stream.write(json.dumps({"stage": stage, "recipe": export_plan["protocol"]["qdq_recipe"],
                                             "calibration_rows": len(indices)}, sort_keys=True) + "\n")
                    stream.flush()
                    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                        quantize_static(str(output / "model_fp32.onnx"), str(rebuilt), Reader(),
                                        quant_format=QuantFormat.QDQ, activation_type=QuantType.QInt8,
                                        weight_type=QuantType.QInt8, per_channel=True, reduce_range=False,
                                        calibrate_method=CalibrationMethod.MinMax,
                                        op_types_to_quantize=["Gemm", "MatMul", "Conv"],
                                        nodes_to_quantize=[], nodes_to_exclude=[], use_external_data_format=False,
                                        calibration_providers=["CPUExecutionProvider"], extra_options={})
                    stream.write(json.dumps({"rebuilt_sha256": sha256(rebuilt), "quantizer_returned": True}) + "\n")
                finally:
                    stream.flush()
                    os.fsync(stream.fileno())
            rebuilt_binding, log_binding = legacy._binding(rebuilt), legacy._binding(log)
            audit_bindings.extend((rebuilt_binding, log_binding))
            require(rebuilt_binding["sha256"] == input_by_path[str(output / "model_qdq_int8.onnx")]["sha256"],
                    "QDQ graph bytes differ from independent fixed-recipe reconstruction")
            replay = {"kind": "independent_exact_qdq_recipe_replay", "passed": True,
                      "equality": "exact entire ONNX protobuf file bytes; no canonicalization or tolerance",
                      "fp32_graph_sha256": input_by_path[str(output / "model_fp32.onnx")]["sha256"],
                      "graph_sha256": rebuilt_binding["sha256"], "graph": str(rebuilt),
                      "log": str(log), "log_sha256": log_binding["sha256"],
                      "fit_selection": selection["fit"], "recipe": export_plan["protocol"]["qdq_recipe"]}
            _write_new(audit / "qdq_recipe_replay.json", replay)
            audit_bindings.append(_written_binding(audit / "qdq_recipe_replay.json", replay))
        stage = "input_closure"
        _check_inputs([*bindings, *audit_bindings])
        expected_artifacts = {"freeze_replay.json"}
        if mode == "qdq":
            expected_artifacts.update({"model_qdq_rebuilt.onnx", "qdq_recipe_replay.log", "qdq_recipe_replay.json"})
        require({path.name for path in audit.iterdir()} == expected_artifacts,
                "Scientific replay audit inventory differs")
        artifacts = {Path(item["path"]).name: item["sha256"] for item in audit_bindings}
        supplemental = {"schema": 1, "kind": "independent_export_scientific_replay",
                        "passed": True, "source_sha256": input_by_path[str(SELF)]["sha256"], "policy": policy(),
                        "source_plan_sha256": neural["content_sha256"],
                        "export_plan_sha256": export_plan["content_sha256"],
                        "dataset": dataset, "model": arm, "mode": mode,
                        "freeze_check": freeze_check, "qdq_recipe_replay": replay,
                        "inputs": bindings, "files_sha256": artifacts}
        _write_new(audit / "scientific_validation.json", supplemental)
        final_report = _written_binding(audit / "scientific_validation.json", supplemental)
        require({path.name for path in audit.iterdir()} == expected_artifacts | {"scientific_validation.json"},
                "Scientific replay final inventory differs")
        for item in [*bindings, *audit_bindings, final_report]:
            legacy._check_binding(item, rehash=False)
        return {**accepted, "independent_freeze_check": freeze_check,
                "independent_qdq_recipe_replay": replay,
                "scientific_adapter": {"source_sha256": input_by_path[str(SELF)]["sha256"], "audit_dir": str(audit),
                                       "report": str(audit / "scientific_validation.json"),
                                       "report_sha256": final_report["sha256"],
                                       "files_sha256": {**artifacts, "scientific_validation.json":
                                                        final_report["sha256"]}}}
    except BaseException as exc:
        _write_new(audit / "FAILED.json", {"schema": 1, "kind": "independent_export_scientific_replay_failure",
                   "passed": False, "stage": stage, "dataset": dataset, "model": arm, "mode": mode,
                   "error": f"{type(exc).__name__}: {exc}", "automatic_retry": False})
        raise
