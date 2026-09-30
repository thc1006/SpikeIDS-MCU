#!/usr/bin/env python3
"""Independent, fail-closed acceptance verifier for two v5 cache rebuilds.

This module deliberately does not import the cache producer.  It validates the
two on-disk rebuilds, re-reads the pinned raw inputs to reproduce the producer's
ordered canonical-model-view digest, and emits one sealed acceptance record.
An unkeyed digest is an integrity check, not an external authenticity claim.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import re
import stat
import tempfile
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "spikeids_v5"
RAW_DATA_ROOT = ROOT / "data"
DATASETS = ("nslkdd", "unsw", "cicids2017", "iot23")
SPLITS = ("fit", "validation", "test")
CATEGORICAL = {
    "nslkdd": ("protocol_type", "service", "flag"),
    "unsw": ("proto", "service", "state"),
    "cicids2017": (),
    "iot23": ("proto", "service", "conn_state"),
}
NSL_LABEL_MAP = {"normal": "normal"}
for _nsl_family, _nsl_attacks in {
    "DoS": "back land neptune pod smurf teardrop mailbomb apache2 processtable udpstorm",
    "Probe": "ipsweep nmap portsweep satan mscan saint",
    "R2L": (
        "ftp_write guess_passwd imap multihop phf spy warezclient warezmaster "
        "sendmail named snmpgetattack snmpguess xlock xsnoop worm"
    ),
    "U2R": "buffer_overflow loadmodule perl rootkit httptunnel ps sqlattack xterm",
}.items():
    NSL_LABEL_MAP.update({attack: _nsl_family for attack in _nsl_attacks.split()})
IOT_LABEL_MAP = {
    "Benign": "Benign",
    "DDoS": "DDoS",
    "Okiru": "Okiru",
    "Okiru-Attack": "Okiru",
    "PartOfAHorizontalPortScan": "PortScan",
    **{
        value: "C&C" for value in (
            "C&C", "C&C-HeartBeat", "Attack", "C&C-FileDownload", "C&C-Torii",
            "FileDownload", "C&C-HeartBeat-FileDownload", "C&C-Mirai",
        )
    },
}
IOT_ORIGIN_COLUMNS = (
    "ts", "uid", "id.orig_h", "id.orig_p", "id.resp_h", "id.resp_p", "proto",
    "service", "duration", "orig_bytes", "resp_bytes", "conn_state", "local_orig",
    "local_resp", "missed_bytes", "history", "orig_pkts", "orig_ip_bytes",
    "resp_pkts", "resp_ip_bytes", "label",
)
IOT_PROVENANCE_LIMITATIONS = {
    "original_iot23_reconstruction_established",
    "upstream_publisher_preprocessing_reproduced",
    "device_group_generalization_established",
    "capture_group_generalization_established",
    "time_group_generalization_established",
    "external_authenticity_established",
}
ARRAY_PREFIXES = (
    "x", "y", "ids", "identity_groups", "assignment_components", "multiplicity",
)
GLOBAL_ARRAYS = (
    "excluded_ids",
    "excluded_reasons",
    "raw_unique_ids",
    "raw_unique_identity_groups",
    "raw_unique_assignment_components",
    "raw_unique_labels",
    "raw_unique_multiplicity",
    "preprocessing_fit_ids",
    "final_dedup_ids",
    "final_dedup_representative_ids",
    "final_dedup_origin_splits",
)
EXPECTED_CACHE_FILES = {
    *(f"{prefix}_{split}.npy" for split in SPLITS for prefix in ARRAY_PREFIXES),
    *(f"{name}.npy" for name in GLOBAL_ARRAYS),
    "preprocessing.json",
}
EXCLUSION_REASONS = {
    1: "duplicate_xy_training_or_combined",
    2: "official_test_assignment_component_touches_official_train",
    3: "duplicate_raw_xy_within_official_test",
    4: "duplicate_final_xy_within_split",
}
SEMANTIC_CHECK_KEYS = (
    "inventory_complete",
    "seals_valid",
    "code_binding_valid",
    "shapes_valid",
    "dtypes_valid",
    "finite_values",
    "canonical_zero",
    "id_accounting_exact",
    "class_support_complete",
    "multiplicity_valid",
    "exclusion_reasons_valid",
    "zero_group_overlap",
    "zero_final_fp32_overlap",
    "raw_model_view_fingerprint_valid",
    "frozen_partition_and_closure_replayed",
)
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class VerificationError(ValueError):
    """An acceptance input is missing, unsafe, inconsistent, or stale."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    def bad_constant(value: str) -> None:
        raise VerificationError(f"Non-finite JSON constant {value}: {path}")

    try:
        payload, _snapshot = _capture_file(path, collect_bytes=True)
        require(payload is not None, f"JSON bytes were not captured: {path}")
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_json_pairs,
            parse_constant=bad_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"Cannot read strict JSON: {path}: {exc}") from exc


def json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VerificationError(f"Value is not canonical finite JSON: {exc}") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()


def sha256(path: Path) -> str:
    _payload, snapshot = _capture_file(path, collect_bytes=False)
    return str(snapshot["sha256"])


def check_seal(value: object, *, key: str = "content_sha256") -> dict:
    require(isinstance(value, dict), "Sealed JSON value must be an object")
    record = value
    claimed = record.get(key)
    require(isinstance(claimed, str) and HEX64.fullmatch(claimed) is not None,
            f"Missing or malformed {key}")
    require(claimed == digest({name: item for name, item in record.items() if name != key}),
            f"Integrity failure: {key}")
    return record


def seal(value: dict) -> dict:
    require("content_sha256" not in value, "Cannot seal an already sealed object")
    return {**value, "content_sha256": digest(value)}


def _assert_no_symlink_components(path: Path, *, include_leaf: bool = True) -> None:
    absolute = path.absolute()
    parts = absolute.parts
    current = Path(parts[0])
    stop = len(parts) if include_leaf else len(parts) - 1
    for part in parts[1:stop]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise VerificationError(f"Missing/unreadable path component: {current}") from exc
        require(not stat.S_ISLNK(mode), f"Symlink path component is forbidden: {current}")


def _stat_signature(status: os.stat_result) -> tuple[int, ...]:
    return (
        status.st_dev,
        status.st_ino,
        status.st_mode,
        status.st_nlink,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _capture_file(
    path: Path,
    *,
    collect_bytes: bool,
    after_ns: int | None = None,
) -> tuple[bytes | None, dict[str, int | str]]:
    """Hash/read one regular file through one FD and prove path/FD stability."""
    _assert_no_symlink_components(path)
    try:
        path_before = path.lstat()
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise VerificationError(f"Cannot open stable regular file: {path}: {exc}") from exc
    chunks: list[bytes] | None = [] if collect_bytes else None
    result = hashlib.sha256()
    try:
        fd_before = os.fstat(descriptor)
        require(stat.S_ISREG(path_before.st_mode) and stat.S_ISREG(fd_before.st_mode),
                f"Expected a regular non-symlink file: {path}")
        require(path_before.st_nlink == fd_before.st_nlink == 1,
                f"Hard-linked input is forbidden: {path}")
        require(_stat_signature(path_before) == _stat_signature(fd_before),
                f"File path changed while opening: {path}")
        if after_ns is not None:
            require(fd_before.st_mtime_ns >= after_ns,
                    f"Cache artifact predates the raw audit and is not fresh: {path}")
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            result.update(block)
            if chunks is not None:
                chunks.append(block)
        fd_after = os.fstat(descriptor)
        require(_stat_signature(fd_after) == _stat_signature(fd_before),
                f"File changed while being read: {path}")
    except OSError as exc:
        raise VerificationError(f"Cannot read stable regular file: {path}: {exc}") from exc
    finally:
        os.close(descriptor)
    try:
        path_after = path.lstat()
    except OSError as exc:
        raise VerificationError(f"File path disappeared after reading: {path}") from exc
    require(_stat_signature(path_after) == _stat_signature(fd_before),
            f"File path changed while being read: {path}")
    snapshot: dict[str, int | str] = {
        "device": fd_before.st_dev,
        "inode": fd_before.st_ino,
        "mode": fd_before.st_mode,
        "links": fd_before.st_nlink,
        "bytes": fd_before.st_size,
        "mtime_ns": fd_before.st_mtime_ns,
        "ctime_ns": fd_before.st_ctime_ns,
        "sha256": result.hexdigest(),
    }
    return (b"".join(chunks) if chunks is not None else None), snapshot


def _file_snapshot(path: Path, *, after_ns: int | None = None) -> dict[str, int | str]:
    return _capture_file(path, collect_bytes=False, after_ns=after_ns)[1]


def _regular_file(path: Path, *, after_ns: int | None = None) -> os.stat_result:
    _assert_no_symlink_components(path)
    try:
        status = path.lstat()
    except OSError as exc:
        raise VerificationError(f"Missing/unreadable file: {path}") from exc
    require(stat.S_ISREG(status.st_mode), f"Expected a regular non-symlink file: {path}")
    require(status.st_nlink == 1, f"Hard-linked input is forbidden: {path}")
    if after_ns is not None:
        require(status.st_mtime_ns >= after_ns,
                f"Cache artifact predates the raw audit and is not fresh: {path}")
    return status


def _real_directory(path: Path) -> tuple[Path, os.stat_result]:
    _assert_no_symlink_components(path)
    try:
        status = path.lstat()
    except OSError as exc:
        raise VerificationError(f"Missing/unreadable directory: {path}") from exc
    require(stat.S_ISDIR(status.st_mode), f"Expected a real directory: {path}")
    return path.resolve(), status


def _contained_file(base: Path, relative: str, *, after_ns: int | None = None) -> Path:
    require(isinstance(relative, str) and relative not in ("", "."),
            "File inventory contains an invalid relative path")
    rel = Path(relative)
    require(not rel.is_absolute() and ".." not in rel.parts,
            f"Absolute/escaping inventory path is forbidden: {relative}")
    path = base / rel
    _regular_file(path, after_ns=after_ns)
    require(path.resolve().is_relative_to(base.resolve()),
            f"Inventory path escapes its root: {relative}")
    return path


def _write_new_json(path: Path, value: dict) -> None:
    require(path.name == "data_acceptance.json",
            "Acceptance output must be named data_acceptance.json")
    require(not path.exists() and not path.is_symlink(),
            "Acceptance output must be a fresh path")
    parent, _ = _real_directory(path.parent)
    require(path.parent.resolve() == parent, "Acceptance output parent changed during validation")
    payload = json.dumps(
        value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False,
    ).encode("utf-8") + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        require(not path.exists() and not path.is_symlink(),
                "Acceptance output appeared during verification")
        os.link(temporary, path)
        os.unlink(temporary)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _strict_keys(value: object, keys: set[str], label: str) -> dict:
    require(isinstance(value, dict), f"{label} must be an object")
    require(set(value) == keys,
            f"{label} keys differ: missing={sorted(keys - set(value))}, "
            f"unexpected={sorted(set(value) - keys)}")
    return value


def _finite_number(value: object, label: str) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool),
            f"{label} must be numeric")
    result = float(value)
    require(math.isfinite(result), f"{label} must be finite")
    return result


def _load_raw_audit(path: Path, package: Path) -> tuple[dict, dict[str, dict], int]:
    audit_snapshot = _file_snapshot(path)
    audit = check_seal(load_json(path))
    require(_file_snapshot(path) == audit_snapshot,
            "Raw audit changed while it was parsed")
    require(audit.get("audit_schema") == 3,
            "Unsupported raw-audit schema")
    require(audit.get("raw_source_audit_passed") is True,
            "Raw-source audit did not pass")
    require(audit.get("data_acceptance_passed") is False,
            "Raw audit must not self-assert final data acceptance")
    require(isinstance(audit.get("data_acceptance_blocker"), str) and
            audit["data_acceptance_blocker"], "Raw audit omits its acceptance blocker")
    datasets = audit.get("datasets")
    require(isinstance(datasets, dict) and set(datasets) == set(DATASETS),
            "Raw audit must contain exactly the four formal datasets")
    fingerprint = audit.get("audit_fingerprint")
    require(isinstance(fingerprint, str) and HEX64.fullmatch(fingerprint) is not None and
            fingerprint == digest({key: value for key, value in audit.items()
                                  if key not in ("content_sha256", "audit_fingerprint")}),
            "Raw-audit semantic fingerprint is invalid")
    audit_source = package / "audit_data.py"
    loader_source = package / "data_loaders.py"
    _regular_file(audit_source)
    _regular_file(loader_source)
    require(audit.get("audit_implementation_sha256") == sha256(audit_source),
            "Raw audit is not bound to the current audit implementation")
    require(audit.get("data_loader_sha256") == sha256(loader_source),
            "Raw audit is not bound to the current cache producer")
    checked: dict[str, dict] = {}
    for name in DATASETS:
        record = datasets[name]
        require(isinstance(record, dict) and record.get("dataset") == name,
                f"Malformed raw-audit dataset record: {name}")
        require(type(record.get("rows")) is int and record["rows"] > 0,
                f"Invalid raw row count: {name}")
        features = record.get("features")
        classes = record.get("classes")
        require(isinstance(features, list) and features and len(features) == len(set(features)) and
                all(isinstance(item, str) and item for item in features),
                f"Invalid ordered feature schema: {name}")
        require(isinstance(classes, list) and len(classes) >= 2 and
                len(classes) == len(set(classes)) and
                all(isinstance(item, str) and item for item in classes),
                f"Invalid class schema: {name}")
        spec_relative = record.get("source_spec")
        require(isinstance(spec_relative, str), f"Missing source spec: {name}")
        spec_path = _contained_file(package, spec_relative)
        spec_snapshot = _file_snapshot(spec_path)
        require(record.get("source_spec_sha256") == spec_snapshot["sha256"],
                f"Source-spec bytes changed: {name}")
        spec = load_json(spec_path)
        require(_file_snapshot(spec_path) == spec_snapshot,
                f"Source spec changed while it was parsed: {name}")
        require(isinstance(spec, dict) and spec.get("dataset") == name,
                f"Source-spec dataset mismatch: {name}")
        raw_files = record.get("files")
        require(isinstance(raw_files, list) and raw_files,
                f"Raw-audit file inventory is empty: {name}")
        expected_projection = []
        total_rows = 0
        for item in raw_files:
            require(isinstance(item, dict), f"Malformed raw file record: {name}")
            relative = item.get("path")
            role = item.get("role")
            claimed_hash = item.get("sha256")
            claimed_bytes = item.get("bytes")
            rows = item.get("rows")
            require(isinstance(relative, str) and isinstance(role, str) and
                    isinstance(claimed_hash, str) and HEX64.fullmatch(claimed_hash) is not None and
                    type(claimed_bytes) is int and claimed_bytes >= 0 and
                    type(rows) is int and rows > 0,
                    f"Malformed raw file identity: {name}")
            expected_projection.append({
                "path": relative,
                "role": role,
                "bytes": claimed_bytes,
                "sha256": claimed_hash,
            })
            total_rows += rows
        require(total_rows == record["rows"], f"Raw file rows do not reconcile: {name}")
        checked[name] = {
            "record": record,
            "source_spec": spec,
            "file_projection": expected_projection,
        }
    return audit, checked, int(audit_snapshot["mtime_ns"])


