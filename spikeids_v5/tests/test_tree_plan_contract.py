from __future__ import annotations

import inspect
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pytest

import tree_baseline as tree


TEMP_PACKAGE = Path("/tmp/spikeids-v5-next-2ZQsR7/spikeids_v5")
if not hasattr(tree, "_neural_data_contract") and TEMP_PACKAGE.is_dir():
    for module_name in (
        "tree_baseline", "evidence", "experiment_all", "metrics",
        "data_loaders", "group_protocol", "contracts",
    ):
        sys.modules.pop(module_name, None)
    sys.path.insert(0, str(TEMP_PACKAGE))
    import tree_baseline as tree

sys.path.append(str(Path(__file__).resolve().parents[2]))
from tools import verify_v5_tree as tree_verifier


class _DummyTree:
    def fit(self, _x, y, **_kwargs):
        self.classes_ = np.unique(y)
        return self


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _cache_fixture(tmp_path: Path, dataset: str = "nslkdd") -> tuple[Path, dict, dict]:
    cache = (tmp_path / dataset).resolve()
    cache.mkdir()
    _write_json(cache / "metadata.json", {"dataset": dataset})
    metadata = {
        "dataset": dataset,
        "data_fingerprint": "a" * 64,
        "raw_rows": 9,
        "counts": {"fit": 3, "validation": 3, "test": 3},
        "features": ["f0", "f1"],
        "class_names": ["normal", "attack"],
        "raw_model_view_sha256": "b" * 64,
        "files_sha256": {"x_fit.npy": "c" * 64},
    }
    accepted = {
        "data_fingerprint": metadata["data_fingerprint"],
        "raw_rows": metadata["raw_rows"],
        "counts": metadata["counts"],
        "features": metadata["features"],
        "class_names": metadata["class_names"],
        "raw_model_view_sha256": metadata["raw_model_view_sha256"],
        "byte_identical_rebuilds": True,
        "semantic_checks": {key: True for key in tree.DATA_ACCEPTANCE_CHECKS},
        "rebuilds": [{
            "resolved_root": str(cache),
            "metadata_sha256": tree.sha256(cache / "metadata.json"),
            "data_fingerprint": metadata["data_fingerprint"],
            "files_sha256": metadata["files_sha256"],
        }, {
            "resolved_root": str((tmp_path / "rebuild-b" / dataset).resolve()),
            "metadata_sha256": tree.sha256(cache / "metadata.json"),
            "data_fingerprint": metadata["data_fingerprint"],
            "files_sha256": metadata["files_sha256"],
        }],
    }
    return cache, metadata, {"datasets": {dataset: accepted}}


def test_cache_contract_rejects_wrong_dataset_even_when_fingerprint_matches(tmp_path):
    cache, metadata, acceptance = _cache_fixture(tmp_path)
    metadata["dataset"] = "unsw"
    with pytest.raises(Exception, match="wrong dataset"):
        tree._cache_contract("nslkdd", cache, metadata, acceptance)


def test_cache_contract_binds_exact_accepted_rebuild(tmp_path):
    cache, metadata, acceptance = _cache_fixture(tmp_path)
    contract = tree._cache_contract("nslkdd", cache, metadata, acceptance)
    assert contract["cache"] == str(cache)
    assert contract["metadata_sha256"] == tree.sha256(cache / "metadata.json")
    acceptance["datasets"]["nslkdd"]["rebuilds"][0]["files_sha256"] = {
        "x_fit.npy": "d" * 64,
    }
    with pytest.raises(Exception, match="exact accepted rebuild"):
        tree._cache_contract("nslkdd", cache, metadata, acceptance)


