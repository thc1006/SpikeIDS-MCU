#!/usr/bin/env python3
"""Create an immutable, plan-addressed SpikeIDS-v5 deployment/evidence bundle."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "spikeids_v5"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PACKAGE))

from check_paper_consistency import check as check_paper_consistency  # noqa: E402
from contracts import (  # noqa: E402
    check_seal,
    load_json,
    require,
    seal,
    sha256,
    write_json,
    write_text,
)
from evidence import verified_suite  # noqa: E402

from tools.run_v5_exports import (  # noqa: E402
    EXPORT_RUNNER_PACKAGES,
    expected_export_macros,
    export_macro_text,
    exporter_invocation,
    load_export_plan,
    replay_scientific_failure,
    scientific_failure,
    validate_export_summary,
    validate_attempt,
)
from tools.verify_v5_neural import (  # noqa: E402
    NEURAL_VERIFIER_PACKAGES,
    tool_provenance,
    validate_tool_provenance,
)
from tools.verify_v5_neural import verify as verify_neural_independent  # noqa: E402
from tools.verify_v5_tree import TREE_VERIFIER_PACKAGES  # noqa: E402
from tools.verify_v5_tree import verify as verify_tree_independent  # noqa: E402
from tree_baseline import load_verified_tree_suite  # noqa: E402

JOBS = (
    ("nslkdd", "relu"), ("nslkdd", "qcfs"), ("nslkdd", "cnn"),
    ("unsw", "relu"), ("unsw", "qcfs"), ("unsw", "cnn"),
    ("cicids2017", "relu"), ("cicids2017", "qcfs"), ("cicids2017", "cnn"),
    ("iot23", "relu"), ("iot23", "qcfs"),
)
PACKAGE_TOOL_PACKAGES = (
    "joblib", "numpy", "onnx", "onnxruntime", "scikit-learn", "scipy",
    "statsmodels", "torch", "xgboost",
)
LIFECYCLE_TOOLS = (
    "verify_v5_neural.py",
    "verify_v5_tree.py",
    "run_v5_exports.py",
    "package_v5_artifacts.py",
    "archive_pre_v5.py",
)
AUXILIARY_TOOLS = ("build_v5_paper.py", "verify_v5_paper_build.py", "v5_retention.py")
ARCHIVE_REPLAY_BLOCKER = {
    "status": "not_replayed_from_bundle",
    "reason": (
        "The compact bundle intentionally omits the complete 440 neural prediction "
        "artifacts and all tree primary/replica models required for safe verifier replay."
    ),
    "gate": "exact bundled lifecycle-tool/report/manifest byte binding only",
}
FORMAL_DATASETS = ("nslkdd", "unsw", "cicids2017", "iot23")
DATA_ACCEPTANCE_SEMANTIC_CHECKS = frozenset({
    "inventory_complete", "seals_valid", "code_binding_valid", "shapes_valid",
    "dtypes_valid", "finite_values", "canonical_zero", "id_accounting_exact",
    "class_support_complete", "multiplicity_valid", "exclusion_reasons_valid",
    "zero_group_overlap", "zero_final_fp32_overlap",
    "raw_model_view_fingerprint_valid", "frozen_partition_and_closure_replayed", "all_passed",
})
DATA_ACCEPTANCE_LIMITATIONS = frozenset({
    "capture_generalization_established", "device_generalization_established",
    "time_generalization_established", "upstream_preprocessing_verified",
    "external_authenticity_verified",
})
IOT_PROVENANCE_LIMITATIONS = frozenset({
    "original_iot23_reconstruction_established",
    "upstream_publisher_preprocessing_reproduced",
    "device_group_generalization_established",
    "capture_group_generalization_established",
    "time_group_generalization_established",
    "external_authenticity_established",
})
IOT_PROVENANCE_COLUMNS = (
    "ts", "uid", "id.orig_h", "id.orig_p", "id.resp_h", "id.resp_p",
    "proto", "service", "duration", "orig_bytes", "resp_bytes", "conn_state",
    "local_orig", "local_resp", "missed_bytes", "history", "orig_pkts",
    "orig_ip_bytes", "resp_pkts", "resp_ip_bytes", "label",
)
IOT_PROVENANCE_TOOL = ROOT / "tools/verify_iot23_provenance.py"
IOT_PROVENANCE_SPEC = PACKAGE / "audit/source_specs/iot23.json"
IOT_PROVENANCE_REPORT_BUNDLE = "payload/evidence/data/iot23_provenance.json"
IOT_PROVENANCE_TOOL_BUNDLE = (
    "payload/source/data_acceptance/iot23_provenance_verifier.py"
)


def snapshot_regular_file(path: Path) -> dict:
    """Capture the immutable identity used across validation and copying."""
    path = Path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and not path.is_symlink(),
            f"Snapshot source is not a regular non-symlink file: {path}")
    require(before.st_nlink == 1, f"Hardlinked source is forbidden: {path}")
    digest = sha256(path)
    after = path.lstat()
    identity_before = (
        before.st_dev, before.st_ino, before.st_mode, before.st_nlink,
        before.st_size, before.st_mtime_ns, before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev, after.st_ino, after.st_mode, after.st_nlink,
        after.st_size, after.st_mtime_ns, after.st_ctime_ns,
    )
    require(identity_after == identity_before and
            stat.S_ISREG(after.st_mode) and not path.is_symlink(),
            f"Snapshot source changed while hashing: {path}")
    return {
        "device": after.st_dev,
        "inode": after.st_ino,
        "mode": after.st_mode,
        "nlink": after.st_nlink,
        "size": after.st_size,
        "mtime_ns": after.st_mtime_ns,
        "ctime_ns": after.st_ctime_ns,
        "sha256": digest,
    }


def copy_snapshot(source: Path, destination: Path, expected: dict) -> None:
    """Copy one frozen source and reject source races or hardlink aliases."""
    source = Path(source)
    destination = Path(destination)
    before = snapshot_regular_file(source)
    require(before == expected, f"Validated source changed before copy: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    after = snapshot_regular_file(source)
    copied = snapshot_regular_file(destination)
    require(after == before, f"Validated source changed during copy: {source}")
    require(copied["sha256"] == before["sha256"] and
            copied["size"] == before["size"] and
            (copied["device"], copied["inode"]) !=
            (before["device"], before["inode"]),
            f"Bundle copy is not an independent exact byte copy: {destination}")


def resolve_evidence_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{label} path is missing")
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    require(not path.is_symlink(), f"{label} path must not be a symlink")
    path = path.resolve()
    require(path.is_file() and not path.is_symlink(), f"{label} is missing or symlinked")
    return path


def fixed_regular_file(root: Path, relative: object, label: str) -> tuple[Path, dict]:
    """Resolve one fixed-root relative file without accepting symlink components."""
    if not isinstance(relative, str):
        raise RuntimeError(f"{label} path is malformed")
    require(relative and "\\" not in relative, f"{label} path is malformed")
    relative_path = Path(relative)
    require(not relative_path.is_absolute() and ".." not in relative_path.parts and
            relative_path.as_posix() == relative,
            f"{label} path escapes its fixed root")
    root = Path(root).absolute()
    require(root.is_dir() and not root.is_symlink(), f"{label} root is unsafe")
    current = root
    for component in relative_path.parts:
        current /= component
        require(current.exists() and not current.is_symlink(),
                f"{label} contains a missing or symlinked component")
    resolved = current.resolve()
    require(resolved.is_relative_to(root.resolve()), f"{label} escapes its fixed root")
    return resolved, snapshot_regular_file(resolved)


def cache_files_sha256(root: Path) -> dict[str, str]:
    """Hash the complete flat cache payload, excluding its separately bound metadata."""
    root = Path(root)
    require(not root.is_symlink(), f"Cache root is symlinked: {root}")
    root = root.resolve()
    require(root.is_dir() and not root.is_symlink(), f"Cache root is missing: {root}")
    entries = sorted(root.iterdir())
    require(entries and all(path.is_file() and not path.is_symlink() and
                            path.lstat().st_nlink == 1 for path in entries),
            f"Cache must be a flat tree of independent regular files: {root}")
    return {path.name: sha256(path) for path in entries if path.name != "metadata.json"}


def validate_iot_provenance(report_path: Path, audit: dict) -> tuple[dict, Path, Path]:
    """Validate the accepted IoT derivative comparison without importing its tool."""
    report_path = resolve_evidence_path(
        str(report_path), "IoT-23 provenance report"
    )
    require(report_path.name == "iot23_provenance.json" and
            report_path == (PACKAGE / "audit/iot23_provenance.json").resolve(),
            "IoT-23 provenance report is not at the fixed formal path")
    snapshot_regular_file(report_path)
    report = load_json(report_path)
    check_seal(report)
    require(report.get("kind") == "spikeids_v5_iot23_provenance" and
            report.get("schema") == 1 and
            report.get("comparison_passed") is True and
            report.get("passed") is True,
            "IoT-23 provenance comparison is missing, failed, or unsupported")
    limitations = report.get("limitations")
    require(isinstance(limitations, dict) and
            set(limitations) == IOT_PROVENANCE_LIMITATIONS and
            all(value is False for value in limitations.values()),
            "IoT-23 provenance limitations are missing or overclaimed")

    tool_record = report.get("tool")
    require(isinstance(tool_record, dict) and set(tool_record) == {"path", "sha256"},
            "IoT-23 provenance tool binding is malformed")
    tool = resolve_evidence_path(tool_record["path"], "IoT-23 provenance tool")
    require(tool == IOT_PROVENANCE_TOOL.resolve() and
            tool_record.get("sha256") == sha256(tool),
            "IoT-23 provenance is not bound to the exact current verifier")
    snapshot_regular_file(tool)

    spec_record = report.get("source_spec")
    require(isinstance(spec_record, dict) and
            set(spec_record) == {"path", "bytes", "sha256"},
            "IoT-23 provenance source-spec binding is malformed")
    spec_path = resolve_evidence_path(
        spec_record["path"], "IoT-23 provenance source spec"
    )
    spec_snapshot = snapshot_regular_file(spec_path)
    audit_iot = audit.get("datasets", {}).get("iot23", {})
    require(spec_path == IOT_PROVENANCE_SPEC.resolve() and
            spec_record.get("bytes") == spec_snapshot["size"] and
            spec_record.get("sha256") == spec_snapshot["sha256"] ==
            audit_iot.get("source_spec_sha256"),
            "IoT-23 provenance source spec differs from the raw audit")
    spec = load_json(spec_path)
    require(spec.get("dataset") == "iot23" and
            spec.get("source_contract_version") == 1 and
            report.get("origin_revision") ==
            spec.get("origin", {}).get("revision"),
            "IoT-23 provenance source contract/revision differs")

    reported_shards = report.get("origin_shards")
    declared_shards = spec.get("origin_shards")
    require(isinstance(reported_shards, list) and
            isinstance(declared_shards, list) and
            len(reported_shards) == len(declared_shards) == 3,
            "IoT-23 provenance must bind exactly three origin shards")
    for index, (reported, declared) in enumerate(zip(
            reported_shards, declared_shards, strict=True)):
        require(isinstance(reported, dict) and isinstance(declared, dict) and
                set(reported) == {
                    "path", "bytes", "sha256", "rows", "physical_schema"
                } and
                {key: reported.get(key) for key in ("path", "bytes", "sha256")} == {
                    "path": declared.get("path"),
                    "bytes": declared.get("bytes"),
                    "sha256": declared.get("lfs_sha256"),
                } and type(reported.get("rows")) is int and reported["rows"] > 0 and
                isinstance(reported.get("physical_schema"), dict),
                f"IoT-23 origin-shard provenance is malformed: {index}")
        _path, live = fixed_regular_file(
            ROOT / "data/iot23_origin", reported["path"],
            f"IoT-23 origin shard {index}",
        )
        require(live["size"] == reported["bytes"] and
                live["sha256"] == reported["sha256"],
                f"IoT-23 origin-shard bytes changed: {index}")

    combined = report.get("combined")
    declared_files = spec.get("files")
    require(isinstance(combined, dict) and set(combined) == {
                "path", "bytes", "sha256", "rows", "physical_schema"
            } and isinstance(declared_files, list) and len(declared_files) == 1 and
            isinstance(declared_files[0], dict),
            "IoT-23 combined provenance binding is malformed")
    declared_combined = declared_files[0]
    combined_identity = {
        key: combined.get(key) for key in ("path", "bytes", "sha256", "rows")
    }
    require(combined_identity == {
                "path": declared_combined.get("path"),
                "bytes": declared_combined.get("bytes"),
                "sha256": declared_combined.get("sha256"),
                "rows": declared_combined.get("expected_rows"),
            } and isinstance(combined.get("physical_schema"), dict),
            "IoT-23 combined provenance differs from the source contract")
    audited_files = audit_iot.get("files")
    require(isinstance(audited_files, list) and len(audited_files) == 1 and
            {key: audited_files[0].get(key)
             for key in ("path", "bytes", "sha256", "rows")} == combined_identity,
            "IoT-23 provenance combined file differs from the raw audit")
    _combined_path, live_combined = fixed_regular_file(
        ROOT / "data", combined["path"], "IoT-23 local combined file"
    )
    require(live_combined["size"] == combined["bytes"] and
            live_combined["sha256"] == combined["sha256"],
            "IoT-23 local combined bytes changed after provenance comparison")

    semantic = report.get("semantic_comparison")
    require(isinstance(semantic, dict) and
            semantic.get("rows") == combined.get("rows") and
            semantic.get("columns") == list(IOT_PROVENANCE_COLUMNS) and
            semantic.get("chunk_rows") == 65536 and
            type(semantic.get("chunks")) is int and semantic["chunks"] > 0 and
            all(semantic.get(key) is True for key in (
                "column_order_equal", "row_order_equal", "values_equal",
                "missingness_equal",
            )) and isinstance(semantic.get("normalizations"), list) and
            type(semantic.get("parquet_schema_metadata_equal")) is bool and
            semantic.get("parquet_schema_metadata_is_semantic") is False,
            "IoT-23 semantic comparison evidence is incomplete")
    return report, tool, spec_path


def validate_data_acceptance(
        acceptance_path: Path, audit_path: Path, audit: dict, plan: dict,
) -> tuple[dict, Path, Path, Path, Path]:
    """Validate two-build data acceptance without importing its producer/verifier."""
    acceptance_path = Path(acceptance_path).resolve()
    audit_path = Path(audit_path).resolve()
    report = load_json(acceptance_path)
    check_seal(report)
    require(report.get("kind") == "spikeids_v5_data_acceptance" and
            report.get("acceptance_schema") == 1 and
            report.get("data_acceptance_passed") is True and
            report.get("two_distinct_fresh_roots") is True and
            report.get("byte_identical_rebuilds") is True,
            "Independent data-acceptance report is missing, failed, or unsupported")
    require(audit.get("raw_source_audit_passed") is True and
            audit.get("data_acceptance_passed") is False,
            "Raw-source audit must not claim final data acceptance")
    raw_audit = report.get("raw_audit")
    require(isinstance(raw_audit, dict) and set(raw_audit) == {
                "path", "sha256", "content_sha256", "audit_implementation_sha256",
                "raw_source_audit_passed",
            } and
            resolve_evidence_path(raw_audit["path"], "Accepted raw audit") == audit_path and
            raw_audit.get("sha256") == sha256(audit_path) and
            raw_audit.get("content_sha256") == audit.get("content_sha256") and
            raw_audit.get("audit_implementation_sha256") ==
            audit.get("audit_implementation_sha256") and
            raw_audit.get("raw_source_audit_passed") is True,
            "Data acceptance is not bound to the exact raw-source audit")
    code_paths = []
    for field in ("producer", "independent_verifier"):
        record = report.get(field)
        require(isinstance(record, dict) and set(record) == {"path", "sha256"},
                f"Data acceptance {field} binding is malformed")
        path = resolve_evidence_path(record["path"], f"Data acceptance {field}")
        require(record["sha256"] == sha256(path),
                f"Data acceptance {field} bytes changed")
        code_paths.append(path)
    require(code_paths[0] != code_paths[1],
            "Data-acceptance producer and verifier must be distinct files")
    require(report["producer"]["sha256"] !=
            report["independent_verifier"]["sha256"],
            "Data-acceptance verifier must not be byte-identical to its producer")

    upstream = report.get("upstream_provenance")
    require(isinstance(upstream, dict) and set(upstream) == {
                "path", "sha256", "content_sha256", "comparison_passed",
            } and upstream.get("comparison_passed") is True,
            "Data acceptance IoT upstream-provenance binding is malformed")
    provenance_path = resolve_evidence_path(
        upstream["path"], "Accepted IoT-23 provenance report"
    )
    provenance, provenance_tool, _provenance_spec = validate_iot_provenance(
        provenance_path, audit
    )
    require(upstream.get("sha256") == sha256(provenance_path) and
            upstream.get("content_sha256") == provenance.get("content_sha256"),
            "Data acceptance differs from the exact IoT provenance report")

    limitations = report.get("limitations")
    require(isinstance(limitations, dict) and
            set(limitations) == DATA_ACCEPTANCE_LIMITATIONS and
            all(value is False for value in limitations.values()),
            "Data-acceptance limitations are missing or overclaimed")
    datasets = report.get("datasets")
    require(isinstance(datasets, dict) and set(datasets) == set(FORMAL_DATASETS),
            "Data acceptance must cover exactly the four formal datasets")
    for dataset in FORMAL_DATASETS:
        accepted = datasets[dataset]
        require(isinstance(accepted, dict) and
                accepted.get("byte_identical_rebuilds") is True,
                f"Malformed or non-identical data acceptance: {dataset}")
        audit_dataset = audit.get("datasets", {}).get(dataset, {})
        require(accepted.get("raw_files") == audit_dataset.get("files"),
                f"Data acceptance raw-file binding differs: {dataset}")
        semantic = accepted.get("semantic_checks")
        require(isinstance(semantic, dict) and
                set(semantic) == DATA_ACCEPTANCE_SEMANTIC_CHECKS and
                all(value is True for value in semantic.values()),
                f"Data acceptance semantic checks are incomplete: {dataset}")
        rebuilds = accepted.get("rebuilds")
        require(isinstance(rebuilds, list) and len(rebuilds) == 2,
                f"Data acceptance requires exactly two rebuilds: {dataset}")
        roots: list[Path] = []
        rebuild_bindings = []
        for rebuild in rebuilds:
            require(isinstance(rebuild, dict) and set(rebuild) == {
                        "resolved_root", "metadata_sha256", "data_fingerprint",
                        "files_sha256",
                    }, f"Malformed rebuild binding: {dataset}")
            root_value = rebuild["resolved_root"]
            require(isinstance(root_value, str) and Path(root_value).is_absolute(),
                    f"Rebuild root is not an absolute canonical path: {dataset}")
            root = Path(root_value).resolve()
            require(str(root) == root_value and root.is_dir() and not root.is_symlink(),
                    f"Rebuild root is missing or noncanonical: {dataset}")
            metadata_path = root / "metadata.json"
            metadata = load_json(metadata_path)
            check_seal(metadata)
            files = cache_files_sha256(root)
            require(rebuild.get("metadata_sha256") == sha256(metadata_path) and
                    rebuild.get("data_fingerprint") == metadata.get("data_fingerprint") and
                    rebuild.get("files_sha256") == files == metadata.get("files_sha256"),
                    f"Rebuild cache bytes/metadata differ: {dataset}")
            roots.append(root)
            rebuild_bindings.append((metadata, files, sha256(metadata_path)))
        require(roots[0] != roots[1] and rebuild_bindings[0] == rebuild_bindings[1],
                f"Rebuild roots are not distinct and byte-identical: {dataset}")
        metadata, files, metadata_sha256 = rebuild_bindings[0]
        require(accepted.get("cache_counts") == metadata.get("counts") and
                accepted.get("features") == metadata.get("features") and
                accepted.get("classes") == metadata.get("class_names") and
                accepted.get("realized_pattern_fractions") ==
                metadata.get("partition", {}).get("retained_pattern_fractions"),
                f"Data acceptance schema/count view differs from cache: {dataset}")
        counts = metadata.get("counts", {})
        partition = metadata.get("partition", {})
        require(audit_dataset.get("rows") == metadata.get("raw_rows") and
                partition.get("retained_rows") == sum(counts.values()) and
                partition.get("retained_rows") + partition.get("excluded_rows") ==
                metadata.get("raw_rows"),
                f"Raw/retained/excluded accounting differs: {dataset}")
        require(metadata.get("exact_model_input_group_leakage_excluded") is True and
                metadata.get("capture_device_time_group_generalization_established") is False and
                metadata.get("upstream_preprocessing_verified") is False,
                f"Cache scope is missing or overclaimed: {dataset}")
        jobs = [job for job in plan.get("jobs", []) if job.get("dataset") == dataset]
        require(jobs and len({job.get("cache") for job in jobs}) == 1 and
                len({job.get("data_fingerprint") for job in jobs}) == 1,
                f"Formal plan cache binding is ambiguous: {dataset}")
        formal_root_input = Path(jobs[0]["cache"])
        require(not formal_root_input.is_symlink(),
                f"Formal cache root is symlinked: {dataset}")
        formal_root = formal_root_input.resolve()
        formal_metadata_path = formal_root / "metadata.json"
        require(sha256(formal_metadata_path) == metadata_sha256 and
                cache_files_sha256(formal_root) == files and
                jobs[0].get("data_fingerprint") == metadata.get("data_fingerprint"),
                f"Formal plan cache differs from accepted rebuilds: {dataset}")
    return (report, code_paths[0], code_paths[1], provenance_path,
            provenance_tool)


def validate_export_matrix(export_root: Path, plan: dict,
                           run_dir: Path | None = None,
                           paper_dir: Path | None = None) -> dict:
    """Recheck the sealed 22-attempt matrix and every referenced evidence/log file."""
    export_plan = load_export_plan(export_root, plan)
    if run_dir is not None:
        require(export_plan["run_dir"] == str(Path(run_dir).resolve()),
                "Export plan belongs to another formal run")
    summary_path = export_root / "summary.json"
    summary = load_json(summary_path)
    check_seal(summary)
    validate_export_summary(export_root, summary, export_plan)
    runner_provenance = summary.get("tool_provenance")
    expected_invocation = None
    if run_dir is not None and paper_dir is not None:
        expected_invocation = {
            "run_dir": str(Path(run_dir).resolve()),
            "output_root": str(export_root.resolve()),
            "paper_dir": str(Path(paper_dir).resolve()),
            "int8_max_disagreement": 0.01,
            "validation_samples": 1024,
            "calibration_samples": 1000,
        }
    validate_tool_provenance(
        runner_provenance, ROOT / "tools/run_v5_exports.py",
        EXPORT_RUNNER_PACKAGES, expected_invocation,
    )
    require(summary.get("source_plan_sha256") == plan["content_sha256"] and
            summary.get("export_plan_sha256") == export_plan["content_sha256"] and
            runner_provenance == export_plan["tool_provenance"],
            "Export matrix belongs to another neural plan")
    require(summary.get("deployment_seed") == 0 and summary.get("fold_bn") is True,
            "Export matrix changed the fixed checkpoint or BN-folding protocol")
    require(summary.get("fp32_atol") == 1e-6 and summary.get("fp32_rtol") == 1e-5 and
            summary.get("fp32_max_prediction_disagreement") == 0.0 and
            summary.get("int8_max_prediction_disagreement") == 0.01 and
            summary.get("validation_samples") == 1024 and
            summary.get("calibration_samples") == 1000,
            "Export matrix changed a predeclared numerical/sample gate")

    attempts = summary.get("attempts")
    require(isinstance(attempts, list) and len(attempts) == 2 * len(JOBS),
            "Export matrix must contain exactly 22 attempts")
    observed: set[tuple[str, str, str]] = set()
    fp32_passed = 0
    qdq_passed = 0
    for row in attempts:
        require(isinstance(row, dict) and type(row.get("passed")) is bool,
                "Malformed export attempt")
        dataset, model, mode = row.get("dataset"), row.get("model"), row.get("mode")
        key = (dataset, model, mode)
        require(row.get("export_plan_sha256") == export_plan["content_sha256"],
                f"Export attempt belongs to another frozen export plan: {key}")
        require((dataset, model) in JOBS and mode in ("fp32", "qdq") and key not in observed,
                f"Unexpected or duplicate export attempt: {key}")
        observed.add(key)
        expected_dir = f"{dataset}/{model}/{mode}"
        expected_evidence = f"{expected_dir}/runner_validation.json"
        expected_log = f"logs/{dataset}_{model}_{mode}.log"
        require(row.get("output_dir") == expected_dir and
                row.get("evidence") == expected_evidence and row.get("log") == expected_log,
                f"Export attempt path contract changed: {key}")
        evidence_path = export_root / expected_evidence
        log_path = export_root / expected_log
        require(evidence_path.is_file() and not evidence_path.is_symlink() and
                log_path.is_file() and not log_path.is_symlink(),
                f"Missing or symlinked export evidence/log: {key}")
        require(row.get("evidence_sha256") == sha256(evidence_path) and
                row.get("log_sha256") == sha256(log_path),
                f"Export evidence/log changed: {key}")
        evidence = load_json(evidence_path)
        check_seal(evidence)
        require(evidence.get("tool_provenance") == runner_provenance,
                f"Export evidence was produced by another runner: {key}")
        declared_output = evidence.get("output_files_sha256")
        output_dir = export_root / expected_dir
        actual_output = {
            path.name: sha256(path)
            for path in sorted(output_dir.iterdir())
            if path.is_file() and not path.is_symlink() and
            path.name != "runner_validation.json"
        }
        require(isinstance(declared_output, dict) and
                declared_output == actual_output and
                all(path.is_file() and not path.is_symlink()
                    for path in output_dir.iterdir()),
                f"Export output inventory is incomplete or changed: {key}")
        require(evidence.get("source_plan_sha256") == plan["content_sha256"] and
                evidence.get("export_plan_sha256") == export_plan["content_sha256"] and
                (evidence.get("dataset"), evidence.get("model"), evidence.get("mode")) == key,
                f"Export runner evidence identity mismatch: {key}")
        require(evidence.get("publication_gate") is row["passed"],
                f"Export pass flag differs from sealed runner evidence: {key}")
        if row["passed"]:
            require(row.get("return_code") == 0 and
                    evidence.get("status") == "independently_validated",
                    f"A passing export lacks independent validation: {key}")
            report_path = export_root / expected_dir / "export_report.json"
            report = load_json(report_path)
            check_seal(report)
            require(evidence.get("export_report_sha256") == sha256(report_path) and
                    report.get("export_plan_sha256") == export_plan["content_sha256"],
                    f"Runner evidence is not bound to the raw export report: {key}")
            expected_payloads = {
                "export_policy.json", "validation_vectors.npz", "preprocessing.json",
                "calibration_rows.json", "model_fp32.onnx",
            }
            if mode == "qdq":
                expected_payloads.add("model_qdq_int8.onnx")
            require(set(report.get("files_sha256", {})) == expected_payloads,
                    f"Raw export report payload set changed: {key}")
            for name, expected_hash in report.get("files_sha256", {}).items():
                payload = report_path.parent / name
                require(payload.is_file() and not payload.is_symlink() and
                        sha256(payload) == expected_hash,
                        f"Export payload changed after independent validation: {key}/{name}")
            fp32_check = evidence.get("fp32_check", {})
            checkpoint_check = evidence.get("checkpoint_check", {})
            require(checkpoint_check.get("allclose") is True and
                    checkpoint_check.get("max_abs_error") == 0.0 and
                    checkpoint_check.get("prediction_disagreement_fraction") == 0.0 and
                    checkpoint_check.get("vectors_checked") == 1024 and
                    fp32_check.get("allclose") is True and
                    fp32_check.get("prediction_disagreement_fraction") == 0.0 and
                    fp32_check.get("vectors_checked") == 1024 and
                    evidence.get("acceptance_basis") ==
                    "independent recomputation; raw export report consistency checked",
                    f"Independent checkpoint/FP32 gate is incomplete: {key}")
            if mode == "qdq":
                qdq_check = evidence.get("qdq_check", {})
                require(qdq_check.get("prediction_disagreement_fraction", 2.0) <= 0.01 and
                        qdq_check.get("vectors_checked") == 1024 and
                        {"QuantizeLinear", "DequantizeLinear"}.issubset(
                            set(evidence.get("qdq_operators", []))) and
                        type(evidence.get("qdq_int8_initializer_count")) is int and
                        evidence["qdq_int8_initializer_count"] > 0,
                        f"Independent QDQ gate is incomplete: {key}")
            else:
                require(evidence.get("qdq_check") is None and
                        evidence.get("qdq_operators") is None and
                        evidence.get("qdq_int8_initializer_count") is None,
                        f"FP32 attempt unexpectedly contains a QDQ gate: {key}")
            if mode == "fp32":
                fp32_passed += 1
            else:
                qdq_passed += 1
        else:
            require(evidence.get("publication_gate") is False,
                    f"Failed export has fail-open evidence: {key}")
            require(evidence.get("status") == "export_subprocess_failed" and
                    evidence.get("failure_classification") == "reproduced_scientific_gate" and
                    evidence.get("failure_replay_error") is None,
                    f"Unclassified/infrastructure failure is not a scientific result: {key}")
            scientific_failure(output_dir, export_plan, dataset, model, mode,
                               row.get("return_code"))
            expected_replay = {
                "kind": "exact_scientific_failure_replay", "passed": True,
                "export_plan_sha256": export_plan["content_sha256"],
                "failure_sha256": sha256(output_dir / "FAILED.json"),
                "output_files_sha256": declared_output,
            }
            require(evidence.get("failure_replay") == expected_replay and
                    evidence.get("return_code") == row["return_code"] and
                    evidence.get("failure_file") == "FAILED.json" and
                    evidence.get("failure_file_sha256") == expected_replay["failure_sha256"],
                    f"Scientific failure replay evidence is stale: {key}")

    require(observed == {(dataset, model, mode) for dataset, model in JOBS
                         for mode in ("fp32", "qdq")},
            "Export attempt matrix is incomplete")
    require(summary.get("fp32_total") == len(JOBS) and
            summary.get("qdq_total") == len(JOBS) and
            summary.get("fp32_passed") == fp32_passed and
            summary.get("qdq_passed") == qdq_passed,
            "Export summary counts are stale or inconsistent")
    require(summary.get("all_gates_passed") is
            (fp32_passed == qdq_passed == len(JOBS)),
            "Export all-gates flag is inconsistent")
    require(fp32_passed == len(JOBS),
            "A deployment bundle requires all 11 independently checked FP32 ONNX gates")
    return summary


def replay_export_matrix(run_dir: Path, export_root: Path, plan: dict,
                         summary: dict) -> None:
    """Replay each independent pass/failure decision before packaging."""
    export_plan = load_export_plan(export_root, plan)
    require(summary.get("export_plan_sha256") == export_plan["content_sha256"],
            "Export replay summary differs from frozen export plan")
    for row in summary["attempts"]:
        dataset, model, mode = row["dataset"], row["model"], row["mode"]
        evidence_path = export_root / row["evidence"]
        evidence = load_json(evidence_path)
        check_seal(evidence)
        kwargs = {
            "run_dir": run_dir,
            "output_dir": export_root / row["output_dir"],
            "plan": plan,
            "dataset": dataset,
            "model": model,
            "mode": mode,
            "validation_samples": 1024,
            "calibration_samples": 1000,
            "int8_max_disagreement": 0.01,
        }
        expected_command = exporter_invocation(
            run_dir,
            export_root / row["output_dir"],
            dataset,
            model,
            mode,
            1024,
            1000,
            0.01,
        )
        require(evidence.get("exporter_invocation") == expected_command,
                f"Exporter invocation differs from the fixed command: {dataset}/{model}/{mode}")
        if row["passed"]:
            require(evidence == seal({
                **validate_attempt(**kwargs),
                "tool_provenance": summary["tool_provenance"],
                "exporter_invocation": expected_command,
                "output_files_sha256": evidence["output_files_sha256"],
            }),
                    f"Live export replay differs from stored evidence: {dataset}/{model}/{mode}")
            continue
        require(evidence.get("status") == "export_subprocess_failed" and
                evidence.get("failure_classification") == "reproduced_scientific_gate",
                f"Unclassified/infrastructure failure is not publishable: {dataset}/{model}/{mode}")
        require(evidence.get("failure_replay") == replay_scientific_failure(
                    run_dir, export_root, export_plan, row),
                f"Scientific failure replay changed: {dataset}/{model}/{mode}")


def validate_staged_semantic_bindings(
        staging: Path, neural_report: dict, tree_report: dict,
        export_summary: dict, selected_models: list[dict],
        data_acceptance: dict) -> None:
    """Revalidate copied artifacts against copied evidence before atomic publish."""
    staged_neural = load_json(
        staging / "payload/evidence/neural/independent_verification.json"
    )
    check_seal(staged_neural)
    require(staged_neural == neural_report,
            "Staged neural independent report differs from validated report")
    for selected in selected_models:
        job_id = f"{selected['dataset']}_{selected['model']}"
        evidence = staged_neural["checkpoints"][job_id]["results"][str(selected["seed"])]
        checkpoint = staging / selected["checkpoint"]
        require(evidence.get("artifact_sha256") == sha256(checkpoint) ==
                selected["checkpoint_sha256"] and
                evidence.get("best_state_sha256") == selected["best_state_sha256"] and
                evidence.get("final_state_sha256") == selected["final_state_sha256"],
                f"Staged neural checkpoint binding differs: {job_id}")

    staged_tree = load_json(
        staging / "payload/evidence/tree/independent_verification.json"
    )
    check_seal(staged_tree)
    require(staged_tree == tree_report,
            "Staged tree independent report differs from validated report")
    for dataset in ("nslkdd", "unsw"):
        for kind in ("random_forest", "xgboost"):
            model = staging / f"payload/tree_models/{dataset}/{kind}/seed_0.joblib"
            evidence = staged_tree["models"][dataset][kind]["0"]["primary"]
            require(evidence.get("artifact_sha256") == sha256(model),
                    f"Staged tree model differs from independent report: {dataset}/{kind}")
    for evidence in staged_tree["rf_onnx"]:
        graph = (staging / "payload/tree_models" / evidence["dataset"] /
                 "random_forest" / Path(evidence["onnx"]).name)
        require(evidence.get("onnx_sha256") == sha256(graph),
                f"Staged RF ONNX differs from independent report: {evidence['dataset']}")

    staged_summary_path = staging / "payload/exports/summary.json"
    staged_summary = load_json(staged_summary_path)
    check_seal(staged_summary)
    require(staged_summary == export_summary and sha256(staged_summary_path) ==
            sha256(staging / "payload/evidence/exports/summary.json"),
            "Staged export summaries differ")
    expected_export_files = {"summary.json", "export_plan.json"}
    for row in staged_summary["attempts"]:
        evidence_relative = row["evidence"]
        log_relative = row["log"]
        evidence_path = staging / "payload/exports" / evidence_relative
        log_path = staging / "payload/exports" / log_relative
        require(sha256(evidence_path) == row["evidence_sha256"] and
                sha256(log_path) == row["log_sha256"],
                "Staged export evidence/log differs from summary")
        expected_export_files.update((evidence_relative, log_relative))
        evidence = load_json(evidence_path)
        check_seal(evidence)
        output_dir = staging / "payload/exports" / row["output_dir"]
        output_files = evidence.get("output_files_sha256")
        require(isinstance(output_files, dict),
                "Staged export evidence omits its complete output inventory")
        for name, expected_sha256 in output_files.items():
            payload = output_dir / name
            require(payload.is_file() and not payload.is_symlink() and
                    sha256(payload) == expected_sha256,
                    f"Staged export payload differs: {row['output_dir']}/{name}")
            expected_export_files.add(
                f"{row['output_dir']}/{name}"
            )
        if row["passed"]:
            report_path = output_dir / "export_report.json"
            require(evidence.get("export_report_sha256") == sha256(report_path),
                    "Staged runner evidence is not bound to export_report.json")
            report = load_json(report_path)
            check_seal(report)
            for name, expected_sha256 in report.get("files_sha256", {}).items():
                require(output_files.get(name) == expected_sha256,
                        f"Staged export report/payload binding differs: {name}")
    actual_export_files = {
        path.relative_to(staging / "payload/exports").as_posix()
        for path in (staging / "payload/exports").rglob("*") if path.is_file()
    }
    require(actual_export_files == expected_export_files,
            "Staged export tree has missing or unbound payloads")

    staged_acceptance = load_json(
        staging / "payload/evidence/data/data_acceptance.json"
    )
    check_seal(staged_acceptance)
    require(staged_acceptance == data_acceptance and
            sha256(staging / "payload/source/data_acceptance/producer.py") ==
            data_acceptance["producer"]["sha256"] and
            sha256(staging / "payload/source/data_acceptance/independent_verifier.py") ==
            data_acceptance["independent_verifier"]["sha256"],
            "Staged data-acceptance report/code binding differs")
    upstream = staged_acceptance["upstream_provenance"]
    staged_iot_report_path = staging / IOT_PROVENANCE_REPORT_BUNDLE
    staged_iot_report = load_json(staged_iot_report_path)
    check_seal(staged_iot_report)
    require(sha256(staged_iot_report_path) == upstream["sha256"] and
            staged_iot_report.get("content_sha256") == upstream["content_sha256"] and
            staged_iot_report.get("comparison_passed") is True and
            sha256(staging / IOT_PROVENANCE_TOOL_BUNDLE) ==
            staged_iot_report["tool"]["sha256"] and
            sha256(staging / "payload/evidence/data/source_specs/iot23.json") ==
            staged_iot_report["source_spec"]["sha256"],
            "Staged IoT provenance report/tool/spec binding differs")


def validate_audit_against_caches(audit: dict, plan: dict) -> None:
    """Bind audited raw file identities and schema to every formal prepared cache."""
    require(set(audit.get("datasets", {})) == {dataset for dataset, _ in JOBS},
            "Data audit does not cover exactly the four formal datasets")
    for dataset in sorted(audit["datasets"]):
        audited = audit["datasets"][dataset]
        expected_spec_relative = f"audit/source_specs/{dataset}.json"
        require(audited.get("source_spec") == expected_spec_relative,
                f"Audit source-spec path mismatch: {dataset}")
        source_spec_path = PACKAGE / expected_spec_relative
        require(source_spec_path.is_file() and not source_spec_path.is_symlink() and
                audited.get("source_spec_sha256") == sha256(source_spec_path),
                f"Audit source-spec file changed: {dataset}")
        source_spec = load_json(source_spec_path)
        jobs = [job for job in plan["jobs"] if job["dataset"] == dataset]
        require(jobs, f"Formal plan omits audited dataset: {dataset}")
        require(len({job["cache"] for job in jobs}) == 1,
                f"Formal arms use different cache paths: {dataset}")
        for job in jobs:
            metadata = load_json(Path(job["cache"]) / "metadata.json")
            check_seal(metadata)
            require(metadata.get("data_fingerprint") == job.get("data_fingerprint"),
                    f"Formal plan/cache fingerprint mismatch: {dataset}")
            require(audited.get("features") == metadata.get("features") and
                    audited.get("classes") == metadata.get("class_names"),
                    f"Audit/cache feature or class order mismatch: {dataset}")
            require(source_spec == metadata["raw_binding"].get("source_spec"),
                    f"Audit/cache source specification mismatch: {dataset}")
            audited_files = {(row["path"], row["role"], row["sha256"])
                             for row in audited.get("files", [])}
            cache_files = {(row["path"], row["role"], row["sha256"])
                           for row in metadata["raw_binding"].get("files", [])}
            require(audited_files == cache_files,
                    f"Audit/cache raw file binding mismatch: {dataset}")
            partition = metadata.get("partition", {})
            require(audited.get("rows") == metadata.get("raw_rows") and
                    partition.get("retained_rows") == sum(metadata["counts"].values()) and
                    partition.get("retained_rows") + partition.get("excluded_rows") ==
                    metadata.get("raw_rows"),
                    f"Audit/cache raw/retained/excluded accounting mismatch: {dataset}")


def display_path(path: Path) -> str:
    path = path.resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def model_card(plan: dict, results: dict, tree_report: dict, export_summary: dict) -> str:
    lines = [
        "# SpikeIDS v5 verified model bundle",
        "",
        f"- Frozen plan SHA-256: `{plan['content_sha256']}`",
        f"- Deployment checkpoint seed: `{plan['deployment_seed']}`",
        f"- Neural repetitions: `{len(plan['seeds'])}` primary plus `{len(plan['seeds'])}` replica fits per arm",
        f"- FP32 ONNX gates passed: `{export_summary['fp32_passed']}/{export_summary['fp32_total']}`",
        f"- QDQ gates passed: `{export_summary['qdq_passed']}/{export_summary['qdq_total']}`",
        "",
        "## Primary neural test metrics",
        "",
        "| Dataset | Model | Overall accuracy (%) | Macro F1 (%) |",
        "|---|---|---:|---:|",
    ]
    for job in plan["jobs"]:
        row = results[(job["dataset"], job["model"])]["aggregate"]
        oa, mf = row["overall_acc"], row["macro_f1"]
        lines.append(
            f"| {job['dataset']} | {job['model']} | "
            f"{oa['mean']:.4f} +/- {oa['std']:.4f} | {mf['mean']:.4f} +/- {mf['std']:.4f} |"
        )
    lines.extend((
        "",
        "## Tree references",
        "",
        "| Dataset | Model | Fits | Overall accuracy (%) | Macro F1 (%) |",
        "|---|---|---:|---:|---:|",
    ))
    for dataset in ("nslkdd", "unsw"):
        for kind in ("random_forest", "xgboost"):
            block = tree_report["results"][dataset][kind]
            oa, mf = block["aggregate"]["overall_acc"], block["aggregate"]["macro_f1"]
            oa_text = f"{oa['mean']:.4f}" if oa["std"] is None else f"{oa['mean']:.4f} +/- {oa['std']:.4f}"
            mf_text = f"{mf['mean']:.4f}" if mf["std"] is None else f"{mf['mean']:.4f} +/- {mf['std']:.4f}"
            lines.append(f"| {dataset} | {kind} | {oa['n_total']} | {oa_text} | {mf_text} |")
    lines.extend((
        "",
        "## Contents and use",
        "",
        "`payload/checkpoints/` contains the selected primary seed-0 neural checkpoints. "
        "`payload/preprocessing/` binds feature order, class order, fit-only encoders, and scaling. "
        "`payload/exports/` preserves every FP32/QDQ pass or failure artifact. "
        "`payload/tree_models/` contains the selected seed-0 tree reference artifacts. "
        "`payload/evidence/` contains plans, verification barriers, statistical reports, paper "
        "provenance, and data-audit evidence. The complete all-seed primary/replica checkpoints "
        "and prediction arrays remain in the plan-bound formal run directories named in the manifest.",
        "`RETENTION_MANIFEST.json` verifies the complete external 440-checkpoint/440-prediction, "
        "84-tree-model, and 22-export evidence inventories. Those external run directories are "
        "required retained evidence, not disposable intermediates. The manuscript PDF is selected "
        "from the verified isolated double build in `payload/evidence/paper_build/`; a live paper PDF "
        "is not used as publication evidence. Resource JSON reports and their raw JSONL traces are "
        "preserved together under `payload/evidence/neural/`.",
        "",
        "Verify every payload file against `BUNDLE_MANIFEST.json` before use. Never load an "
        "untrusted checkpoint; these checkpoints are intended to be consumed only by the pinned "
        "SpikeIDS-v5 code and recorded environment.",
        "",
        "## Scope limits",
        "",
        "This bundle demonstrates deterministic repetition on the recorded stack and sampled ONNX "
        "Runtime parity where a gate passed. It does not prove cross-platform bitwise determinism, "
        "unseen-device/capture/time generalization, all-integer execution, vendor-NPU placement, "
        "physical-board parity, latency, or energy. A QDQ failure remains a failure in the payload.",
        "",
    ))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--tree-run-dir", required=True, type=Path)
    parser.add_argument("--export-root", required=True, type=Path)
    parser.add_argument("--data-audit", required=True, type=Path)
    parser.add_argument("--data-acceptance", required=True, type=Path)
    parser.add_argument("--paper-dir", required=True, type=Path)
    parser.add_argument("--paper-build", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    args = parser.parse_args()
    for path, label in (
        (args.run_dir, "formal run"),
        (args.tree_run_dir, "tree run"),
        (args.export_root, "export root"),
        (args.data_audit, "data audit"),
        (args.data_acceptance, "data acceptance"),
        (args.paper_dir, "paper directory"),
        (args.paper_build, "paper build"),
        (args.artifact_root, "artifact root"),
    ):
        require(not path.is_symlink(), f"Package {label} path must not be a symlink")
    package_provenance = tool_provenance(
        Path(__file__), [sys.executable, *sys.argv], PACKAGE_TOOL_PACKAGES
    )
    lifecycle_source_sha256 = {
        name: sha256(ROOT / "tools" / name) for name in LIFECYCLE_TOOLS
    }
    require(
        lifecycle_source_sha256["package_v5_artifacts.py"] ==
        package_provenance["tool"]["source_sha256"],
        "Packager source changed while its provenance was captured",
    )

    run_dir = args.run_dir.resolve()
    tree_run_dir = args.tree_run_dir.resolve()
    export_root = args.export_root.resolve()
    paper_dir = args.paper_dir.resolve()
    paper_build = args.paper_build.resolve()
    data_acceptance_path = args.data_acceptance.resolve()
    source_snapshots: dict[Path, dict] = {}

    def freeze_source(path: Path) -> None:
        candidate = Path(path)
        require(not candidate.is_symlink(),
                f"Snapshot source path must not be a symlink: {candidate}")
        resolved = candidate.resolve()
        snapshot = snapshot_regular_file(resolved)
        previous = source_snapshots.setdefault(resolved, snapshot)
        require(previous == snapshot, f"Source changed while freezing inputs: {resolved}")

    preliminary_plan = load_json(run_dir / "plan.json")
    check_seal(preliminary_plan)
    preliminary_acceptance = load_json(data_acceptance_path)
    check_seal(preliminary_acceptance)
    preliminary_acceptance_code = []
    for field in ("producer", "independent_verifier"):
        record = preliminary_acceptance.get(field)
        require(isinstance(record, dict) and isinstance(record.get("path"), str),
                f"Data acceptance {field} binding is missing")
        preliminary_acceptance_code.append(
            resolve_evidence_path(record["path"], f"Data acceptance {field}")
        )
    preliminary_upstream = preliminary_acceptance.get("upstream_provenance")
    require(isinstance(preliminary_upstream, dict) and
            isinstance(preliminary_upstream.get("path"), str),
            "Data acceptance upstream provenance binding is missing")
    preliminary_iot_provenance = resolve_evidence_path(
        preliminary_upstream["path"], "Accepted IoT-23 provenance report"
    )
    frozen_sources = [
        run_dir / name for name in (
            "plan.json", "environment.json", "verification_fit.json",
            "verification_evaluate.json", "independent_verification.json",
            "stats_report_globecom.json", "equivalence_v5.json",
            "equivalence_v5.md", "paper_numeric_check.json",
            "export_registration.json", "export_prior_exposure.json",
        )
    ]
    from resource_evidence import validate_resource_reports
    resource_files = validate_resource_reports(run_dir, preliminary_plan)
    frozen_sources.extend(resource_files)
    for job in preliminary_plan["jobs"]:
        stem = run_dir / "results" / job["id"]
        frozen_sources.extend((
            stem.with_suffix(".json"), stem / "manifest.json",
            stem / "runs" / f"{job['model']}_seed_{preliminary_plan['deployment_seed']}.pt",
        ))
    frozen_sources.extend(
        tree_run_dir / name for name in (
            "plan.json", "verification_fit.json", "results.json",
            "independent_verification.json", "test_exposure.json",
        )
    )
    tree_execution_records = sorted(path for execution in ("primary", "replica")
                                    for path in (tree_run_dir / execution).rglob("*.json"))
    frozen_sources.extend(tree_execution_records)
    for dataset in ("nslkdd", "unsw"):
        for kind in ("random_forest", "xgboost"):
            frozen_sources.append(
                tree_run_dir / "primary" / dataset / kind / "seed_0.joblib"
            )
        frozen_sources.append(tree_run_dir / "onnx" / f"rf_{dataset}_seed_0.onnx")
    frozen_sources.extend(
        path for path in sorted(export_root.rglob("*")) if path.is_file()
    )
    frozen_sources.extend(
        paper_dir / name for name in (
            "main.tex", "references.bib", "result_macros_v5.tex",
            "result_macros_v5.provenance.json", "export_macros_v5.tex",
            "export_macros_v5.provenance.json",
        )
    )
    paper_build_files = sorted(path for path in paper_build.rglob("*") if path.is_file())
    frozen_sources.extend(paper_build_files)
    frozen_sources.extend((
        args.data_audit.resolve(),
        data_acceptance_path,
        *preliminary_acceptance_code,
        preliminary_iot_provenance,
        IOT_PROVENANCE_TOOL,
        PACKAGE / "audit" / "PROVENANCE_REVIEW_20260921.md",
        ROOT / "requirements.txt", PACKAGE / "README.md", PACKAGE / "NOTICE.md",
        PACKAGE / "EXPORT_PROTOCOL.md",
    ))
    for dataset in ("nslkdd", "unsw", "cicids2017", "iot23"):
        frozen_sources.append(PACKAGE / "audit" / "source_specs" / f"{dataset}.json")
        cache = Path(next(
            job["cache"] for job in preliminary_plan["jobs"]
            if job["dataset"] == dataset
        ))
        frozen_sources.extend((cache / "metadata.json", cache / "preprocessing.json"))
    for relative in preliminary_plan.get("sources", {}):
        frozen_sources.append(PACKAGE / relative)
    frozen_sources.extend(ROOT / "tools" / name for name in (*LIFECYCLE_TOOLS, *AUXILIARY_TOOLS))
    from tools.v5_retention import build_retention, validate_retention
    retention_roots = {"neural": run_dir, "tree": tree_run_dir, "exports": export_root}
    retention = build_retention(run_dir, tree_run_dir, export_root, {
        "neural": preliminary_plan["content_sha256"],
        "tree": load_json(tree_run_dir / "plan.json")["content_sha256"],
        "exports": load_json(export_root / "export_plan.json")["content_sha256"],
    })
    frozen_sources.extend(validate_retention(retention, retention_roots))
    for source in frozen_sources:
        freeze_source(source)
    from tools.verify_v5_paper_build import validate_paper_build
    paper_plan_paths = {"neural": run_dir / "plan.json", "tree": tree_run_dir / "plan.json",
                        "export": export_root / "export_plan.json"}
    validate_paper_build(paper_build, paper_dir, paper_plan_paths, replay=True)

    plan, results = verified_suite(run_dir)
    require(plan.get("protocol_role") == "planned_benchmark" and
            plan.get("seeds") == list(range(20)) and
            plan.get("deployment_seed") == 0,
            "Only the fixed full 20-seed benchmark may be packaged")
    environment = load_json(run_dir / "environment.json")
    require(environment == plan.get("environment"),
            "Standalone environment record differs from the frozen neural plan")
    neural_independent_path = run_dir / "independent_verification.json"
    neural_independent_sha256 = source_snapshots[
        neural_independent_path.resolve()
    ]["sha256"]
    neural_independent = load_json(neural_independent_path)
    check_seal(neural_independent)
    validate_tool_provenance(
        neural_independent.get("tool_provenance"),
        ROOT / "tools/verify_v5_neural.py",
        NEURAL_VERIFIER_PACKAGES,
        {
            "run_dir": str(run_dir),
            "output": str(neural_independent_path.resolve()),
        },
    )
    require(neural_independent.get("passed") is True and
            neural_independent.get("kind") ==
            "independent_formal_neural_and_statistics_verification" and
            neural_independent.get("plan_sha256") == plan["content_sha256"] and
            neural_independent.get("verification_fit_sha256") ==
            sha256(run_dir / "verification_fit.json") and
            neural_independent.get("verification_evaluate_sha256") ==
            sha256(run_dir / "verification_evaluate.json") and
            neural_independent.get("prediction_artifacts_checked") == 440 and
            neural_independent.get("checkpoints_checked") == 440,
            "Independent neural/statistics recomputation is missing, failed, or stale")
    require(neural_independent == seal({
        **verify_neural_independent(run_dir),
        "tool_provenance": neural_independent["tool_provenance"],
    }),
            "Stored independent neural/statistics report differs from a live recomputation")
    require(sha256(neural_independent_path) == neural_independent_sha256,
            "Independent neural report changed during package validation")
    tree_plan, tree_report = load_verified_tree_suite(tree_run_dir)
    require(tree_plan.get("neural_plan") == {
                "path": str(run_dir / "plan.json"), "sha256": sha256(run_dir / "plan.json"),
                "content_sha256": plan["content_sha256"]} and
            tree_plan.get("data_acceptance") == {
                "path": str(data_acceptance_path), "sha256": sha256(data_acceptance_path),
                "content_sha256": preliminary_acceptance["content_sha256"]},
            "Tree evidence is bound to another neural plan/data acceptance")
    require(tree_plan.get("random_forest_seeds") == list(range(20)) and
            tree_plan.get("xgboost_seeds") == [0] and
            tree_plan.get("deployment_seed") == 0 and
            tree_plan.get("threads") == 16 and
            tree_plan.get("hyperparameters", {}).get("random_forest", {}).get("n_estimators") == 100 and
            tree_plan.get("hyperparameters", {}).get("xgboost", {}).get("n_estimators") == 100,
            "Tree evidence differs from the fixed formal baseline plan")
    tree_independent_path = tree_run_dir / "independent_verification.json"
    tree_independent_sha256 = source_snapshots[
        tree_independent_path.resolve()
    ]["sha256"]
    tree_independent = load_json(tree_independent_path)
    check_seal(tree_independent)
    validate_tool_provenance(
        tree_independent.get("tool_provenance"),
        ROOT / "tools/verify_v5_tree.py",
        TREE_VERIFIER_PACKAGES,
        {
            "tree_run_dir": str(tree_run_dir),
            "neural_run_dir": str(run_dir),
            "output": str(tree_independent_path.resolve()),
        },
    )
    require(tree_independent.get("passed") is True and
            tree_independent.get("tree_plan_sha256") == tree_plan["content_sha256"] and
            tree_independent.get("tree_results_sha256") == sha256(tree_run_dir / "results.json") and
            tree_independent.get("tree_fit_verification_sha256") ==
            sha256(tree_run_dir / "verification_fit.json"),
            "Independent tree recomputation is missing, failed, or stale")
    require(tree_independent == seal({
        **verify_tree_independent(tree_run_dir, run_dir),
        "tool_provenance": tree_independent["tool_provenance"],
    }),
            "Stored independent tree report differs from a live recomputation")
    require(sha256(tree_independent_path) == tree_independent_sha256,
            "Independent tree report changed during package validation")
    export_source_snapshots = {
        path.relative_to(export_root).as_posix(): source_snapshots[path.resolve()]
        for path in sorted(export_root.rglob("*")) if path.is_file()
    }
    export_summary = validate_export_matrix(
        export_root, plan, run_dir=run_dir, paper_dir=paper_dir
    )
    replay_export_matrix(run_dir, export_root, plan, export_summary)
    current_export_files = {
        path.relative_to(export_root).as_posix(): path
        for path in sorted(export_root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
    require(set(current_export_files) == set(export_source_snapshots) and
            all(snapshot_regular_file(current_export_files[relative]) == expected
                for relative, expected in export_source_snapshots.items()),
            "Export tree changed during package validation")
    export_macro = paper_dir / "export_macros_v5.tex"
    require(export_macro.is_file() and export_macro.read_text(encoding="utf-8") ==
            export_macro_text(expected_export_macros(export_root, export_summary)),
            "Export paper macros are missing, hand-edited, or stale")
    export_macro_provenance_path = paper_dir / "export_macros_v5.provenance.json"
    export_macro_provenance_sha256 = source_snapshots[
        export_macro_provenance_path.resolve()
    ]["sha256"]
    export_macro_provenance = load_json(export_macro_provenance_path)
    check_seal(export_macro_provenance)
    require(export_macro_provenance.get("kind") == "spikeids_v5_export_paper_macros" and
            export_macro_provenance.get("plan_sha256") == plan["content_sha256"] and
            export_macro_provenance.get("export_summary_sha256") ==
            sha256(export_root / "summary.json") and
            export_macro_provenance.get("macro_sha256") == sha256(export_macro) and
            export_macro_provenance.get("tool_provenance") ==
            export_summary["tool_provenance"],
            "Export paper macro provenance is invalid or stale")
    require(sha256(export_macro_provenance_path) == export_macro_provenance_sha256,
            "Export macro provenance changed during package validation")
    audit = load_json(args.data_audit.resolve())
    check_seal(audit)
    require(audit.get("raw_source_audit_passed") is True and
            audit.get("data_acceptance_passed") is False,
            "Raw-source audit is missing or improperly claims final acceptance")
    validate_audit_against_caches(audit, plan)
    (data_acceptance, acceptance_producer, acceptance_verifier,
     iot_provenance_path, iot_provenance_tool) = (
        validate_data_acceptance(
            data_acceptance_path, args.data_audit.resolve(), audit, plan
        )
    )
    require(data_acceptance == preliminary_acceptance and
            sha256(data_acceptance_path) ==
            source_snapshots[data_acceptance_path]["sha256"] and
            acceptance_producer == preliminary_acceptance_code[0] and
            acceptance_verifier == preliminary_acceptance_code[1] and
            iot_provenance_path == preliminary_iot_provenance and
            iot_provenance_tool == IOT_PROVENANCE_TOOL.resolve(),
            "Data-acceptance evidence changed during package validation")
    paper_check = load_json(run_dir / "paper_numeric_check.json")
    check_seal(paper_check)
    require(paper_check.get("numeric_consistency_passed") is True and
            paper_check.get("strict_heuristic_scan_passed") is True,
            "Strict paper numeric/prose scan has not passed")
    current_paper_check = check_paper_consistency(
        run_dir, tree_run_dir, paper_dir, strict=True, export_root=export_root
    )
    require(paper_check == seal(current_paper_check),
            "Stored paper check differs from a live strict consistency check")
    paper_pdf = paper_build / "main.pdf"
    require(paper_pdf.is_file() and paper_pdf.stat().st_size > 0,
            "The checked manuscript PDF is missing or empty")
    # The clean-build verifier binds exact inputs and independently reproduced
    # PDF/auxiliary bytes; filesystem mtimes are not evidence of compilation.
    macro_provenance = load_json(paper_dir / "result_macros_v5.provenance.json")
    check_seal(macro_provenance)
    require(macro_provenance.get("plan_sha256") == plan["content_sha256"] and
            macro_provenance.get("tree_plan_sha256") == tree_plan["content_sha256"] and
            macro_provenance.get("macro_sha256") ==
            sha256(paper_dir / "result_macros_v5.tex") and
            macro_provenance.get("tree_result_sha256") == sha256(tree_run_dir / "results.json"),
            "Paper macro provenance is stale or refers to another formal run")

    artifact_root = args.artifact_root.resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    target = artifact_root / plan["content_sha256"]
    require(not target.exists(), f"Artifact bundle already exists: {target}")
    staging = Path(tempfile.mkdtemp(prefix=f".{plan['content_sha256']}.tmp-", dir=artifact_root))
    sources: dict[str, str] = {}

    def copy(source: Path, relative: str) -> Path:
        source = Path(source)
        require(not source.is_symlink(), f"Bundle source path is symlinked: {source}")
        source = source.resolve()
        destination = staging / relative
        require(source in source_snapshots,
                f"Bundle source was not frozen before validation: {source}")
        copy_snapshot(source, destination, source_snapshots[source])
        sources[relative] = display_path(source)
        return destination

    try:
        evidence = {
            "neural/plan.json": run_dir / "plan.json",
            "neural/environment.json": run_dir / "environment.json",
            "neural/verification_fit.json": run_dir / "verification_fit.json",
            "neural/verification_evaluate.json": run_dir / "verification_evaluate.json",
            "neural/independent_verification.json": neural_independent_path,
            "neural/stats_report_globecom.json": run_dir / "stats_report_globecom.json",
            "neural/equivalence_v5.json": run_dir / "equivalence_v5.json",
            "neural/equivalence_v5.md": run_dir / "equivalence_v5.md",
            "neural/paper_numeric_check.json": run_dir / "paper_numeric_check.json",
            "neural/export_registration.json": run_dir / "export_registration.json",
            "neural/export_prior_exposure.json": run_dir / "export_prior_exposure.json",
            "tree/plan.json": tree_run_dir / "plan.json",
            "tree/verification_fit.json": tree_run_dir / "verification_fit.json",
            "tree/results.json": tree_run_dir / "results.json",
            "tree/independent_verification.json": tree_independent_path,
            "tree/test_exposure.json": tree_run_dir / "test_exposure.json",
            "exports/summary.json": export_root / "summary.json",
            "data/data_audit.json": args.data_audit,
            "data/data_acceptance.json": data_acceptance_path,
            "data/iot23_provenance.json": iot_provenance_path,
            "data/PROVENANCE_REVIEW_20260921.md":
                PACKAGE / "audit" / "PROVENANCE_REVIEW_20260921.md",
            "paper/result_macros_v5.tex": paper_dir / "result_macros_v5.tex",
            "paper/result_macros_v5.provenance.json": paper_dir / "result_macros_v5.provenance.json",
            "paper/export_macros_v5.tex": export_macro,
            "paper/export_macros_v5.provenance.json": export_macro_provenance_path,
            "paper/main.tex": paper_dir / "main.tex",
            "paper/references.bib": paper_dir / "references.bib",
            "paper/main.pdf": paper_build / "main.pdf",
        }
        for resource in resource_files:
            evidence[f"neural/{resource.name}"] = resource
        for source in tree_execution_records:
            evidence[f"tree/{source.relative_to(tree_run_dir).as_posix()}"] = source
        for source in paper_build_files:
            evidence[f"paper_build/{source.relative_to(paper_build).as_posix()}"] = source
        for dataset in ("nslkdd", "unsw", "cicids2017", "iot23"):
            evidence[f"data/source_specs/{dataset}.json"] = (
                PACKAGE / "audit" / "source_specs" / f"{dataset}.json"
            )
        for relative, source in evidence.items():
            copy(source, f"payload/evidence/{relative}")

        copy(
            acceptance_producer,
            "payload/source/data_acceptance/producer.py",
        )
        copy(
            acceptance_verifier,
            "payload/source/data_acceptance/independent_verifier.py",
        )
        copy(iot_provenance_tool, IOT_PROVENANCE_TOOL_BUNDLE)

        require(isinstance(plan.get("sources"), dict) and plan["sources"],
                "Formal plan has no frozen source inventory")
        for relative, expected_hash in sorted(plan["sources"].items()):
            source = PACKAGE / relative
            require(source.is_file() and not source.is_symlink() and
                    sha256(source) == expected_hash,
                    f"Frozen training source is missing or changed: {relative}")
            copy(source, f"payload/source/spikeids_v5/{relative}")
        for source, relative in (
            (ROOT / "requirements.txt", "requirements.txt"),
            (PACKAGE / "README.md", "spikeids_v5/README.md"),
            (PACKAGE / "NOTICE.md", "spikeids_v5/NOTICE.md"),
            (PACKAGE / "EXPORT_PROTOCOL.md", "spikeids_v5/EXPORT_PROTOCOL.md"),
        ):
            copy(source, f"payload/source/{relative}")
        lifecycle_tool_sha256 = {}
        for name in LIFECYCLE_TOOLS:
            destination = copy(
                ROOT / "tools" / name, f"payload/source/tools/{name}"
            )
            copied_sha256 = sha256(destination)
            require(copied_sha256 == lifecycle_source_sha256[name],
                    f"Lifecycle tool changed during packaging: {name}")
            lifecycle_tool_sha256[f"payload/source/tools/{name}"] = copied_sha256
        auxiliary_tool_sha256 = {}
        for name in AUXILIARY_TOOLS:
            destination = copy(ROOT / "tools" / name, f"payload/source/tools/{name}")
            auxiliary_tool_sha256[f"payload/source/tools/{name}"] = sha256(destination)

        for dataset in ("nslkdd", "unsw", "cicids2017", "iot23"):
            cache = Path(next(job["cache"] for job in plan["jobs"] if job["dataset"] == dataset))
            copy(cache / "metadata.json", f"payload/preprocessing/{dataset}/metadata.json")
            copy(cache / "preprocessing.json", f"payload/preprocessing/{dataset}/preprocessing.json")

        selected_models = []
        seed = plan["deployment_seed"]
        for job in plan["jobs"]:
            stem = run_dir / "results" / job["id"]
            checkpoint = stem / "runs" / f"{job['model']}_seed_{seed}.pt"
            checkpoint_evidence = (
                neural_independent["checkpoints"][job["id"]]["results"][str(seed)]
            )
            expected_checkpoint_path = checkpoint.relative_to(run_dir).as_posix()
            require(checkpoint_evidence.get("path") == expected_checkpoint_path and
                    checkpoint_evidence.get("artifact_sha256") == sha256(checkpoint),
                    f"Independent verifier checkpoint binding differs: {job['id']}")
            destination = copy(checkpoint,
                               f"payload/checkpoints/{job['dataset']}/{job['model']}/seed_{seed}.pt")
            copy(stem.with_suffix(".json"),
                 f"payload/evidence/neural/results/{job['id']}.json")
            copy(stem / "manifest.json",
                 f"payload/evidence/neural/results/{job['id']}_manifest.json")
            fit_result = results[(job["dataset"], job["model"])]
            selected_fit = next(row for row in fit_result["fit_runs"] if row["seed"] == seed)
            require(checkpoint_evidence.get("best_state_sha256") ==
                    selected_fit["best_state_sha256"] and
                    checkpoint_evidence.get("final_state_sha256") ==
                    selected_fit["final_state_sha256"],
                    f"Checkpoint semantic digests differ: {job['id']}")
            selected_models.append({
                "dataset": job["dataset"],
                "model": job["model"],
                "seed": seed,
                "checkpoint": destination.relative_to(staging).as_posix(),
                "checkpoint_sha256": sha256(destination),
                "best_state_sha256": selected_fit["best_state_sha256"],
                "final_state_sha256": selected_fit["final_state_sha256"],
                "best_epoch": selected_fit["best_epoch"],
                "data_fingerprint": job["data_fingerprint"],
            })

        for dataset in ("nslkdd", "unsw"):
            for kind in ("random_forest", "xgboost"):
                source = tree_run_dir / "primary" / dataset / kind / "seed_0.joblib"
                copy(source, f"payload/tree_models/{dataset}/{kind}/seed_0.joblib")
        for record in tree_report["rf_onnx"]:
            source = tree_run_dir / record["onnx"]
            copy(source, f"payload/tree_models/{record['dataset']}/random_forest/{source.name}")

        for source in sorted(export_root.rglob("*")):
            if source.is_file():
                copy(source, f"payload/exports/{source.relative_to(export_root).as_posix()}")

        validate_staged_semantic_bindings(
            staging, neural_independent, tree_independent,
            export_summary, selected_models, data_acceptance,
        )
        require({path.name for path in validate_resource_reports(
                    staging / "payload/evidence/neural", plan)} ==
                {path.name for path in resource_files},
                "Staged resource report/trace set changed")
        (final_data_acceptance, final_producer, final_verifier,
         final_iot_provenance, final_iot_tool) = (
            validate_data_acceptance(
                data_acceptance_path, args.data_audit.resolve(), audit, plan
            )
        )
        require(final_data_acceptance == data_acceptance and
                final_producer == acceptance_producer and
                final_verifier == acceptance_verifier and
                final_iot_provenance == iot_provenance_path and
                final_iot_tool == iot_provenance_tool,
                "Data-acceptance evidence changed before atomic publication")
        validate_retention(retention, retention_roots)
        validate_paper_build(staging / "payload/evidence/paper_build", paper_dir,
                             paper_plan_paths, replay=False)
        write_json(staging / "RETENTION_MANIFEST.json", retention)
        sources["RETENTION_MANIFEST.json"] = "generated full scientific artifact inventory"
        for source, expected in source_snapshots.items():
            require(snapshot_regular_file(source) == expected,
                    f"Frozen release input changed before publication: {source}")

        card = model_card(plan, results, tree_report, export_summary)
        write_text(staging / "MODEL_CARD.md", card)
        sources["MODEL_CARD.md"] = "generated from verified bundle inputs"
        files = []
        for path in sorted(staging.rglob("*")):
            if path.is_file() and path.name != "BUNDLE_MANIFEST.json":
                relative = path.relative_to(staging).as_posix()
                files.append({
                    "path": relative,
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                    "source": sources[relative],
                })
        manifest = {
            "schema": 1,
            "kind": "spikeids_v5_plan_addressed_model_bundle",
            "plan_sha256": plan["content_sha256"],
            "tree_plan_sha256": tree_plan["content_sha256"],
            "export_plan_sha256": export_summary["export_plan_sha256"],
            "formal_run": display_path(run_dir),
            "formal_tree_run": display_path(tree_run_dir),
            "export_run": display_path(export_root),
            "data_audit": display_path(args.data_audit.resolve()),
            "data_acceptance": display_path(data_acceptance_path),
            "paper_dir": display_path(paper_dir),
            "paper_build": display_path(paper_build),
            "artifact_root": display_path(artifact_root),
            "deployment_seed": seed,
            "selected_models": selected_models,
            "creator_provenance": package_provenance,
            "lifecycle_tools_sha256": lifecycle_tool_sha256,
            "auxiliary_tools_sha256": auxiliary_tool_sha256,
            "bundle_replay": ARCHIVE_REPLAY_BLOCKER,
            "files": files,
            "full_all_seed_evidence_in_formal_runs": True,
            "large_payload_intended_for_git": False,
        }
        write_json(staging / "BUNDLE_MANIFEST.json", seal(manifest))
        os.replace(staging, target)
        print(f"Created {target}")
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == "__main__":
    main()
