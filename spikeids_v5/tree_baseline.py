"""Leakage-safe RF/XGBoost baselines with an independent-fit test barrier.

The fixed paper baselines are evaluated only on NSL-KDD and UNSW-NB15, using
the same immutable v5 fit/validation/test caches as the neural models. Random
Forest has stochastic seeds; the declared XGBoost configuration has no row or
column subsampling and is therefore reported as one deterministic fit rather
than fake multi-seed uncertainty.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import secrets
import string
import tempfile
import time

import joblib
import numpy as np
import onnx
import onnxruntime as ort
import sklearn
from sklearn.ensemble import RandomForestClassifier
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType
import xgboost
from xgboost import XGBClassifier

from contracts import (SCHEMA, check_seal, digest, file_lock, load_json, require,
                       seal, sha256, sources, write_json)
from data_loaders import open_cache, open_fit_cache
from evidence import read_plan
from experiment_all import array_sha256
import metrics as metrics_module


PACKAGE = Path(__file__).resolve().parent
DATASETS = ("nslkdd", "unsw")
KINDS = ("random_forest", "xgboost")
DATA_ACCEPTANCE_CHECKS = {
    "inventory_complete", "seals_valid", "code_binding_valid", "shapes_valid",
    "dtypes_valid", "finite_values", "canonical_zero", "id_accounting_exact",
    "class_support_complete", "multiplicity_valid", "exclusion_reasons_valid",
    "zero_group_overlap", "zero_final_fp32_overlap",
    "raw_model_view_fingerprint_valid", "frozen_partition_and_closure_replayed", "all_passed",
}
DATA_ACCEPTANCE_LIMITATIONS = {
    "capture_generalization_established", "device_generalization_established",
    "time_generalization_established", "upstream_preprocessing_verified",
    "external_authenticity_verified",
}


def _sealed_file(path: Path, label: str) -> tuple[Path, dict, str]:
    absolute = Path(path).absolute()
    require(absolute.resolve() == absolute and absolute.is_file() and
            not absolute.is_symlink() and absolute.stat().st_nlink == 1,
            f"{label} must be a canonical regular unaliased file")
    record = load_json(absolute); check_seal(record)
    return absolute, record, sha256(absolute)


def _cache_contract(dataset: str, cache: Path, metadata: dict,
                    acceptance: dict) -> dict:
    require(metadata.get("dataset") == dataset,
            f"Selected tree cache contains the wrong dataset: {dataset}")
    accepted = acceptance.get("datasets", {}).get(dataset)
    require(isinstance(accepted, dict) and
            accepted.get("byte_identical_rebuilds") is True and
            set(accepted.get("semantic_checks", {})) == DATA_ACCEPTANCE_CHECKS and
            all(value is True for value in accepted["semantic_checks"].values()),
            f"Accepted semantic checks are incomplete: {dataset}")
    require(accepted.get("data_fingerprint") == metadata.get("data_fingerprint") and
            accepted.get("raw_rows") == metadata.get("raw_rows") and
            accepted.get("counts") == metadata.get("counts") and
            accepted.get("features") == metadata.get("features") and
            accepted.get("class_names") == metadata.get("class_names") and
            accepted.get("raw_model_view_sha256") ==
            metadata.get("raw_model_view_sha256"),
            f"Accepted data semantics differ from selected tree cache: {dataset}")
    rebuilds = accepted.get("rebuilds", [])
    require(isinstance(rebuilds, list) and len(rebuilds) == 2 and
            len({row.get("resolved_root") for row in rebuilds
                 if isinstance(row, dict)}) == 2,
            f"Accepted rebuild inventory is malformed: {dataset}")
    matches = [row for row in rebuilds
               if row.get("resolved_root") == str(cache)]
    require(len(matches) == 1 and
            matches[0].get("metadata_sha256") == sha256(cache / "metadata.json") and
            matches[0].get("data_fingerprint") == metadata.get("data_fingerprint") and
            matches[0].get("files_sha256") == metadata.get("files_sha256"),
            f"Selected tree cache is not an exact accepted rebuild: {dataset}")
    return {
        "cache": str(cache),
        "metadata_sha256": sha256(cache / "metadata.json"),
        "files_sha256": metadata["files_sha256"],
        "data_fingerprint": metadata["data_fingerprint"],
        "raw_rows": metadata["raw_rows"],
        "counts": metadata["counts"],
        "features": metadata["features"],
        "classes": metadata["class_names"],
        "raw_model_view_sha256": metadata["raw_model_view_sha256"],
    }


def _neural_data_contract(neural_run_dir: Path, cache_root: Path) -> tuple[dict, dict, dict]:
    neural_run_dir = Path(neural_run_dir).resolve()
    neural_plan_path = neural_run_dir / "plan.json"
    checked_plan_path, checked_plan, neural_plan_sha = _sealed_file(
        neural_plan_path, "Neural plan",
    )
    neural_plan = read_plan(neural_run_dir)
    require(neural_plan == checked_plan,
            "Neural plan changed while validating the tree contract")
    evidence = neural_plan.get("data_evidence")
    require(isinstance(evidence, dict) and
            set(evidence) == {"raw_audit", "data_acceptance", "independent_verifier",
                              "upstream_provenance", "accepted_cache_root"},
            "Formal tree baselines require the neural plan's accepted data evidence")
    acceptance_binding = evidence.get("data_acceptance")
    require(isinstance(acceptance_binding, dict) and
            set(acceptance_binding) == {"path", "sha256", "content_sha256"},
            "Neural plan data-acceptance binding is malformed")
    acceptance_path, acceptance, acceptance_sha = _sealed_file(
        Path(acceptance_binding["path"]), "Neural-plan data acceptance",
    )
    raw_binding = evidence.get("raw_audit")
    require(isinstance(raw_binding, dict) and
            set(raw_binding) == {"path", "sha256", "content_sha256"},
            "Neural plan raw-audit binding is malformed")
    raw_path, raw_audit, raw_sha = _sealed_file(
        Path(raw_binding["path"]), "Neural-plan raw audit",
    )
    verifier_binding = evidence.get("independent_verifier")
    require(isinstance(verifier_binding, dict) and
            set(verifier_binding) == {"path", "sha256"},
            "Neural plan data-verifier binding is malformed")
    verifier_path = Path(verifier_binding["path"])
    require(verifier_path.resolve() == verifier_path and verifier_path.is_file() and
            not verifier_path.is_symlink() and verifier_path.stat().st_nlink == 1 and
            verifier_path == (PACKAGE.parent / "tools" / "verify_v5_data.py").resolve() and
            verifier_binding["sha256"] == sha256(verifier_path),
            "Neural plan data verifier changed")
    require(acceptance_binding == {
                "path": str(acceptance_path), "sha256": acceptance_sha,
                "content_sha256": acceptance["content_sha256"],
            } and acceptance.get("kind") == "spikeids_v5_data_acceptance" and
            acceptance.get("acceptance_schema") == 1 and
            acceptance.get("data_acceptance_passed") is True and
            acceptance.get("two_distinct_fresh_roots") is True and
            acceptance.get("byte_identical_rebuilds") is True and
            set(acceptance.get("datasets", {})) ==
            {"nslkdd", "unsw", "cicids2017", "iot23"} and
            set(acceptance.get("limitations", {})) == DATA_ACCEPTANCE_LIMITATIONS and
            all(value is False for value in acceptance["limitations"].values()),
            "Neural plan data acceptance is stale, incomplete, or overclaimed")
    accepted_raw = acceptance.get("raw_audit", {})
    require(raw_binding == {
                "path": str(raw_path), "sha256": raw_sha,
                "content_sha256": raw_audit["content_sha256"],
            } and accepted_raw.get("path") == str(raw_path) and
            accepted_raw.get("sha256") == raw_sha and
            accepted_raw.get("content_sha256") == raw_audit["content_sha256"] and
            accepted_raw.get("audit_implementation_sha256") ==
            raw_audit.get("audit_implementation_sha256") and
            accepted_raw.get("raw_source_audit_passed") is True and
            raw_audit.get("raw_source_audit_passed") is True and
            raw_audit.get("data_acceptance_passed") is False and
            raw_audit.get("audit_implementation_sha256") ==
            sha256(PACKAGE / "audit_data.py") and
            raw_audit.get("data_loader_sha256") ==
            sha256(PACKAGE / "data_loaders.py") and
            acceptance.get("producer") == {
                "path": str((PACKAGE / "data_loaders.py").resolve()),
                "sha256": sha256(PACKAGE / "data_loaders.py"),
            } and acceptance.get("independent_verifier") == verifier_binding,
            "Neural plan/raw audit/data acceptance/verifier binding differs")
    upstream_binding = evidence.get("upstream_provenance")
    require(isinstance(upstream_binding, dict) and
            set(upstream_binding) == {
                "path", "sha256", "content_sha256", "comparison_passed",
            }, "Neural plan upstream-provenance binding is malformed")
    upstream_path, upstream, upstream_sha = _sealed_file(
        Path(upstream_binding["path"]), "Neural-plan IoT provenance",
    )
    require(upstream_binding == {
                "path": str(upstream_path), "sha256": upstream_sha,
                "content_sha256": upstream["content_sha256"],
                "comparison_passed": True,
            } and acceptance.get("upstream_provenance") == upstream_binding and
            upstream.get("comparison_passed") is True,
            "Neural plan/data acceptance IoT provenance binding differs")
    cache_root = Path(cache_root).resolve()
    require(evidence.get("accepted_cache_root") == str(cache_root),
            "Tree cache root differs from the neural plan's accepted cache root")
    datasets = {}
    for dataset in DATASETS:
        jobs = [job for job in neural_plan["jobs"] if job.get("dataset") == dataset]
        require(jobs and len({job.get("cache") for job in jobs}) == 1 and
                len({job.get("data_fingerprint") for job in jobs}) == 1,
                f"Neural plan cache identity is ambiguous: {dataset}")
        cache = (cache_root / dataset).resolve()
        require(jobs[0]["cache"] == str(cache),
                f"Tree cache differs from the neural plan cache: {dataset}")
        metadata, _arrays = open_fit_cache(cache)
        require(jobs[0]["data_fingerprint"] == metadata.get("data_fingerprint"),
                f"Tree cache fingerprint differs from neural plan: {dataset}")
        datasets[dataset] = _cache_contract(dataset, cache, metadata, acceptance)
    neural_binding = {
        "path": str(checked_plan_path),
        "sha256": neural_plan_sha,
        "content_sha256": neural_plan["content_sha256"],
    }
    return neural_binding, acceptance_binding, datasets


def _validate_plan_inputs(plan: dict, neural_run_dir: Path | None = None) -> None:
    binding = plan.get("neural_plan")
    require(isinstance(binding, dict) and
            set(binding) == {"path", "sha256", "content_sha256"},
            "Tree plan lacks an exact neural-plan binding")
    bound_plan = Path(binding["path"])
    bound_run = bound_plan.parent
    if neural_run_dir is not None:
        require(Path(neural_run_dir).resolve() == bound_run,
                "Requested neural run differs from the frozen tree plan")
    require(set(plan.get("datasets", {})) == set(DATASETS) and
            all(isinstance(row, dict) for row in plan["datasets"].values()),
            "Tree plan dataset inventory is incomplete")
    cache_parents = {str(Path(row["cache"]).resolve().parent)
                     for row in plan.get("datasets", {}).values()}
    require(len(cache_parents) == 1, "Tree datasets do not share one accepted cache root")
    neural_binding, acceptance_binding, datasets = _neural_data_contract(
        bound_run, Path(next(iter(cache_parents))),
    )
    require(binding == neural_binding and
            plan.get("data_acceptance") == acceptance_binding and
            plan.get("datasets") == datasets,
            "Tree plan/neural plan/data acceptance/cache cross-binding changed")


def _bytes_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _rf_semantic_digest(model: RandomForestClassifier) -> str:
    trees = []
    for estimator in model.estimators_:
        tree = estimator.tree_
        trees.append({name: array_sha256(np.asarray(getattr(tree, name))) for name in (
            "children_left", "children_right", "feature", "threshold", "value",
            "impurity", "n_node_samples", "weighted_n_node_samples")})
    return digest({
        "kind": "random_forest",
        "params": model.get_params(deep=False),
        "classes_sha256": array_sha256(np.asarray(model.classes_)),
        "n_features_in": int(model.n_features_in_),
        "trees": trees,
    })


def model_semantic_digest(kind: str, model) -> str:
    if kind == "random_forest":
        return _rf_semantic_digest(model)
    require(kind == "xgboost", f"Unknown tree kind: {kind}")
    return _bytes_sha256(bytes(model.get_booster().save_raw(raw_format="json")))


def make_estimator(kind: str, seed: int, threads: int, n_estimators: int):
    if kind == "random_forest":
        return RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=20,
            class_weight="balanced",
            random_state=seed,
            n_jobs=threads,
        )
    require(kind == "xgboost", f"Unknown tree kind: {kind}")
    return XGBClassifier(
        n_estimators=n_estimators,
        max_depth=6,
        learning_rate=0.1,
        random_state=seed,
        eval_metric="mlogloss",
        tree_method="hist",
        device="cpu",
        n_jobs=threads,
        subsample=1.0,
        colsample_bytree=1.0,
        verbosity=0,
    )


def _sample_weights(y: np.ndarray, classes: int) -> np.ndarray:
    counts = np.bincount(y, minlength=classes).astype(np.float64)
    require((counts > 0).all(), "Fit split lacks a declared class")
    weights = 1.0 / counts[y]
    return np.asarray(weights / weights.sum() * len(y), dtype=np.float64)


def _atomic_joblib(path: Path, model) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    os.close(fd)
    try:
        joblib.dump(model, name, compress=0, protocol=5)
        with open(name, "rb") as stream:
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _record_path(run_dir: Path, execution: str, dataset: str, kind: str, seed: int) -> Path:
    return run_dir / execution / dataset / kind / f"seed_{seed}.json"


def _artifact_path(record_path: Path) -> Path:
    return record_path.with_suffix(".joblib")


def _ledger_path(record_path: Path) -> Path:
    return record_path.with_suffix(".ledger.json")


def _write_once(path: Path, value: dict) -> None:
    if path.exists():
        require(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1,
                f"Immutable tree evidence is missing or aliased: {path}")
        existing = load_json(path); check_seal(existing)
        require(existing == value, f"Immutable tree evidence differs: {path}")
    else:
        write_json(path, value)


def _completed_run_guard(run_dir: Path, neural_run_dir: Path) -> bool:
    result_path = run_dir / "results.json"
    exposure_path = run_dir / "test_exposure.json"
    if not (result_path.exists() or exposure_path.exists()):
        return False
    require(result_path.exists() and exposure_path.exists(),
            "Tree test exposure/result ledger is partial; use a fresh run directory")
    load_verified_tree_suite(run_dir, neural_run_dir)
    return True


def _execution_ledger(path: Path, expected: dict, run_dir: Path,
                      *, create: bool) -> dict:
    ledger_path = _ledger_path(path)
    if create:
        require(not ledger_path.exists(),
                f"Tree execution ledger already exists and cannot be reset: {ledger_path}")
        identity = {
            "execution_id": secrets.token_hex(16),
            "execution": expected["execution"],
            "record_path": str(path.resolve()),
            "artifact_path": str(_artifact_path(path).resolve()),
        }
        ledger = seal({
            **expected,
            "ledger_kind": "tree_execution_ledger",
            "execution_identity": identity,
            "run_dir": str(run_dir.resolve()),
        })
        write_json(ledger_path, ledger)
        return ledger
    require(ledger_path.is_file() and not ledger_path.is_symlink() and
            ledger_path.stat().st_nlink == 1,
            f"Tree execution ledger is missing or aliased: {ledger_path}")
    ledger = load_json(ledger_path); check_seal(ledger)
    for key, value in expected.items():
        require(ledger.get(key) == value, f"Stale tree execution ledger {ledger_path}: {key}")
    require(ledger.get("ledger_kind") == "tree_execution_ledger" and
            ledger.get("run_dir") == str(run_dir.resolve()) and
            ledger.get("execution_identity") == {
                "execution_id": ledger.get("execution_identity", {}).get("execution_id"),
                "execution": expected["execution"],
                "record_path": str(path.resolve()),
                "artifact_path": str(_artifact_path(path).resolve()),
            } and isinstance(ledger["execution_identity"]["execution_id"], str) and
            len(ledger["execution_identity"]["execution_id"]) == 32 and
            set(ledger["execution_identity"]["execution_id"]) <= set(string.hexdigits),
            f"Tree execution ledger namespace differs: {ledger_path}")
    return ledger


def _load_fit_record(path: Path, expected: dict) -> tuple[dict, object]:
    run_dir = path.parents[3]
    ledger = _execution_ledger(path, expected, run_dir, create=False)
    require(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1,
            f"Tree fit record is missing or aliased: {path}")
    record = load_json(path); check_seal(record)
    for key, value in expected.items():
        require(record.get(key) == value, f"Stale tree fit record {path}: {key}")
    artifact = _artifact_path(path)
    require(record.get("artifact") == artifact.relative_to(run_dir).as_posix() and
            record.get("execution_identity") == ledger["execution_identity"] and
            record.get("execution_ledger_sha256") == sha256(_ledger_path(path)) and
            record.get("execution_ledger_content_sha256") == ledger["content_sha256"] and
            artifact.is_file() and not artifact.is_symlink() and
            artifact.stat().st_nlink == 1 and
            sha256(artifact) == record["artifact_sha256"],
            f"Missing/changed tree artifact: {artifact}")
    model = joblib.load(artifact)
    require(getattr(model, "spikeids_execution_identity_", None) ==
            ledger["execution_identity"] and
            getattr(model, "spikeids_plan_sha256_", None) == expected["plan_sha256"] and
            getattr(model, "spikeids_data_fingerprint_", None) ==
            expected["data_fingerprint"],
            f"Tree artifact belongs to another execution namespace: {artifact}")
    require(model_semantic_digest(record["kind"], model) == record["model_semantic_sha256"],
            f"Tree artifact semantic digest mismatch: {artifact}")
    return record, model


def fit_one(run_dir: Path, execution: str, dataset: str, kind: str, seed: int,
            x_fit, y_fit, classes: int, threads: int, n_estimators: int,
            plan_sha256: str, data_fingerprint: str) -> dict:
    path = _record_path(run_dir, execution, dataset, kind, seed)
    expected = {"schema": SCHEMA, "plan_sha256": plan_sha256, "execution": execution,
                "dataset": dataset, "kind": kind, "seed": seed,
                "data_fingerprint": data_fingerprint}
    artifact = _artifact_path(path)
    ledger_path = _ledger_path(path)
    existing = (path.exists(), artifact.exists(), ledger_path.exists())
    if any(existing):
        require(all(existing),
                f"Partial tree execution namespace cannot be reset/resumed: {path}")
        return _load_fit_record(path, expected)[0]
    ledger = _execution_ledger(path, expected, run_dir, create=True)
    started = time.perf_counter()
    model = make_estimator(kind, seed, threads, n_estimators)
    kwargs = {"sample_weight": _sample_weights(y_fit, classes)} if kind == "xgboost" else {}
    model.fit(x_fit, y_fit, **kwargs)
    require(np.array_equal(np.asarray(model.classes_), np.arange(classes)),
            "Tree probability columns do not match declared class IDs")
    semantic = model_semantic_digest(kind, model)
    model.spikeids_execution_identity_ = ledger["execution_identity"]
    model.spikeids_plan_sha256_ = plan_sha256
    model.spikeids_data_fingerprint_ = data_fingerprint
    _atomic_joblib(artifact, model)
    record = {**expected, "model_semantic_sha256": semantic,
              "execution_identity": ledger["execution_identity"],
              "execution_ledger_sha256": sha256(ledger_path),
              "execution_ledger_content_sha256": ledger["content_sha256"],
              "artifact": artifact.relative_to(run_dir).as_posix(),
              "artifact_sha256": sha256(artifact), "fit_rows": len(y_fit),
              "elapsed_seconds": time.perf_counter() - started}
    write_json(path, seal(record))
    print(f"fit {execution} {dataset} {kind} seed={seed} semantic={semantic}", flush=True)
    return record


def evaluate_one(run_dir: Path, execution: str, dataset: str, kind: str, seed: int,
                 x_test, y_test, class_names: list[str], plan_sha256: str,
                 data_fingerprint: str) -> dict:
    fit_path = _record_path(run_dir, execution, dataset, kind, seed)
    expected = {"schema": SCHEMA, "plan_sha256": plan_sha256, "execution": execution,
                "dataset": dataset, "kind": kind, "seed": seed,
                "data_fingerprint": data_fingerprint}
    fit, model = _load_fit_record(fit_path, expected)
    if kind == "random_forest":
        # Parallel prediction reduces per-tree probabilities in scheduler
        # order and can differ by one float64 ULP across otherwise identical
        # calls. Training remains parallel; evidence generation fixes the
        # reduction order without changing the fitted forest.
        model.n_jobs = 1
    prediction = np.asarray(model.predict(x_test), dtype=np.int64)
    probability = np.asarray(model.predict_proba(x_test))
    require(probability.dtype.kind == "f", "Tree predict_proba must return floating probabilities")
    metrics = metrics_module.full_evaluate(y_test, prediction, probability, len(class_names), class_names)
    metrics["seed"] = seed
    return {"fit_semantic_sha256": fit["model_semantic_sha256"],
            "prediction_sha256": array_sha256(prediction),
            "probability_sha256": array_sha256(probability),
            "labels_sha256": array_sha256(np.asarray(y_test)),
            "metrics_sha256": digest(metrics), "metrics": metrics}


def export_rf_onnx(run_dir: Path, dataset: str, cache: Path, plan: dict) -> dict:
    seed = plan["deployment_seed"]
    path = _record_path(run_dir, "primary", dataset, "random_forest", seed)
    expected = {"schema": SCHEMA, "plan_sha256": plan["content_sha256"], "execution": "primary",
                "dataset": dataset, "kind": "random_forest", "seed": seed,
                "data_fingerprint": plan["datasets"][dataset]["data_fingerprint"]}
    fit, model = _load_fit_record(path, expected)
    meta, arrays = open_cache(cache)
    frozen = plan["datasets"][dataset]
    require(meta.get("dataset") == dataset and
            frozen["cache"] == str(cache.resolve()) and
            frozen["metadata_sha256"] == sha256(cache / "metadata.json") and
            frozen["files_sha256"] == meta.get("files_sha256") and
            frozen["data_fingerprint"] == meta.get("data_fingerprint"),
            f"RF export cache differs from frozen neural/tree binding: {dataset}")
    width = len(meta["features"])
    graph = convert_sklearn(model, initial_types=[("float_input", FloatTensorType([None, width]))],
                            target_opset=17, options={id(model): {"zipmap": False}})
    output = run_dir / "onnx" / f"rf_{dataset}_seed_{seed}.onnx"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(graph.SerializeToString())
    checked = onnx.load(output); onnx.checker.check_model(checked)
    operators = sorted({node.op_type for node in checked.graph.node})
    require("TreeEnsembleClassifier" in operators, "RF ONNX lacks TreeEnsembleClassifier")
    count = min(4096, len(arrays["x_validation"]))
    x = np.asarray(arrays["x_validation"][:count], dtype=np.float32)
    expected_labels = np.asarray(model.predict(x), dtype=np.int64)
    expected_prob = np.asarray(model.predict_proba(x))
    session = ort.InferenceSession(str(output), providers=["CPUExecutionProvider"])
    actual_labels, actual_prob = session.run(None, {session.get_inputs()[0].name: x})
    actual_labels, actual_prob = np.asarray(actual_labels, dtype=np.int64), np.asarray(actual_prob)
    maximum = float(np.max(np.abs(expected_prob - actual_prob)))
    tolerance = plan["rf_onnx_probability_atol"]
    require(np.array_equal(expected_labels, actual_labels), f"RF ONNX label mismatch for {dataset}")
    require(maximum <= tolerance, f"RF ONNX probability drift {maximum} > {tolerance}")
    return {"dataset": dataset, "seed": seed, "fit_semantic_sha256": fit["model_semantic_sha256"],
            "onnx": output.relative_to(run_dir).as_posix(), "onnx_sha256": sha256(output),
            "operators": operators, "validation_rows": count,
            "labels_equal": True, "probability_max_abs_error": maximum,
            "probability_atol": tolerance}


def _current_plan(cache_root: Path, neural_run_dir: Path, seeds: list[int],
                  threads: int, n_estimators: int) -> dict:
    neural_binding, acceptance_binding, datasets = _neural_data_contract(
        neural_run_dir, cache_root,
    )
    plan = {"schema": SCHEMA, "kind": "tree_baseline_plan", "sources": sources(),
            "neural_plan": neural_binding, "data_acceptance": acceptance_binding,
            "datasets": datasets, "random_forest_seeds": seeds, "xgboost_seeds": [0],
            "deployment_seed": 0, "threads": threads,
            "hyperparameters": {
                "random_forest": {"n_estimators": n_estimators, "max_depth": 20,
                                  "class_weight": "balanced"},
                "xgboost": {"n_estimators": n_estimators, "max_depth": 6, "learning_rate": 0.1,
                             "tree_method": "hist", "subsample": 1.0, "colsample_bytree": 1.0,
                             "sample_weight": "inverse fit-class frequency"}},
            "xgboost_replication_note": "No stochastic subsampling: one seed is reported, not fake repeated zero variance.",
            "selection": "fixed hyperparameters; validation and test are not used for selection",
            "test_barrier": "all primary/replica semantic model digests must match before any test prediction",
            "rf_onnx_probability_atol": 1e-5,
            "versions": {"numpy": np.__version__, "sklearn": sklearn.__version__,
                         "xgboost": xgboost.__version__, "onnx": onnx.__version__,
                         "onnxruntime": ort.__version__}}
    return seal(plan)


def load_verified_tree_suite(run_dir: Path,
                             neural_run_dir: Path | None = None) -> tuple[dict,dict]:
    run_dir=Path(run_dir).resolve()
    _plan_path, plan, _plan_file_sha = _sealed_file(run_dir/'plan.json', 'Tree plan')
    require(plan['kind']=='tree_baseline_plan' and plan['sources']==sources(),
            'Tree baseline source changed after its plan was frozen')
    _validate_plan_inputs(plan, neural_run_dir)
    _verification_path, verification, _verification_file_sha = _sealed_file(
        run_dir/'verification_fit.json', 'Tree fit verification',
    )
    require(verification['passed'] and verification['plan_sha256']==plan['content_sha256'],
            'Tree fit verification is missing or stale')
    require(set(verification.get('models', {})) == set(DATASETS) and
            all(set(verification['models'][dataset]) == set(KINDS)
                for dataset in DATASETS),
            'Tree fit verification model inventory is incomplete')
    execution_ids = set()
    for dataset in DATASETS:
        for kind in KINDS:
            seeds=plan['random_forest_seeds'] if kind=='random_forest' else plan['xgboost_seeds']
            require(set(verification['models'][dataset][kind]) ==
                    {str(seed) for seed in seeds},
                    f'Tree fit verification seed inventory is incomplete: {dataset}/{kind}')
            for seed in seeds:
                expected={"schema":SCHEMA,"plan_sha256":plan['content_sha256'],"dataset":dataset,
                          "kind":kind,"seed":seed,"data_fingerprint":plan['datasets'][dataset]['data_fingerprint']}
                records=[]
                for execution in ('primary','replica'):
                    record,_=_load_fit_record(_record_path(run_dir,execution,dataset,kind,seed),
                                              {**expected,'execution':execution})
                    identity = record['execution_identity']['execution_id']
                    require(identity not in execution_ids,
                            'Tree primary/replica reused an execution namespace')
                    execution_ids.add(identity)
                    records.append(record)
                want=verification['models'][dataset][kind][str(seed)]
                require(records[0]['model_semantic_sha256']==records[1]['model_semantic_sha256']==want,
                        f'Tree verification digest is stale: {dataset}/{kind}/seed={seed}')
                require(records[0]['artifact_sha256'] != records[1]['artifact_sha256'] and
                        records[0]['content_sha256'] != records[1]['content_sha256'],
                        f'Tree replica is a copied primary namespace: {dataset}/{kind}/seed={seed}')
    require(verification.get('execution_ids') == sorted(execution_ids),
            'Tree fit verification execution namespace inventory is stale')
    _report_path, report, _report_file_sha = _sealed_file(
        run_dir/'results.json', 'Tree results',
    )
    require(report['plan_sha256']==plan['content_sha256'] and
            report['verification_fit_sha256']==sha256(run_dir/'verification_fit.json') and
            report['test_evaluated_after_global_fit_barrier'] is True and
            report.get('neural_plan') == plan['neural_plan'] and
            report.get('data_acceptance') == plan['data_acceptance'] and
            set(report.get('results', {})) == set(DATASETS) and
            all(set(report['results'][dataset]) == set(KINDS)
                for dataset in DATASETS),
            'Tree result report is missing its global test barrier binding')
    _exposure_path, exposure, _exposure_file_sha = _sealed_file(
        run_dir/'test_exposure.json', 'Tree test-exposure ledger',
    )
    require(exposure.get('kind') == 'tree_test_exposure_ledger' and
            exposure.get('plan_sha256') == plan['content_sha256'] and
            exposure.get('status') == 'complete' and
            exposure.get('test_sessions_started') == 1 and
            exposure.get('test_sessions_completed') == 1 and
            exposure.get('results_sha256') == sha256(run_dir/'results.json') and
            report.get('test_exposure') == {
                'session_id': exposure.get('session_id'),
                'opened_content_sha256': exposure.get('opened_content_sha256'),
            }, 'Tree test-exposure ledger is missing, reset, or stale')
    require(isinstance(report.get('rf_onnx'), list) and
            len(report['rf_onnx']) == len(DATASETS) and
            {row.get('dataset') for row in report['rf_onnx']
             if isinstance(row, dict)} == set(DATASETS),
            'Tree RF ONNX inventory is incomplete')
    for dataset in DATASETS:
        classes=plan['datasets'][dataset]['classes']
        for kind in KINDS:
            rows=report['results'][dataset][kind]['per_seed']
            require(report['results'][dataset][kind]['aggregate']==metrics_module.aggregate(rows,classes),
                    f'Stale tree aggregate: {dataset}/{kind}')
        onnx_record=next((row for row in report['rf_onnx'] if row['dataset']==dataset),None)
        require(onnx_record is not None and onnx_record['labels_equal'] and
                onnx_record['probability_max_abs_error']<=onnx_record['probability_atol'],
                f'RF ONNX parity missing/failed: {dataset}')
        graph=run_dir/onnx_record['onnx']
        require(graph.is_file() and sha256(graph)==onnx_record['onnx_sha256'] and
                'TreeEnsembleClassifier' in onnx_record['operators'],
                f'RF ONNX artifact changed: {dataset}')
    return plan,report


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--neural-run-dir", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--seeds", nargs="+", type=int, default=list(range(20)))
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument("--n-estimators", type=int, default=100)
    return parser


def main() -> None:
    args = parser().parse_args()
    require(args.seeds and len(args.seeds) == len(set(args.seeds)) and
            all(0 <= seed < 2**32 for seed in args.seeds), "Unique uint32 RF seeds required")
    require(1 <= args.threads <= 64 and args.n_estimators >= 1, "Invalid tree resource/model budget")
    seeds = sorted(args.seeds)
    cache_root, run_dir = args.cache_root.resolve(), args.run_dir.resolve()
    neural_run_dir = args.neural_run_dir.resolve()
    current = _current_plan(
        cache_root, neural_run_dir, seeds, args.threads, args.n_estimators,
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    with file_lock(run_dir / "pipeline.lock"):
        plan_path = run_dir / "plan.json"
        if plan_path.exists():
            plan = load_json(plan_path); check_seal(plan)
            require(plan == current, "Tree baseline plan/source/environment changed; use a fresh run directory")
        else:
            plan = current; write_json(plan_path, plan)
        _validate_plan_inputs(plan, neural_run_dir)
        result_path = run_dir / "results.json"
        exposure_path = run_dir / "test_exposure.json"
        if _completed_run_guard(run_dir, neural_run_dir):
            print(f"TREE BASELINES ALREADY COMPLETE {result_path}", flush=True)
            return
        caches = {}
        for dataset in DATASETS:
            meta, arrays = open_fit_cache(Path(plan["datasets"][dataset]["cache"]))
            require(meta.get("dataset") == dataset and
                    meta.get("data_fingerprint") ==
                    plan["datasets"][dataset]["data_fingerprint"] and
                    sha256(Path(plan["datasets"][dataset]["cache"]) / "metadata.json") ==
                    plan["datasets"][dataset]["metadata_sha256"] and
                    meta.get("files_sha256") == plan["datasets"][dataset]["files_sha256"],
                    f"Fit-only cache differs from frozen tree/neural plan: {dataset}")
            caches[dataset] = (meta, arrays)
            x_fit, y_fit = arrays["x_fit"], np.asarray(arrays["y_fit"])
            for kind in KINDS:
                kind_seeds = seeds if kind == "random_forest" else [0]
                for execution in ("primary", "replica"):
                    for seed in kind_seeds:
                        fit_one(run_dir, execution, dataset, kind, seed, x_fit, y_fit,
                                len(meta["class_names"]), args.threads, args.n_estimators,
                                plan["content_sha256"], meta["data_fingerprint"])
        verified = {}
        execution_ids = set()
        for dataset in DATASETS:
            meta = caches[dataset][0]
            verified[dataset] = {}
            for kind in KINDS:
                kind_seeds = seeds if kind == "random_forest" else [0]
                verified[dataset][kind] = {}
                for seed in kind_seeds:
                    base = {"schema": SCHEMA, "plan_sha256": plan["content_sha256"],
                            "dataset": dataset, "kind": kind, "seed": seed,
                            "data_fingerprint": meta["data_fingerprint"]}
                    a, _ = _load_fit_record(
                        _record_path(run_dir,"primary",dataset,kind,seed),
                        {**base, "execution": "primary"},
                    )
                    b, _ = _load_fit_record(
                        _record_path(run_dir,"replica",dataset,kind,seed),
                        {**base, "execution": "replica"},
                    )
                    require(a["model_semantic_sha256"] == b["model_semantic_sha256"],
                            f"Independent tree fits differ: {dataset}/{kind}/seed={seed}")
                    identities = [a["execution_identity"]["execution_id"],
                                  b["execution_identity"]["execution_id"]]
                    require(identities[0] != identities[1] and
                            not execution_ids.intersection(identities) and
                            a["artifact_sha256"] != b["artifact_sha256"] and
                            a["content_sha256"] != b["content_sha256"],
                            f"Tree replica reused/copied an execution namespace: "
                            f"{dataset}/{kind}/seed={seed}")
                    execution_ids.update(identities)
                    verified[dataset][kind][str(seed)] = a["model_semantic_sha256"]
        verification = seal({"schema": SCHEMA, "plan_sha256": plan["content_sha256"],
                             "passed": True, "models": verified,
                             "execution_ids": sorted(execution_ids)})
        _write_once(run_dir / "verification_fit.json", verification)
        del caches
        opened_exposure = seal({
            "schema": SCHEMA,
            "kind": "tree_test_exposure_ledger",
            "plan_sha256": plan["content_sha256"],
            "session_id": secrets.token_hex(16),
            "status": "opened",
            "test_sessions_started": 1,
            "test_sessions_completed": 0,
        })
        require(not exposure_path.exists(),
                "Tree test exposure has already started; use a fresh run directory")
        write_json(exposure_path, opened_exposure)
        test_caches = {}
        for dataset in DATASETS:
            cache = Path(plan["datasets"][dataset]["cache"])
            meta, arrays = open_cache(cache)
            require(meta.get("dataset") == dataset and
                    meta.get("data_fingerprint") ==
                    plan["datasets"][dataset]["data_fingerprint"] and
                    sha256(cache / "metadata.json") ==
                    plan["datasets"][dataset]["metadata_sha256"] and
                    meta.get("files_sha256") == plan["datasets"][dataset]["files_sha256"],
                    f"Test cache differs from frozen tree/neural plan: {dataset}")
            test_caches[dataset] = (meta, arrays)
        results = {}
        for dataset in DATASETS:
            meta, arrays = test_caches[dataset]
            results[dataset] = {}
            for kind in KINDS:
                rows = []
                kind_seeds = seeds if kind == "random_forest" else [0]
                for seed in kind_seeds:
                    primary = evaluate_one(run_dir,"primary",dataset,kind,seed,arrays["x_test"],
                                           np.asarray(arrays["y_test"]),meta["class_names"],
                                           plan["content_sha256"],meta["data_fingerprint"])
                    replica = evaluate_one(run_dir,"replica",dataset,kind,seed,arrays["x_test"],
                                           np.asarray(arrays["y_test"]),meta["class_names"],
                                           plan["content_sha256"],meta["data_fingerprint"])
                    require({k:primary[k] for k in ("prediction_sha256","probability_sha256","metrics_sha256")} ==
                            {k:replica[k] for k in ("prediction_sha256","probability_sha256","metrics_sha256")},
                            f"Independent tree test evidence differs: {dataset}/{kind}/seed={seed}")
                    rows.append(primary["metrics"])
                results[dataset][kind] = {"per_seed": rows,
                    "aggregate": metrics_module.aggregate(rows, meta["class_names"]),
                    "n_unique_model_digests": len(set(verified[dataset][kind].values()))}
        onnx_reports = [export_rf_onnx(run_dir,dataset,Path(plan["datasets"][dataset]["cache"]),plan)
                        for dataset in DATASETS]
        report = seal({"schema": SCHEMA, "plan_sha256": plan["content_sha256"],
                       "verification_fit_sha256": sha256(run_dir/"verification_fit.json"),
                       "test_evaluated_after_global_fit_barrier": True,
                       "neural_plan": plan["neural_plan"],
                       "data_acceptance": plan["data_acceptance"],
                       "test_exposure": {
                           "session_id": opened_exposure["session_id"],
                           "opened_content_sha256": opened_exposure["content_sha256"],
                       },
                       "results": results, "rf_onnx": onnx_reports})
        require(not result_path.exists(), "Tree results already exist; refusing overwrite")
        write_json(result_path, report)
        completed_exposure = seal({
            "schema": SCHEMA,
            "kind": "tree_test_exposure_ledger",
            "plan_sha256": plan["content_sha256"],
            "session_id": opened_exposure["session_id"],
            "opened_content_sha256": opened_exposure["content_sha256"],
            "status": "complete",
            "test_sessions_started": 1,
            "test_sessions_completed": 1,
            "results_sha256": sha256(result_path),
        })
        write_json(exposure_path, completed_exposure)
        print(f"TREE BASELINES COMPLETE {run_dir/'results.json'}", flush=True)


if __name__ == "__main__":
    main()
