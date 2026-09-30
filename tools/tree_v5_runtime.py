#!/usr/bin/env python3
"""Explicit, source-bound tree execution adapter; never edits frozen v5 sources.

The unchanged producer owns all fitting, fit barriers, metrics and one-shot test
ledger. This adapter adds endpoint health checks, verifies saved model budgets,
and makes validation-only RF export use the independent verifier's exact
prediction/ORT settings. A separate controller owns fresh namespaces, process
identity, cgroup limits, prior disclosure, resource replay and final acceptance.
This module is process-global by design: call in a dedicated, single-run worker.
"""
from __future__ import annotations

import contextlib
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "spikeids_v5"))
import tree_baseline as tree  # noqa: E402
from contracts import check_seal, json_bytes, load_json, require, seal, sha256  # noqa: E402

_ORIGINAL_PLAN = tree._current_plan
_RUN_ACTIVE = False


def adapter_policy() -> dict:
    return {
        "schema": 1,
        "kind": "explicit_tree_runtime_adapter",
        "fit_matrix": {"datasets": ["nslkdd", "unsw"], "rf_seeds": list(range(20)),
                       "xgb_seeds": [0], "executions": ["primary", "replica"],
                       "fits": 84, "threads": 16, "n_estimators": 100},
        "rf_training": "unchanged_parallel_16_saved_model",
        "rf_export_reference": "joblib_sequential_backend",
        "ort_export": {"intra_op_num_threads": 1, "inter_op_num_threads": 1,
                       "execution_mode": "ORT_SEQUENTIAL", "graph_optimization_level": "ORT_ENABLE_BASIC",
                       "providers": ["CPUExecutionProvider"]},
        "health_boundaries": ["before_and_after_each_fit", "before_test_open",
                              "after_model_budget_validation", "before_and_after_export", "return"],
        "model_budget_validation": "84_saved_models_before_test_and_after_return",
        "test_and_metrics": "unchanged_producer_global_barrier_and_once_only_ledger",
        "limitation": "model config is checked; historical sample weights cannot be inferred from saved boosters",
    }


def resource_limits() -> dict:
    return {"maximum_process_tree_rss_bytes": 14 * 1024**3,
            "maximum_cgroup_memory_bytes": 16 * 1024**3,
            "maximum_sample_gap_seconds": 15.0,
            "require_bounded_cgroup": True, "require_zero_oom_kills": True,
            "require_zero_swap_io": False,
            "host_swap_scope": "host context only; workload cgroup swap must remain disabled"}


def _equal(actual, expected) -> bool:
    return json_bytes(actual) == json_bytes(expected)


def build_tree_plan(cache_root: Path, neural_run_dir: Path, binding: dict) -> dict:
    require(type(binding) is dict and bool(binding), "Explicit controller binding is required")
    base = _ORIGINAL_PLAN(Path(cache_root), Path(neural_run_dir), list(range(20)), 16, 100)
    check_seal(base)
    return seal({**{k: v for k, v in base.items() if k != "content_sha256"},
                 "execution_adapter": {"binding": binding, "policy": adapter_policy(),
                                       "source": {"path": str(Path(__file__).resolve()),
                                                  "sha256": sha256(Path(__file__))}},
                 "protocol_role": "planned_benchmark", "jobs": [],
                 "resource_limits": resource_limits()})


def _validate_plan(plan: dict) -> None:
    check_seal(plan)
    require(_equal(plan.get("random_forest_seeds"), list(range(20))) and
            _equal(plan.get("xgboost_seeds"), [0]) and
            type(plan.get("deployment_seed")) is int and plan["deployment_seed"] == 0 and
            type(plan.get("threads")) is int and plan["threads"] == 16 and
            set(plan.get("datasets", {})) == {"nslkdd", "unsw"}, "Tree fixed matrix differs")
    require(_equal(plan.get("hyperparameters"), {
        "random_forest": {"n_estimators": 100, "max_depth": 20, "class_weight": "balanced"},
        "xgboost": {"n_estimators": 100, "max_depth": 6, "learning_rate": 0.1,
                    "tree_method": "hist", "subsample": 1.0, "colsample_bytree": 1.0,
                    "sample_weight": "inverse fit-class frequency"}}), "Tree fixed hyperparameters differ")
    adapter = plan.get("execution_adapter", {})
    require(_equal(adapter.get("policy"), adapter_policy()) and
            adapter.get("source") == {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__))} and
            type(adapter.get("binding")) is dict and bool(adapter["binding"]), "Tree execution adapter differs")
    require(plan.get("protocol_role") == "planned_benchmark" and _equal(plan.get("jobs"), []) and
            _equal(plan.get("resource_limits"), resource_limits()) and
            type(plan.get("rf_onnx_probability_atol")) is float and plan["rf_onnx_probability_atol"] == 1e-5,
            "Tree resource/export protocol differs")


