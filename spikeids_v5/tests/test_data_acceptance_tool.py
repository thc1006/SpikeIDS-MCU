from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "verify_v5_data.py"
SPEC = importlib.util.spec_from_file_location("verify_v5_data_under_test", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    value = hashlib.sha256()
    value.update(path.read_bytes())
    return value.hexdigest()


def _seal(value: dict) -> dict:
    return {**value, "content_sha256": tool.digest(value)}


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "package"
    (package / "audit" / "source_specs").mkdir(parents=True)
    for filename in ("audit_data.py", "contracts.py", "data_loaders.py", "group_protocol.py"):
        (package / filename).write_text(f"# synthetic {filename}\n", encoding="utf-8")
    return package


def _raw_audit(tmp_path: Path, package: Path) -> tuple[Path, dict[str, str]]:
    synthetic_raw_sha256 = hashlib.sha256(b"x").hexdigest()
    fingerprints = {
        dataset: hashlib.sha256(("raw-model-view:" + dataset).encode()).hexdigest()
        for dataset in tool.DATASETS
    }
    datasets = {}
    for dataset in tool.DATASETS:
        features = [*tool.CATEGORICAL[dataset], "numeric"]
        spec = {
            "dataset": dataset,
            "source_contract_version": 1,
            "provenance_note": "synthetic verifier fixture",
            "files": [{
                "path": f"{dataset}.csv",
                "role": "train" if dataset in ("nslkdd", "unsw") else "combined",
                "bytes": 1,
                "sha256": synthetic_raw_sha256,
                "expected_rows": 9,
                "expected_columns": len(features) + 2,
            }],
        }
        spec_path = package / "audit" / "source_specs" / f"{dataset}.json"
        _write_json(spec_path, spec)
        datasets[dataset] = {
            "dataset": dataset,
            "source_spec": f"audit/source_specs/{dataset}.json",
            "source_spec_sha256": _sha(spec_path),
            "provenance_note": "synthetic verifier fixture",
            "rows": 9,
            "features": features,
            "classes": ["class0", "class1"],
            "mapped_label_counts": {"class0": 6, "class1": 3},
            "files": [{
                "path": f"{dataset}.csv",
                "role": "train" if dataset in ("nslkdd", "unsw") else "combined",
                "bytes": 1,
                "sha256": synthetic_raw_sha256,
                "rows": 9,
                "physical_columns": features + ["label", "ignored"],
                "physical_duplicate_columns": {},
                "dropped_physical_column_index": None,
                "selected_columns": features + ["label", "ignored"],
                "raw_label_counts": {"class0": 6, "class1": 3},
                "mapped_label_counts": {"class0": 6, "class1": 3},
            }],
        }
    report = {
        "schema": 5,
        "audit_schema": 3,
        "raw_source_audit_passed": True,
        "data_acceptance_passed": False,
        "data_acceptance_blocker": "two fresh rebuilds plus independent verifier required",
        "audit_implementation_sha256": _sha(package / "audit_data.py"),
        "data_loader_sha256": _sha(package / "data_loaders.py"),
        "datasets": datasets,
        "supporting_artifacts": {},
        "scope": "synthetic test",
        "limitations": {},
        "json_evidence_path": "synthetic/data_audit.json",
    }
    report["audit_fingerprint"] = tool.digest(report)
    path = tmp_path / "data_audit.json"
    _write_json(path, _seal(report))
    return path, fingerprints


def _cache_dataset(
    directory: Path,
    dataset: str,
    package: Path,
    raw_record: dict,
    fingerprint: str,
    audit_path: Path,
    audit: dict,
) -> None:
    directory.mkdir(parents=True)
    features = raw_record["features"]
    width = len(features)
    classes = raw_record["classes"]
    counts = {split: 3 for split in tool.SPLITS}
    ids = {
        "fit": np.arange(0, 3, dtype=np.int64),
        "validation": np.arange(3, 6, dtype=np.int64),
        "test": np.arange(6, 9, dtype=np.int64),
    }
    for split_index, split in enumerate(tool.SPLITS):
        x = np.zeros((3, width), dtype=np.float32)
        x[:, 0] = np.arange(split_index * 3 + 1, split_index * 3 + 4, dtype=np.float32)
        x[:, -1] += np.float32(split_index + 0.25)
        values = {
            "x": x,
            "y": np.array([0, 1, 0], dtype=np.int64),
            "ids": ids[split],
            "identity_groups": ids[split],
            "assignment_components": ids[split],
            "multiplicity": np.ones(3, dtype=np.int64),
        }
        for prefix, value in values.items():
            np.save(directory / f"{prefix}_{split}.npy", value, allow_pickle=False)
    np.save(directory / "excluded_ids.npy", np.array([], dtype=np.int64), allow_pickle=False)
    np.save(directory / "excluded_reasons.npy", np.array([], dtype=np.uint8), allow_pickle=False)
    np.save(directory / "raw_unique_ids.npy", np.arange(9, dtype=np.int64), allow_pickle=False)
    np.save(directory / "raw_unique_identity_groups.npy", np.arange(9, dtype=np.int64),
            allow_pickle=False)
    np.save(directory / "raw_unique_assignment_components.npy", np.arange(9, dtype=np.int64),
            allow_pickle=False)
    np.save(directory / "raw_unique_labels.npy", np.tile([0, 1, 0], 3).astype(np.int64),
            allow_pickle=False)
    np.save(directory / "raw_unique_multiplicity.npy", np.ones(9, dtype=np.int64),
            allow_pickle=False)
    np.save(directory / "preprocessing_fit_ids.npy", ids["fit"], allow_pickle=False)
    np.save(directory / "final_dedup_ids.npy", np.array([], dtype=np.int64), allow_pickle=False)
    np.save(directory / "final_dedup_representative_ids.npy", np.array([], dtype=np.int64),
            allow_pickle=False)
    np.save(directory / "final_dedup_origin_splits.npy", np.array([], dtype=np.uint8),
            allow_pickle=False)
    categories = {column: ["V:a"] for column in tool.CATEGORICAL[dataset]}
    preprocessing = {
        "feature_columns": features,
        "categorical_columns": list(tool.CATEGORICAL[dataset]),
        "categories": categories,
        "mean": [0.0] * width,
        "var": [1.0] * width,
        "scale": [1.0] * width,
        "n_fit": 3,
        "class_names": classes,
        "class_grouping": None,
        "grouping_note": None,
        "nonfinite_replacements": {"numeric": 0},
        "unknown_categories_pre_final_raw_unique": {
            split: {column: 0 for column in tool.CATEGORICAL[dataset]}
            for split in tool.SPLITS
        },
        "fit_population":
            "canonical-raw-(X,label)-unique assigned fit patterns before stable-final-(X,label) dedup",
        "model_population": "stable-final-FP32-(X,label)-unique patterns",
    }
    _write_json(directory / "preprocessing.json", preprocessing)
    source_spec = json.loads(
        (package / "audit" / "source_specs" / f"{dataset}.json").read_text(encoding="utf-8")
    )
    projection = [{
        "path": raw_record["files"][0]["path"],
        "role": raw_record["files"][0]["role"],
        "bytes": raw_record["files"][0]["bytes"],
        "sha256": raw_record["files"][0]["sha256"],
    }]
    binding = {
        "schema": 5,
        "dataset": dataset,
        "files": projection,
        "val_fraction": 0.2,
        "split_seed": 20260920,
        "test_seed": 42,
        "chunksize": 65536,
        "implementation_sha256": _sha(package / "data_loaders.py"),
        "contracts_sha256": _sha(package / "contracts.py"),
        "group_protocol_sha256": _sha(package / "group_protocol.py"),
        "numpy": np.__version__,
        "pandas": tool.pd.__version__,
        "sklearn": tool.importlib.metadata.version("scikit-learn"),
        "source_spec": source_spec,
        "source_spec_sha256": raw_record["source_spec_sha256"],
        "raw_audit": {
            "path": str(audit_path.resolve()),
            "sha256": _sha(audit_path),
            "content_sha256": audit["content_sha256"],
            "audit_implementation_sha256": audit["audit_implementation_sha256"],
        },
        "policy": (
            "raw_identity_assignment_component_final_xy_v2; frozen_fold_zero; "
            "fit_only_ordinal_minus1; fit_only_incremental_standard_scaler; "
            "final_fp32_fixed_point"
        ),
    }
    if dataset == "iot23":
        binding["pyarrow"] = tool.importlib.metadata.version("pyarrow")
    files = {
        name: _sha(directory / name) for name in sorted(tool.EXPECTED_CACHE_FILES)
    }
    reason_codes = {
        "1": "duplicate_xy_training_or_combined",
        "2": "official_test_assignment_component_touches_official_train",
        "3": "duplicate_raw_xy_within_official_test",
        "4": "duplicate_final_xy_within_split",
    }
    partition = {
        "protocol_version": "raw_identity_assignment_component_final_xy_v2",
        "role": ("official_train_grouped_validation_and_clean_official_test"
                 if dataset in ("nslkdd", "unsw") else
                 "xy_deduplicated_exact_x_grouped_target_64_16_20"),
        "stratifier": "sklearn.model_selection.StratifiedGroupKFold",
        "objective": "approximate per-class balance over retained labelled patterns",
        "n_splits": 5,
        "fold_index": 0,
        "test_seed": None if dataset in ("nslkdd", "unsw") else 42,
        "validation_seed": 20260920,
        "selection_prohibition":
            "fold zero is fixed before training; no model/test performance may select a fold",
        "raw_rows": 9,
        "retained_rows": 9,
        "excluded_rows": 0,
        "exclusion_reason_counts": {reason: 0 for reason in reason_codes.values()},
        "support": {split: [2, 1] for split in tool.SPLITS},
        "source_multiplicity": {split: 3 for split in tool.SPLITS},
        "raw_unique_patterns": 9,
        "raw_unique_source_multiplicity": 9,
        "stable_final_xy_removed_patterns": 0,
        "official_overlap_source_rows": 0,
        "retained_source_rows": 9,
        "source_rows_reconciled": 9,
        "retained_pattern_fractions": {split: 1 / 3 for split in tool.SPLITS},
        "target_pattern_fractions": (
            None if dataset in ("nslkdd", "unsw")
            else {"fit": 0.64, "validation": 0.16, "test": 0.20}
        ),
    }
    metadata = {
        "schema": 5,
        "dataset": dataset,
        "request_sha256": tool.digest(binding),
        "raw_binding": binding,
        "features": features,
        "class_names": classes,
        "raw_rows": 9,
        "official_train_raw_rows": 6 if dataset in ("nslkdd", "unsw") else None,
        "counts": counts,
        "n_train_validation_patterns": 6,
        "files_sha256": files,
        "scope": "synthetic",
        "upstream_preprocessing_verified": False,
        "exact_model_input_group_leakage_excluded": True,
        "capture_device_time_group_generalization_established": False,
        "raw_model_view_sha256": fingerprint,
        "partition": partition,
        "groups": {
            "raw_identity_groups": 9,
            "final_assignment_components": 9,
            "mixed_label_raw_identity_groups": 0,
            "maximum_raw_identity_group_rows": 1,
            "split_raw_identity_group_counts": {split: 3 for split in tool.SPLITS},
            "split_assignment_component_counts": {split: 3 for split in tool.SPLITS},
            "split_assignment_component_overlap": {
                "fit_vs_validation": 0,
                "fit_vs_test": 0,
                "validation_vs_test": 0,
            },
        },
        "collision_iterations": [{
            "iteration": 0,
            "input_groups": 9,
            "output_groups": 9,
            "new_group_unions": 0,
        }],
        "final_fp32_overlap": {
            "fit_vs_validation": 0,
            "fit_vs_test": 0,
            "validation_vs_test": 0,
        },
        "exclusion_reason_codes": reason_codes,
        "preprocessor_sha256": tool.digest({
            key: value for key, value in preprocessing.items()
            if key not in ("nonfinite_replacements",
                           "unknown_categories_pre_final_raw_unique")
        }),
    }
    metadata["data_fingerprint"] = tool.digest(metadata)
    _write_json(directory / "metadata.json", _seal(metadata))


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    package = _package(tmp_path)
    audit_path, fingerprints = _raw_audit(tmp_path, package)
    raw_audit = json.loads(audit_path.read_text(encoding="utf-8"))
    roots = [tmp_path / "cache_a", tmp_path / "cache_b"]
    for root in roots:
        root.mkdir()
        for dataset in tool.DATASETS:
            (root / f"{dataset}.lock").write_bytes(b"0")
            _cache_dataset(
                root / dataset,
                dataset,
                package,
                raw_audit["datasets"][dataset],
                fingerprints[dataset],
                audit_path,
                raw_audit,
            )
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    for dataset in tool.DATASETS:
        (raw_root / f"{dataset}.csv").write_bytes(b"x")
    provenance_path = tmp_path / "iot23_provenance.json"
    _write_json(provenance_path, _seal({
        "kind": "spikeids_v5_iot23_provenance",
        "comparison_passed": True,
    }))
    monkeypatch.setattr(
        tool,
        "_verify_raw_identity_and_dedup",
        lambda _root, raw, _metadata, _arrays, **_kwargs: fingerprints[raw["record"]["dataset"]],
    )
    monkeypatch.setattr(
        tool,
        "_verify_raw_cache_semantics",
        lambda _raw_root, _raw, _cache_root, _metadata, _arrays: None,
    )
    monkeypatch.setattr(
        tool,
        "_raw_file_snapshot",
        lambda _raw_root, record: {record["dataset"]: "synthetic-stable"},
    )
    monkeypatch.setattr(
        tool,
        "_load_iot_provenance",
        lambda path, _audit, _package, _repository_root: {
            "path": str(path.resolve()),
            "sha256": _sha(path),
            "content_sha256": json.loads(path.read_text(encoding="utf-8"))["content_sha256"],
            "comparison_passed": True,
        },
    )
    return audit_path, roots, package, raw_root, provenance_path


def _reseal_cache(root: Path, dataset: str) -> None:
    directory = root / dataset
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    metadata.pop("content_sha256")
    metadata["files_sha256"] = {
        name: _sha(directory / name) for name in sorted(tool.EXPECTED_CACHE_FILES)
    }
    metadata.pop("data_fingerprint")
    metadata["data_fingerprint"] = tool.digest(metadata)
    _write_json(directory / "metadata.json", _seal(metadata))


def _verify(fixture):
    audit_path, roots, package, raw_root, provenance_path = fixture
    return tool.verify(
        audit_path,
        roots[0],
        roots[1],
        package=package,
        raw_data_root=raw_root,
        iot_provenance_path=provenance_path,
        verifier_path=TOOL_PATH,
    )


def test_accepts_two_independently_built_identical_caches(tmp_path, monkeypatch):
    report = _verify(_fixture(tmp_path, monkeypatch))
    assert report["kind"] == "spikeids_v5_data_acceptance"
    assert report["data_acceptance_passed"] is True
    assert report["two_distinct_fresh_roots"] is True
    assert report["byte_identical_rebuilds"] is True
    assert set(report["raw_audit"]) == {
        "path", "sha256", "content_sha256", "audit_implementation_sha256",
        "raw_source_audit_passed",
    }
    assert set(report["producer"]) == {"path", "sha256"}
    assert set(report["independent_verifier"]) == {"path", "sha256"}
    assert set(report["upstream_provenance"]) == {
        "path", "sha256", "content_sha256", "comparison_passed",
    }
    assert set(report["datasets"]) == set(tool.DATASETS)
    assert all(len(record["rebuilds"]) == 2 for record in report["datasets"].values())
    assert all(
        all(set(rebuild) == {
            "resolved_root", "metadata_sha256", "data_fingerprint", "files_sha256",
        } for rebuild in record["rebuilds"])
        for record in report["datasets"].values()
    )
    assert all(
        set(record["semantic_checks"]) == set(tool.SEMANTIC_CHECK_KEYS) | {"all_passed"}
        and all(record["semantic_checks"].values())
        for record in report["datasets"].values()
    )
    assert set(report["limitations"].values()) == {False}


@pytest.mark.parametrize("bad", ["nan", "negative_zero"])
def test_rejects_coordinated_resealed_nonfinite_or_negative_zero(
    tmp_path, monkeypatch, bad,
):
    fixture = _fixture(tmp_path, monkeypatch)
    for root in fixture[1]:
        path = root / "nslkdd" / "x_fit.npy"
        value = np.load(path, allow_pickle=False)
        value[0, 0] = np.nan if bad == "nan" else np.float32(-0.0)
        np.save(path, value, allow_pickle=False)
        _reseal_cache(root, "nslkdd")
    with pytest.raises(tool.VerificationError):
        _verify(fixture)


def test_rejects_coordinated_resealed_split_group_collision(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    for root in fixture[1]:
        fit = np.load(root / "unsw" / "assignment_components_fit.npy", allow_pickle=False)
        path = root / "unsw" / "assignment_components_validation.npy"
        value = np.load(path, allow_pickle=False)
        value[0] = fit[0]
        np.save(path, value, allow_pickle=False)
        metadata = json.loads((root / "unsw" / "metadata.json").read_text(encoding="utf-8"))
        metadata["groups"]["split_assignment_component_counts"]["validation"] = int(
            len(np.unique(value))
        )
        metadata["groups"]["split_assignment_component_overlap"]["fit_vs_validation"] = 1
        metadata.pop("content_sha256")
        metadata["files_sha256"]["assignment_components_validation.npy"] = _sha(path)
        metadata.pop("data_fingerprint")
        metadata["data_fingerprint"] = tool.digest(metadata)
        _write_json(root / "unsw" / "metadata.json", _seal(metadata))
    with pytest.raises(tool.VerificationError, match="raw-unique|overlap"):
        _verify(fixture)


def test_rejects_coordinated_resealed_row_count_mismatch(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    for root in fixture[1]:
        path = root / "iot23" / "metadata.json"
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata.pop("content_sha256")
        metadata["counts"]["fit"] += 1
        metadata.pop("data_fingerprint")
        metadata["data_fingerprint"] = tool.digest(metadata)
        _write_json(path, _seal(metadata))
    with pytest.raises(tool.VerificationError):
        _verify(fixture)


def test_rejects_same_cache_root(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    audit_path, roots, package, raw_root, provenance_path = fixture
    with pytest.raises(tool.VerificationError, match="distinct"):
        tool.verify(
            audit_path, roots[0], roots[0], package=package,
            raw_data_root=raw_root, iot_provenance_path=provenance_path,
            verifier_path=TOOL_PATH,
        )


def test_rejects_symlinked_cache_file(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    target = fixture[1][0] / "nslkdd" / "x_fit.npy"
    attacked = fixture[1][1] / "nslkdd" / "x_fit.npy"
    attacked.unlink()
    attacked.symlink_to(target)
    with pytest.raises(tool.VerificationError, match="Symlink"):
        _verify(fixture)


def test_rejects_hardlinked_cache_file(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    target = fixture[1][0] / "nslkdd" / "x_fit.npy"
    attacked = fixture[1][1] / "nslkdd" / "x_fit.npy"
    attacked.unlink()
    os.link(target, attacked)
    with pytest.raises(tool.VerificationError, match="Hard-linked"):
        _verify(fixture)


def _mutate_and_restore_same_inode(path: Path) -> None:
    before = path.stat()
    payload = path.read_bytes()
    assert payload
    changed = bytes([payload[0] ^ 1]) + payload[1:]
    with path.open("r+b") as stream:
        stream.write(changed)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())
        stream.seek(0)
        stream.write(payload)
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = path.stat()
    assert after.st_ino == before.st_ino
    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_ctime_ns != before.st_ctime_ns
    assert path.read_bytes() == payload


def test_npy_load_is_private_and_immutable(tmp_path):
    path = tmp_path / "array.npy"
    expected = np.arange(12, dtype=np.float32).reshape(3, 4)
    np.save(path, expected, allow_pickle=False)
    loaded = tool._load_npy(path)
    assert loaded.flags.owndata and loaded.flags.c_contiguous
    assert not loaded.flags.writeable
    assert not isinstance(loaded, np.memmap)
    np.save(path, np.zeros_like(expected), allow_pickle=False)
    assert np.array_equal(loaded, expected)


def test_rejects_npy_mutate_restore_during_same_fd_load(tmp_path, monkeypatch):
    path = tmp_path / "race.npy"
    np.save(path, np.arange(8, dtype=np.int64), allow_pickle=False)
    original_load = tool.np.load

    def racing_load(stream, *args, **kwargs):
        result = original_load(stream, *args, **kwargs)
        _mutate_and_restore_same_inode(path)
        return result

    monkeypatch.setattr(tool.np, "load", racing_load)
    with pytest.raises(tool.VerificationError, match="changed while loading"):
        tool._load_npy(path)


def test_rejects_cache_mutate_restore_during_verification(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path, monkeypatch)
    target = fixture[1][0] / "nslkdd" / "x_fit.npy"
    mutated = False

    def mutate_once(*_args):
        nonlocal mutated
        if not mutated:
            _mutate_and_restore_same_inode(target)
            mutated = True

    monkeypatch.setattr(tool, "_verify_raw_cache_semantics", mutate_once)
    with pytest.raises(tool.VerificationError, match="inode/timestamp"):
        _verify(fixture)


@pytest.mark.parametrize("target_kind", ["tool", "spec", "raw", "evidence"])
def test_rejects_bound_input_mutate_restore_during_verification(
    tmp_path, monkeypatch, target_kind,
):
    fixture = _fixture(tmp_path, monkeypatch)
    audit_path, roots, package, raw_root, provenance_path = fixture
    targets = {
        "tool": package / "data_loaders.py",
        "spec": package / "audit/source_specs/nslkdd.json",
        "raw": raw_root / "nslkdd.csv",
        "evidence": provenance_path,
    }
    target = targets[target_kind]
    mutated = False

    def mutate_once(*_args):
        nonlocal mutated
        if not mutated:
            _mutate_and_restore_same_inode(target)
            mutated = True

    monkeypatch.setattr(tool, "_verify_raw_cache_semantics", mutate_once)
    with pytest.raises(tool.VerificationError, match="tool/spec/raw/evidence"):
        tool.verify(
            audit_path,
            roots[0],
            roots[1],
            package=package,
            raw_data_root=raw_root,
            iot_provenance_path=provenance_path,
            verifier_path=TOOL_PATH,
        )


def test_independently_recomputes_raw_model_view_fingerprint(tmp_path):
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    path = raw_root / "nsl.txt"
    path.write_text(
        "tcp,http,SF,1.5,class0,0\n"
        "udp,dns,S0,-0.0,class1,0\n",
        encoding="utf-8",
    )
    features = ["protocol_type", "service", "flag", "numeric"]
    selected = features + ["label", "difficulty"]
    record = {
        "dataset": "nslkdd",
        "rows": 2,
        "features": features,
        "files": [{
            "path": "nsl.txt",
            "role": "train",
            "bytes": path.stat().st_size,
            "sha256": _sha(path),
            "rows": 2,
            "physical_columns": selected,
            "selected_columns": selected,
            "dropped_physical_column_index": None,
        }],
    }
    matrix = np.array([
        [0, 1, 1, 1.5],
        [1, 0, 0, 0.0],
    ], dtype=np.float32)
    expected = hashlib.sha256()
    expected.update(b"<f4:2:4")
    expected.update(memoryview(matrix).cast("B"))
    assert tool._recompute_raw_model_view_fingerprint(raw_root, record) == expected.hexdigest()


def test_rejects_transient_unknown_collision_that_drops_distinct_final_pattern(tmp_path):
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    raw_path = raw_root / "iot.csv"
    raw_path.write_text(
        "proto,service,conn_state,numeric,label\n"
        "a,http,SF,0,Benign\n"
        "b,http,SF,0,Benign\n"
        "b,http,SF,1,DDoS\n"
        "a,http,SF,2,Benign\n"
        "b,http,SF,3,DDoS\n",
        encoding="utf-8",
    )
    features = ["proto", "service", "conn_state", "numeric"]
    raw_record = {
        "dataset": "iot23",
        "rows": 5,
        "features": features,
        "files": [{
            "path": "iot.csv",
            "role": "combined",
            "bytes": raw_path.stat().st_size,
            "sha256": _sha(raw_path),
            "rows": 5,
            "physical_columns": features + ["label"],
            "selected_columns": features + ["label"],
            "dropped_physical_column_index": None,
        }],
    }
    cache_root = tmp_path / "cache"
    directory = cache_root / "iot23"
    directory.mkdir(parents=True)
    preprocessing = {
        "categories": {
            "proto": ["V:a", "V:b"],
            "service": ["V:http"],
            "conn_state": ["V:SF"],
        },
        "mean": [0.5, 0.0, 0.0, 0.5],
        "var": [0.25, 0.0, 0.0, 0.25],
        "scale": [0.5, 1.0, 1.0, 0.5],
        "n_fit": 2,
        "nonfinite_replacements": {"numeric": 0},
        "unknown_categories_pre_final_raw_unique": {
            split: {column: 0 for column in tool.CATEGORICAL["iot23"]}
            for split in tool.SPLITS
        },
    }
    _write_json(directory / "preprocessing.json", preprocessing)
    # Raw row 1 (proto=b, numeric=0) was incorrectly dropped as a duplicate of
    # row 0 during an earlier unknown-category state.  Because row 2 places b in
    # fit, the final vocabulary separates row 1 from every retained pattern.
    ids_by_split = {
        "fit": np.array([0, 2], dtype=np.int64),
        "validation": np.array([3], dtype=np.int64),
        "test": np.array([4], dtype=np.int64),
    }
    x_by_split = {
        "fit": np.array([[-1, 0, 0, -1], [1, 0, 0, 1]], dtype=np.float32),
        "validation": np.array([[-1, 0, 0, 3]], dtype=np.float32),
        "test": np.array([[1, 0, 0, 5]], dtype=np.float32),
    }
    y_by_split = {
        "fit": np.array([0, 1], dtype=np.int64),
        "validation": np.array([0], dtype=np.int64),
        "test": np.array([1], dtype=np.int64),
    }
    arrays = {
        "excluded_ids": np.array([1], dtype=np.int64),
        "excluded_reasons": np.array([4], dtype=np.uint8),
        "preprocessing_fit_ids": np.array([0, 2], dtype=np.int64),
        "final_dedup_ids": np.array([], dtype=np.int64),
        "final_dedup_origin_splits": np.array([], dtype=np.uint8),
    }
    for split in tool.SPLITS:
        arrays[f"x_{split}"] = x_by_split[split]
        arrays[f"y_{split}"] = y_by_split[split]
        arrays[f"ids_{split}"] = ids_by_split[split]
        arrays[f"multiplicity_{split}"] = np.ones(len(ids_by_split[split]), dtype=np.int64)
    metadata = {
        "dataset": "iot23",
        "raw_rows": 5,
        "official_train_raw_rows": None,
        "counts": {split: len(ids_by_split[split]) for split in tool.SPLITS},
        "features": features,
        "class_names": ["Benign", "DDoS"],
        "exclusion_reason_codes": {
            "1": "duplicate_xy_training_or_combined",
            "2": "official_test_assignment_component_touches_official_train",
            "3": "duplicate_raw_xy_within_official_test",
            "4": "duplicate_final_xy_within_split",
        },
    }
    with pytest.raises(tool.VerificationError, match="distinct final"):
        tool._verify_raw_cache_semantics(
            raw_root,
            {"record": raw_record, "source_spec": {}},
            cache_root,
            metadata,
            arrays,
        )


def _raw_identity_fixture(tmp_path: Path):
    raw_root = tmp_path / "raw_identity"
    raw_root.mkdir()
    train_path = raw_root / "train.txt"
    test_path = raw_root / "test.txt"
    train_path.write_text(
        "tcp,http,SF,0,normal,0\n"
        "tcp,http,SF,0,back,0\n"
        "udp,dns,S0,1,normal,0\n"
        "icmp,x,R,2,back,0\n"
        "udp,dns,S0,1,normal,0\n",
        encoding="utf-8",
    )
    test_path.write_text(
        "tcp,http,SF,0,normal,0\n"
        "a,http,SF,3,normal,0\n"
        "b,http,SF,3,normal,0\n"
        "b,http,SF,3,normal,0\n",
        encoding="utf-8",
    )
    features = ["protocol_type", "service", "flag", "numeric"]
    selected = features + ["label", "difficulty"]
    files = []
    for path, role, rows in ((train_path, "train", 5), (test_path, "test", 4)):
        files.append({
            "path": path.name,
            "role": role,
            "bytes": path.stat().st_size,
            "sha256": _sha(path),
            "rows": rows,
            "physical_columns": selected,
            "selected_columns": selected,
            "dropped_physical_column_index": None,
        })
    raw = {
        "record": {
            "dataset": "nslkdd",
            "rows": 9,
            "features": features,
            "files": files,
        },
        "source_spec": {},
    }
    metadata = {
        "dataset": "nslkdd",
        "raw_rows": 9,
        "features": features,
        "class_names": ["normal", "DoS"],
        "official_train_raw_rows": 5,
        "groups": {
            "raw_identity_groups": 5,
            "maximum_raw_identity_group_rows": 3,
            "mixed_label_raw_identity_groups": 1,
        },
    }
    arrays = {
        "raw_unique_ids": np.array([0, 1, 2, 3, 5, 6, 7], dtype=np.int64),
        # Deliberately non-dense/arbitrary names: equivalence, not numeric ID,
        # is the contract under independent verification.
        "raw_unique_identity_groups": np.array(
            [99, 99, 7, 42, 99, 5, 1000], dtype=np.int64,
        ),
        "raw_unique_labels": np.array([0, 1, 0, 1, 0, 0, 0], dtype=np.int64),
        "raw_unique_multiplicity": np.array([1, 1, 2, 1, 1, 1, 2], dtype=np.int64),
        "excluded_ids": np.array([4, 8], dtype=np.int64),
        "excluded_reasons": np.array([1, 3], dtype=np.uint8),
    }
    return raw_root, raw, metadata, arrays


def test_raw_identity_verification_is_invariant_to_group_id_renaming(tmp_path):
    raw_root, raw, metadata, arrays = _raw_identity_fixture(tmp_path)
    fingerprint = tool._verify_raw_identity_and_dedup(
        raw_root, raw, metadata, arrays,
    )
    assert fingerprint == tool._recompute_raw_model_view_fingerprint(
        raw_root, raw["record"],
    )


@pytest.mark.parametrize(
    ("victim", "reason", "representative", "attack"),
    [
        (1, 1, 0, "mixed-label identity collapsed as a raw duplicate"),
        (5, 3, 0, "cross-role duplicate collapsed across the official boundary"),
        (6, 3, 7, "distinct unknown-category identities collapsed before final encoding"),
    ],
)
def test_rejects_coordinated_false_raw_duplicate_reason(
    tmp_path, victim, reason, representative, attack,
):
    raw_root, raw, metadata, arrays = _raw_identity_fixture(tmp_path)
    keep = arrays["raw_unique_ids"] != victim
    arrays["raw_unique_ids"] = arrays["raw_unique_ids"][keep]
    arrays["raw_unique_identity_groups"] = arrays["raw_unique_identity_groups"][keep]
    arrays["raw_unique_labels"] = arrays["raw_unique_labels"][keep]
    arrays["raw_unique_multiplicity"] = arrays["raw_unique_multiplicity"][keep]
    representative_position = int(np.flatnonzero(
        arrays["raw_unique_ids"] == representative,
    )[0])
    arrays["raw_unique_multiplicity"][representative_position] += 1
    attacked_ids = np.r_[arrays["excluded_ids"], np.int64(victim)]
    attacked_reasons = np.r_[arrays["excluded_reasons"], np.uint8(reason)]
    attack_order = np.argsort(attacked_ids)
    arrays["excluded_ids"] = attacked_ids[attack_order]
    arrays["excluded_reasons"] = attacked_reasons[attack_order]
    with pytest.raises(
        tool.VerificationError,
        match="Raw exact-\\(X,label\\) representatives/multiplicity differ",
    ):
        tool._verify_raw_identity_and_dedup(raw_root, raw, metadata, arrays)