def test_tree_plan_rejects_neural_or_cache_rebinding(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache"
    datasets = {
        name: {"cache": str((cache_root / name).resolve())}
        for name in tree.DATASETS
    }
    neural = {
        "path": str((tmp_path / "neural/plan.json").resolve()),
        "sha256": "a" * 64,
        "content_sha256": "b" * 64,
    }
    acceptance = {
        "path": str((tmp_path / "acceptance.json").resolve()),
        "sha256": "c" * 64,
        "content_sha256": "d" * 64,
    }
    plan = {
        "neural_plan": neural,
        "data_acceptance": acceptance,
        "datasets": datasets,
    }
    monkeypatch.setattr(
        tree, "_neural_data_contract",
        lambda _run, _cache: (neural, acceptance, datasets),
    )
    tree._validate_plan_inputs(plan, Path(neural["path"]).parent)
    changed = {**plan, "data_acceptance": {**acceptance, "sha256": "e" * 64}}
    with pytest.raises(Exception, match="cross-binding changed"):
        tree._validate_plan_inputs(changed, Path(neural["path"]).parent)
    with pytest.raises(Exception, match="Requested neural run differs"):
        tree._validate_plan_inputs(plan, tmp_path / "other-neural")


def test_neural_data_contract_rejects_job_cache_rebinding(tmp_path, monkeypatch):
    package = Path(__file__).resolve().parents[1]
    repo = package.parent
    monkeypatch.setattr(tree, "PACKAGE", package)
    raw_path = (tmp_path / "raw_audit.json").resolve()
    raw = tree.seal({
        "raw_source_audit_passed": True,
        "data_acceptance_passed": False,
        "audit_implementation_sha256": tree.sha256(package / "audit_data.py"),
        "data_loader_sha256": tree.sha256(package / "data_loaders.py"),
    })
    _write_json(raw_path, raw)
    upstream_path = (tmp_path / "iot23_provenance.json").resolve()
    upstream = tree.seal({"comparison_passed": True})
    _write_json(upstream_path, upstream)
    raw_binding = {
        "path": str(raw_path), "sha256": tree.sha256(raw_path),
        "content_sha256": raw["content_sha256"],
    }
    upstream_binding = {
        "path": str(upstream_path), "sha256": tree.sha256(upstream_path),
        "content_sha256": upstream["content_sha256"],
        "comparison_passed": True,
    }
    cache_root = (tmp_path / "cache-a").resolve()
    other_root = (tmp_path / "cache-b").resolve()
    metadata = {}
    accepted_datasets = {}
    for index, dataset in enumerate(tree.DATASETS):
        cache = cache_root / dataset
        cache.mkdir(parents=True)
        _write_json(cache / "metadata.json", {"dataset": dataset})
        row = {
            "dataset": dataset,
            "data_fingerprint": f"{index + 1}" * 64,
            "raw_rows": 9,
            "counts": {"fit": 3, "validation": 3, "test": 3},
            "features": ["f0", "f1"],
            "class_names": ["normal", "attack"],
            "raw_model_view_sha256": f"{index + 3}" * 64,
            "files_sha256": {"x_fit.npy": f"{index + 5}" * 64},
        }
        metadata[dataset] = row
        accepted_datasets[dataset] = {
            **{key: row[key] for key in (
                "data_fingerprint", "raw_rows", "counts", "features",
                "class_names", "raw_model_view_sha256",
            )},
            "byte_identical_rebuilds": True,
            "semantic_checks": {
                key: True for key in tree.DATA_ACCEPTANCE_CHECKS
            },
            "rebuilds": [{
                "resolved_root": str(cache),
                "metadata_sha256": tree.sha256(cache / "metadata.json"),
                "data_fingerprint": row["data_fingerprint"],
                "files_sha256": row["files_sha256"],
            }, {
                "resolved_root": str(other_root / dataset),
                "metadata_sha256": tree.sha256(cache / "metadata.json"),
                "data_fingerprint": row["data_fingerprint"],
                "files_sha256": row["files_sha256"],
            }],
        }
    accepted_datasets.update({"cicids2017": {}, "iot23": {}})
    verifier_path = (repo / "tools" / "verify_v5_data.py").resolve()
    verifier_binding = {
        "path": str(verifier_path), "sha256": tree.sha256(verifier_path),
    }
    acceptance_path = (tmp_path / "data_acceptance.json").resolve()
    acceptance = tree.seal({
        "kind": "spikeids_v5_data_acceptance",
        "acceptance_schema": 1,
        "data_acceptance_passed": True,
        "two_distinct_fresh_roots": True,
        "byte_identical_rebuilds": True,
        "raw_audit": {
            **raw_binding,
            "audit_implementation_sha256": raw["audit_implementation_sha256"],
            "raw_source_audit_passed": True,
        },
        "upstream_provenance": upstream_binding,
        "producer": {
            "path": str((package / "data_loaders.py").resolve()),
            "sha256": tree.sha256(package / "data_loaders.py"),
        },
        "independent_verifier": verifier_binding,
        "datasets": accepted_datasets,
        "limitations": {
            key: False for key in tree.DATA_ACCEPTANCE_LIMITATIONS
        },
    })
    _write_json(acceptance_path, acceptance)
    acceptance_binding = {
        "path": str(acceptance_path), "sha256": tree.sha256(acceptance_path),
        "content_sha256": acceptance["content_sha256"],
    }
    neural_dir = (tmp_path / "neural").resolve()
    neural_dir.mkdir()
    evidence = {
        "raw_audit": raw_binding,
        "data_acceptance": acceptance_binding,
        "independent_verifier": verifier_binding,
        "upstream_provenance": upstream_binding,
        "accepted_cache_root": str(cache_root),
    }

    def neural_plan(cache_override=None):
        jobs = [{
            "dataset": dataset,
            "cache": str(cache_override or (cache_root / dataset)),
            "data_fingerprint": metadata[dataset]["data_fingerprint"],
        } for dataset in tree.DATASETS]
        return tree.seal({"data_evidence": evidence, "jobs": jobs})

    valid_plan = neural_plan()
    _write_json(neural_dir / "plan.json", valid_plan)
    monkeypatch.setattr(tree, "read_plan", lambda _run: valid_plan)
    monkeypatch.setattr(
        tree, "open_fit_cache",
        lambda cache: (metadata[Path(cache).name], {}),
    )
    _neural, _acceptance, datasets = tree._neural_data_contract(
        neural_dir, cache_root,
    )
    assert set(datasets) == set(tree.DATASETS)

    rebound = neural_plan((tmp_path / "attacker-cache").resolve())
    _write_json(neural_dir / "plan.json", rebound)
    monkeypatch.setattr(tree, "read_plan", lambda _run: rebound)
    with pytest.raises(Exception, match="Tree cache differs"):
        tree._neural_data_contract(neural_dir, cache_root)


def test_fit_records_and_joblib_are_execution_namespace_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(tree, "make_estimator", lambda *_args: _DummyTree())
    monkeypatch.setattr(tree, "model_semantic_digest", lambda *_args: "f" * 64)
    x = np.arange(12, dtype=np.float32).reshape(6, 2)
    y = np.array([0, 1, 0, 1, 0, 1], dtype=np.int64)
    common = (tmp_path, "nslkdd", "random_forest", 0, x, y, 2, 1, 1,
              "a" * 64, "b" * 64)
    primary = tree.fit_one(common[0], "primary", *common[1:])
    replica = tree.fit_one(common[0], "replica", *common[1:])
    assert primary["execution_identity"]["execution_id"] != \
        replica["execution_identity"]["execution_id"]
    assert primary["artifact_sha256"] != replica["artifact_sha256"]

    primary_path = tree._record_path(tmp_path, "primary", "nslkdd", "random_forest", 0)
    replica_path = tree._record_path(tmp_path, "replica", "nslkdd", "random_forest", 0)
    for source, target in (
        (primary_path, replica_path),
        (tree._artifact_path(primary_path), tree._artifact_path(replica_path)),
        (tree._ledger_path(primary_path), tree._ledger_path(replica_path)),
    ):
        shutil.copyfile(source, target)
    with pytest.raises(Exception, match="ledger|namespace|Stale"):
        tree.fit_one(common[0], "replica", *common[1:])


@pytest.mark.parametrize("copied", ["record", "artifact", "ledger"])
def test_each_primary_execution_file_is_rejected_in_replica_namespace(
        tmp_path, monkeypatch, copied):
    monkeypatch.setattr(tree, "make_estimator", lambda *_args: _DummyTree())
    monkeypatch.setattr(tree, "model_semantic_digest", lambda *_args: "f" * 64)
    x = np.arange(12, dtype=np.float32).reshape(6, 2)
    y = np.array([0, 1, 0, 1, 0, 1], dtype=np.int64)
    common = (tmp_path, "nslkdd", "random_forest", 0, x, y, 2, 1, 1,
              "a" * 64, "b" * 64)
    tree.fit_one(common[0], "primary", *common[1:])
    tree.fit_one(common[0], "replica", *common[1:])
    primary = tree._record_path(
        tmp_path, "primary", "nslkdd", "random_forest", 0,
    )
    replica = tree._record_path(
        tmp_path, "replica", "nslkdd", "random_forest", 0,
    )
    paths = {
        "record": (primary, replica),
        "artifact": (tree._artifact_path(primary), tree._artifact_path(replica)),
        "ledger": (tree._ledger_path(primary), tree._ledger_path(replica)),
    }
    shutil.copyfile(*paths[copied])
    with pytest.raises(Exception, match="ledger|namespace|Stale|artifact"):
        tree.fit_one(common[0], "replica", *common[1:])


def test_hardlinked_fit_record_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(tree, "make_estimator", lambda *_args: _DummyTree())
    monkeypatch.setattr(tree, "model_semantic_digest", lambda *_args: "f" * 64)
    x = np.arange(12, dtype=np.float32).reshape(6, 2)
    y = np.array([0, 1, 0, 1, 0, 1], dtype=np.int64)
    args = (tmp_path, "primary", "nslkdd", "random_forest", 0,
            x, y, 2, 1, 1, "a" * 64, "b" * 64)
    tree.fit_one(*args)
    record = tree._record_path(
        tmp_path, "primary", "nslkdd", "random_forest", 0,
    )
    alias = tmp_path / "record-alias.json"
    alias.hardlink_to(record)
    with pytest.raises(Exception, match="aliased"):
        tree.fit_one(*args)


def test_partial_execution_namespace_cannot_reset_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(tree, "make_estimator", lambda *_args: _DummyTree())
    monkeypatch.setattr(tree, "model_semantic_digest", lambda *_args: "f" * 64)
    x = np.arange(12, dtype=np.float32).reshape(6, 2)
    y = np.array([0, 1, 0, 1, 0, 1], dtype=np.int64)
    args = (tmp_path, "primary", "nslkdd", "random_forest", 0,
            x, y, 2, 1, 1, "a" * 64, "b" * 64)
    tree.fit_one(*args)
    tree._artifact_path(tree._record_path(
        tmp_path, "primary", "nslkdd", "random_forest", 0,
    )).unlink()
    with pytest.raises(Exception, match="cannot be reset"):
        tree.fit_one(*args)


def test_completed_or_partial_test_exposure_blocks_refit(tmp_path, monkeypatch):
    neural = tmp_path / "neural"
    assert tree._completed_run_guard(tmp_path, neural) is False
    (tmp_path / "test_exposure.json").write_text("{}", encoding="utf-8")
    with pytest.raises(Exception, match="partial"):
        tree._completed_run_guard(tmp_path, neural)
    (tmp_path / "results.json").write_text("{}", encoding="utf-8")
    called = []
    monkeypatch.setattr(
        tree, "load_verified_tree_suite",
        lambda run, neural_run: called.append((run, neural_run)),
    )
    assert tree._completed_run_guard(tmp_path, neural) is True
    assert called == [(tmp_path, neural)]


def test_fit_phase_has_no_open_cache_call_before_exposure_barrier():
    source = inspect.getsource(tree.main)
    before_exposure = source.split("opened_exposure =", 1)[0]
    assert "open_fit_cache(" in before_exposure
    assert "open_cache(" not in before_exposure


def test_formal_cli_requires_neural_run_dir(tmp_path):
    with pytest.raises(SystemExit):
        tree.parser().parse_args([
            "--cache-root", str(tmp_path / "cache"),
            "--run-dir", str(tmp_path / "tree"),
        ])


def test_independent_verifier_rejects_wrong_cache_dataset(tmp_path, monkeypatch):
    datasets = {}
    for name in tree.DATASETS:
        cache = (tmp_path / name).resolve()
        cache.mkdir()
        _write_json(cache / "metadata.json", {"dataset": name})
        datasets[name] = {
            "cache": str(cache),
            "metadata_sha256": tree.sha256(cache / "metadata.json"),
            "files_sha256": {},
            "data_fingerprint": "a" * 64,
            "raw_rows": 3,
            "counts": {"fit": 1, "validation": 1, "test": 1},
            "features": ["f0"],
            "classes": ["normal", "attack"],
            "raw_model_view_sha256": "b" * 64,
        }
    plan = {
        "schema": tree.SCHEMA,
        "content_sha256": "c" * 64,
        "random_forest_seeds": list(range(20)),
        "xgboost_seeds": [0],
        "deployment_seed": 0,
        "threads": 16,
        "datasets": datasets,
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
    report = {"rf_onnx": [{"dataset": name} for name in tree.DATASETS]}
    requested_neural = tmp_path / "neural"
    calls = []
    monkeypatch.setattr(
        tree_verifier, "load_verified_tree_suite",
        lambda run, neural: calls.append((run, neural)) or (plan, report),
    )
    monkeypatch.setattr(
        tree_verifier, "open_cache",
        lambda _cache: ({
            "dataset": "unsw",
            "data_fingerprint": "a" * 64,
            "files_sha256": {},
            "counts": datasets["nslkdd"]["counts"],
            "features": ["f0"],
            "class_names": ["normal", "attack"],
            "raw_rows": 3,
            "raw_model_view_sha256": "b" * 64,
        }, {}),
    )
    with pytest.raises(Exception, match="plan/cache fingerprint mismatch"):
        tree_verifier.verify(tmp_path, requested_neural)
    assert calls == [(tmp_path.resolve(), requested_neural)]