def _evidence_path(value: object, repository_root: Path, label: str) -> Path:
    require(isinstance(value, str) and value, f"{label} path is absent")
    path = Path(value)
    if not path.is_absolute():
        path = repository_root / path
    path = path.absolute()
    _regular_file(path)
    return path.resolve()


def _load_iot_provenance(path: Path, audit: dict, package: Path,
                         repository_root: Path) -> dict[str, object]:
    report_snapshot = _file_snapshot(path)
    require(path.resolve() == (package / "audit/iot23_provenance.json").resolve(),
            "IoT-23 provenance evidence must use the fixed formal path")
    report_sha = str(report_snapshot["sha256"])
    report = check_seal(load_json(path))
    require(report.get("kind") == "spikeids_v5_iot23_provenance" and
            report.get("schema") == 1 and report.get("comparison_passed") is True and
            report.get("passed") is True,
            "IoT-23 upstream provenance comparison did not pass")
    require(set(report.get("limitations", {})) == IOT_PROVENANCE_LIMITATIONS and
            all(value is False for value in report["limitations"].values()),
            "IoT-23 provenance limitations are missing or overclaimed")

    tool_record = report.get("tool")
    require(isinstance(tool_record, dict) and set(tool_record) == {"path", "sha256"},
            "IoT-23 provenance tool binding is malformed")
    provenance_tool = _evidence_path(
        tool_record["path"], repository_root, "IoT-23 provenance tool",
    )
    require(provenance_tool == (repository_root / "tools/verify_iot23_provenance.py").resolve() and
            tool_record["sha256"] == sha256(provenance_tool),
            "IoT-23 provenance report is not bound to the current comparison tool")
    provenance_tool_snapshot = _file_snapshot(provenance_tool)

    spec_record = report.get("source_spec")
    require(isinstance(spec_record, dict) and
            set(spec_record) == {"path", "bytes", "sha256"},
            "IoT-23 provenance source-spec binding is malformed")
    source_spec = _evidence_path(
        spec_record["path"], repository_root, "IoT-23 provenance source spec",
    )
    expected_spec = (package / "audit/source_specs/iot23.json").resolve()
    audit_iot = audit["datasets"]["iot23"]
    source_spec_snapshot = _file_snapshot(source_spec)
    require(source_spec == expected_spec and
            spec_record["bytes"] == source_spec_snapshot["bytes"] and
            spec_record["sha256"] == source_spec_snapshot["sha256"] ==
            audit_iot["source_spec_sha256"],
            "IoT-23 provenance source spec differs from the raw audit")
    source_spec_value = load_json(source_spec)
    require(report.get("origin_revision") ==
            source_spec_value.get("origin", {}).get("revision"),
            "IoT-23 provenance revision differs from the source contract")

    shard_records = report.get("origin_shards")
    declared_shards = source_spec_value.get("origin_shards")
    require(isinstance(shard_records, list) and isinstance(declared_shards, list) and
            len(shard_records) == len(declared_shards) == 3,
            "IoT-23 provenance must bind exactly three origin shards")
    origin_root = repository_root / "data/iot23_origin"
    shard_snapshots = []
    for index, (reported, declared) in enumerate(zip(
            shard_records, declared_shards, strict=True)):
        require(isinstance(reported, dict) and isinstance(declared, dict),
                f"Malformed IoT-23 origin shard record: {index}")
        identity = {key: reported.get(key) for key in ("path", "bytes", "sha256")}
        expected = {
            "path": declared.get("path"),
            "bytes": declared.get("bytes"),
            "sha256": declared.get("lfs_sha256"),
        }
        require(identity == expected and reported.get("rows", 0) > 0 and
                isinstance(reported.get("physical_schema"), dict),
                f"IoT-23 origin shard report differs from source contract: {index}")
        shard_path = _contained_file(origin_root, expected["path"])
        snapshot = _file_snapshot(shard_path)
        require(snapshot["bytes"] == expected["bytes"] and
                snapshot["sha256"] == expected["sha256"],
                f"IoT-23 origin shard bytes differ: {index}")
        shard_snapshots.append((shard_path, snapshot))

    combined = report.get("combined")
    declared_combined = source_spec_value.get("files", [None])[0]
    require(isinstance(combined, dict) and isinstance(declared_combined, dict) and
            {key: combined.get(key) for key in ("path", "bytes", "sha256", "rows")} == {
                "path": declared_combined.get("path"),
                "bytes": declared_combined.get("bytes"),
                "sha256": declared_combined.get("sha256"),
                "rows": declared_combined.get("expected_rows"),
            } and isinstance(combined.get("physical_schema"), dict),
            "IoT-23 combined provenance binding differs from the source contract")
    audited_iot_file = audit_iot.get("files")
    require(isinstance(audited_iot_file, list) and len(audited_iot_file) == 1 and
            {key: audited_iot_file[0].get(key) for key in ("path", "bytes", "sha256", "rows")} ==
            {key: combined.get(key) for key in ("path", "bytes", "sha256", "rows")},
            "IoT-23 combined provenance binding differs from the raw audit")
    combined_path = _contained_file(repository_root / "data", combined["path"])
    combined_snapshot = _file_snapshot(combined_path)
    require(combined_snapshot["bytes"] == combined["bytes"] and
            combined_snapshot["sha256"] == combined["sha256"],
            "IoT-23 combined bytes changed after provenance comparison")

    semantic = report.get("semantic_comparison")
    require(isinstance(semantic, dict) and semantic.get("rows") == combined["rows"] and
            semantic.get("columns") == list(IOT_ORIGIN_COLUMNS) and
            semantic.get("chunk_rows") == 65536 and
            type(semantic.get("chunks")) is int and semantic["chunks"] > 0 and
            all(semantic.get(key) is True for key in (
                "column_order_equal", "row_order_equal", "values_equal",
                "missingness_equal",
            )) and isinstance(semantic.get("normalizations"), list) and
            type(semantic.get("parquet_schema_metadata_equal")) is bool and
            semantic.get("parquet_schema_metadata_is_semantic") is False,
            "IoT-23 semantic comparison evidence is incomplete")

    # Recheck all byte identities after parsing and hashing the evidence graph.
    require(_file_snapshot(path) == report_snapshot,
            "IoT-23 provenance report changed during acceptance")
    require(_file_snapshot(source_spec) == source_spec_snapshot,
            "IoT-23 source spec changed during acceptance")
    require(_file_snapshot(provenance_tool) == provenance_tool_snapshot,
            "IoT-23 provenance tool changed during acceptance")
    require(_file_snapshot(combined_path) == combined_snapshot,
            "IoT-23 combined file changed during acceptance")
    for shard_path, snapshot in shard_snapshots:
        require(_file_snapshot(shard_path) == snapshot,
                f"IoT-23 origin shard changed during acceptance: {shard_path.name}")
    return {
        "path": str(path.resolve()),
        "sha256": report_sha,
        "content_sha256": report["content_sha256"],
        "comparison_passed": True,
    }


def _cache_root_inventory(root: Path, *, after_ns: int) -> dict[str, dict[str, object]]:
    expected_root = set(DATASETS) | {f"{name}.lock" for name in DATASETS}
    try:
        actual_root = {entry.name for entry in os.scandir(root)}
    except OSError as exc:
        raise VerificationError(f"Cannot inventory cache root: {root}") from exc
    require(actual_root == expected_root,
            f"Cache-root inventory differs: missing={sorted(expected_root - actual_root)}, "
            f"unexpected={sorted(actual_root - expected_root)}")
    inventory: dict[str, dict[str, object]] = {}
    for dataset in DATASETS:
        lock = _contained_file(root, f"{dataset}.lock", after_ns=after_ns)
        require(lock.read_bytes() == b"0", f"Unexpected cache lock content: {lock}")
        inventory[f"{dataset}.lock"] = {
            "bytes": lock.stat().st_size,
            "sha256": sha256(lock),
        }
        directory, _ = _real_directory(root / dataset)
        require(directory.parent == root, f"Dataset cache escapes root: {dataset}")
        expected_dataset = EXPECTED_CACHE_FILES | {"metadata.json"}
        actual_dataset = {entry.name for entry in os.scandir(directory)}
        require(actual_dataset == expected_dataset,
                f"Cache inventory differs for {dataset}: "
                f"missing={sorted(expected_dataset - actual_dataset)}, "
                f"unexpected={sorted(actual_dataset - expected_dataset)}")
        for filename in sorted(expected_dataset):
            item = _contained_file(directory, filename, after_ns=after_ns)
            inventory[f"{dataset}/{filename}"] = {
                "bytes": item.stat().st_size,
                "sha256": sha256(item),
            }
    return inventory


def _stability_record(status: os.stat_result) -> dict[str, int]:
    return {
        "device": status.st_dev,
        "inode": status.st_ino,
        "mode": status.st_mode,
        "links": status.st_nlink,
        "bytes": status.st_size,
        "mtime_ns": status.st_mtime_ns,
        "ctime_ns": status.st_ctime_ns,
    }


def _cache_root_stability(root: Path, *, after_ns: int) -> dict[str, dict[str, int]]:
    """Capture identity/timestamps separately from cross-root byte equality."""
    root_real, root_status = _real_directory(root)
    require(root_real == root, f"Cache root changed identity: {root}")
    result = {".": _stability_record(root_status)}
    for dataset in DATASETS:
        lock = root / f"{dataset}.lock"
        result[f"{dataset}.lock"] = _stability_record(
            _regular_file(lock, after_ns=after_ns),
        )
        directory, directory_status = _real_directory(root / dataset)
        require(directory == root / dataset,
                f"Dataset cache directory changed identity: {dataset}")
        result[dataset] = _stability_record(directory_status)
        for filename in sorted(EXPECTED_CACHE_FILES | {"metadata.json"}):
            item = directory / filename
            result[f"{dataset}/{filename}"] = _stability_record(
                _regular_file(item, after_ns=after_ns),
            )
    return result


