#!/usr/bin/env python3
"""Independently recompute every formal tree prediction, metric, and RF ONNX gate."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "spikeids_v5"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PACKAGE))

from contracts import (  # noqa: E402
    check_seal,
    digest,
    load_json,
    require,
    seal,
    sha256,
    write_json,
)
from experiment_all import array_sha256  # noqa: E402

from data_loaders import open_cache  # noqa: E402
from metrics import full_evaluate  # noqa: E402
from tools.verify_v5_neural import (  # noqa: E402
    compare_aggregate,
    compare_metric_record,
    metric_oracle,
    tool_provenance,
)
from tree_baseline import (  # noqa: E402
    _ledger_path,
    _load_fit_record,
    _record_path,
    load_verified_tree_suite,
    model_semantic_digest,
)

TREE_VERIFIER_PACKAGES = (
    "joblib", "numpy", "onnxruntime", "scikit-learn", "xgboost",
)


def evaluate_model(model, kind: str, x_test, y_test: np.ndarray,
                   class_names: list[str], seed: int) -> tuple[dict, dict, dict]:
    if kind == "random_forest":
        model.n_jobs = 1
    prediction = np.asarray(model.predict(x_test), dtype=np.int64)
    probability = np.asarray(model.predict_proba(x_test))
    calculated = full_evaluate(
        y_test, prediction, probability, len(class_names), class_names
    )
    independent = metric_oracle(y_test, prediction, probability, class_names)
    compare_metric_record(calculated, independent,
                          f"tree/{kind}/seed={seed}/v5-vs-independent")
    calculated["seed"] = seed
    independent["seed"] = seed
    labels = list(range(len(class_names)))
    require(np.array_equal(
        np.asarray(calculated["confusion_matrix"]),
        confusion_matrix(y_test, prediction, labels=labels),
    ), "Independent sklearn confusion matrix differs")
    require(abs(calculated["overall_acc"] -
                100.0 * accuracy_score(y_test, prediction)) <= 1e-12,
            "Independent sklearn overall accuracy differs")
    require(abs(calculated["macro_f1"] - 100.0 * f1_score(
        y_test, prediction, labels=labels, average="macro", zero_division=0
    )) <= 1e-12, "Independent sklearn macro F1 differs")
    evidence = {
        "prediction_sha256": array_sha256(prediction),
        "probability_sha256": array_sha256(probability),
        "labels_sha256": array_sha256(y_test),
        "metrics_sha256": digest(calculated),
    }
    return calculated, independent, evidence


def evaluate_rf_onnx(path: Path, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
    session = ort.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    require(len(session.get_inputs()) == 1 and len(session.get_outputs()) == 2,
            "RF ONNX input/output contract changed")
    labels, probability = session.run(
        None, {session.get_inputs()[0].name: np.asarray(x, dtype=np.float32)}
    )
    return np.asarray(labels, dtype=np.int64), np.asarray(probability)


def verify(tree_run_dir: Path, neural_run_dir: Path | None = None) -> dict:
    tree_run_dir = tree_run_dir.resolve()
    plan, report = (load_verified_tree_suite(tree_run_dir)
                    if neural_run_dir is None else
                    load_verified_tree_suite(tree_run_dir, neural_run_dir))
    require(plan.get("random_forest_seeds") == list(range(20)) and
            plan.get("xgboost_seeds") == [0] and plan.get("deployment_seed") == 0 and
            plan.get("threads") == 16,
            "Only the fixed formal tree plan may pass independent verification")
    require(plan.get("hyperparameters") == {
        "random_forest": {
            "n_estimators": 100,
            "max_depth": 20,
            "class_weight": "balanced",
        },
        "xgboost": {
            "n_estimators": 100,
            "max_depth": 6,
            "learning_rate": 0.1,
            "tree_method": "hist",
            "subsample": 1.0,
            "colsample_bytree": 1.0,
            "sample_weight": "inverse fit-class frequency",
        },
    }, "Formal tree hyperparameters differ from the fixed baseline")
    require(set(plan.get("datasets", {})) == {"nslkdd", "unsw"},
            "Formal tree plan has a missing/unexpected dataset")
    onnx_rows = report.get("rf_onnx")
    require(isinstance(onnx_rows, list) and len(onnx_rows) == 2 and
            {row.get("dataset") for row in onnx_rows if isinstance(row, dict)} ==
            {"nslkdd", "unsw"},
            "RF ONNX evidence must contain exactly one row per formal dataset")
    onnx_by_dataset = {row["dataset"]: row for row in onnx_rows}

    verified: dict[str, dict] = {}
    onnx_evidence = []
    for dataset in ("nslkdd", "unsw"):
        frozen = plan["datasets"][dataset]
        cache = Path(frozen["cache"])
        metadata, arrays = open_cache(cache)
        require(metadata.get("dataset") == dataset and
                metadata["data_fingerprint"] == frozen["data_fingerprint"] and
                sha256(cache / "metadata.json") == frozen["metadata_sha256"] and
                metadata.get("files_sha256") == frozen["files_sha256"] and
                metadata.get("counts") == frozen["counts"] and
                metadata.get("features") == frozen["features"] and
                metadata.get("class_names") == frozen["classes"] and
                metadata.get("raw_rows") == frozen["raw_rows"] and
                metadata.get("raw_model_view_sha256") ==
                frozen["raw_model_view_sha256"],
                f"Tree plan/cache fingerprint mismatch: {dataset}")
        y_test = np.asarray(arrays["y_test"])
        verified[dataset] = {}
        for kind in ("random_forest", "xgboost"):
            seeds = (plan["random_forest_seeds"] if kind == "random_forest"
                     else plan["xgboost_seeds"])
            reported_rows = report["results"][dataset][kind]["per_seed"]
            reported = {row["seed"]: row for row in reported_rows}
            require(set(reported) == set(seeds) and len(reported) == len(reported_rows),
                    f"Tree result seed set is incomplete: {dataset}/{kind}")
            verified[dataset][kind] = {}
            independent_rows = []
            for seed in seeds:
                executions = {}
                for execution in ("primary", "replica"):
                    record_path = _record_path(
                        tree_run_dir, execution, dataset, kind, seed,
                    )
                    expected = {
                        "schema": plan["schema"],
                        "plan_sha256": plan["content_sha256"],
                        "execution": execution,
                        "dataset": dataset,
                        "kind": kind,
                        "seed": seed,
                        "data_fingerprint": frozen["data_fingerprint"],
                    }
                    record, model = _load_fit_record(record_path, expected)
                    artifact = record_path.with_suffix(".joblib")
                    require(artifact.is_file() and not artifact.is_symlink() and
                            artifact.stat().st_nlink == 1,
                            f"Missing/aliased formal tree model: {artifact}")
                    semantic = model_semantic_digest(kind, model)
                    metrics, independent, evidence = evaluate_model(
                        model, kind, arrays["x_test"], y_test,
                        metadata["class_names"], seed,
                    )
                    require(metrics == reported[seed],
                            f"Recomputed metrics differ: {dataset}/{kind}/seed={seed}/{execution}")
                    compare_metric_record(
                        reported[seed], independent,
                        f"tree/{dataset}/{kind}/seed={seed}/{execution}",
                    )
                    if execution == "primary":
                        independent_rows.append(independent)
                    executions[execution] = {
                        "artifact": artifact.relative_to(tree_run_dir).as_posix(),
                        "artifact_sha256": sha256(artifact),
                        "record_sha256": sha256(record_path),
                        "execution_ledger_sha256": sha256(_ledger_path(record_path)),
                        "execution_identity": record["execution_identity"],
                        "model_semantic_sha256": semantic,
                        **evidence,
                    }
                for key in ("model_semantic_sha256", "prediction_sha256",
                            "probability_sha256", "labels_sha256", "metrics_sha256"):
                    require(executions["primary"][key] == executions["replica"][key],
                            f"Independent tree repetitions differ: {dataset}/{kind}/seed={seed}/{key}")
                require(executions["primary"]["execution_identity"]["execution_id"] !=
                        executions["replica"]["execution_identity"]["execution_id"] and
                        executions["primary"]["artifact_sha256"] !=
                        executions["replica"]["artifact_sha256"] and
                        executions["primary"]["record_sha256"] !=
                        executions["replica"]["record_sha256"],
                        f"Tree replica copied a primary execution namespace: "
                        f"{dataset}/{kind}/seed={seed}")
                verified[dataset][kind][str(seed)] = executions
            independent_rows.sort(key=lambda item: item["seed"])
            compare_aggregate(
                report["results"][dataset][kind]["aggregate"],
                independent_rows,
                metadata["class_names"],
                f"tree/{dataset}/{kind}",
            )

        onnx_row = onnx_by_dataset[dataset]
        expected_graph = f"onnx/rf_{dataset}_seed_0.onnx"
        expected_validation_rows = min(4096, len(arrays["x_validation"]))
        require(onnx_row.get("seed") == 0 and
                onnx_row.get("onnx") == expected_graph and
                onnx_row.get("validation_rows") == expected_validation_rows and
                onnx_row.get("probability_atol") == plan["rf_onnx_probability_atol"] and
                onnx_row.get("labels_equal") is True and
                "TreeEnsembleClassifier" in onnx_row.get("operators", []),
                f"RF ONNX evidence contract differs: {dataset}")
        graph = tree_run_dir / onnx_row["onnx"]
        require(graph.is_file() and not graph.is_symlink() and
                sha256(graph) == onnx_row.get("onnx_sha256"),
                f"RF ONNX artifact is missing, symlinked, or changed: {dataset}")
        validation_rows = onnx_row["validation_rows"]
        x_validation = np.asarray(arrays["x_validation"][:validation_rows], dtype=np.float32)
        _primary_record, primary_rf = _load_fit_record(
            _record_path(tree_run_dir, "primary", dataset, "random_forest", 0),
            {
                "schema": plan["schema"],
                "plan_sha256": plan["content_sha256"],
                "execution": "primary",
                "dataset": dataset,
                "kind": "random_forest",
                "seed": 0,
                "data_fingerprint": frozen["data_fingerprint"],
            },
        )
        primary_rf.n_jobs = 1
        expected_labels = np.asarray(primary_rf.predict(x_validation), dtype=np.int64)
        expected_probability = np.asarray(primary_rf.predict_proba(x_validation))
        actual_labels, actual_probability = evaluate_rf_onnx(graph, x_validation)
        maximum = float(np.max(np.abs(expected_probability - actual_probability)))
        require(np.array_equal(expected_labels, actual_labels) and
                maximum <= plan["rf_onnx_probability_atol"],
                f"Independent RF ONNX gate failed: {dataset}")
        require(maximum == onnx_row["probability_max_abs_error"],
                f"RF ONNX report differs from independent recomputation: {dataset}")
        onnx_evidence.append({
            "dataset": dataset,
            "onnx": onnx_row["onnx"],
            "onnx_sha256": sha256(graph),
            "validation_rows": validation_rows,
            "labels_sha256": array_sha256(actual_labels),
            "probability_sha256": array_sha256(actual_probability),
            "probability_max_abs_error": maximum,
            "probability_atol": plan["rf_onnx_probability_atol"],
        })

    return {
        "schema": 1,
        "kind": "independent_formal_tree_verification",
        "passed": True,
        "tree_plan_sha256": plan["content_sha256"],
        "tree_results_sha256": sha256(tree_run_dir / "results.json"),
        "tree_fit_verification_sha256": sha256(tree_run_dir / "verification_fit.json"),
        "neural_plan": plan["neural_plan"],
        "data_acceptance": plan["data_acceptance"],
        "test_exposure_sha256": sha256(tree_run_dir / "test_exposure.json"),
        "models": verified,
        "rf_onnx": onnx_evidence,
        "metric_oracle":
            "independent sklearn/direct full metrics plus aggregate recomputation",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--tree-run-dir", required=True, type=Path)
    parser.add_argument("--neural-run-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    tree_run_dir = args.tree_run_dir.resolve()
    output = (args.output.resolve() if args.output else
              tree_run_dir / "independent_verification.json")
    require(output.parent == tree_run_dir,
            "Independent verification output must be a direct child of the tree run directory")
    provenance = tool_provenance(
        Path(__file__), [sys.executable, *sys.argv], TREE_VERIFIER_PACKAGES
    )
    value = seal({**verify(tree_run_dir, args.neural_run_dir.resolve()),
                  "tool_provenance": provenance})
    if output.exists():
        existing = load_json(output)
        check_seal(existing)
        require(existing == value,
                "Existing independent tree verification differs; use a fresh formal run")
    else:
        write_json(output, value)
    print(f"INDEPENDENT TREE VERIFICATION PASSED: {output}", flush=True)


if __name__ == "__main__":
    main()