def _model_parameters(model, kind: str, seed: int, classes: int, width: int) -> None:
    expected = tree.make_estimator(kind, seed, 16, 100)
    require(type(model) is type(expected), "Tree estimator class differs")
    expected_params = expected.get_params(deep=False)
    if kind == "xgboost" and classes > 2:
        expected_params["objective"] = "multi:softprob"
    actual = model.get_params(deep=False)
    require(set(actual) == set(expected_params), "Tree estimator parameter inventory differs")
    for key, value in expected_params.items():
        observed = actual[key]
        if isinstance(value, float) and math.isnan(value):
            require(type(observed) is float and math.isnan(observed), f"Tree parameter differs: {key}")
        else:
            require(_equal(observed, value), f"Tree parameter differs: {key}")
    require(np.array_equal(np.asarray(model.classes_), np.arange(classes)) and
            model.n_features_in_ == width, "Tree fitted class/feature contract differs")
    if kind == "random_forest":
        require(len(model.estimators_) == 100 and model.n_outputs_ == 1,
                "RF fitted tree count/output count differs")
        seeds = np.random.RandomState(seed).randint(np.iinfo(np.int32).max, size=100)
        for estimator, state in zip(model.estimators_, seeds):
            require(estimator.random_state == int(state) and estimator.max_depth == 20 and
                    estimator.n_features_in_ == width and estimator.tree_.n_features == width and
                    estimator.tree_.max_depth <= 20 and estimator.tree_.n_classes[0] == classes,
                    "RF fitted tree budget/seed/shape differs")
    else:
        booster = model.get_booster()
        require(booster.num_boosted_rounds() == 100 and booster.num_features() == width,
                "XGB fitted round count/features differ")
        learner = json.loads(booster.save_config())["learner"]
        generic = learner["generic_param"]
        require(all(generic.get(key) == value for key, value in {
            "device": "cpu", "n_jobs": "16", "nthread": "16", "random_state": str(seed),
            "seed": str(seed), "seed_per_iteration": "0"}.items()), "XGB fitted runtime/seed differs")
        gradient = learner["gradient_booster"]
        training = gradient["tree_train_param"]
        require(gradient.get("name") == "gbtree" and
                gradient["gbtree_train_param"]["tree_method"] == "hist" and
                gradient["gbtree_model_param"]["num_parallel_tree"] == "1" and
                int(gradient["gbtree_model_param"]["num_trees"]) == 100 * (classes if classes > 2 else 1) and
                training["max_depth"] == "6" and training["subsample"] == "1" and
                training["colsample_bytree"] == "1" and
                np.float32(float(training["learning_rate"])) == np.float32(0.1),
                "XGB fitted booster budget differs")
        require(int(learner["learner_model_param"]["num_class"]) == (classes if classes > 2 else 0) and
                learner["learner_train_param"]["objective"] == expected_params["objective"] and
                learner["metrics"] == [{"name": "mlogloss"}], "XGB fitted objective/classes differ")


def validate_models(tree_run_dir: Path) -> dict:
    run = Path(tree_run_dir).resolve()
    plan = load_json(run / "plan.json")
    _validate_plan(plan)
    expected_paths, seen, digests = set(), set(), {}
    for dataset in tree.DATASETS:
        frozen = plan["datasets"][dataset]
        for kind in tree.KINDS:
            for seed in (range(20) if kind == "random_forest" else [0]):
                pair = []
                for execution in ("primary", "replica"):
                    path = tree._record_path(run, execution, dataset, kind, seed)
                    expected_paths.update({path, tree._artifact_path(path), tree._ledger_path(path)})
                    identity_fields = {
                        "schema": tree.SCHEMA, "plan_sha256": plan["content_sha256"],
                        "execution": execution, "dataset": dataset, "kind": kind, "seed": seed,
                        "data_fingerprint": frozen["data_fingerprint"]}
                    record, model = tree._load_fit_record(path, identity_fields)
                    ledger = load_json(tree._ledger_path(path))
                    require(all(_equal(record.get(key), value) and _equal(ledger.get(key), value)
                                for key, value in identity_fields.items()), "Tree typed fit identity differs")
                    identity = record["execution_identity"]["execution_id"]
                    require(identity not in seen, "Tree execution identity reused")
                    seen.add(identity)
                    require(type(record.get("fit_rows")) is int and record["fit_rows"] == frozen["counts"]["fit"],
                            "Tree fitted row count differs")
                    _model_parameters(model, kind, seed, len(frozen["classes"]), len(frozen["features"]))
                    pair.append(record["model_semantic_sha256"])
                require(pair[0] == pair[1], "Tree independent model pair differs")
                digests[f"{dataset}/{kind}/{seed}"] = pair[0]
    actual_paths, actual_directories, expected_directories = set(), set(), set()
    for path in expected_paths:
        expected_directories.update(parent for parent in path.parents if parent != run and run in parent.parents)
    for execution in ("primary", "replica"):
        root = run / execution
        require(root.is_dir() and not root.is_symlink(), "Tree model root is missing or aliased")
        actual_directories.add(root)
        for path in root.rglob("*"):
            require(not path.is_symlink(), "Tree artifact directory contains a symlink")
            if path.is_file():
                require(path.stat().st_nlink == 1, "Tree artifact is hardlinked")
                actual_paths.add(path)
            else:
                require(path.is_dir(), "Unsupported tree artifact file type")
                actual_directories.add(path)
    require(actual_paths == expected_paths and actual_directories == expected_directories and len(seen) == 84,
            "Tree exact 84-fit inventory differs")
    return {"schema": 1, "kind": "tree_saved_model_budget_verification", "passed": True,
            "plan_sha256": plan["content_sha256"], "fits": 84, "model_pairs": digests,
            "execution_ids": sorted(seen)}


