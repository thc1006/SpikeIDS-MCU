"""Fail-closed, bounded-memory audit of the four real benchmark sources.

This verifies local bytes, physical schemas, row/file roles, label mappings, and
supporting archive bindings.  Passing this audit does not claim that upstream
publishers excluded group/capture/device leakage; those limits remain explicit.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np

from contracts import (
    DATASETS,
    SCHEMA,
    digest,
    load_json,
    require,
    seal,
    sha256,
    write_json,
    write_text,
)
from data_loaders import (
    CIC_DUPLICATE_INDICES,
    CIC_DUPLICATE_NAME,
    CLASSES,
    _batches,
    _labels_and_features,
    _source_snapshot,
    source_files,
)

PACKAGE = Path(__file__).resolve().parent


def _snapshot(path: Path) -> dict:
    return _source_snapshot(path)


def _physical_schema(path: Path, dataset: str) -> list[str]:
    if path.suffix.lower() == ".parquet":
        import pyarrow.parquet as pq
        return [str(name).strip() for name in pq.ParquetFile(path).schema.names]
    if dataset == "nslkdd":
        # NSL-KDD is headerless; its 43-column contract is checked per chunk.
        return [f"column_{i}" for i in range(43)]
    with path.open("r", encoding="utf-8", errors="strict", newline="") as stream:
        try:
            raw = next(csv.reader(stream))
            if raw:
                raw[0] = raw[0].removeprefix("\ufeff")
            return [str(name).strip() for name in raw]
        except StopIteration as exc:
            raise ValueError(f"Empty CSV: {path}") from exc


def _physical_duplicates(columns: list[str]) -> dict[str, list[int]]:
    positions: dict[str, list[int]] = {}
    for index, name in enumerate(columns):
        positions.setdefault(name, []).append(index)
    return {name: indices for name, indices in positions.items() if len(indices) > 1}


def _member_sha256(archive: zipfile.ZipFile, member: str) -> str:
    h = hashlib.sha256()
    with archive.open(member) as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _file_md5(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _supporting_artifacts(spec: dict, repository_root: Path, file_records: list[dict]) -> list[dict]:
    checked = []
    for record in spec.get("supporting_archives", []):
        path = (repository_root / record["path_from_repository_root"]).resolve()
        try:
            path.relative_to(repository_root)
        except ValueError as exc:
            raise ValueError(f"Supporting artifact escapes repository root: {path}") from exc
        require(path.is_file(), f"Missing supporting artifact: {path}")
        require(path.stat().st_size == record["bytes"], f"Supporting artifact byte mismatch: {path.name}")
        require(sha256(path) == record["sha256"], f"Supporting artifact SHA-256 mismatch: {path.name}")
        actual = {"path": record["path_from_repository_root"], "bytes": path.stat().st_size,
                  "sha256": sha256(path), "use": record["use"]}
        if "md5" in record:
            md5 = _file_md5(path)
            require(md5 == record["md5"], f"Supporting artifact MD5 mismatch: {path.name}")
            actual["md5"] = md5
        if path.name == "MachineLearningCSV.zip":
            by_name = {Path(row["path"]).name: row for row in file_records}
            with zipfile.ZipFile(path) as archive:
                names = {name for name in archive.namelist() if not name.endswith("/")}
                expected = {f"MachineLearningCVE/{name}" for name in by_name}
                require(names == expected, "MachineLearningCSV.zip member inventory differs from the eight pinned CSVs")
                for member in sorted(expected):
                    require(_member_sha256(archive, member) == by_name[Path(member).name]["sha256"],
                            f"Archive member differs from pinned CSV: {member}")
            actual["member_binding"] = "all_eight_csv_sha256_match"
        checked.append(actual)
    return checked


def audit_dataset(dataset: str, data_dir: Path, spec_path: Path, chunksize: int) -> dict:
    data_dir = Path(data_dir).resolve()
    spec_path = Path(spec_path).resolve()
    spec = load_json(spec_path)
    items = source_files(dataset, data_dir, spec_path)
    declared = {(data_dir / row["path"]).resolve(): row for row in spec["files"]}
    files = []
    total_rows = 0
    common_features = None
    combined_mapped = Counter()
    for path, role in items:
        source_start = _snapshot(path)
        row_spec = declared[path]
        physical_columns = _physical_schema(path, dataset)
        require(len(physical_columns) == row_spec["expected_columns"],
                f"{path.name}: physical column count differs from source contract")
        duplicates = _physical_duplicates(physical_columns)
        if dataset == "cicids2017" and path.suffix.lower() == ".csv":
            policy = spec.get("physical_duplicate_column_policy")
            require(policy == {
                "name": CIC_DUPLICATE_NAME,
                "indices_zero_based": list(CIC_DUPLICATE_INDICES),
                "drop_index_zero_based": CIC_DUPLICATE_INDICES[1],
                "require_chunkwise_value_identity": True,
            }, f"{path.name}: missing/mismatched CIC duplicate-column source contract")
            require(duplicates == {CIC_DUPLICATE_NAME: list(CIC_DUPLICATE_INDICES)},
                    f"{path.name}: CIC physical duplicates differ from contract: {duplicates}")
        else:
            require(not duplicates,
                    f"{path.name}: duplicate physical columns after whitespace normalization")
        rows = 0
        selected_columns = None
        raw_counts = Counter()
        mapped_counts = Counter()
        expected_unsw_id = 1
        for frame, observed_role in _batches(
                [(path, role)], dataset, chunksize, strict_source_contract=True):
            require(observed_role == role, "File role changed during audit")
            columns = list(frame.columns)
            if selected_columns is None:
                selected_columns = columns
            require(columns == selected_columns, f"{path.name}: schema/order changed between chunks")
            y, features = _labels_and_features(frame, dataset)
            if common_features is None:
                common_features = features
            require(features == common_features, f"{path.name}: feature schema/order differs across source files")
            label_column = "attack_cat" if dataset == "unsw" else (
                "Label" if dataset == "cicids2017" and "Label" in frame else "label")
            raw = frame[label_column].astype(str).str.strip()
            raw_counts.update(raw.tolist())
            mapped_counts.update(CLASSES[dataset][int(code)] for code in y)
            if dataset == "unsw":
                ids = frame["id"].astype(np.int64).to_numpy()
                expected = np.arange(expected_unsw_id, expected_unsw_id + len(ids), dtype=np.int64)
                require(np.array_equal(ids, expected), f"{path.name}: id is not contiguous 1..N in file order")
                expected_unsw_id += len(ids)
            rows += len(frame)
        require(rows == row_spec["expected_rows"], f"{path.name}: row count differs from source contract")
        if "expected_raw_label_counts" in row_spec:
            require(dict(sorted(raw_counts.items())) == row_spec["expected_raw_label_counts"],
                    f"{path.name}: raw label composition differs from source contract")
        require(sum(mapped_counts.values()) == rows, f"{path.name}: not every row mapped to a declared class")
        require(_snapshot(path) == source_start,
                f"{path.name}: source changed while its rows were audited")
        total_rows += rows
        combined_mapped.update(mapped_counts)
        files.append({
            "path": path.relative_to(data_dir).as_posix(), "role": role,
            "bytes": source_start["bytes"], "sha256": source_start["sha256"],
            "rows": rows, "physical_columns": physical_columns,
            "physical_duplicate_columns": duplicates,
            "dropped_physical_column_index": CIC_DUPLICATE_INDICES[1]
                if duplicates else None,
            "selected_columns": selected_columns, "raw_label_counts": dict(sorted(raw_counts.items())),
            "mapped_label_counts": dict(sorted(mapped_counts.items())),
        })
    if "expected_total_rows" in spec:
        require(total_rows == spec["expected_total_rows"], f"{dataset}: total row count differs from source contract")
    require(set(combined_mapped) == set(CLASSES[dataset]), f"{dataset}: declared mapped classes are incomplete")
    return {
        "dataset": dataset,
        "source_spec": spec_path.relative_to(PACKAGE).as_posix(),
        "source_spec_sha256": sha256(spec_path),
        "provenance_note": spec["provenance_note"],
        "origin": spec.get("origin"),
        "rows": total_rows,
        "features": common_features,
        "classes": CLASSES[dataset],
        "mapped_label_counts": dict(sorted(combined_mapped.items())),
        "files": files,
    }


def _markdown(report: dict) -> str:
    lines = [
        "# SpikeIDS v5 real-data audit",
        "",
        f"`raw_source_audit_passed`: **{str(report['raw_source_audit_passed']).lower()}**",
        f"`data_acceptance_passed`: **{str(report['data_acceptance_passed']).lower()}**",
        "",
        "This pass binds exact local bytes, file roles, row counts, physical/selected column order, and every label mapping. It is not a claim that an upstream publisher excluded semantic duplicates or capture/device/time leakage.",
        "",
        "| Dataset | Rows | Model features | Classes | Source files |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in DATASETS:
        row = report["datasets"][name]
        lines.append(f"| {name} | {row['rows']} | {len(row['features'])} | {len(row['classes'])} | {len(row['files'])} |")
    lines.extend([
        "",
        "## Scope limits",
        "",
        "- NSL-KDD and UNSW-NB15 preserve their declared official train/test roles; validation is drawn only from official training rows.",
        "- CICIDS2017 and IoT-23 use a frozen exact-X-grouped target-64/16/20 protocol after exact-(X,label) deduplication; group constraints make the realized fractions approximate. This does not establish unseen-capture, unseen-device, or temporal generalization.",
        "- The IoT-23 derivative was globally deduplicated upstream and lacks trustworthy group identifiers. Its source manifest records this limitation and `upstream_preprocessing_verified` remains false in the cache.",
        "- The CIC MachineLearningCSV archive is byte-bound to all eight 79-column physical CSVs; the audited drop policy leaves 76 model features. GeneratedLabelledFlows is provenance only.",
        "- Passing SHA checks establishes artifact identity, not an external trust root or physical attestation.",
        "",
        f"Sealed JSON evidence: `{report['json_evidence_path']}`",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--source-spec-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--summary", type=Path, default=PACKAGE / "DATA_AUDIT.md")
    parser.add_argument("--repository-root", type=Path, default=PACKAGE.parent)
    parser.add_argument("--chunksize", type=int, default=65536)
    args = parser.parse_args()
    require(args.chunksize >= 2, "chunksize must be at least 2")
    data_dir = args.data_dir.resolve()
    spec_dir = args.source_spec_dir.resolve()
    repository_root = args.repository_root.resolve()
    implementation_path = Path(__file__).resolve()
    loader_path = PACKAGE / "data_loaders.py"
    implementation_start = _snapshot(implementation_path)
    loader_start = _snapshot(loader_path)
    spec_start = {
        dataset: _snapshot(spec_dir / f"{dataset}.json") for dataset in DATASETS
    }
    all_source_snapshots = {}
    for dataset in DATASETS:
        spec_path = spec_dir / f"{dataset}.json"
        for path, _ in source_files(dataset, data_dir, spec_path):
            all_source_snapshots[path] = _snapshot(path)
        spec = load_json(spec_path)
        for artifact in spec.get("supporting_archives", []):
            artifact_path = repository_root / artifact["path_from_repository_root"]
            all_source_snapshots[artifact_path] = _snapshot(artifact_path)
    datasets = {}
    artifacts = {}
    for dataset in DATASETS:
        spec_path = spec_dir / f"{dataset}.json"
        datasets[dataset] = audit_dataset(dataset, data_dir, spec_path, args.chunksize)
        spec = load_json(spec_path)
        checked = _supporting_artifacts(spec, repository_root, spec["files"])
        if checked:
            artifacts[dataset] = checked
        print(f"audited {dataset}: {datasets[dataset]['rows']} rows", flush=True)
    # Fail closed if any source/spec/tool identity changed during this multi-pass
    # audit, including a same-size mutate-and-restore attempt detectable by ctime.
    require(_snapshot(implementation_path) == implementation_start,
            "Audit implementation changed during execution")
    require(_snapshot(loader_path) == loader_start,
            "Data loader changed during audit execution")
    for path, original in all_source_snapshots.items():
        require(_snapshot(path) == original,
                f"Raw/supporting source changed across audit execution: {path}")
    for dataset in DATASETS:
        require(_snapshot(spec_dir / f"{dataset}.json") == spec_start[dataset],
                f"{dataset} source spec changed during audit")
        for record in datasets[dataset]["files"]:
            path = data_dir / record["path"]
            current = _snapshot(path)
            require(current["bytes"] == record["bytes"] and
                    current["sha256"] == record["sha256"],
                    f"{dataset} raw source changed during audit: {record['path']}")
        for record in artifacts.get(dataset, []):
            path = repository_root / record["path"]
            current = _snapshot(path)
            require(current["bytes"] == record["bytes"] and
                    current["sha256"] == record["sha256"],
                    f"{dataset} supporting artifact changed during audit: {record['path']}")
    output_dir = args.output_dir.resolve()
    json_path = output_dir / "data_audit.json"
    report = {
        "schema": SCHEMA,
        "audit_schema": 3,
        "raw_source_audit_passed": True,
        "data_acceptance_passed": False,
        "data_acceptance_blocker": "requires two fresh byte-identical cache builds plus an independent semantic verifier",
        "audit_implementation_sha256": implementation_start["sha256"],
        "data_loader_sha256": loader_start["sha256"],
        "datasets": datasets,
        "supporting_artifacts": artifacts,
        "scope": "exact-source and declared row-protocol audit; not upstream semantic/group-leakage attestation",
        "limitations": {
            "cicids2017_group_holdout": False,
            "iot23_group_holdout": False,
            "iot23_upstream_preprocessing_fully_verified": False,
        },
        "json_evidence_path": json_path.relative_to(repository_root).as_posix(),
    }
    report["audit_fingerprint"] = digest(report)
    write_json(json_path, seal(report))
    write_text(args.summary, _markdown(report))
    print(f"raw_source_audit_passed=true data_acceptance_passed=false evidence={json_path}",
          flush=True)


if __name__ == "__main__":
    main()