def _input_stability(paths: Iterator[Path] | list[Path]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for path in paths:
        absolute = path.absolute()
        status = _regular_file(absolute)
        resolved = absolute.resolve()
        key = str(resolved)
        if key in result:
            continue
        result[key] = _stability_record(status)
    return result


def _load_npy(path: Path) -> np.ndarray:
    _assert_no_symlink_components(path)
    try:
        path_before = path.lstat()
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
    except (OSError, ValueError, EOFError) as exc:
        raise VerificationError(f"Invalid non-pickled NPY: {path}: {exc}") from exc
    try:
        fd_before = os.fstat(descriptor)
        require(stat.S_ISREG(path_before.st_mode) and stat.S_ISREG(fd_before.st_mode) and
                path_before.st_nlink == fd_before.st_nlink == 1 and
                _stat_signature(path_before) == _stat_signature(fd_before),
                f"NPY path changed while opening: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            loaded = np.load(stream, allow_pickle=False)
        fd_after = os.fstat(descriptor)
        require(_stat_signature(fd_after) == _stat_signature(fd_before),
                f"NPY changed while loading: {path}")
    except (OSError, ValueError, EOFError) as exc:
        raise VerificationError(f"Invalid non-pickled NPY: {path}: {exc}") from exc
    finally:
        os.close(descriptor)
    try:
        path_after = path.lstat()
    except OSError as exc:
        raise VerificationError(f"NPY path disappeared after loading: {path}") from exc
    require(_stat_signature(path_after) == _stat_signature(fd_before),
            f"NPY path changed while loading: {path}")
    require(isinstance(loaded, np.ndarray), f"NPY did not contain one array: {path}")
    result = np.array(loaded, copy=True, order="C", subok=False)
    require(result.flags.c_contiguous and result.flags.owndata and
            not isinstance(result, np.memmap),
            f"NPY did not load into private C-contiguous storage: {path}")
    result.setflags(write=False)
    return result


def _row_keys(matrix: np.ndarray) -> np.ndarray:
    array = np.ascontiguousarray(matrix)
    require(array.ndim == 2 and array.shape[1] > 0,
            "Exact-row comparison requires a nonempty-width matrix")
    return array.view(np.dtype((np.void, array.dtype.itemsize * array.shape[1]))).reshape(-1)


def _exact_overlap(matrices: Mapping[str, np.ndarray]) -> dict[str, int]:
    keys = {name: np.unique(_row_keys(np.asarray(matrices[name], dtype=np.float32)))
            for name in SPLITS}
    return {
        f"{left}_vs_{right}": int(np.intersect1d(keys[left], keys[right]).size)
        for left, right in (("fit", "validation"), ("fit", "test"),
                            ("validation", "test"))
    }


def _validate_preprocessing(path: Path, metadata: dict, dataset: str) -> None:
    preprocessor = load_json(path)
    require(isinstance(preprocessor, dict), f"Malformed preprocessing JSON: {dataset}")
    semantic = {key: value for key, value in preprocessor.items()
                if key not in ("nonfinite_replacements",
                               "unknown_categories_pre_final_raw_unique")}
    require(metadata.get("preprocessor_sha256") == digest(semantic),
            f"Preprocessor semantic digest differs: {dataset}")
    features = metadata["features"]
    classes = metadata["class_names"]
    require(preprocessor.get("feature_columns") == features and
            preprocessor.get("class_names") == classes,
            f"Preprocessor schema differs from metadata: {dataset}")
    require(preprocessor.get("categorical_columns") == list(CATEGORICAL[dataset]),
            f"Categorical preprocessing schema differs: {dataset}")
    require(set(CATEGORICAL[dataset]) <= set(features),
            f"Categorical columns are absent from the feature schema: {dataset}")
    categories = preprocessor.get("categories")
    require(isinstance(categories, dict) and set(categories) == set(CATEGORICAL[dataset]),
            f"Categorical vocabulary keys differ: {dataset}")
    for column, values in categories.items():
        require(isinstance(values, list) and values and values == sorted(set(values)) and
                all(isinstance(item, str) for item in values),
                f"Categorical vocabulary is not sorted and unique: {dataset}/{column}")
    width = len(features)
    for key in ("mean", "var", "scale"):
        values = preprocessor.get(key)
        require(isinstance(values, list) and len(values) == width,
                f"Preprocessor {key} width differs: {dataset}")
        parsed = [_finite_number(item, f"{dataset}/{key}") for item in values]
        if key == "var":
            require(all(item >= 0 for item in parsed), f"Negative scaler variance: {dataset}")
        if key == "scale":
            require(all(item > 0 for item in parsed), f"Non-positive scaler scale: {dataset}")
    require(preprocessor.get("fit_population") ==
            "canonical-raw-(X,label)-unique assigned fit patterns before stable-final-(X,label) dedup" and
            preprocessor.get("model_population") ==
            "stable-final-FP32-(X,label)-unique patterns",
            f"Preprocessing/model population declaration differs: {dataset}")
    replacements = preprocessor.get("nonfinite_replacements")
    require(isinstance(replacements, dict) and
            all(isinstance(key, str) and type(value) is int and value >= 0
                for key, value in replacements.items()),
            f"Invalid non-finite replacement diagnostics: {dataset}")
    unknown = preprocessor.get("unknown_categories_pre_final_raw_unique")
    require(isinstance(unknown, dict) and set(unknown) == set(SPLITS),
            f"Invalid unknown-category diagnostics: {dataset}")
    for split in SPLITS:
        require(isinstance(unknown[split], dict) and
                set(unknown[split]) == set(CATEGORICAL[dataset]) and
                all(type(value) is int and value >= 0 for value in unknown[split].values()),
                f"Invalid unknown-category count: {dataset}/{split}")


def _validate_one_cache(
    root: Path,
    dataset: str,
    raw: dict,
    package: Path,
) -> tuple[dict, dict[str, np.ndarray], dict[str, object]]:
    directory = root / dataset
    metadata = check_seal(load_json(directory / "metadata.json"))
    require(metadata.get("dataset") == dataset, f"Cache dataset mismatch: {dataset}")
    claimed_fingerprint = metadata.get("data_fingerprint")
    require(isinstance(claimed_fingerprint, str) and
            claimed_fingerprint == digest({key: value for key, value in metadata.items()
                                          if key not in ("content_sha256", "data_fingerprint")}),
            f"Cache semantic fingerprint is invalid: {dataset}")
    require(metadata.get("raw_rows") == raw["record"]["rows"] and
            metadata.get("features") == raw["record"]["features"] and
            metadata.get("class_names") == raw["record"]["classes"],
            f"Cache/raw-audit schema differs: {dataset}")
    binding = metadata.get("raw_binding")
    require(isinstance(binding, dict) and binding.get("dataset") == dataset,
            f"Missing cache raw binding: {dataset}")
    require(metadata.get("request_sha256") == digest(binding),
            f"Cache request binding is invalid: {dataset}")
    expected_binding_keys = {
        "schema", "dataset", "files", "val_fraction", "split_seed", "test_seed",
        "chunksize", "implementation_sha256", "contracts_sha256",
        "group_protocol_sha256", "numpy", "pandas", "sklearn", "source_spec",
        "source_spec_sha256", "raw_audit", "policy",
    }
    if dataset == "iot23":
        expected_binding_keys.add("pyarrow")
    require(set(binding) == expected_binding_keys and
            binding.get("numpy") == np.__version__ and
            binding.get("pandas") == pd.__version__ and
            binding.get("sklearn") == importlib.metadata.version("scikit-learn") and
            (dataset != "iot23" or
             binding.get("pyarrow") == importlib.metadata.version("pyarrow")),
            f"Cache runtime/source binding schema differs: {dataset}")
    require(binding.get("schema") == 5 and metadata.get("schema") == 5 and
            binding.get("val_fraction") == 0.2 and
            binding.get("split_seed") == 20260920 and
            binding.get("test_seed") == 42 and
            binding.get("chunksize") == 65536 and
            binding.get("policy") ==
            "raw_identity_assignment_component_final_xy_v2; frozen_fold_zero; "
            "fit_only_ordinal_minus1; fit_only_incremental_standard_scaler; "
            "final_fp32_fixed_point",
            f"Cache preparation protocol differs from the formal contract: {dataset}")
    require(binding.get("files") == raw["file_projection"],
            f"Cache/raw-audit file identity differs: {dataset}")
    require(binding.get("source_spec") == raw["source_spec"],
            f"Cache/raw-audit source spec differs: {dataset}")
    require(binding.get("source_spec_sha256") == raw["record"]["source_spec_sha256"],
            f"Cache/raw-audit source-spec byte hash differs: {dataset}")
    require(binding.get("raw_audit") == raw["raw_audit_binding"],
            f"Cache is not bound to the selected sealed raw audit: {dataset}")
    producer_paths = {
        "implementation_sha256": package / "data_loaders.py",
        "contracts_sha256": package / "contracts.py",
        "group_protocol_sha256": package / "group_protocol.py",
    }
    for key, source in producer_paths.items():
        _regular_file(source)
        require(binding.get(key) == sha256(source),
                f"Cache producer code binding differs: {dataset}/{key}")
    require(binding.get("implementation_sha256") ==
            raw["record"].get("_audit_data_loader_sha256"),
            f"Cache producer is not the raw-audited loader: {dataset}")
    files = metadata.get("files_sha256")
    require(isinstance(files, dict) and set(files) == EXPECTED_CACHE_FILES,
            f"Metadata cache inventory differs: {dataset}")
    for filename, expected_hash in files.items():
        require(isinstance(expected_hash, str) and HEX64.fullmatch(expected_hash) is not None and
                sha256(directory / filename) == expected_hash,
                f"Cache file hash differs: {dataset}/{filename}")

    counts = metadata.get("counts")
    features = metadata.get("features")
    classes = metadata.get("class_names")
    require(isinstance(counts, dict) and set(counts) == set(SPLITS) and
            all(type(value) is int and value > 0 for value in counts.values()),
            f"Invalid split counts: {dataset}")
    require(isinstance(features, list) and features and len(features) == len(set(features)),
            f"Invalid feature schema: {dataset}")
    require(isinstance(classes, list) and len(classes) >= 2 and len(classes) == len(set(classes)),
            f"Invalid class schema: {dataset}")
    arrays = {
        f"{prefix}_{split}": _load_npy(directory / f"{prefix}_{split}.npy")
        for split in SPLITS for prefix in ARRAY_PREFIXES
    }
    arrays.update({name: _load_npy(directory / f"{name}.npy") for name in GLOBAL_ARRAYS})
    for split in SPLITS:
        count = counts[split]
        x = arrays[f"x_{split}"]
        require(x.shape == (count, len(features)) and x.dtype == np.dtype("float32"),
                f"Feature shape/dtype differs: {dataset}/{split}")
        for start in range(0, count, 65536):
            block = np.asarray(x[start:start + 65536])
            require(np.isfinite(block).all(), f"Non-finite cached feature: {dataset}/{split}")
            require(not (np.signbit(block) & (block == 0)).any(),
                    f"Noncanonical negative zero: {dataset}/{split}")
        for prefix in ("y", "ids", "identity_groups", "assignment_components",
                       "multiplicity"):
            array = arrays[f"{prefix}_{split}"]
            require(array.shape == (count,) and array.dtype == np.dtype("int64"),
                    f"Array shape/dtype differs: {dataset}/{prefix}_{split}")
        require((arrays[f"identity_groups_{split}"] >= 0).all() and
                (arrays[f"assignment_components_{split}"] >= 0).all(),
                f"Negative identity/component ID: {dataset}/{split}")
        require((arrays[f"multiplicity_{split}"] > 0).all(),
                f"Non-positive multiplicity: {dataset}/{split}")
        y = arrays[f"y_{split}"]
        require((y >= 0).all() and (y < len(classes)).all(),
                f"Class ID outside schema: {dataset}/{split}")
        require(len(np.unique(_xy_keys(x, y))) == count,
                f"Duplicate stable final (X,label) pattern remains: {dataset}/{split}")

    excluded_ids = arrays["excluded_ids"]
    excluded_reasons = arrays["excluded_reasons"]
    require(excluded_ids.ndim == excluded_reasons.ndim == 1 and
            excluded_ids.shape == excluded_reasons.shape and
            excluded_ids.dtype == np.dtype("int64") and
            excluded_reasons.dtype == np.dtype("uint8"),
            f"Excluded evidence shape/dtype differs: {dataset}")
    reason_codes = metadata.get("exclusion_reason_codes")
    expected_reason_codes = {str(code): reason for code, reason in EXCLUSION_REASONS.items()}
    require(reason_codes == expected_reason_codes,
            f"Exclusion-reason schema differs: {dataset}")
    allowed_codes = set(EXCLUSION_REASONS)
    require(set(np.unique(excluded_reasons).tolist()) <= allowed_codes,
            f"Unknown excluded-row reason: {dataset}")

    raw_rows = metadata["raw_rows"]
    seen = np.zeros(raw_rows, dtype=np.uint8)
    for split in SPLITS:
        ids = arrays[f"ids_{split}"]
        require(len(ids) > 0 and ids[0] >= 0 and ids[-1] < raw_rows and
                (np.diff(ids) > 0).all(),
                f"Retained IDs are not sorted/unique/in-range: {dataset}/{split}")
        require(not seen[ids].any(), f"Retained ID repeats: {dataset}/{split}")
        seen[ids] = 1
    require((not len(excluded_ids)) or
            (excluded_ids[0] >= 0 and excluded_ids[-1] < raw_rows and
             (np.diff(excluded_ids) > 0).all()),
            f"Excluded IDs are not sorted/unique/in-range: {dataset}")
    require(not seen[excluded_ids].any(), f"Excluded ID is retained: {dataset}")
    seen[excluded_ids] = 1
    require((seen == 1).all(), f"Raw-row accounting is not exact: {dataset}")

    raw_unique_ids = arrays["raw_unique_ids"]
    raw_unique_shape = raw_unique_ids.shape
    raw_unique_companions = (
        "raw_unique_identity_groups",
        "raw_unique_assignment_components",
        "raw_unique_labels",
        "raw_unique_multiplicity",
    )
    require(raw_unique_ids.dtype == np.dtype("int64") and raw_unique_ids.ndim == 1 and
            all(arrays[name].shape == raw_unique_shape and
                arrays[name].dtype == np.dtype("int64")
                for name in raw_unique_companions),
            f"Raw-unique evidence shape/dtype differs: {dataset}")
    require(len(raw_unique_ids) > 0 and raw_unique_ids[0] >= 0 and
            raw_unique_ids[-1] < raw_rows and (np.diff(raw_unique_ids) > 0).all(),
            f"Raw-unique IDs are not sorted/unique/in-range: {dataset}")
    require((arrays["raw_unique_identity_groups"] >= 0).all() and
            (arrays["raw_unique_assignment_components"] >= 0).all() and
            (arrays["raw_unique_labels"] >= 0).all() and
            (arrays["raw_unique_labels"] < len(classes)).all() and
            (arrays["raw_unique_multiplicity"] > 0).all() and
            int(arrays["raw_unique_multiplicity"].sum()) == raw_rows,
            f"Raw-unique identity/component/label/multiplicity is invalid: {dataset}")
    # Codes 1 and 3 are precisely the non-representative raw-(X,label)
    # duplicates.  Reasons 2 and 4 remain in the raw-unique population.
    non_unique_excluded = excluded_ids[np.isin(excluded_reasons, [1, 3])]
    expected_raw_unique = np.setdiff1d(
        np.arange(raw_rows, dtype=np.int64), non_unique_excluded,
        assume_unique=True,
    )
    require(np.array_equal(raw_unique_ids, expected_raw_unique),
            f"Raw-unique IDs do not match raw duplicate exclusions: {dataset}")

    raw_unique_reason_lookup = np.zeros(raw_rows, dtype=np.uint8)
    raw_unique_reason_lookup[excluded_ids] = excluded_reasons
    official_rows = metadata.get("official_train_raw_rows")
    if dataset in ("nslkdd", "unsw"):
        require(type(official_rows) is int and 0 < official_rows < raw_rows,
                f"Official role boundary is invalid: {dataset}")
        require(not (excluded_ids[excluded_reasons == 1] >= official_rows).any() and
                not (excluded_ids[excluded_reasons == 3] < official_rows).any(),
                f"Raw duplicate reason crosses the official role boundary: {dataset}")
        raw_train = raw_unique_ids < official_rows
        train_components = np.unique(arrays["raw_unique_assignment_components"][raw_train])
        expected_reason_two = (~raw_train) & np.isin(
            arrays["raw_unique_assignment_components"], train_components,
        )
        require(np.array_equal(
            raw_unique_reason_lookup[raw_unique_ids] == 2, expected_reason_two,
        ), f"Official-test component exclusions are invalid: {dataset}")
        require((arrays["ids_fit"] < official_rows).all() and
                (arrays["ids_validation"] < official_rows).all() and
                (arrays["ids_test"] >= official_rows).all(),
                f"Official train/test roles cross: {dataset}")
    else:
        require(official_rows is None and
                not np.isin(excluded_reasons, [2, 3]).any(),
                f"Combined-source dataset claims an official-test exclusion: {dataset}")

    final_ids = arrays["final_dedup_ids"]
    final_representatives = arrays["final_dedup_representative_ids"]
    final_origins = arrays["final_dedup_origin_splits"]
    require(final_ids.shape == final_representatives.shape == final_origins.shape and
            final_ids.dtype == final_representatives.dtype == np.dtype("int64") and
            final_origins.dtype == np.dtype("uint8") and
            ((not len(final_ids)) or
             (final_ids[0] >= 0 and final_ids[-1] < raw_rows and
              (np.diff(final_ids) > 0).all())) and
            set(np.unique(final_origins).tolist()) <= {0, 1, 2},
            f"Stable-final dedup evidence shape/dtype/order differs: {dataset}")
    require(np.isin(final_ids, raw_unique_ids).all() and
            (final_representatives < final_ids).all() and
            np.array_equal(final_ids, excluded_ids[excluded_reasons == 4]),
            f"Stable-final dedup IDs/reasons/mappings differ: {dataset}")
    expected_preprocessing_ids: np.ndarray | None = None
    for split_code, split in enumerate(SPLITS):
        removed_mask = final_origins == split_code
        removed = final_ids[removed_mask]
        representatives = final_representatives[removed_mask]
        ids = arrays[f"ids_{split}"]
        require(np.isin(representatives, ids).all(),
                f"Stable-final representative is absent from its split: {dataset}/{split}")
        representative_positions = np.searchsorted(ids, representatives)
        require((representative_positions < len(ids)).all() and
                np.array_equal(ids[representative_positions], representatives),
                f"Stable-final representative lookup differs: {dataset}/{split}")
        removed_positions = np.searchsorted(raw_unique_ids, removed)
        require((removed_positions < len(raw_unique_ids)).all() and
                np.array_equal(raw_unique_ids[removed_positions], removed),
                f"Stable-final removed ID is absent from raw-unique evidence: {dataset}/{split}")
        if removed_mask.any():
            require(np.array_equal(
                arrays[f"y_{split}"][representative_positions],
                arrays["raw_unique_labels"][removed_positions],
            ), f"Stable-final representative label differs: {dataset}/{split}")
        if split == "fit":
            expected_preprocessing_ids = np.sort(np.r_[ids, removed])
    preprocessing_fit_ids = arrays["preprocessing_fit_ids"]
    require(expected_preprocessing_ids is not None and
            preprocessing_fit_ids.dtype == np.dtype("int64") and
            preprocessing_fit_ids.ndim == 1 and len(preprocessing_fit_ids) > 0 and
            (np.diff(preprocessing_fit_ids) > 0).all() and
            np.array_equal(preprocessing_fit_ids, expected_preprocessing_ids),
            f"Preprocessing-fit population differs: {dataset}")
    preprocessor_for_count = load_json(directory / "preprocessing.json")
    require(preprocessor_for_count.get("n_fit") == len(preprocessing_fit_ids),
            f"Scaler fit count differs from sealed fit population: {dataset}")

    partition = metadata.get("partition")
    require(isinstance(partition, dict), f"Missing partition report: {dataset}")
    _validate_partition_contract(metadata)
    require(partition.get("raw_rows") == raw_rows and
            partition.get("retained_rows") == sum(counts.values()) and
            partition.get("excluded_rows") == len(excluded_ids),
            f"Partition row accounting differs: {dataset}")
    actual_support = {
        split: np.bincount(arrays[f"y_{split}"], minlength=len(classes)).astype(int).tolist()
        for split in SPLITS
    }
    require(all(all(value > 0 for value in support) for support in actual_support.values()) and
            partition.get("support") == actual_support,
            f"Class support is incomplete or misreported: {dataset}")
    actual_multiplicity = {
        split: int(arrays[f"multiplicity_{split}"].sum()) for split in SPLITS
    }
    require(partition.get("source_multiplicity") == actual_multiplicity,
            f"Source multiplicity differs: {dataset}")
    require(metadata.get("n_train_validation_patterns") ==
            counts["fit"] + counts["validation"],
            f"Training/validation pattern count differs: {dataset}")

    reason_counts = partition.get("exclusion_reason_counts")
    require(isinstance(reason_counts, dict) and set(reason_counts) == set(reason_codes.values()) and
            all(type(value) is int and value >= 0 for value in reason_counts.values()),
            f"Excluded-reason counts schema differs: {dataset}")
    actual_reasons = {
        reason: int((excluded_reasons == int(code)).sum())
        for code, reason in reason_codes.items()
    }
    require(reason_counts == actual_reasons and sum(actual_reasons.values()) == len(excluded_ids),
            f"Excluded-reason counts differ: {dataset}")

    require(partition.get("raw_unique_patterns") == len(raw_unique_ids) and
            partition.get("raw_unique_source_multiplicity") == raw_rows and
            partition.get("stable_final_xy_removed_patterns") == len(final_ids),
            f"Raw-unique/final-dedup partition counts differ: {dataset}")
    for split_code, split in enumerate(SPLITS):
        ids = arrays[f"ids_{split}"]
        raw_positions = np.searchsorted(raw_unique_ids, ids)
        require((raw_positions < len(raw_unique_ids)).all() and
                np.array_equal(raw_unique_ids[raw_positions], ids) and
                np.array_equal(arrays["raw_unique_labels"][raw_positions],
                               arrays[f"y_{split}"]) and
                np.array_equal(arrays["raw_unique_identity_groups"][raw_positions],
                               arrays[f"identity_groups_{split}"]) and
                np.array_equal(arrays["raw_unique_assignment_components"][raw_positions],
                               arrays[f"assignment_components_{split}"]),
                f"Retained row differs from raw-unique evidence: {dataset}/{split}")
        expected_multiplicity = arrays["raw_unique_multiplicity"][raw_positions].copy()
        removed_mask = final_origins == split_code
        if removed_mask.any():
            removed_positions = np.searchsorted(raw_unique_ids, final_ids[removed_mask])
            representative_positions = np.searchsorted(
                ids, final_representatives[removed_mask],
            )
            np.add.at(expected_multiplicity, representative_positions,
                      arrays["raw_unique_multiplicity"][removed_positions])
        require(np.array_equal(expected_multiplicity, arrays[f"multiplicity_{split}"]),
                f"Final source multiplicity aggregation differs: {dataset}/{split}")
    official_overlap_source_rows = int(arrays["raw_unique_multiplicity"][
        raw_unique_reason_lookup[raw_unique_ids] == 2
    ].sum())
    retained_source_rows = sum(actual_multiplicity.values())
    require(retained_source_rows + official_overlap_source_rows == raw_rows and
            partition.get("official_overlap_source_rows") == official_overlap_source_rows and
            partition.get("retained_source_rows") == retained_source_rows and
            partition.get("source_rows_reconciled") == raw_rows,
            f"Source multiplicity does not reconcile to raw rows: {dataset}")

    groups = metadata.get("groups")
    expected_group_keys = {
        "raw_identity_groups",
        "final_assignment_components",
        "mixed_label_raw_identity_groups",
        "maximum_raw_identity_group_rows",
        "split_raw_identity_group_counts",
        "split_assignment_component_counts",
        "split_assignment_component_overlap",
    }
    require(isinstance(groups, dict) and set(groups) == expected_group_keys,
            f"Group-report schema differs: {dataset}")
    group_overlap = {}
    for left, right in (("fit", "validation"), ("fit", "test"),
                        ("validation", "test")):
        count = int(np.intersect1d(
            arrays[f"assignment_components_{left}"],
            arrays[f"assignment_components_{right}"],
        ).size)
        group_overlap[f"{left}_vs_{right}"] = count
    require(all(value == 0 for value in group_overlap.values()) and
            groups["split_assignment_component_overlap"] == group_overlap,
            f"Assignment components overlap or are misreported: {dataset}")
    split_identity_counts = {
        split: int(len(np.unique(arrays[f"identity_groups_{split}"]))) for split in SPLITS
    }
    split_component_counts = {
        split: int(len(np.unique(arrays[f"assignment_components_{split}"])))
        for split in SPLITS
    }
    require(groups["split_raw_identity_group_counts"] == split_identity_counts and
            groups["split_assignment_component_counts"] == split_component_counts,
            f"Split identity/component counts differ: {dataset}")
    raw_identity_groups = arrays["raw_unique_identity_groups"]
    raw_labels = arrays["raw_unique_labels"]
    normalized_identity_groups = _first_occurrence_partition(raw_identity_groups)
    identity_label_pairs = np.empty(len(raw_unique_ids), dtype=np.dtype([
        ("identity", "<i8"), ("label", "<i8"),
    ]))
    identity_label_pairs["identity"] = normalized_identity_groups
    identity_label_pairs["label"] = raw_labels
    unique_identity_labels = np.unique(identity_label_pairs)
    label_counts = np.bincount(
        unique_identity_labels["identity"],
        minlength=int(normalized_identity_groups.max()) + 1,
    )
    identity_source_rows = np.zeros(
        int(normalized_identity_groups.max()) + 1, dtype=np.int64,
    )
    np.add.at(identity_source_rows, normalized_identity_groups,
              arrays["raw_unique_multiplicity"])
    all_components = arrays["raw_unique_assignment_components"]
    identity_component_pairs = np.empty(len(raw_unique_ids), dtype=np.dtype([
        ("identity", "<i8"), ("component", "<i8"),
    ]))
    identity_component_pairs["identity"] = raw_identity_groups
    identity_component_pairs["component"] = all_components
    require(len(np.unique(identity_component_pairs)) == len(np.unique(raw_identity_groups)),
            f"One raw identity maps to multiple final components: {dataset}")
    require(groups["raw_identity_groups"] == len(np.unique(raw_identity_groups)) and
            groups["final_assignment_components"] == len(np.unique(all_components)) and
            groups["mixed_label_raw_identity_groups"] == int((label_counts > 1).sum()) and
            groups["maximum_raw_identity_group_rows"] == int(identity_source_rows.max()),
            f"Global identity/component statistics differ: {dataset}")
    _validate_collision_trace(metadata)
    final_overlap = _exact_overlap({split: arrays[f"x_{split}"] for split in SPLITS})
    require(all(value == 0 for value in final_overlap.values()) and
            metadata.get("final_fp32_overlap") == final_overlap,
            f"Final FP32 model inputs overlap or are misreported: {dataset}")

    fractions = partition.get("retained_pattern_fractions")
    retained = sum(counts.values())
    expected_fractions = {split: counts[split] / retained for split in SPLITS}
    require(isinstance(fractions, dict) and set(fractions) == set(SPLITS) and
            all(_finite_number(fractions[split], f"{dataset}/{split} fraction") ==
                expected_fractions[split] for split in SPLITS),
            f"Realized split fractions differ: {dataset}")
    if dataset in ("cicids2017", "iot23"):
        require(partition.get("target_pattern_fractions") ==
                {"fit": 0.64, "validation": 0.16, "test": 0.20},
                f"Combined-source target fractions differ: {dataset}")
    else:
        require(partition.get("target_pattern_fractions") is None,
                f"Official-role dataset must not claim 64/16/20 targets: {dataset}")
    require(metadata.get("exact_model_input_group_leakage_excluded") is True and
            metadata.get("capture_device_time_group_generalization_established") is False and
            metadata.get("upstream_preprocessing_verified") is False,
            f"Cache scope flags overclaim: {dataset}")
    require(metadata.get("raw_model_view_sha256") and
            HEX64.fullmatch(metadata["raw_model_view_sha256"]) is not None,
            f"Raw model-view fingerprint is invalid: {dataset}")
    _validate_preprocessing(directory / "preprocessing.json", metadata, dataset)

    summary = {
        "data_fingerprint": metadata["data_fingerprint"],
        "raw_rows": raw_rows,
        "counts": counts,
        "features": features,
        "class_names": classes,
        "realized_pattern_fractions": expected_fractions,
        "raw_model_view_sha256": metadata["raw_model_view_sha256"],
    }
    return metadata, arrays, summary


def _validate_raw_files(raw_data_root: Path, record: dict) -> None:
    for file_record in record["files"]:
        path = _contained_file(raw_data_root, file_record["path"])
        require(path.stat().st_size == file_record["bytes"] and
                sha256(path) == file_record["sha256"],
                f"Raw source bytes differ: {path}")


def _raw_file_snapshot(raw_data_root: Path, record: dict) -> dict[str, dict[str, object]]:
    snapshot = {}
    for file_record in record["files"]:
        path = _contained_file(raw_data_root, file_record["path"])
        file_snapshot = _file_snapshot(path)
        require(file_snapshot["bytes"] == file_record["bytes"] and
                file_snapshot["sha256"] == file_record["sha256"],
                f"Raw source bytes differ: {path}")
        snapshot[file_record["path"]] = file_snapshot
    return snapshot


def _iter_raw_frames(raw_data_root: Path, record: dict, chunksize: int = 65536
                     ) -> Iterator[pd.DataFrame]:
    for file_record in record["files"]:
        path = _contained_file(raw_data_root, file_record["path"])
        selected = file_record.get("selected_columns")
        require(isinstance(selected, list) and selected and len(selected) == len(set(selected)),
                f"Raw audit omits a unique selected schema: {path}")
        if path.suffix.lower() == ".parquet":
            try:
                import pyarrow.parquet as pq
            except ImportError as exc:
                raise VerificationError("Raw Parquet verification requires pyarrow") from exc
            parquet = pq.ParquetFile(path)
            iterator = (batch.to_pandas() for batch in parquet.iter_batches(
                batch_size=chunksize, columns=selected, use_threads=False,
            ))
            expected_input_width = len(selected)
        elif record["dataset"] == "nslkdd":
            iterator = pd.read_csv(
                path, header=None, chunksize=chunksize, dtype=str,
                keep_default_na=False, encoding="utf-8", encoding_errors="strict",
            )
            expected_input_width = len(file_record["physical_columns"])
        else:
            iterator = pd.read_csv(
                path, header="infer", chunksize=chunksize, dtype=str,
                keep_default_na=False, encoding="utf-8", encoding_errors="strict",
            )
            expected_input_width = len(file_record["physical_columns"])
        rows = 0
        for frame in iterator:
            require(frame.shape[1] == expected_input_width,
                    f"Raw physical width differs: {path}")
            drop_index = file_record.get("dropped_physical_column_index")
            if drop_index is not None:
                require(type(drop_index) is int and 0 <= drop_index < frame.shape[1],
                        f"Invalid physical duplicate drop: {path}")
                duplicate_name = file_record["physical_columns"][drop_index]
                positions = [index for index, name in enumerate(file_record["physical_columns"])
                             if name == duplicate_name]
                require(len(positions) == 2 and np.array_equal(
                    frame.iloc[:, positions[0]].astype(str).to_numpy(),
                    frame.iloc[:, positions[1]].astype(str).to_numpy(),
                ), f"Physical duplicate values differ: {path}")
                frame = frame.drop(frame.columns[drop_index], axis=1)
            require(frame.shape[1] == len(selected), f"Selected raw width differs: {path}")
            frame.columns = selected
            rows += len(frame)
            yield frame
        require(rows == file_record["rows"], f"Independent raw row count differs: {path}")


def _identity_token(value: object) -> str:
    if pd.isna(value):
        return "M:"
    require(isinstance(value, str), "Categorical raw token must be a string")
    return "V:" + value


def _numeric_fp32(series: pd.Series, *, reject_nonfinite: bool) -> tuple[np.ndarray, int]:
    cleaned = series.replace({
        "-": np.nan,
        "": np.nan,
        "NaN": np.nan,
        "nan": np.nan,
        "Infinity": np.inf,
        "-Infinity": -np.inf,
    })
    try:
        values = pd.to_numeric(cleaned, errors="raise").to_numpy(dtype=np.float64, copy=True)
    except (TypeError, ValueError) as exc:
        raise VerificationError(f"Raw numeric conversion failed: {series.name}") from exc
    bad = ~np.isfinite(values)
    require(not (reject_nonfinite and bad.any()),
            f"Non-finite NSL raw model input: {series.name}")
    values[bad] = 0.0
    require((np.abs(values) <= np.finfo(np.float32).max).all(),
            f"Raw numeric value overflows FP32: {series.name}")
    result = values.astype(np.float32)
    result[result == 0] = np.float32(0.0)
    return result, int(bad.sum())


def _canonical_numeric(series: pd.Series, *, reject_nonfinite: bool) -> np.ndarray:
    return _numeric_fp32(series, reject_nonfinite=reject_nonfinite)[0]


def _identity_mappings(
    raw_data_root: Path,
    record: dict,
) -> dict[str, dict[str, int]]:
    dataset = record["dataset"]
    categorical = CATEGORICAL[dataset]
    vocab_sets = {column: set() for column in categorical}
    observed = 0
    for frame in _iter_raw_frames(raw_data_root, record):
        require(all(column in frame for column in record["features"]),
                f"Raw frame omits model features: {dataset}")
        for column in categorical:
            vocab_sets[column].update(_identity_token(value) for value in frame[column])
            require(len(vocab_sets[column]) <= 100000,
                    f"Raw categorical identity cardinality is implausible: {dataset}/{column}")
        observed += len(frame)
    require(observed == record["rows"], f"Independent raw row total differs: {dataset}")
    mappings = {
        column: {token: index for index, token in enumerate(sorted(values))}
        for column, values in vocab_sets.items()
    }
    for column, mapping in mappings.items():
        require(mapping and len(mapping) <= 2**24,
                f"Categorical identities cannot be represented exactly: {dataset}/{column}")
    return mappings


def _canonical_group_matrix(
    frame: pd.DataFrame,
    dataset: str,
    features: list[str],
    mappings: Mapping[str, Mapping[str, int]],
) -> np.ndarray:
    matrix = np.empty((len(frame), len(features)), dtype=np.float32)
    for column_index, column in enumerate(features):
        if column in CATEGORICAL[dataset]:
            encoded = frame[column].map(
                lambda value: mappings[column].get(_identity_token(value))
            )
            require(encoded.notna().all(),
                    f"Raw identity vocabulary changed between passes: {dataset}/{column}")
            matrix[:, column_index] = encoded.to_numpy(dtype=np.float32)
        else:
            matrix[:, column_index] = _canonical_numeric(
                frame[column], reject_nonfinite=(dataset == "nslkdd"),
            )
    matrix[matrix == 0] = np.float32(0.0)
    return matrix


def _recompute_raw_model_view_fingerprint(
    raw_data_root: Path,
    record: dict,
) -> str:
    dataset = record["dataset"]
    features = record["features"]
    categorical = CATEGORICAL[dataset]
    _validate_raw_files(raw_data_root, record)
    require(set(categorical) <= set(features),
            f"Raw feature schema omits a declared category: {dataset}")
    mappings = _identity_mappings(raw_data_root, record) if categorical else {}

    result = hashlib.sha256()
    result.update(
        f"{np.dtype(np.float32).str}:{record['rows']}:{len(features)}".encode("ascii")
    )
    observed = 0
    for frame in _iter_raw_frames(raw_data_root, record):
        require(all(column in frame for column in features),
                f"Raw frame omits model features: {dataset}")
        matrix = _canonical_group_matrix(frame, dataset, features, mappings)
        result.update(memoryview(np.ascontiguousarray(matrix)).cast("B"))
        observed += len(frame)
    require(observed == record["rows"], f"Independent raw row total differs: {dataset}")
    return result.hexdigest()


def _first_occurrence_partition(labels: np.ndarray) -> np.ndarray:
    """Canonicalize arbitrary group names while preserving their equivalence relation."""
    _, first, inverse = np.unique(labels, return_index=True, return_inverse=True)
    first_order = np.argsort(first, kind="stable")
    remap = np.empty(len(first_order), dtype=np.int64)
    remap[first_order] = np.arange(len(first_order), dtype=np.int64)
    return remap[inverse]


def _deduplicate_identity_label(
    indices: np.ndarray,
    identity_groups: np.ndarray,
    labels: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Independent stable exact-(raw-X,label) deduplication for one source role."""
    indices = np.asarray(indices, dtype=np.int64)
    require(indices.ndim == 1 and len(indices) > 0,
            "Independent raw deduplication received an empty role")
    order = indices[np.lexsort((indices, labels[indices], identity_groups[indices]))]
    ordered_groups = identity_groups[order]
    ordered_labels = labels[order]
    first = np.r_[
        True,
        (ordered_groups[1:] != ordered_groups[:-1]) |
        (ordered_labels[1:] != ordered_labels[:-1]),
    ]
    starts = np.flatnonzero(first)
    representatives = order[starts]
    multiplicity = np.diff(np.r_[starts, len(order)]).astype(np.int64)
    retained = np.zeros(len(identity_groups), dtype=bool)
    retained[representatives] = True
    excluded = indices[~retained[indices]]
    representative_order = np.argsort(representatives)
    return (
        np.sort(representatives),
        multiplicity[representative_order],
        np.sort(excluded),
    )


def _validate_partition_contract(metadata: dict) -> None:
    """Validate the declared rule; numerical replay separately proves its execution."""
    official = metadata["dataset"] in ("nslkdd", "unsw")
    expected = {
        "protocol_version": "raw_identity_assignment_component_final_xy_v2",
        "role": ("official_train_grouped_validation_and_clean_official_test" if official else
                 "xy_deduplicated_exact_x_grouped_target_64_16_20"),
        "stratifier": "sklearn.model_selection.StratifiedGroupKFold",
        "objective": "approximate per-class balance over retained labelled patterns",
        "n_splits": 5,
        "fold_index": 0,
        "test_seed": None if official else 42,
        "validation_seed": 20260920,
        "selection_prohibition":
            "fold zero is fixed before training; no model/test performance may select a fold",
    }
    partition = metadata.get("partition")
    require(isinstance(partition, dict), "Missing frozen partition declaration")
    for key, value in expected.items():
        require(type(partition.get(key)) is type(value) and partition[key] == value,
                f"Frozen partition declaration differs: {metadata['dataset']}/{key}")


def _validate_collision_trace(metadata: dict) -> None:
    """There are at most G0-1 strictly coarsening rounds and one stable scan."""
    dataset = metadata["dataset"]
    groups = metadata["groups"]
    initial, final = groups["raw_identity_groups"], groups["final_assignment_components"]
    require(type(initial) is int and type(final) is int and 1 <= final <= initial,
            f"Invalid collision-closure population: {dataset}")
    trace = metadata.get("collision_iterations")
    require(isinstance(trace, list) and 1 <= len(trace) <= initial - final + 1,
            f"Collision-closure evidence violates its finite progress bound: {dataset}")
    previous = initial
    keys = {"iteration", "input_groups", "output_groups", "new_group_unions"}
    for index, row in enumerate(trace):
        require(isinstance(row, dict) and set(row) == keys and
                all(type(row.get(key)) is int for key in keys),
                f"Collision-closure row schema differs: {dataset}/iteration={index}")
        terminal = index == len(trace) - 1
        require(row["iteration"] == index and row["input_groups"] == previous and
                row["output_groups"] > 0 and
                row["output_groups"] == previous - row["new_group_unions"] and
                (row["new_group_unions"] == 0 if terminal else row["new_group_unions"] > 0),
                f"Collision-closure transition differs: {dataset}/iteration={index}")
        previous = row["output_groups"]
    require(previous == final, f"Collision closure has an inconsistent final population: {dataset}")


def _independent_fold_zero(indices: np.ndarray, labels: np.ndarray,
                           components: np.ndarray, classes: int, seed: int
                           ) -> tuple[np.ndarray, np.ndarray]:
    """Independent frozen split replay, without importing producer functions."""
    indices = np.asarray(indices, dtype=np.int64)
    local_labels = np.asarray(labels[indices], dtype=np.int64)
    local_groups = _first_occurrence_partition(components[indices])
    require(len(indices) > 0 and (np.diff(indices) > 0).all(),
            "Independent grouped split requires sorted unique candidates")
    require((np.bincount(local_labels, minlength=classes) >= 5).all() and
            all(len(np.unique(local_groups[local_labels == label])) >= 5
                for label in range(classes)),
            "Independent grouped split lacks five labelled patterns/groups per class")
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    fit_local, held_local = next(splitter.split(
        local_labels.reshape(-1, 1), local_labels, local_groups,
    ))
    return np.sort(indices[fit_local]), np.sort(indices[held_local])


def _independent_pre_final_splits(raw_unique_ids: np.ndarray, labels: np.ndarray,
                                   components: np.ndarray, classes: int,
                                   official_rows: int | None) -> dict[str, np.ndarray]:
    if official_rows is None:
        train, test = _independent_fold_zero(raw_unique_ids, labels, components, classes, 42)
    else:
        train = raw_unique_ids[raw_unique_ids < official_rows]
        candidates = raw_unique_ids[raw_unique_ids >= official_rows]
        test = candidates[~np.isin(components[candidates], np.unique(components[:official_rows]))]
    fit, validation = _independent_fold_zero(train, labels, components, classes, 20260920)
    splits = {"fit": fit, "validation": validation, "test": test}
    require(all((np.bincount(labels[ids], minlength=classes) > 0).all()
                for ids in splits.values()),
            "Independent grouped protocol leaves a split without a declared class")
    return splits


def _independent_collision_union(matrix: np.ndarray, retained_ids: np.ndarray,
                                  components: np.ndarray) -> tuple[np.ndarray, int]:
    """Join every observed exact final-X equivalence class, including within split."""
    _, dense = np.unique(components, return_inverse=True)
    parents = np.arange(int(dense.max()) + 1, dtype=np.int64)
    keys = _row_keys(matrix)
    order = np.argsort(keys, kind="stable")
    ordered_keys = keys[order]
    ordered_groups = dense[retained_ids[order]]
    starts = np.r_[True, ordered_keys[1:] != ordered_keys[:-1]]
    anchor_locations = np.maximum.accumulate(np.where(starts, np.arange(len(starts)), 0))
    anchors = ordered_groups[anchor_locations]
    candidates = np.flatnonzero(ordered_groups != anchors)
    unions = 0

    def representative(value: int) -> int:
        while parents[value] != value:
            parents[value] = parents[parents[value]]
            value = int(parents[value])
        return value

    for position in candidates:
        left = representative(int(anchors[position]))
        right = representative(int(ordered_groups[position]))
        if left != right:
            parents[max(left, right)] = min(left, right)
            unions += 1
    # Vectorized path compression, independent of the numeric group names.
    while True:
        compressed = parents[parents]
        if np.array_equal(compressed, parents):
            break
        parents = compressed
    _, result = np.unique(parents[dense], return_inverse=True)
    require(len(np.unique(result)) == len(parents) - unions,
            "Independent collision union failed strict component accounting")
    return result.astype(np.int64, copy=False), unions


def _fit_replay_scaler(encode: Callable[[np.ndarray], np.ndarray], fit_ids: np.ndarray,
                       chunk_bounds: list[tuple[int, int]]) -> StandardScaler:
    """Preserve original raw-file/chunk boundaries, including each short file tail."""
    scaler = StandardScaler()
    for start, stop in chunk_bounds:
        left, right = np.searchsorted(fit_ids, [start, stop])
        if right > left:
            scaler.partial_fit(encode(fit_ids[left:right]))
    require(int(np.asarray(scaler.n_samples_seen_).min()) == len(fit_ids),
            "Independent replay scaler fit population differs")
    return scaler


def _scale_fp32_in_place(block: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """Pinned sklearn 1.8 casts both parameters to input dtype before each ufunc."""
    require(block.ndim == 2 and block.dtype == np.dtype("float32"),
            "Independent transform requires FP32 model inputs")
    block -= np.asarray(mean, dtype=np.float32)
    block /= np.asarray(scale, dtype=np.float32)
    block[block == 0] = np.float32(0.0)
    require(np.isfinite(block).all(), "Independent transformed raw input is non-finite")
    return block


def _replay_group_protocol(
    group_view: np.ndarray,
    labels: np.ndarray,
    identity_groups: np.ndarray,
    raw_unique_ids: np.ndarray,
    chunk_bounds: list[tuple[int, int]],
    mappings: Mapping[str, Mapping[str, int]],
    metadata: dict,
    arrays: Mapping[str, np.ndarray],
    temporary: Path,
) -> None:
    """Replay every frozen fold/scaler/collision round from independently parsed raw rows.

    Global lexical categorical codes are only raw identity tokens: every round
    remaps the fit-observed tokens to its own fit-only ordinal vocabulary. Raw
    numeric values are already canonical FP32. Keeping the original per-file
    batch boundaries preserves incremental StandardScaler's FP64 fit arithmetic;
    the two FP32 in-place transform operations preserve deployment rounding.
    No cached component assignment, fit population, scaler, or history is used
    to *construct* the replay. They are compared only against its results.
    """
    _validate_partition_contract(metadata)
    _validate_collision_trace(metadata)
    dataset = metadata["dataset"]
    features = metadata["features"]
    classes = len(metadata["class_names"])
    raw_rows = len(labels)
    require(group_view.shape == (raw_rows, len(features)) and
            group_view.dtype == np.dtype("float32") and
            chunk_bounds and chunk_bounds[0][0] == 0 and chunk_bounds[-1][1] == raw_rows and
            all(0 <= start < stop <= raw_rows for start, stop in chunk_bounds) and
            all(left[1] == right[0] for left, right in zip(chunk_bounds, chunk_bounds[1:])),
            "Independent protocol replay input/chunk boundaries are invalid")
    components = np.asarray(identity_groups, dtype=np.int64).copy()
    initial = len(np.unique(components))
    require(initial == metadata["groups"]["raw_identity_groups"],
            "Independent initial component count differs")
    category_columns = {features.index(column): column for column in CATEGORICAL[dataset]}
    official_rows = metadata.get("official_train_raw_rows")
    for iteration, declared in enumerate(metadata["collision_iterations"]):
        splits = _independent_pre_final_splits(
            raw_unique_ids, labels, components, classes, official_rows,
        )
        fit = splits["fit"]
        category_remaps = {}
        for column_index, column in category_columns.items():
            observed = np.unique(group_view[fit, column_index]).astype(np.int64)
            require(len(observed) > 0 and observed.min() >= 0 and
                    observed.max() < len(mappings[column]),
                    "Independent fit-only category identity is outside the raw vocabulary")
            remap = np.full(len(mappings[column]), -1, dtype=np.float32)
            remap[observed] = np.arange(len(observed), dtype=np.float32)
            category_remaps[column_index] = remap

        def encoded(ids: np.ndarray) -> np.ndarray:
            block = np.array(group_view[ids], dtype=np.float32, order="C", copy=True)
            for index, remap in category_remaps.items():
                block[:, index] = remap[block[:, index].astype(np.int64)]
            return block

        scaler = _fit_replay_scaler(encoded, fit, chunk_bounds)
        retained_ids = np.sort(np.concatenate(list(splits.values())))
        output = np.lib.format.open_memmap(
            temporary / "protocol_final_x.npy", mode="w+", dtype=np.float32,
            shape=(len(retained_ids), len(features)),
        )
        for start in range(0, len(retained_ids), 65536):
            stop = min(len(retained_ids), start + 65536)
            block = encoded(retained_ids[start:stop])
            output[start:stop] = _scale_fp32_in_place(block, scaler.mean_, scaler.scale_)
        output.flush()
        merged, unions = _independent_collision_union(output, retained_ids, components)
        actual = {"iteration": iteration, "input_groups": len(np.unique(components)),
                  "output_groups": len(np.unique(merged)), "new_group_unions": unions}
        del output
        require(actual == declared,
                f"Independent collision-closure replay differs: {dataset}/iteration={iteration}; "
                f"actual={actual}, declared={declared}")
        if unions == 0:
            require(np.array_equal(
                _first_occurrence_partition(components[raw_unique_ids]),
                _first_occurrence_partition(np.asarray(arrays["raw_unique_assignment_components"])),
            ), f"Independent final component equivalence differs: {dataset}")
            cached_splits = {"fit": np.asarray(arrays["preprocessing_fit_ids"])}
            for split_code, split in enumerate(SPLITS[1:], start=1):
                removed = arrays["final_dedup_ids"][arrays["final_dedup_origin_splits"] == split_code]
                cached_splits[split] = np.sort(np.r_[arrays[f"ids_{split}"], removed])
            for split in SPLITS:
                require(np.array_equal(splits[split], cached_splits[split]),
                        f"Independent frozen pre-final split differs: {dataset}/{split}")
            return
        components = merged
    raise VerificationError(f"Independent collision replay did not reach a fixed point: {dataset}")


def _verify_raw_identity_and_dedup(
    raw_data_root: Path,
    raw: dict,
    metadata: dict,
    arrays: Mapping[str, np.ndarray],
    *,
    replay_protocol: bool = False,
) -> str:
    """Rebuild immutable raw identities and role-local dedup from raw bytes.

    The cache's numeric identity-group names are deliberately treated as
    arbitrary labels.  What is verified is the exact equivalence relation,
    labelled-pattern representatives, multiplicities, and reason-1/3 IDs.
    This prevents a fitted-encoder collision from masquerading as a raw
    duplicate while remaining invariant to a harmless group-ID renaming.
    """
    record = raw["record"]
    dataset = metadata["dataset"]
    features = metadata["features"]
    raw_rows = metadata["raw_rows"]
    require(record["dataset"] == dataset and record["rows"] == raw_rows and
            record["features"] == features,
            f"Raw identity reconstruction schema differs: {dataset}")
    if dataset in ("nslkdd", "unsw"):
        roles = [row["role"] for row in record["files"]]
        require(set(roles) == {"train", "test"} and
                roles == sorted(roles, key={"train": 0, "test": 1}.__getitem__),
                f"Pinned official source roles are not ordered train then test: {dataset}")
        official_boundary = sum(row["rows"] for row in record["files"] if row["role"] == "train")
        require(type(metadata.get("official_train_raw_rows")) is int and
                metadata["official_train_raw_rows"] == official_boundary,
                f"Official role boundary differs from pinned raw file rows: {dataset}")
    _validate_raw_files(raw_data_root, record)
    mappings = (_identity_mappings(raw_data_root, record)
                if CATEGORICAL[dataset] else {})

    with tempfile.TemporaryDirectory(prefix=f"spikeids-{dataset}-identity-") as temporary:
        temporary_path = Path(temporary)
        group_view = np.lib.format.open_memmap(
            temporary_path / "group_view.npy", mode="w+", dtype=np.float32,
            shape=(raw_rows, len(features)),
        )
        raw_labels = np.lib.format.open_memmap(
            temporary_path / "labels.npy", mode="w+", dtype=np.int64,
            shape=(raw_rows,),
        )
        fingerprint = hashlib.sha256()
        fingerprint.update(
            f"{np.dtype(np.float32).str}:{raw_rows}:{len(features)}".encode("ascii")
        )
        offset = 0
        chunk_bounds: list[tuple[int, int]] = []
        for frame in _iter_raw_frames(raw_data_root, record):
            stop = offset + len(frame)
            matrix = _canonical_group_matrix(frame, dataset, features, mappings)
            labels = _mapped_labels(frame, dataset, metadata["class_names"], raw["source_spec"])
            group_view[offset:stop] = matrix
            raw_labels[offset:stop] = labels
            chunk_bounds.append((offset, stop))
            fingerprint.update(memoryview(np.ascontiguousarray(matrix)).cast("B"))
            offset = stop
        require(offset == raw_rows,
                f"Raw identity reconstruction row total differs: {dataset}")
        group_view.flush()
        raw_labels.flush()

        unique_rows, identity_groups, identity_counts = np.unique(
            _row_keys(group_view), return_inverse=True, return_counts=True,
        )
        del unique_rows
        identity_groups = identity_groups.astype(np.int64, copy=False)
        identity_counts = identity_counts.astype(np.int64, copy=False)

        reason_one = np.empty(0, dtype=np.int64)
        reason_three = np.empty(0, dtype=np.int64)
        representatives: list[np.ndarray] = []
        multiplicities: list[np.ndarray] = []
        official_rows = metadata.get("official_train_raw_rows")
        if dataset in ("nslkdd", "unsw"):
            require(type(official_rows) is int and 0 < official_rows < raw_rows,
                    f"Official role boundary is invalid during raw dedup: {dataset}")
            train_rep, train_mult, reason_one = _deduplicate_identity_label(
                np.arange(official_rows, dtype=np.int64), identity_groups, raw_labels,
            )
            test_rep, test_mult, reason_three = _deduplicate_identity_label(
                np.arange(official_rows, raw_rows, dtype=np.int64),
                identity_groups, raw_labels,
            )
            representatives.extend((train_rep, test_rep))
            multiplicities.extend((train_mult, test_mult))
        else:
            require(official_rows is None,
                    f"Combined-source dataset has an official boundary: {dataset}")
            combined_rep, combined_mult, reason_one = _deduplicate_identity_label(
                np.arange(raw_rows, dtype=np.int64), identity_groups, raw_labels,
            )
            representatives.append(combined_rep)
            multiplicities.append(combined_mult)

        expected_ids_unsorted = np.concatenate(representatives)
        expected_multiplicity_unsorted = np.concatenate(multiplicities)
        expected_order = np.argsort(expected_ids_unsorted)
        expected_ids = expected_ids_unsorted[expected_order]
        expected_multiplicity = expected_multiplicity_unsorted[expected_order]
        cached_ids = np.asarray(arrays["raw_unique_ids"])
        require(np.array_equal(cached_ids, expected_ids) and
                np.array_equal(np.asarray(arrays["raw_unique_multiplicity"]),
                               expected_multiplicity),
                f"Raw exact-(X,label) representatives/multiplicity differ: {dataset}")

        excluded_ids = np.asarray(arrays["excluded_ids"])
        excluded_reasons = np.asarray(arrays["excluded_reasons"])
        require(np.array_equal(excluded_ids[excluded_reasons == 1], reason_one) and
                np.array_equal(excluded_ids[excluded_reasons == 3], reason_three),
                f"Raw duplicate exclusion reasons differ by identity/label/role: {dataset}")
        if dataset in ("nslkdd", "unsw"):
            require((reason_one < official_rows).all() and
                    (reason_three >= official_rows).all(),
                    f"Raw duplicate reason crossed the official role boundary: {dataset}")
        else:
            require(not len(reason_three),
                    f"Combined-source dataset claims an official-test duplicate: {dataset}")

        cached_groups = np.asarray(arrays["raw_unique_identity_groups"])
        expected_groups = identity_groups[expected_ids]
        require(np.array_equal(
            _first_occurrence_partition(cached_groups),
            _first_occurrence_partition(expected_groups),
        ), f"Raw identity equivalence relation differs: {dataset}")
        require(np.array_equal(np.asarray(arrays["raw_unique_labels"]),
                               np.asarray(raw_labels[expected_ids])),
                f"Raw-unique labels differ from independent mapping: {dataset}")

        groups = metadata["groups"]
        identity_label_pairs = np.empty(raw_rows, dtype=np.dtype([
            ("identity", "<i8"), ("label", "<i8"),
        ]))
        identity_label_pairs["identity"] = identity_groups
        identity_label_pairs["label"] = raw_labels
        unique_pairs = np.unique(identity_label_pairs)
        label_counts = np.bincount(
            unique_pairs["identity"], minlength=len(identity_counts),
        )
        require(groups["raw_identity_groups"] == len(identity_counts) and
                groups["maximum_raw_identity_group_rows"] == int(identity_counts.max()) and
                groups["mixed_label_raw_identity_groups"] == int((label_counts > 1).sum()),
                f"Raw identity population statistics differ: {dataset}")
        if replay_protocol:
            _replay_group_protocol(
                group_view, raw_labels, identity_groups, expected_ids, chunk_bounds,
                mappings, metadata, arrays, temporary_path,
            )
        result = fingerprint.hexdigest()
        del identity_groups, identity_counts, identity_label_pairs, unique_pairs
        del group_view, raw_labels
        return result


def _mapped_labels(frame: pd.DataFrame, dataset: str, classes: list[str],
                   source_spec: dict) -> np.ndarray:
    if dataset == "unsw":
        column = "attack_cat"
    elif dataset == "cicids2017":
        column = "Label" if "Label" in frame else "label"
    else:
        column = "label"
    require(column in frame, f"Independent label column is absent: {dataset}/{column}")
    labels = frame[column].astype(str).str.strip()
    if dataset == "nslkdd":
        labels = labels.map(NSL_LABEL_MAP)
    elif dataset == "unsw":
        labels = labels.replace({"Backdoors": "Backdoor"})
        require("label" in frame, "Independent UNSW binary label is absent")
        binary = pd.to_numeric(frame["label"], errors="raise").to_numpy(dtype=np.int64)
        require(np.array_equal(binary, (labels != "Normal").to_numpy(dtype=np.int64)),
                "Independent UNSW label/attack category check failed")
    elif dataset == "iot23":
        labels = labels.map(IOT_LABEL_MAP)
    else:
        normalization = source_spec.get("label_normalization", {})
        aliases = normalization.get("aliases", {})
        require(isinstance(aliases, dict) and
                all(isinstance(key, str) and isinstance(value, str)
                    for key, value in aliases.items()),
                "Independent CIC label-alias contract is absent")
        labels = labels.replace(aliases)
    require(labels.notna().all(), f"Independent raw label mapping failed: {dataset}")
    mapping = {name: index for index, name in enumerate(classes)}
    encoded = labels.map(mapping)
    require(encoded.notna().all(), f"Independent mapped label is outside schema: {dataset}")
    return encoded.to_numpy(dtype=np.int64)


def _unscaled_raw(frame: pd.DataFrame, dataset: str, metadata: dict,
                  preprocessor: dict) -> tuple[np.ndarray, dict[str, int]]:
    features = metadata["features"]
    categories = preprocessor["categories"]
    unscaled = np.empty((len(frame), len(features)), dtype=np.float32)
    nonfinite: dict[str, int] = {}
    for index, column in enumerate(features):
        require(column in frame, f"Independent raw feature is absent: {dataset}/{column}")
        if column in CATEGORICAL[dataset]:
            mapping = {token: value for value, token in enumerate(categories[column])}
            encoded = frame[column].map(
                lambda value: mapping.get(_identity_token(value), -1)
            )
            unscaled[:, index] = encoded.to_numpy(dtype=np.float32)
        else:
            unscaled[:, index], nonfinite[column] = _numeric_fp32(
                frame[column], reject_nonfinite=(dataset == "nslkdd"),
            )
    return unscaled, nonfinite


def _transform_raw(frame: pd.DataFrame, dataset: str, metadata: dict,
                   preprocessor: dict) -> np.ndarray:
    unscaled, _ = _unscaled_raw(frame, dataset, metadata, preprocessor)
    transformed = np.ascontiguousarray(unscaled, dtype=np.float32)
    # StandardScaler.transform(copy=True) applies these operations in place to
    # an FP32 input.  Keeping the destination FP32 reproduces its rounding.
    return _scale_fp32_in_place(transformed, preprocessor["mean"], preprocessor["scale"])


def _xy_keys(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    labels = np.asarray(y, dtype=np.int64)
    require(x.ndim == 2 and labels.shape == (len(x),), "Invalid X/Y key input")
    # All class IDs are exactly representable in FP32.  Appending one FP32
    # column gives a fixed-width collision-free key for (final-X, label).
    joined = np.empty((len(x), x.shape[1] + 1), dtype=np.float32)
    joined[:, :-1] = np.asarray(x, dtype=np.float32)
    joined[:, -1] = labels.astype(np.float32)
    return _row_keys(joined)


class _KeyIndex:
    def __init__(self, keys: np.ndarray, source_indices: np.ndarray):
        keys = np.asarray(keys)
        source_indices = np.asarray(source_indices, dtype=np.int64)
        require(keys.ndim == 1 and source_indices.shape == keys.shape,
                "Invalid independent retained-key index")
        order = np.argsort(keys, kind="stable")
        self.keys = keys[order]
        self.source_indices = source_indices[order]
        require(not len(self.keys) or not (self.keys[1:] == self.keys[:-1]).any(),
                "A retained final key is duplicated within one source role")

    def lookup(self, query: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        query = np.asarray(query)
        locations = np.searchsorted(self.keys, query)
        matched = locations < len(self.keys)
        if matched.any():
            selected = np.flatnonzero(matched)
            matched[selected] = self.keys[locations[selected]] == query[selected]
        result = np.full(len(query), -1, dtype=np.int64)
        if matched.any():
            result[matched] = self.source_indices[locations[matched]]
        return matched, result


def _official_overlap_lineage_index(
    raw_data_root: Path, raw: dict, metadata: dict, arrays: Mapping[str, np.ndarray],
) -> tuple[_KeyIndex | None, dict[str, dict[str, int]]]:
    """Index excluded official-test representatives by *raw* (X,label), not final X.

    Raw identity/dedup replay proves the representatives; protocol replay proves
    their components touch official training. This additional raw-byte index
    carries that exclusion to every role-local duplicate source row. In
    particular, an unknown-category collision must never stand in for raw
    identity, and a transient component need not still collide with train X.
    """
    if metadata["dataset"] not in ("nslkdd", "unsw"):
        return None, {}
    ids = arrays["excluded_ids"][arrays["excluded_reasons"] == 2]
    if not len(ids):
        return None, {}
    require((ids >= metadata["official_train_raw_rows"]).all(),
            "Official-overlap lineage has a non-test representative")
    dataset, features = metadata["dataset"], metadata["features"]
    mappings = _identity_mappings(raw_data_root, raw["record"]) if CATEGORICAL[dataset] else {}
    keys, observed_ids = [], []
    offset = 0
    for frame in _iter_raw_frames(raw_data_root, raw["record"]):
        stop = offset + len(frame)
        left, right = np.searchsorted(ids, [offset, stop])
        if right > left:
            selected_ids = ids[left:right]
            selected = frame.iloc[selected_ids - offset]
            matrix = _canonical_group_matrix(selected, dataset, features, mappings)
            labels = _mapped_labels(selected, dataset, metadata["class_names"], raw["source_spec"])
            keys.append(_xy_keys(matrix, labels))
            observed_ids.append(selected_ids)
        offset = stop
    require(offset == metadata["raw_rows"] and observed_ids and
            np.array_equal(np.concatenate(observed_ids), ids),
            "Official-overlap raw lineage was not reconstructed exactly")
    return _KeyIndex(np.concatenate(keys), ids), mappings


def _verify_raw_cache_semantics(raw_data_root: Path, raw: dict, cache_root: Path,
                                metadata: dict, arrays: dict[str, np.ndarray]) -> None:
    """Tie every retained/excluded row and multiplicity back to raw semantics.

    This catches coordinated resealing and, importantly, a producer that drops
    a raw identity after a transient unknown-category collision even though the
    two patterns are distinct under the final fitted preprocessing state.
    """
    dataset = metadata["dataset"]
    preprocessor = load_json(cache_root / dataset / "preprocessing.json")
    preprocessing_fit_ids = np.asarray(arrays["preprocessing_fit_ids"])

    # Independently prove fit-only vocabulary and scaler provenance.  The
    # producer streams raw shards with the same sealed chunk size; reproducing
    # that order also makes the floating-point partial-fit state bit-exact.
    fit_categories = {column: set() for column in CATEGORICAL[dataset]}
    raw_offset = 0
    for frame in _iter_raw_frames(raw_data_root, raw["record"]):
        stop = raw_offset + len(frame)
        left = int(np.searchsorted(preprocessing_fit_ids, raw_offset, side="left"))
        right = int(np.searchsorted(preprocessing_fit_ids, stop, side="left"))
        if right > left:
            local = preprocessing_fit_ids[left:right] - raw_offset
            for column in CATEGORICAL[dataset]:
                fit_categories[column].update(
                    _identity_token(value) for value in frame.iloc[local][column]
                )
        raw_offset = stop
    expected_categories = {
        column: sorted(values) for column, values in fit_categories.items()
    }
    require(expected_categories == preprocessor["categories"],
            f"Categorical vocabulary was not fitted on exactly the sealed fit rows: {dataset}")

    pre_final_ids = {
        "fit": preprocessing_fit_ids,
        "validation": np.sort(np.r_[
            arrays["ids_validation"],
            arrays["final_dedup_ids"][arrays["final_dedup_origin_splits"] == 1],
        ]),
        "test": np.sort(np.r_[
            arrays["ids_test"],
            arrays["final_dedup_ids"][arrays["final_dedup_origin_splits"] == 2],
        ]),
    }
    scaler = StandardScaler()
    diagnostic_counts = {
        column: 0 for column in metadata["features"]
        if column not in CATEGORICAL[dataset]
    }
    unknown_counts = {
        split: {column: 0 for column in CATEGORICAL[dataset]} for split in SPLITS
    }
    raw_offset = 0
    for frame in _iter_raw_frames(raw_data_root, raw["record"]):
        stop = raw_offset + len(frame)
        unscaled, nonfinite = _unscaled_raw(frame, dataset, metadata, preprocessor)
        for column, count in nonfinite.items():
            diagnostic_counts[column] += count
        fit_left = int(np.searchsorted(preprocessing_fit_ids, raw_offset, side="left"))
        fit_right = int(np.searchsorted(preprocessing_fit_ids, stop, side="left"))
        if fit_right > fit_left:
            local = preprocessing_fit_ids[fit_left:fit_right] - raw_offset
            scaler.partial_fit(unscaled[local])
        for split, ids in pre_final_ids.items():
            left = int(np.searchsorted(ids, raw_offset, side="left"))
            right = int(np.searchsorted(ids, stop, side="left"))
            if right <= left:
                continue
            local = ids[left:right] - raw_offset
            for column in CATEGORICAL[dataset]:
                column_index = metadata["features"].index(column)
                unknown_counts[split][column] += int(
                    (unscaled[local, column_index] == -1).sum()
                )
        raw_offset = stop
    require(raw_offset == metadata["raw_rows"] and
            int(np.asarray(scaler.n_samples_seen_).min()) == len(preprocessing_fit_ids),
            f"Independent scaler fit population differs: {dataset}")
    require(np.array_equal(np.asarray(preprocessor["mean"]), scaler.mean_) and
            np.array_equal(np.asarray(preprocessor["var"]), scaler.var_) and
            np.array_equal(np.asarray(preprocessor["scale"]), scaler.scale_),
            f"Scaler statistics were not fitted on exactly the sealed fit rows: {dataset}")
    require(preprocessor["nonfinite_replacements"] == diagnostic_counts and
            preprocessor["unknown_categories_pre_final_raw_unique"] == unknown_counts,
            f"Preprocessing diagnostics differ from independent raw reconstruction: {dataset}")

    split_offsets: dict[str, tuple[int, int]] = {}
    retained_x_parts = []
    retained_y_parts = []
    retained_multiplicity_parts = []
    retained_ids_parts = []
    offset = 0
    for split in SPLITS:
        count = metadata["counts"][split]
        split_offsets[split] = (offset, offset + count)
        retained_x_parts.append(np.asarray(arrays[f"x_{split}"]))
        retained_y_parts.append(np.asarray(arrays[f"y_{split}"]))
        retained_multiplicity_parts.append(np.asarray(arrays[f"multiplicity_{split}"]))
        retained_ids_parts.append(np.asarray(arrays[f"ids_{split}"]))
        offset += count
    retained_x = np.concatenate(retained_x_parts, axis=0)
    retained_y = np.concatenate(retained_y_parts)
    retained_multiplicity = np.concatenate(retained_multiplicity_parts)
    retained_ids = np.concatenate(retained_ids_parts)
    observed_multiplicity = np.zeros(len(retained_ids), dtype=np.int64)

    def role_index(split_names: tuple[str, ...], *, labels: bool) -> _KeyIndex:
        positions = np.concatenate([
            np.arange(*split_offsets[split], dtype=np.int64) for split in split_names
        ])
        keys = (_xy_keys(retained_x[positions], retained_y[positions]) if labels
                else _row_keys(retained_x[positions]))
        return _KeyIndex(keys, positions)

    if dataset in ("nslkdd", "unsw"):
        official_train = int(metadata["official_train_raw_rows"])
        xy_indices = {
            "train": role_index(("fit", "validation"), labels=True),
            "test": role_index(("test",), labels=True),
        }
    else:
        official_train = -1
        xy_indices = {"combined": role_index(SPLITS, labels=True)}

    excluded_ids = np.asarray(arrays["excluded_ids"])
    excluded_reasons = np.asarray(arrays["excluded_reasons"])
    overlap_index, identity_mappings = _official_overlap_lineage_index(
        raw_data_root, raw, metadata, arrays,
    )
    reason_names = {
        int(code): reason for code, reason in metadata["exclusion_reason_codes"].items()
    }
    verified_excluded = np.zeros(len(excluded_ids), dtype=bool)
    raw_offset = 0
    for frame in _iter_raw_frames(raw_data_root, raw["record"]):
        stop = raw_offset + len(frame)
        raw_ids = np.arange(raw_offset, stop, dtype=np.int64)
        transformed = _transform_raw(frame, dataset, metadata, preprocessor)
        labels = _mapped_labels(frame, dataset, metadata["class_names"], raw["source_spec"])

        # Independently compare the producer's saved row with the raw row at
        # every retained identity, not merely with a self-reported digest.
        for split in SPLITS:
            ids = np.asarray(arrays[f"ids_{split}"])
            left = int(np.searchsorted(ids, raw_offset, side="left"))
            right = int(np.searchsorted(ids, stop, side="left"))
            if right <= left:
                continue
            selected_ids = ids[left:right]
            local = selected_ids - raw_offset
            require(np.array_equal(
                np.asarray(arrays[f"x_{split}"][left:right]), transformed[local],
            ), f"Retained final input differs from independent raw transform: {dataset}/{split}")
            require(np.array_equal(
                np.asarray(arrays[f"y_{split}"][left:right]), labels[local],
            ), f"Retained label differs from independent raw mapping: {dataset}/{split}")

        query_xy = _xy_keys(transformed, labels)
        excluded_source_lineage = np.zeros(len(raw_ids), dtype=bool)
        if overlap_index is not None:
            raw_identity_matrix = _canonical_group_matrix(
                frame, dataset, metadata["features"], identity_mappings,
            )
            raw_match, _ = overlap_index.lookup(_xy_keys(raw_identity_matrix, labels))
            excluded_source_lineage = raw_match & (raw_ids >= official_train)
        if dataset in ("nslkdd", "unsw"):
            role_masks = {
                "train": raw_ids < official_train,
                "test": raw_ids >= official_train,
            }
        else:
            role_masks = {"combined": np.ones(len(raw_ids), dtype=bool)}
        role_matches: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for role, mask in role_masks.items():
            matched = np.zeros(len(raw_ids), dtype=bool)
            positions = np.full(len(raw_ids), -1, dtype=np.int64)
            if mask.any():
                local_match, local_positions = xy_indices[role].lookup(query_xy[mask])
                matched[mask] = local_match
                positions[mask] = local_positions
                counted = local_match & ~excluded_source_lineage[mask]
                if counted.any():
                    np.add.at(observed_multiplicity, local_positions[counted], 1)
            role_matches[role] = matched, positions

        excluded_left = int(np.searchsorted(excluded_ids, raw_offset, side="left"))
        excluded_right = int(np.searchsorted(excluded_ids, stop, side="left"))
        for position in range(excluded_left, excluded_right):
            local = int(excluded_ids[position] - raw_offset)
            reason = reason_names[int(excluded_reasons[position])]
            lowered = reason.lower()
            role = ("train" if dataset in ("nslkdd", "unsw") and
                    excluded_ids[position] < official_train else
                    "test" if dataset in ("nslkdd", "unsw") else "combined")
            if reason == EXCLUSION_REASONS[2]:
                require(role == "test" and bool(excluded_source_lineage[local]),
                        f"Official-test component reason lacks raw test lineage: {dataset}")
                # Component membership is checked independently against the
                # sealed raw-unique final-component vector.  Do not substitute
                # final-X equality: a conservative monotonic component can
                # remain joined after a transient collision disappears.
            elif "duplicate" in lowered:
                excluded_test_duplicate = (reason == EXCLUSION_REASONS[3] and
                                           role == "test" and
                                           bool(excluded_source_lineage[local]))
                require(excluded_test_duplicate or bool(role_matches[role][0][local]),
                        f"Claimed duplicate is a distinct final (X,label) pattern: {dataset}")
                if reason == EXCLUSION_REASONS[4]:
                    final_position = int(np.searchsorted(
                        arrays["final_dedup_ids"], excluded_ids[position],
                    ))
                    require(final_position < len(arrays["final_dedup_ids"]) and
                            arrays["final_dedup_ids"][final_position] == excluded_ids[position],
                            f"Final duplicate lacks a sealed mapping: {dataset}")
                    retained_position = int(role_matches[role][1][local])
                    require(retained_position >= 0 and
                            retained_ids[retained_position] ==
                            arrays["final_dedup_representative_ids"][final_position],
                            f"Final duplicate maps to the wrong retained representative: {dataset}")
            else:
                raise VerificationError(
                    f"Independent raw semantics do not recognize exclusion reason: {dataset}/{reason}"
                )
            verified_excluded[position] = True
        raw_offset = stop
    require(raw_offset == metadata["raw_rows"],
            f"Independent semantic raw row total differs: {dataset}")
    require(verified_excluded.all(), f"Not every excluded row was semantically verified: {dataset}")
    require(np.array_equal(observed_multiplicity, retained_multiplicity),
            f"Independent per-pattern multiplicity differs: {dataset}")


def verify(
    raw_audit_path: Path,
    cache_root_a: Path,
    cache_root_b: Path,
    *,
    iot_provenance_path: Path,
    package: Path = PACKAGE,
    raw_data_root: Path = RAW_DATA_ROOT,
    repository_root: Path = ROOT,
    verifier_path: Path | None = None,
) -> dict:
    raw_audit_path = raw_audit_path.absolute()
    cache_root_a = cache_root_a.absolute()
    cache_root_b = cache_root_b.absolute()
    package, _ = _real_directory(package.absolute())
    raw_data_root, _ = _real_directory(raw_data_root.absolute())
    repository_root, _ = _real_directory(repository_root.absolute())
    root_a, stat_a = _real_directory(cache_root_a)
    root_b, stat_b = _real_directory(cache_root_b)
    require(root_a != root_b and (stat_a.st_dev, stat_a.st_ino) != (stat_b.st_dev, stat_b.st_ino),
            "The two cache rebuild roots must be distinct real directories")
    raw_audit_snapshot = _file_snapshot(raw_audit_path)
    raw_audit_sha256 = str(raw_audit_snapshot["sha256"])
    audit, raw_records, audit_mtime_ns = _load_raw_audit(raw_audit_path, package)
    require(_file_snapshot(raw_audit_path) == raw_audit_snapshot,
            "Raw audit changed between selection and validation")
    upstream_provenance = _load_iot_provenance(
        iot_provenance_path.absolute(), audit, package, repository_root,
    )
    verifier = Path(__file__) if verifier_path is None else verifier_path
    verifier_snapshot = _file_snapshot(verifier)
    producer_sources = ("audit_data.py", "contracts.py", "data_loaders.py", "group_protocol.py")
    stability_paths = [
        raw_audit_path,
        iot_provenance_path.absolute(),
        verifier,
        repository_root / "tools/verify_iot23_provenance.py",
        *(package / filename for filename in producer_sources),
        *(package / raw_records[name]["record"]["source_spec"] for name in DATASETS),
    ]
    for name in DATASETS:
        stability_paths.extend(
            raw_data_root / item["path"]
            for item in raw_records[name]["record"]["files"]
        )
    stability_paths.extend(
        repository_root / "data/iot23_origin" / item["path"]
        for item in raw_records["iot23"]["source_spec"].get("origin_shards", [])
    )
    input_stability = _input_stability(stability_paths)
    selected_raw_audit_binding = {
        "path": str(raw_audit_path.resolve()),
        "sha256": raw_audit_sha256,
        "content_sha256": audit["content_sha256"],
        "audit_implementation_sha256": audit["audit_implementation_sha256"],
    }
    for name in DATASETS:
        raw_records[name]["record"]["_audit_data_loader_sha256"] = audit["data_loader_sha256"]
        raw_records[name]["raw_audit_binding"] = selected_raw_audit_binding

    inventory_a = _cache_root_inventory(root_a, after_ns=audit_mtime_ns)
    inventory_b = _cache_root_inventory(root_b, after_ns=audit_mtime_ns)
    require(inventory_a == inventory_b, "The two fresh cache rebuilds are not byte-identical")
    stability_a = _cache_root_stability(root_a, after_ns=audit_mtime_ns)
    stability_b = _cache_root_stability(root_b, after_ns=audit_mtime_ns)
    producer = {filename: sha256(package / filename) for filename in producer_sources}

    reports: dict[str, dict] = {}
    for dataset in DATASETS:
        raw_snapshot = _raw_file_snapshot(raw_data_root, raw_records[dataset]["record"])
        metadata_a, arrays_a, summary_a = _validate_one_cache(
            root_a, dataset, raw_records[dataset], package,
        )
        metadata_b, _arrays_b, summary_b = _validate_one_cache(
            root_b, dataset, raw_records[dataset], package,
        )
        require(metadata_a == metadata_b and summary_a == summary_b,
                f"Rebuild metadata differs: {dataset}")
        del _arrays_b
        independent_raw = _verify_raw_identity_and_dedup(
            raw_data_root, raw_records[dataset], metadata_a, arrays_a, replay_protocol=True,
        )
        require(independent_raw == metadata_a["raw_model_view_sha256"],
                f"Independent raw model-view fingerprint differs: {dataset}")
        _verify_raw_cache_semantics(
            raw_data_root, raw_records[dataset], root_a, metadata_a, arrays_a,
        )
        require(_raw_file_snapshot(raw_data_root, raw_records[dataset]["record"]) == raw_snapshot,
                f"Raw source changed during independent verification: {dataset}")
        semantic_checks = {key: True for key in SEMANTIC_CHECK_KEYS}
        semantic_checks["all_passed"] = all(semantic_checks.values())
        reports[dataset] = {
            **summary_a,
            "raw_files": raw_records[dataset]["record"]["files"],
            "byte_identical_rebuilds": True,
            "semantic_checks": semantic_checks,
            "cache_counts": summary_a["counts"],
            "classes": summary_a["class_names"],
            "rebuilds": [
                {
                    "resolved_root": str((root_a / dataset).resolve()),
                    "metadata_sha256": sha256(root_a / dataset / "metadata.json"),
                    "data_fingerprint": metadata_a["data_fingerprint"],
                    "files_sha256": metadata_a["files_sha256"],
                },
                {
                    "resolved_root": str((root_b / dataset).resolve()),
                    "metadata_sha256": sha256(root_b / dataset / "metadata.json"),
                    "data_fingerprint": metadata_b["data_fingerprint"],
                    "files_sha256": metadata_b["files_sha256"],
                },
            ],
        }
        del arrays_a

    require(all(set(record["semantic_checks"]) ==
                set(SEMANTIC_CHECK_KEYS) | {"all_passed"} and
                all(record["semantic_checks"].values())
                for record in reports.values()),
            "Semantic acceptance checklist is incomplete")
    require({filename: sha256(package / filename) for filename in producer_sources} == producer,
            "Producer source changed during independent verification")
    require(_file_snapshot(raw_audit_path) == raw_audit_snapshot,
            "Raw audit changed during independent verification")
    require(_cache_root_inventory(root_a, after_ns=audit_mtime_ns) == inventory_a and
            _cache_root_inventory(root_b, after_ns=audit_mtime_ns) == inventory_b,
            "Cache-root content changed during independent verification")
    require(_cache_root_stability(root_a, after_ns=audit_mtime_ns) == stability_a and
            _cache_root_stability(root_b, after_ns=audit_mtime_ns) == stability_b,
            "Cache-root inode/timestamp state changed during independent verification")
    require(_input_stability(stability_paths) == input_stability,
            "A verifier/tool/spec/raw/evidence input changed during verification")
    require(_file_snapshot(verifier) == verifier_snapshot,
            "Independent verifier bytes changed during verification")
    return {
        "kind": "spikeids_v5_data_acceptance",
        "acceptance_schema": 1,
        "data_acceptance_passed": True,
        "two_distinct_fresh_roots": True,
        "byte_identical_rebuilds": True,
        "raw_audit": {
            "path": str(raw_audit_path.resolve()),
            "sha256": raw_audit_sha256,
            "content_sha256": audit["content_sha256"],
            "audit_implementation_sha256": audit["audit_implementation_sha256"],
            "raw_source_audit_passed": True,
        },
        "upstream_provenance": upstream_provenance,
        "producer": {
            "path": str((package / "data_loaders.py").resolve()),
            "sha256": producer["data_loaders.py"],
        },
        "independent_verifier": {
            "path": str(verifier.resolve()),
            "sha256": verifier_snapshot["sha256"],
        },
        "datasets": reports,
        "limitations": {
            "capture_generalization_established": False,
            "device_generalization_established": False,
            "time_generalization_established": False,
            "upstream_preprocessing_verified": False,
            "external_authenticity_verified": False,
        },
        "freshness_definition": (
            "distinct resolved root inodes; no symlink or multiply-linked input; exact root/file "
            "inventory; every cache file timestamp is not older than the sealed raw audit"
        ),
        "scope": (
            "two byte-identical rebuilds, exact-source canonical model-view recomputation, and "
            "independent cache semantic validation; no capture/device/time generalization or "
            "external authenticity claim"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--raw-audit", required=True, type=Path)
    parser.add_argument("--iot-provenance", required=True, type=Path)
    parser.add_argument("--cache-root-a", required=True, type=Path)
    parser.add_argument("--cache-root-b", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.absolute()
    for root in (args.cache_root_a.absolute(), args.cache_root_b.absolute()):
        require(not output.resolve(strict=False).is_relative_to(root.resolve()),
                "Acceptance output must be outside both immutable cache roots")
    report = seal(verify(
        args.raw_audit,
        args.cache_root_a,
        args.cache_root_b,
        iot_provenance_path=args.iot_provenance,
    ))
    _write_new_json(output, report)
    print(
        f"data_acceptance_passed=true evidence={output.resolve()} "
        f"content_sha256={report['content_sha256']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