@contextlib.contextmanager
def deterministic_export_context():
    """Only the producer's ORT module reference is replaced; verifier is untouched."""
    original = tree.ort

    def session(path, providers):
        require(providers == ["CPUExecutionProvider"], "Unexpected tree ORT providers")
        options = original.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        options.execution_mode = original.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = original.GraphOptimizationLevel.ORT_ENABLE_BASIC
        return original.InferenceSession(path, sess_options=options, providers=providers)

    tree.ort = SimpleNamespace(InferenceSession=session)
    try:
        with joblib.parallel_backend("sequential"):
            yield
    finally:
        tree.ort = original


def run_tree(cache_root: Path, neural_run_dir: Path, tree_run_dir: Path,
             binding: dict, healthcheck) -> dict:
    global _RUN_ACTIVE
    require(not _RUN_ACTIVE, "Tree adapter is non-reentrant")
    run = Path(tree_run_dir).resolve()
    require(all(not (run / name).exists() and not (run / name).is_symlink() for name in (
        "plan.json", "primary", "replica", "verification_fit.json", "test_exposure.json", "results.json", "onnx")),
        "Tree adapter requires a fresh scientific namespace")
    require(callable(healthcheck), "Resource health callback is mandatory")
    frozen = build_tree_plan(cache_root, neural_run_dir, binding)
    _validate_plan(frozen)
    originals = {name: getattr(tree, name) for name in ("_current_plan", "fit_one", "write_json", "export_rf_onnx")}
    argv = sys.argv
    fit_keys = set()
    opened = False

    def current(cache, neural, seeds, threads, count):
        require(Path(cache).resolve() == Path(cache_root).resolve() and
                Path(neural).resolve() == Path(neural_run_dir).resolve() and
                seeds == list(range(20)) and threads == 16 and count == 100, "Tree invocation changed")
        return frozen

    def fit(*args, **kwargs):
        require(not kwargs and len(args) == 12, "Unexpected tree fit call shape")
        key = (args[1], args[2], args[3], args[4])
        require(key not in fit_keys and not opened, "Tree fit repeated or attempted after test")
        healthcheck()
        result = originals["fit_one"](*args)
        fit_keys.add(key)
        healthcheck()
        return result

    def write(path, value):
        nonlocal opened
        if Path(path) == run / "test_exposure.json" and value.get("status") == "opened":
            require(not opened and len(fit_keys) == 84, "Tree test requires all 84 new fits exactly once")
            healthcheck()
            validate_models(run)
            healthcheck()
            opened = True
        return originals["write_json"](path, value)

    def export(*args, **kwargs):
        healthcheck()
        with deterministic_export_context():
            result = originals["export_rf_onnx"](*args, **kwargs)
        healthcheck()
        return result

    _RUN_ACTIVE = True
    tree._current_plan, tree.fit_one, tree.write_json, tree.export_rf_onnx = current, fit, write, export
    sys.argv = [str(Path(tree.__file__)), "--cache-root", str(Path(cache_root).resolve()),
                "--neural-run-dir", str(Path(neural_run_dir).resolve()), "--run-dir", str(run),
                "--seeds", *map(str, range(20)), "--threads", "16", "--n-estimators", "100"]
    try:
        healthcheck()
        tree.main()
        require(opened and len(fit_keys) == 84, "Tree run did not complete the frozen matrix")
        result = validate_models(run)
        healthcheck()
        return result
    finally:
        for name, original in originals.items():
            setattr(tree, name, original)
        sys.argv = argv
        _RUN_ACTIVE = False
