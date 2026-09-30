#!/usr/bin/env python3
"""Quarantine pre-v5 workflows/results and separate historical hardware evidence.

Dry-run is the default. Execution is gated on a completed formal neural run and
an already-created plan-addressed v5 artifact bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORMAL_JOBS = (
    ("nslkdd", "relu"), ("nslkdd", "qcfs"), ("nslkdd", "cnn"),
    ("unsw", "relu"), ("unsw", "qcfs"), ("unsw", "cnn"),
    ("cicids2017", "relu"), ("cicids2017", "qcfs"),
    ("cicids2017", "cnn"), ("iot23", "relu"), ("iot23", "qcfs"),
)
LIFECYCLE_TOOL_PACKAGES = {
    "verify_v5_neural.py": {"numpy", "scikit-learn", "scipy", "statsmodels"},
    "verify_v5_tree.py": {"joblib", "numpy", "onnxruntime", "scikit-learn", "xgboost"},
    "run_v5_exports.py": {"numpy", "onnx", "onnxruntime", "torch"},
    "package_v5_artifacts.py": {
        "joblib", "numpy", "onnx", "onnxruntime", "scikit-learn", "scipy",
        "statsmodels", "torch", "xgboost",
    },
    "archive_pre_v5.py": set(),
}
# Trust anchor for the four non-self lifecycle tools. The archive tool is
# anchored by byte equality with the executing file below, avoiding a
# self-referential digest. Any lifecycle-tool edit intentionally requires a
# reviewed update to this release allowlist and new formal reports/bundle.
TRUSTED_LIFECYCLE_TOOL_SHA256 = {
    "verify_v5_neural.py":
        "07adcf5bf6b87bcb6019fa782ce957a411f093fcf3d5c0bf67c0e3159dbc0dc6",
    "verify_v5_tree.py":
        "6faeedbb009720af286c766d31fdfc76969ef5892c7a476ea98b948b1c92ff53",
    "run_v5_exports.py":
        "da67941a11895e9eadb202b2da8785c84dbedde61b04bd97dccc9ad44d196b16",
    "package_v5_artifacts.py":
        "c1f33c753ca548ad489df6190f4995209aa4b9308f1f8bf4f7b24d14a1f82dda",
}
LIFECYCLE_TOOL_PATHS = frozenset(
    f"payload/source/tools/{name}" for name in LIFECYCLE_TOOL_PACKAGES
)
AUXILIARY_TOOLS = ("build_v5_paper.py", "verify_v5_paper_build.py", "v5_retention.py")
AUXILIARY_TOOL_PATHS = frozenset(f"payload/source/tools/{name}" for name in AUXILIARY_TOOLS)
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
IOT_PROVENANCE_REPORT_BUNDLE = "payload/evidence/data/iot23_provenance.json"
IOT_PROVENANCE_SPEC_BUNDLE = (
    "payload/evidence/data/source_specs/iot23.json"
)
IOT_PROVENANCE_TOOL_BUNDLE = (
    "payload/source/data_acceptance/iot23_provenance_verifier.py"
)
REQUIRED_BUNDLE_PATHS = frozenset({
    "MODEL_CARD.md",
    "RETENTION_MANIFEST.json",
    "payload/evidence/paper_build/paper_build.json",
    "payload/evidence/paper_build/main.pdf",
    "payload/evidence/neural/plan.json",
    "payload/evidence/neural/environment.json",
    "payload/evidence/neural/verification_fit.json",
    "payload/evidence/neural/verification_evaluate.json",
    "payload/evidence/neural/independent_verification.json",
    "payload/evidence/neural/stats_report_globecom.json",
    "payload/evidence/neural/equivalence_v5.json",
    "payload/evidence/neural/paper_numeric_check.json",
    "payload/evidence/neural/export_registration.json",
    "payload/evidence/neural/export_prior_exposure.json",
    "payload/evidence/tree/plan.json",
    "payload/evidence/tree/verification_fit.json",
    "payload/evidence/tree/results.json",
    "payload/evidence/tree/independent_verification.json",
    "payload/evidence/tree/test_exposure.json",
    "payload/evidence/exports/summary.json",
    "payload/exports/export_plan.json",
    "payload/evidence/data/data_audit.json",
    "payload/evidence/data/data_acceptance.json",
    IOT_PROVENANCE_REPORT_BUNDLE,
    IOT_PROVENANCE_SPEC_BUNDLE,
    "payload/evidence/paper/main.tex",
    "payload/evidence/paper/main.pdf",
    "payload/evidence/paper/result_macros_v5.tex",
    "payload/evidence/paper/result_macros_v5.provenance.json",
    "payload/evidence/paper/export_macros_v5.tex",
    "payload/evidence/paper/export_macros_v5.provenance.json",
    "payload/source/requirements.txt",
    "payload/source/data_acceptance/producer.py",
    "payload/source/data_acceptance/independent_verifier.py",
    IOT_PROVENANCE_TOOL_BUNDLE,
}) | LIFECYCLE_TOOL_PATHS | AUXILIARY_TOOL_PATHS
HARDWARE_RESULTS = {
    "onboard_ethernet.tsv",
    "qcfs_floor_fallback_onboard.md",
    "related_work_table.json",
    "st_cloud_benchmarks.json",
    "three_platform_latency.md",
    "three_platform_sweep.tsv",
}
HARDWARE_SCRIPTS = {
    "gen_width_onnx.py",
    "n6_bench.py",
    "n6_bench_report.py",
    "n6_cpu_run.py",
    "n6_fetch_deps.sh",
    "n6_validate_pathB.py",
    "n6b_run.py",
    "validate_onnx_neuralart.py",
}


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict:
    def reject_constant(value: str) -> None:
        raise RuntimeError(f"Non-finite JSON constant {value} in {path}")

    value = json.loads(path.read_text(encoding="utf-8"),
                       object_pairs_hook=_unique_object, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object: {path}")
    return value


def check_seal(value: dict, path: Path) -> None:
    claimed = value.get("content_sha256")
    body = {key: item for key, item in value.items() if key != "content_sha256"}
    if not isinstance(claimed, str) or claimed != json_digest(body):
        raise RuntimeError(f"Integrity seal failed: {path}")


def _runtime_identity() -> dict:
    return {
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "version_full": sys.version,
            "executable": str(Path(sys.executable).resolve()),
        },
        "platform": {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "packages": {},
    }


def _canonical_lifecycle_invocation(name: str, argv: list[str], cwd: str) -> dict:
    """Parse report argv locally; never trust a report's claimed parsed fields."""
    specifications: dict[str, tuple[set[str], set[str], set[str]]] = {
        "verify_v5_neural.py": (
            {"--run-dir", "--output"}, set(), {"--run-dir"}
        ),
        "verify_v5_tree.py": (
            {"--tree-run-dir", "--neural-run-dir", "--output"}, set(),
            {"--tree-run-dir", "--neural-run-dir"}
        ),
        "run_v5_exports.py": (
            {"--run-dir", "--output-root", "--paper-dir",
             "--int8-max-disagreement", "--validation-samples",
             "--calibration-samples"},
            set(), {"--run-dir", "--output-root", "--paper-dir"},
        ),
        "package_v5_artifacts.py": (
            {"--run-dir", "--tree-run-dir", "--export-root", "--data-audit",
             "--data-acceptance", "--paper-dir", "--paper-build", "--artifact-root"},
            set(), {"--run-dir", "--tree-run-dir", "--export-root", "--data-audit",
                    "--data-acceptance", "--paper-dir", "--paper-build", "--artifact-root"},
        ),
    }
    if name not in specifications:
        raise RuntimeError(f"Unsupported lifecycle invocation: {name}")
    if len(argv) < 2:
        raise RuntimeError(f"Lifecycle invocation omits executable/tool: {name}")
    value_options, boolean_options, required = specifications[name]
    values: dict[str, str | bool] = {}
    index = 2
    while index < len(argv):
        option = argv[index]
        if option not in value_options | boolean_options:
            raise RuntimeError(f"Unsupported lifecycle invocation option: {name}/{option}")
        if option in values:
            raise RuntimeError(f"Duplicate lifecycle invocation option: {name}/{option}")
        if option in boolean_options:
            values[option] = True
            index += 1
            continue
        if index + 1 >= len(argv):
            raise RuntimeError(f"Missing lifecycle invocation value: {name}/{option}")
        values[option] = argv[index + 1]
        index += 2
    if not required.issubset(values):
        raise RuntimeError(f"Lifecycle invocation omits required options: {name}")

    base = Path(cwd)

    def resolved(option: str) -> str:
        value = values[option]
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"Malformed lifecycle path option: {name}/{option}")
        path = Path(value)
        if not path.is_absolute():
            path = base / path
        return str(path.resolve())

    if name == "verify_v5_neural.py":
        run_dir = Path(resolved("--run-dir"))
        return {
            "run_dir": str(run_dir),
            "output": (resolved("--output") if "--output" in values else
                       str((run_dir / "independent_verification.json").resolve())),
        }
    if name == "verify_v5_tree.py":
        run_dir = Path(resolved("--tree-run-dir"))
        return {
            "tree_run_dir": str(run_dir),
            "neural_run_dir": resolved("--neural-run-dir"),
            "output": (resolved("--output") if "--output" in values else
                       str((run_dir / "independent_verification.json").resolve())),
        }
    if name == "run_v5_exports.py":
        try:
            disagreement = float(values.get("--int8-max-disagreement", "0.01"))
            validation = int(values.get("--validation-samples", "1024"))
            calibration = int(values.get("--calibration-samples", "1000"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Malformed fixed export protocol value") from exc
        if disagreement != 0.01 or validation != 1024 or calibration != 1000:
            raise RuntimeError("Export invocation changed a fixed protocol value")
        return {
            "run_dir": resolved("--run-dir"),
            "output_root": resolved("--output-root"),
            "paper_dir": resolved("--paper-dir"),
            "int8_max_disagreement": disagreement,
            "validation_samples": validation,
            "calibration_samples": calibration,
        }
    return {
        option.removeprefix("--").replace("-", "_"): resolved(option)
        for option in sorted(required)
    }


def archive_tool_provenance() -> dict:
    """Record the exact archive executable and canonical invocation."""
    source = Path(__file__).resolve()
    cwd = Path.cwd().resolve()
    argv = [sys.executable, *sys.argv]
    values: dict[str, str | bool] = {}
    index = 2
    while index < len(argv):
        option = argv[index]
        if option == "--execute":
            if option in values:
                raise RuntimeError(f"Duplicate archive invocation option: {option}")
            values[option] = True
            index += 1
            continue
        if option not in ("--formal-run", "--bundle") or option in values:
            raise RuntimeError(f"Unsupported/duplicate archive invocation option: {option}")
        if index + 1 >= len(argv):
            raise RuntimeError(f"Missing archive invocation value: {option}")
        values[option] = argv[index + 1]
        index += 2
    if not {"--formal-run", "--bundle"}.issubset(values):
        raise RuntimeError("Archive invocation omits formal-run or bundle")

    def resolved(option: str) -> str:
        value = values[option]
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"Malformed archive path option: {option}")
        path = Path(value)
        if not path.is_absolute():
            path = cwd / path
        return str(path.resolve())

    return {
        "schema": 1,
        "tool": {
            "path": "tools/archive_pre_v5.py",
            "source_sha256": digest_file(source),
        },
        "invocation": {
            "argv": argv,
            "cwd": str(cwd),
            "parsed": {
                "formal_run": resolved("--formal-run"),
                "bundle": resolved("--bundle"),
                "execute": values.get("--execute") is True,
            },
        },
        **_runtime_identity(),
    }


def _validate_provenance_shape(value: object, name: str,
                               expected_sha256: str,
                               creator: dict | None = None) -> dict:
    """Validate a report provenance record against a bundled exact tool."""
    if not isinstance(value, dict):
        raise RuntimeError(f"Missing or malformed tool provenance: {name}")
    expected_keys = {"schema", "tool", "invocation", "python", "platform", "packages"}
    if set(value) != expected_keys or value.get("schema") != 1:
        raise RuntimeError(f"Unsupported tool provenance schema: {name}")
    tool = value.get("tool")
    invocation = value.get("invocation")
    python = value.get("python")
    platform_value = value.get("platform")
    packages = value.get("packages")
    if (not isinstance(tool, dict) or
            tool != {"path": f"tools/{name}", "source_sha256": expected_sha256}):
        raise RuntimeError(f"Report is bound to different tool bytes: {name}")
    if (not isinstance(invocation, dict) or
            set(invocation) != {"argv", "cwd", "parsed"} or
            not isinstance(invocation.get("argv"), list) or
            len(invocation["argv"]) < 2 or
            not all(isinstance(item, str) and item for item in invocation["argv"]) or
            not isinstance(invocation.get("cwd"), str) or not invocation["cwd"] or
            not isinstance(invocation.get("parsed"), dict)):
        raise RuntimeError(f"Malformed exact invocation provenance: {name}")
    if (not isinstance(python, dict) or
            set(python) != {"implementation", "version", "version_full", "executable"} or
            not all(isinstance(item, str) and item for item in python.values())):
        raise RuntimeError(f"Malformed Python provenance: {name}")
    if (not isinstance(platform_value, dict) or
            set(platform_value) != {"platform", "system", "release", "machine"} or
            not all(isinstance(item, str) for item in platform_value.values())):
        raise RuntimeError(f"Malformed platform provenance: {name}")
    if (not isinstance(packages, dict) or
            set(packages) != LIFECYCLE_TOOL_PACKAGES[name] or
            not all(isinstance(item, str) and item for item in packages.values())):
        raise RuntimeError(f"Malformed relevant-package provenance: {name}")
    argv = invocation["argv"]
    if Path(argv[0]).resolve() != Path(python["executable"]):
        raise RuntimeError(f"Invocation Python differs from runtime provenance: {name}")
    invoked_tool = Path(argv[1])
    if not invoked_tool.is_absolute():
        invoked_tool = Path(invocation["cwd"]) / invoked_tool
    if invoked_tool.resolve() != ROOT / "tools" / name:
        raise RuntimeError(f"Invocation refers to another tool path: {name}")
    if invocation["parsed"] != _canonical_lifecycle_invocation(
            name, argv, invocation["cwd"]):
        raise RuntimeError(f"Claimed parsed invocation differs from exact argv: {name}")
    if creator is not None:
        if python != creator.get("python") or platform_value != creator.get("platform"):
            raise RuntimeError(f"Report runtime differs from bundle-creation runtime: {name}")
        creator_packages = creator.get("packages")
        if (not isinstance(creator_packages, dict) or
                any(creator_packages.get(package) != version
                    for package, version in packages.items())):
            raise RuntimeError(f"Report package versions differ from bundle creator: {name}")
    else:
        current = _runtime_identity()
        if python != current["python"] or platform_value != current["platform"]:
            raise RuntimeError("Bundle creator runtime differs from the archive runtime")
        expected_packages = {
            package: importlib.metadata.version(package)
            for package in LIFECYCLE_TOOL_PACKAGES[name]
        }
        if packages != expected_packages:
            raise RuntimeError("Bundle creator package versions differ from the archive runtime")
    return value


def validate_bundled_lifecycle_tools(
        bundle: Path, manifest: dict,
        inventory_by_path: dict[str, dict]) -> tuple[dict, dict]:
    """Validate the mandatory exact lifecycle-tool inventory and creator."""
    declared = manifest.get("lifecycle_tools_sha256")
    expected_paths = set(LIFECYCLE_TOOL_PATHS)
    if not isinstance(declared, dict) or set(declared) != expected_paths:
        raise RuntimeError("Bundle lifecycle-tool inventory is missing or unexpected")
    actual_paths = {
        relative for relative in inventory_by_path
        if relative.startswith("payload/source/tools/")
    }
    if actual_paths != expected_paths | AUXILIARY_TOOL_PATHS:
        raise RuntimeError("Bundle contains an unbound lifecycle tool")
    for relative in sorted(expected_paths):
        path = bundle / relative
        row = inventory_by_path.get(relative)
        if (not isinstance(row, dict) or not path.is_file() or path.is_symlink() or
                path.lstat().st_nlink != 1 or
                row.get("sha256") != declared[relative] or
                digest_file(path) != declared[relative]):
            raise RuntimeError(f"Bundled lifecycle tool is missing or changed: {relative}")
    for name, expected_sha256 in TRUSTED_LIFECYCLE_TOOL_SHA256.items():
        if declared[f"payload/source/tools/{name}"] != expected_sha256:
            raise RuntimeError(f"Bundled lifecycle tool is not release-trusted: {name}")
    auxiliary = manifest.get("auxiliary_tools_sha256")
    if not isinstance(auxiliary, dict) or set(auxiliary) != AUXILIARY_TOOL_PATHS:
        raise RuntimeError("Auxiliary release verifier source inventory is incomplete")
    for relative, expected_sha in auxiliary.items():
        current = ROOT / "tools" / Path(relative).name
        if (current.resolve() != current or not current.is_file() or
                current.stat().st_nlink != 1 or digest_file(current) != expected_sha or
                digest_file(bundle / relative) != expected_sha or
                inventory_by_path[relative].get("sha256") != expected_sha):
            raise RuntimeError("Auxiliary release verifier differs from installed reviewed source")
    bundled_archive = bundle / "payload/source/tools/archive_pre_v5.py"
    if digest_file(bundled_archive) != digest_file(Path(__file__).resolve()):
        raise RuntimeError("Bundled archive gate differs from the executing archive gate")
    creator = _validate_provenance_shape(
        manifest.get("creator_provenance"),
        "package_v5_artifacts.py",
        declared["payload/source/tools/package_v5_artifacts.py"],
    )
    if manifest.get("bundle_replay") != ARCHIVE_REPLAY_BLOCKER:
        raise RuntimeError("Bundle does not preserve the fail-closed replay blocker")
    return declared, creator


def validate_bundled_lifecycle_provenance(
        bundle: Path, manifest: dict, inventory_by_path: dict[str, dict]) -> None:
    """Cross-bind bundled reports to exact bundled tools without trusting live verifiers."""
    declared, creator = validate_bundled_lifecycle_tools(
        bundle, manifest, inventory_by_path
    )

    neural = _sealed_bundle_json(
        bundle, "payload/evidence/neural/independent_verification.json"
    )
    tree = _sealed_bundle_json(
        bundle, "payload/evidence/tree/independent_verification.json"
    )
    export_summary = _sealed_bundle_json(
        bundle, "payload/evidence/exports/summary.json"
    )
    expected_reports = (
        (neural, "verify_v5_neural.py"),
        (tree, "verify_v5_tree.py"),
        (export_summary, "run_v5_exports.py"),
    )
    validated = {}
    for report, name in expected_reports:
        validated[name] = _validate_provenance_shape(
            report.get("tool_provenance"), name,
            declared[f"payload/source/tools/{name}"], creator,
        )
    resolved_manifest_paths = {}
    for field in ("formal_run", "formal_tree_run", "export_run", "data_audit",
                  "data_acceptance", "paper_dir", "paper_build", "artifact_root"):
        value = manifest.get(field)
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"Bundle manifest omits invocation path: {field}")
        path = Path(value)
        if not path.is_absolute():
            path = ROOT / path
        resolved_manifest_paths[field] = str(path.resolve())
    if validated["verify_v5_neural.py"]["invocation"]["parsed"] != {
        "run_dir": resolved_manifest_paths["formal_run"],
        "output": str(Path(resolved_manifest_paths["formal_run"]) /
                      "independent_verification.json"),
    }:
        raise RuntimeError("Neural verifier canonical invocation differs from manifest")
    if validated["verify_v5_tree.py"]["invocation"]["parsed"] != {
        "tree_run_dir": resolved_manifest_paths["formal_tree_run"],
        "neural_run_dir": resolved_manifest_paths["formal_run"],
        "output": str(Path(resolved_manifest_paths["formal_tree_run"]) /
                      "independent_verification.json"),
    }:
        raise RuntimeError("Tree verifier canonical invocation differs from manifest")
    if validated["run_v5_exports.py"]["invocation"]["parsed"] != {
        "run_dir": resolved_manifest_paths["formal_run"],
        "output_root": resolved_manifest_paths["export_run"],
        "paper_dir": resolved_manifest_paths["paper_dir"],
        "int8_max_disagreement": 0.01,
        "validation_samples": 1024,
        "calibration_samples": 1000,
    }:
        raise RuntimeError("Export runner canonical invocation differs from manifest")
    if creator["invocation"]["parsed"] != {
        "run_dir": resolved_manifest_paths["formal_run"],
        "tree_run_dir": resolved_manifest_paths["formal_tree_run"],
        "export_root": resolved_manifest_paths["export_run"],
        "data_audit": resolved_manifest_paths["data_audit"],
        "data_acceptance": resolved_manifest_paths["data_acceptance"],
        "paper_dir": resolved_manifest_paths["paper_dir"],
        "paper_build": resolved_manifest_paths["paper_build"],
        "artifact_root": resolved_manifest_paths["artifact_root"],
    }:
        raise RuntimeError("Packager canonical invocation differs from manifest")
    attempts = export_summary.get("attempts")
    if not isinstance(attempts, list):
        raise RuntimeError("Bundled export summary has no attempt matrix")
    formal_run = Path(resolved_manifest_paths["formal_run"])
    export_run = Path(resolved_manifest_paths["export_run"])
    runner_python = validated["run_v5_exports.py"]["invocation"]["argv"][0]
    for row in attempts:
        if not isinstance(row, dict) or not isinstance(row.get("evidence"), str):
            raise RuntimeError("Malformed bundled export attempt provenance")
        evidence = _sealed_bundle_json(
            bundle, f"payload/exports/{row['evidence']}"
        )
        if evidence.get("tool_provenance") != validated["run_v5_exports.py"]:
            raise RuntimeError("Bundled export attempt has different runner provenance")
        expected_command = [
            runner_python,
            str(ROOT / "spikeids_v5/export_verified.py"),
            "--run-dir", str(formal_run.resolve()),
            "--dataset", str(row.get("dataset")),
            "--model", str(row.get("model")),
            "--output-dir", str((export_run / str(row.get("output_dir"))).resolve()),
            "--export-plan", str(export_run / "export_plan.json"),
            "--fold-bn",
            "--validation-samples", "1024",
            "--calibration-samples", "1000",
            "--atol", "1e-6",
            "--rtol", "1e-5",
        ]
        if row.get("mode") == "qdq":
            expected_command.extend(("--int8", "--int8-max-disagreement", "0.01"))
        if evidence.get("exporter_invocation") != expected_command:
            raise RuntimeError("Bundled export attempt invocation is stale or forged")
    export_macro = _sealed_bundle_json(
        bundle, "payload/evidence/paper/export_macros_v5.provenance.json"
    )
    if export_macro.get("tool_provenance") != validated["run_v5_exports.py"]:
        raise RuntimeError("Bundled export macro has different runner provenance")


def _sealed_bundle_json(bundle: Path, relative: str) -> dict:
    path = bundle / relative
    value = load_json(path)
    check_seal(value, path)
    return value


def _cache_files_sha256(root: Path) -> dict[str, str]:
    root = Path(root)
    if root.is_symlink():
        raise RuntimeError(f"Accepted cache root is symlinked: {root}")
    root = root.resolve()
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError(f"Accepted cache root is missing or symlinked: {root}")
    entries = sorted(root.iterdir())
    if (not entries or any(not path.is_file() or path.is_symlink() or
                           path.lstat().st_nlink != 1 for path in entries)):
        raise RuntimeError(f"Accepted cache is not a flat independent file tree: {root}")
    return {
        path.name: digest_file(path) for path in entries
        if path.name != "metadata.json"
    }


def _resolve_manifest_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"Missing path binding: {label}")
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    if path.is_symlink():
        raise RuntimeError(f"Symlinked path binding: {label}")
    return path.resolve()


def validate_bundled_iot_provenance(
        bundle: Path, audit: dict, upstream: object,
        inventory_by_path: dict[str, dict]) -> None:
    """Bind the accepted IoT comparison to bundled report/tool/spec bytes."""
    if (not isinstance(upstream, dict) or set(upstream) != {
                "path", "sha256", "content_sha256", "comparison_passed"
            } or upstream.get("comparison_passed") is not True):
        raise RuntimeError("Data acceptance IoT upstream-provenance binding is malformed")
    report = _sealed_bundle_json(bundle, IOT_PROVENANCE_REPORT_BUNDLE)
    report_path = bundle / IOT_PROVENANCE_REPORT_BUNDLE
    live_report = _resolve_manifest_path(
        upstream.get("path"), "IoT-23 provenance report"
    )
    report_row = inventory_by_path.get(IOT_PROVENANCE_REPORT_BUNDLE, {})
    if (not live_report.is_file() or live_report.is_symlink() or
            live_report.lstat().st_nlink != 1 or
            live_report.name != "iot23_provenance.json" or
            live_report != (ROOT / "spikeids_v5/audit/iot23_provenance.json").resolve() or
            upstream.get("sha256") != report_row.get("sha256") or
            digest_file(live_report) != report_row.get("sha256") or
            digest_file(report_path) != report_row.get("sha256") or
            upstream.get("content_sha256") != report.get("content_sha256")):
        raise RuntimeError("Bundled/live IoT provenance report bytes differ")
    if (report.get("kind") != "spikeids_v5_iot23_provenance" or
            report.get("schema") != 1 or
            report.get("comparison_passed") is not True or
            report.get("passed") is not True):
        raise RuntimeError("Bundled IoT provenance comparison is failed or unsupported")
    limitations = report.get("limitations")
    if (not isinstance(limitations, dict) or
            set(limitations) != IOT_PROVENANCE_LIMITATIONS or
            any(value is not False for value in limitations.values())):
        raise RuntimeError("Bundled IoT provenance limitations are missing or overclaimed")

    tool_record = report.get("tool")
    tool_path = bundle / IOT_PROVENANCE_TOOL_BUNDLE
    tool_row = inventory_by_path.get(IOT_PROVENANCE_TOOL_BUNDLE, {})
    live_tool = (ROOT / "tools/verify_iot23_provenance.py").resolve()
    if (not isinstance(tool_record, dict) or
            set(tool_record) != {"path", "sha256"} or
            tool_record.get("path") != "tools/verify_iot23_provenance.py" or
            tool_record.get("sha256") != tool_row.get("sha256") or
            digest_file(tool_path) != tool_record.get("sha256") or
            not live_tool.is_file() or live_tool.is_symlink() or
            live_tool.lstat().st_nlink != 1 or
            digest_file(live_tool) != tool_record.get("sha256")):
        raise RuntimeError("Bundled IoT provenance verifier bytes differ")

    spec_record = report.get("source_spec")
    spec_path = bundle / IOT_PROVENANCE_SPEC_BUNDLE
    spec_row = inventory_by_path.get(IOT_PROVENANCE_SPEC_BUNDLE, {})
    if (not isinstance(spec_record, dict) or
            set(spec_record) != {"path", "bytes", "sha256"} or
            spec_record.get("path") != "spikeids_v5/audit/source_specs/iot23.json" or
            spec_record.get("bytes") != spec_row.get("bytes") or
            spec_record.get("sha256") != spec_row.get("sha256") or
            digest_file(spec_path) != spec_record.get("sha256")):
        raise RuntimeError("Bundled IoT provenance source-spec bytes differ")
    spec = load_json(spec_path)
    audited = audit.get("datasets", {}).get("iot23", {})
    if (spec.get("dataset") != "iot23" or spec.get("source_contract_version") != 1 or
            audited.get("source_spec_sha256") != spec_record.get("sha256") or
            report.get("origin_revision") != spec.get("origin", {}).get("revision")):
        raise RuntimeError("Bundled IoT provenance source contract differs")
    reported_shards = report.get("origin_shards")
    declared_shards = spec.get("origin_shards")
    if (not isinstance(reported_shards, list) or
            not isinstance(declared_shards, list) or
            len(reported_shards) != len(declared_shards) or len(reported_shards) != 3):
        raise RuntimeError("Bundled IoT provenance lacks exactly three origin shards")
    for index, (reported, declared) in enumerate(zip(
            reported_shards, declared_shards, strict=True)):
        if (not isinstance(reported, dict) or not isinstance(declared, dict) or
                set(reported) != {
                    "path", "bytes", "sha256", "rows", "physical_schema"
                } or
                {key: reported.get(key) for key in ("path", "bytes", "sha256")} != {
                    "path": declared.get("path"),
                    "bytes": declared.get("bytes"),
                    "sha256": declared.get("lfs_sha256"),
                } or type(reported.get("rows")) is not int or reported["rows"] <= 0 or
                not isinstance(reported.get("physical_schema"), dict)):
            raise RuntimeError(f"Malformed bundled IoT origin shard: {index}")
    combined = report.get("combined")
    declared_files = spec.get("files")
    if (not isinstance(combined, dict) or set(combined) != {
                "path", "bytes", "sha256", "rows", "physical_schema"
            } or not isinstance(declared_files, list) or len(declared_files) != 1 or
            not isinstance(declared_files[0], dict)):
        raise RuntimeError("Malformed bundled IoT combined-file provenance")
    combined_identity = {
        key: combined.get(key) for key in ("path", "bytes", "sha256", "rows")
    }
    expected_combined = {
        "path": declared_files[0].get("path"),
        "bytes": declared_files[0].get("bytes"),
        "sha256": declared_files[0].get("sha256"),
        "rows": declared_files[0].get("expected_rows"),
    }
    audited_files = audited.get("files")
    if (combined_identity != expected_combined or
            not isinstance(combined.get("physical_schema"), dict) or
            not isinstance(audited_files, list) or len(audited_files) != 1 or
            {key: audited_files[0].get(key)
             for key in ("path", "bytes", "sha256", "rows")} != combined_identity):
        raise RuntimeError("Bundled IoT combined provenance differs from audit/spec")
    semantic = report.get("semantic_comparison")
    if (not isinstance(semantic, dict) or
            semantic.get("rows") != combined.get("rows") or
            semantic.get("columns") != list(IOT_PROVENANCE_COLUMNS) or
            semantic.get("chunk_rows") != 65536 or
            type(semantic.get("chunks")) is not int or semantic["chunks"] <= 0 or
            any(semantic.get(key) is not True for key in (
                "column_order_equal", "row_order_equal", "values_equal",
                "missingness_equal",
            )) or not isinstance(semantic.get("normalizations"), list) or
            type(semantic.get("parquet_schema_metadata_equal")) is not bool or
            semantic.get("parquet_schema_metadata_is_semantic") is not False):
        raise RuntimeError("Bundled IoT semantic comparison is incomplete")


def validate_data_acceptance_evidence(
        bundle: Path, manifest: dict, plan: dict, audit: dict,
        inventory_by_path: dict[str, dict]) -> None:
    """Recheck the sealed two-rebuild acceptance report and its live caches."""
    report_relative = "payload/evidence/data/data_acceptance.json"
    report = _sealed_bundle_json(bundle, report_relative)
    live_report = _resolve_manifest_path(
        manifest.get("data_acceptance"), "data_acceptance"
    )
    if (not live_report.is_file() or live_report.is_symlink() or
            live_report.lstat().st_nlink != 1 or
            digest_file(live_report) != inventory_by_path[report_relative].get("sha256")):
        raise RuntimeError("Live data-acceptance report differs from the bundle")
    if (report.get("kind") != "spikeids_v5_data_acceptance" or
            report.get("acceptance_schema") != 1 or
            report.get("data_acceptance_passed") is not True or
            report.get("two_distinct_fresh_roots") is not True or
            report.get("byte_identical_rebuilds") is not True):
        raise RuntimeError("Bundled data acceptance is missing, failed, or unsupported")
    raw = report.get("raw_audit")
    expected_audit_path = _resolve_manifest_path(manifest.get("data_audit"), "data_audit")
    audit_relative = "payload/evidence/data/data_audit.json"
    if (not isinstance(raw, dict) or set(raw) != {
                "path", "sha256", "content_sha256", "audit_implementation_sha256",
                "raw_source_audit_passed",
            } or
            _resolve_manifest_path(raw.get("path"), "accepted raw audit") !=
            expected_audit_path or
            raw.get("sha256") != inventory_by_path[audit_relative].get("sha256") or
            raw.get("content_sha256") != audit.get("content_sha256") or
            raw.get("audit_implementation_sha256") !=
            audit.get("audit_implementation_sha256") or
            raw.get("raw_source_audit_passed") is not True):
        raise RuntimeError("Data acceptance is not bound to the bundled raw audit")
    if (audit.get("raw_source_audit_passed") is not True or
            audit.get("data_acceptance_passed") is not False):
        raise RuntimeError("Raw audit is missing or improperly claims final acceptance")

    code_paths = []
    for field, relative in (
        ("producer", "payload/source/data_acceptance/producer.py"),
        ("independent_verifier",
         "payload/source/data_acceptance/independent_verifier.py"),
    ):
        record = report.get(field)
        if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
            raise RuntimeError(f"Malformed data-acceptance {field} binding")
        live_path = _resolve_manifest_path(record.get("path"), field)
        code_paths.append(live_path)
        if (not live_path.is_file() or live_path.is_symlink() or
                live_path.lstat().st_nlink != 1 or
                digest_file(live_path) != record.get("sha256") or
                inventory_by_path.get(relative, {}).get("sha256") !=
                record.get("sha256")):
            raise RuntimeError(f"Data-acceptance {field} bytes differ")
    if (code_paths[0] == code_paths[1] or
            report["producer"]["sha256"] ==
            report["independent_verifier"]["sha256"]):
        raise RuntimeError("Data-acceptance producer and verifier are not independent")
    validate_bundled_iot_provenance(
        bundle, audit, report.get("upstream_provenance"), inventory_by_path
    )
    limitations = report.get("limitations")
    if (not isinstance(limitations, dict) or
            set(limitations) != DATA_ACCEPTANCE_LIMITATIONS or
            any(value is not False for value in limitations.values())):
        raise RuntimeError("Data-acceptance limitations are missing or overclaimed")
    datasets = report.get("datasets")
    if not isinstance(datasets, dict) or set(datasets) != set(FORMAL_DATASETS):
        raise RuntimeError("Data acceptance does not cover exactly four datasets")
    for dataset in FORMAL_DATASETS:
        accepted = datasets[dataset]
        audited = audit.get("datasets", {}).get(dataset, {})
        if (not isinstance(accepted, dict) or
                accepted.get("byte_identical_rebuilds") is not True or
                accepted.get("raw_files") != audited.get("files")):
            raise RuntimeError(f"Data-acceptance raw-file binding differs: {dataset}")
        semantic = accepted.get("semantic_checks")
        if (not isinstance(semantic, dict) or
                set(semantic) != DATA_ACCEPTANCE_SEMANTIC_CHECKS or
                any(value is not True for value in semantic.values())):
            raise RuntimeError(f"Data-acceptance semantic checks are incomplete: {dataset}")
        rebuilds = accepted.get("rebuilds")
        if not isinstance(rebuilds, list) or len(rebuilds) != 2:
            raise RuntimeError(f"Data acceptance lacks two rebuilds: {dataset}")
        roots = []
        bindings = []
        for rebuild in rebuilds:
            if not isinstance(rebuild, dict) or set(rebuild) != {
                    "resolved_root", "metadata_sha256", "data_fingerprint",
                    "files_sha256"}:
                raise RuntimeError(f"Malformed accepted rebuild: {dataset}")
            root_value = rebuild["resolved_root"]
            if not isinstance(root_value, str) or not Path(root_value).is_absolute():
                raise RuntimeError(f"Accepted rebuild root is not absolute: {dataset}")
            root = Path(root_value).resolve()
            if str(root) != root_value:
                raise RuntimeError(f"Accepted rebuild root is noncanonical: {dataset}")
            metadata_path = root / "metadata.json"
            metadata = load_json(metadata_path)
            check_seal(metadata, metadata_path)
            files = _cache_files_sha256(root)
            binding = (metadata, files, digest_file(metadata_path))
            if (rebuild.get("metadata_sha256") != binding[2] or
                    rebuild.get("data_fingerprint") != metadata.get("data_fingerprint") or
                    rebuild.get("files_sha256") != files or
                    metadata.get("files_sha256") != files):
                raise RuntimeError(f"Accepted rebuild bytes/metadata differ: {dataset}")
            roots.append(root)
            bindings.append(binding)
        if roots[0] == roots[1] or bindings[0] != bindings[1]:
            raise RuntimeError(f"Accepted rebuilds are not distinct/byte-identical: {dataset}")
        metadata, files, metadata_sha256 = bindings[0]
        counts = metadata.get("counts", {})
        partition = metadata.get("partition", {})
        if (accepted.get("cache_counts") != counts or
                accepted.get("features") != metadata.get("features") or
                accepted.get("classes") != metadata.get("class_names") or
                accepted.get("realized_pattern_fractions") !=
                partition.get("retained_pattern_fractions") or
                audited.get("rows") != metadata.get("raw_rows") or
                partition.get("retained_rows") != sum(counts.values()) or
                partition.get("retained_rows") + partition.get("excluded_rows") !=
                metadata.get("raw_rows")):
            raise RuntimeError(f"Accepted cache schema/accounting differs: {dataset}")
        if (metadata.get("exact_model_input_group_leakage_excluded") is not True or
                metadata.get("capture_device_time_group_generalization_established") is not False or
                metadata.get("upstream_preprocessing_verified") is not False):
            raise RuntimeError(f"Accepted cache scope is missing or overclaimed: {dataset}")
        jobs = [job for job in plan.get("jobs", []) if job.get("dataset") == dataset]
        if (not jobs or len({job.get("cache") for job in jobs}) != 1 or
                len({job.get("data_fingerprint") for job in jobs}) != 1):
            raise RuntimeError(f"Formal cache binding is ambiguous: {dataset}")
        formal_root_input = Path(jobs[0]["cache"])
        if formal_root_input.is_symlink():
            raise RuntimeError(f"Formal cache root is symlinked: {dataset}")
        formal_root = formal_root_input.resolve()
        if (digest_file(formal_root / "metadata.json") != metadata_sha256 or
                _cache_files_sha256(formal_root) != files or
                jobs[0].get("data_fingerprint") != metadata.get("data_fingerprint")):
            raise RuntimeError(f"Formal cache differs from accepted rebuilds: {dataset}")


def expected_live_source(relative: str, manifest: dict, plan: dict) -> Path | None:
    """Derive the only allowed live source for every compacted evidence payload."""
    if relative == IOT_PROVENANCE_TOOL_BUNDLE:
        return (ROOT / "tools/verify_iot23_provenance.py").resolve()
    if relative.startswith("payload/checkpoints/"):
        formal = _resolve_manifest_path(manifest.get("formal_run"), "formal_run")
        parts = Path(relative).parts
        if len(parts) != 5:
            raise RuntimeError(f"Unsafe checkpoint bundle path: {relative}")
        _, _, dataset, model, filename = parts
        return (formal / "results" / f"{dataset}_{model}" / "runs" /
                f"{model}_{filename}").resolve()
    neural_prefix = "payload/evidence/neural/"
    if relative.startswith(neural_prefix):
        formal = _resolve_manifest_path(manifest.get("formal_run"), "formal_run")
        suffix = relative.removeprefix(neural_prefix)
        if suffix.startswith("results/") and suffix.endswith("_manifest.json"):
            job_id = Path(suffix).name.removesuffix("_manifest.json")
            return (formal / "results" / job_id / "manifest.json").resolve()
        return (formal / suffix).resolve()
    tree_prefix = "payload/evidence/tree/"
    if relative.startswith(tree_prefix):
        tree = _resolve_manifest_path(manifest.get("formal_tree_run"), "formal_tree_run")
        return (tree / relative.removeprefix(tree_prefix)).resolve()
    if relative == "payload/evidence/exports/summary.json":
        exports = _resolve_manifest_path(manifest.get("export_run"), "export_run")
        return (exports / "summary.json").resolve()
    tree_model_prefix = "payload/tree_models/"
    if relative.startswith(tree_model_prefix):
        tree = _resolve_manifest_path(manifest.get("formal_tree_run"), "formal_tree_run")
        parts = Path(relative).parts
        if len(parts) != 5:
            raise RuntimeError(f"Unsafe tree-model bundle path: {relative}")
        _, _, dataset, kind, filename = parts
        if filename.endswith(".joblib"):
            return (tree / "primary" / dataset / kind / filename).resolve()
        if kind == "random_forest" and filename.endswith(".onnx"):
            return (tree / "onnx" / filename).resolve()
        raise RuntimeError(f"Unexpected tree-model bundle path: {relative}")
    export_prefix = "payload/exports/"
    if relative.startswith(export_prefix):
        exports = _resolve_manifest_path(manifest.get("export_run"), "export_run")
        return (exports / relative.removeprefix(export_prefix)).resolve()
    data_prefix = "payload/evidence/data/"
    if relative.startswith(data_prefix):
        suffix = relative.removeprefix(data_prefix)
        if suffix == "data_audit.json":
            return _resolve_manifest_path(manifest.get("data_audit"), "data_audit")
        if suffix == "data_acceptance.json":
            return _resolve_manifest_path(
                manifest.get("data_acceptance"), "data_acceptance"
            )
        return (ROOT / "spikeids_v5/audit" / suffix).resolve()
    paper_prefix = "payload/evidence/paper/"
    if relative.startswith(paper_prefix):
        if relative == "payload/evidence/paper/main.pdf":
            return _resolve_manifest_path(manifest.get("paper_build"), "paper_build") / "main.pdf"
        paper = _resolve_manifest_path(manifest.get("paper_dir"), "paper_dir")
        return (paper / relative.removeprefix(paper_prefix)).resolve()
    build_prefix = "payload/evidence/paper_build/"
    if relative.startswith(build_prefix):
        build = _resolve_manifest_path(manifest.get("paper_build"), "paper_build")
        return (build / relative.removeprefix(build_prefix)).resolve()
    preprocessing_prefix = "payload/preprocessing/"
    if relative.startswith(preprocessing_prefix):
        parts = Path(relative).parts
        if len(parts) != 4:
            raise RuntimeError(f"Unsafe preprocessing bundle path: {relative}")
        dataset, filename = parts[2], parts[3]
        jobs = [job for job in plan.get("jobs", []) if job.get("dataset") == dataset]
        if not jobs or len({job.get("cache") for job in jobs}) != 1:
            raise RuntimeError(f"Ambiguous preprocessing source: {dataset}")
        return (Path(jobs[0]["cache"]) / filename).resolve()
    return None



def fixed_export_protocol() -> dict:
    """The policy is fixed in code; no observed export can select these values."""
    return {
        "deployment_seed": 0, "fold_bn": True, "opset": 17, "export_batch": 1,
        "fp32_atol": 1e-6, "fp32_rtol": 1e-5,
        "fp32_max_prediction_disagreement": 0.0,
        "int8_max_prediction_disagreement": 0.01,
        "validation_samples": 1024, "calibration_samples": 1000,
        "row_selection": {
            "generator": "numpy.random.default_rng(0); PCG64",
            "order": ["validation", "fit"], "replace": False,
            "indices": "ascending sorted choice indices",
            "validation_partition": "validation", "calibration_partition": "fit",
            "insufficient_rows": "fail; never silently truncate",
        },
        "qdq_recipe": {
            "quant_format": "QDQ", "activation_type": "QInt8",
            "weight_type": "QInt8", "per_channel": True,
            "reduce_range": False, "calibrate_method": "MinMax",
            "op_types_to_quantize": ["Gemm", "MatMul", "Conv"],
            "nodes_to_quantize": [], "nodes_to_exclude": [],
            "use_external_data_format": False,
            "calibration_providers": ["CPUExecutionProvider"],
            "extra_options": {},
            "unspecified_behavior": "bound to the recorded ONNX Runtime version and source",
        },
        "runtime": {
            "provider": "CPUExecutionProvider", "intra_op_threads": 1,
            "inter_op_threads": 1, "execution_mode": "ORT_SEQUENTIAL",
            "graph_optimization_level": "ORT_ENABLE_BASIC",
            "torch_deterministic_algorithms": True,
            "torch_float32_matmul_precision": "highest",
        },
        "retry_policy": "one registered matrix per neural run; failed artifacts retained",
    }


def validate_export_binding(record: dict) -> None:
    if not isinstance(record, dict) or set(record) != {"path", "sha256", "stat"}:
        raise RuntimeError("Malformed frozen export binding")
    path = Path(record["path"])
    if (not path.is_absolute() or path.resolve() != path or
            not path.is_file() or path.stat().st_nlink != 1):
        raise RuntimeError("Frozen export binding path is unsafe")
    before = path.stat()
    identity = {"device": before.st_dev, "inode": before.st_ino,
                "size": before.st_size, "mtime_ns": before.st_mtime_ns,
                "ctime_ns": before.st_ctime_ns}
    if record["stat"] != identity or digest_file(path) != record["sha256"]:
        raise RuntimeError("Frozen export binding changed")
    after = path.stat()
    if ({"device": after.st_dev, "inode": after.st_ino,
         "size": after.st_size, "mtime_ns": after.st_mtime_ns,
         "ctime_ns": after.st_ctime_ns} != identity or
            after.st_mode != before.st_mode or after.st_nlink != 1 or
            path.resolve() != path):
        raise RuntimeError("Frozen export binding raced validation")


def validate_bundled_export_plan(bundle: Path, manifest: dict, neural: dict,
                                 summary: dict) -> dict:
    relative = "payload/exports/export_plan.json"
    plan = _sealed_bundle_json(bundle, relative)
    formal = _resolve_manifest_path(manifest.get("formal_run"), "formal_run")
    exports = _resolve_manifest_path(manifest.get("export_run"), "export_run")
    expected_attempts = [(d, m, q) for d, m in FORMAL_JOBS for q in ("fp32", "qdq")]
    if (plan.get("schema") != 1 or plan.get("kind") != "spikeids_v5_export_plan" or
            plan.get("source_plan_sha256") != neural["content_sha256"] or
            plan.get("run_dir") != str(formal) or plan.get("output_root") != str(exports) or
            plan.get("protocol") != fixed_export_protocol() or
            plan.get("tool_provenance") != summary.get("tool_provenance") or
            summary.get("export_plan_sha256") != plan["content_sha256"] or
            manifest.get("export_plan_sha256") != plan["content_sha256"] or
            [(row.get("dataset"), row.get("model"), row.get("mode"))
             for row in plan.get("attempts", [])] != expected_attempts):
        raise RuntimeError("Bundled frozen export plan policy/identity/matrix differs")
    source = plan.get("source_plan", {})
    if (source.get("path") != str(formal / "plan.json") or
            source.get("sha256") != digest_file(bundle / "payload/evidence/neural/plan.json")):
        raise RuntimeError("Bundled export plan neural binding differs")
    registration = _sealed_bundle_json(bundle, "payload/evidence/neural/export_registration.json")
    expected_registration = {
        "schema": 1, "kind": "spikeids_v5_export_registration",
        "source_plan_sha256": neural["content_sha256"],
        "export_plan_path": str(exports / "export_plan.json"),
        "export_plan_sha256": plan["content_sha256"],
        "export_plan_file_sha256": digest_file(bundle / relative),
    }
    if {k: v for k, v in registration.items() if k != "content_sha256"} != expected_registration:
        raise RuntimeError("Bundled export registration differs")
    exposure_relative = "payload/evidence/neural/export_prior_exposure.json"
    exposure = _sealed_bundle_json(bundle, exposure_relative)
    if (exposure.get("schema") != 1 or
            exposure.get("kind") != "spikeids_v5_export_prior_exposure" or
            exposure.get("source_plan_sha256") != neural["content_sha256"] or
            not isinstance(exposure.get("known_exposures"), list) or
            not isinstance(exposure.get("declaration"), str) or
            not exposure["declaration"].strip() or
            exposure.get("complete_history_independently_verified") is not False or
            exposure.get("local_freeze_is_external_preregistration") is not False or
            plan.get("prior_exposure", {}).get("declaration") != exposure or
            plan.get("prior_exposure", {}).get("binding", {}).get("path") !=
            str(formal / "export_prior_exposure.json") or
            plan["prior_exposure"]["binding"].get("sha256") !=
            digest_file(bundle / exposure_relative)):
        raise RuntimeError("Bundled prior export exposure differs or overclaims chronology")
    inputs, sources = plan.get("inputs"), plan.get("sources")
    if (not isinstance(inputs, list) or not inputs or
            not isinstance(sources, list) or not sources):
        raise RuntimeError("Frozen export plan lacks complete inputs/sources")
    expected_sources = [str(path.resolve()) for path in (
        *sorted((ROOT / "spikeids_v5").glob("*.py")),
        ROOT / "tools/run_v5_exports.py", ROOT / "tools/verify_v5_neural.py",
        ROOT / "spikeids_v5/EXPORT_PROTOCOL.md",
    )]
    if [row.get("path") for row in sources] != expected_sources:
        raise RuntimeError("Frozen export source inventory is incomplete or changed")
    for records in (inputs, sources):
        paths = [row.get("path") for row in records]
        if len(paths) != len(set(paths)):
            raise RuntimeError("Frozen export plan duplicates input/source bindings")
        for row in records:
            validate_export_binding(row)
    indexed = {row["path"]: row for row in inputs}
    if indexed.get(source["path"]) != source or indexed.get(
            str(formal / "export_prior_exposure.json")) != plan["prior_exposure"]["binding"]:
        raise RuntimeError("Frozen export plan omits its mandatory input bindings")
    for row in exposure["known_exposures"]:
        if (not isinstance(row, dict) or
                set(row) != {"description", "evidence_path", "evidence_sha256"} or
                not isinstance(row["description"], str) or not row["description"].strip() or
                indexed.get(row["evidence_path"], {}).get("sha256") != row["evidence_sha256"]):
            raise RuntimeError("Known prior export exposure is not bound to evidence")
    if plan.get("python_executable_sha256") != digest_file(Path(sys.executable).resolve()):
        raise RuntimeError("Frozen export Python runtime changed")
    return plan


def validate_bundled_resource_evidence(bundle: Path, plan: dict) -> None:
    # Load only the installed reviewed module, never executable bundle payloads.
    package = ROOT / "spikeids_v5"
    for name in ("resource_evidence.py", "contracts.py"):
        source = package / name
        if (not source.is_file() or source.resolve() != source or
                digest_file(source) != plan.get("sources", {}).get(name)):
            raise RuntimeError("Resource verifier source differs from frozen plan")
    sys.path.insert(0, str(package))
    import contracts
    import resource_evidence
    from resource_evidence import validate_resource_reports
    if (Path(resource_evidence.__file__).resolve() != package / "resource_evidence.py" or
            Path(contracts.__file__).resolve() != package / "contracts.py"):
        raise RuntimeError("Unexpected imported resource verifier")
    validate_resource_reports(bundle / "payload/evidence/neural", plan)


def validate_bundled_release_inputs(bundle: Path, manifest: dict, plan: dict) -> None:
    # Auxiliary sources were checked against their installed reviewed bytes by
    # validate_bundled_lifecycle_tools before any module is imported here.
    sys.path.insert(0, str(ROOT))
    from tools import v5_retention, verify_v5_paper_build
    for module in (v5_retention, verify_v5_paper_build):
        if Path(module.__file__).resolve() != ROOT / "tools" / (module.__name__.split('.')[-1] + ".py"):
            raise RuntimeError("Unexpected imported release verifier")
    roots = {
        "neural": _resolve_manifest_path(manifest.get("formal_run"), "formal_run"),
        "tree": _resolve_manifest_path(manifest.get("formal_tree_run"), "formal_tree_run"),
        "exports": _resolve_manifest_path(manifest.get("export_run"), "export_run"),
    }
    retention = _sealed_bundle_json(bundle, "RETENTION_MANIFEST.json")
    if retention.get("plan_identities") != {
        "neural": plan["content_sha256"], "tree": manifest.get("tree_plan_sha256"),
        "exports": manifest.get("export_plan_sha256"),
    }:
        raise RuntimeError("Full retention manifest belongs to another scientific run")
    v5_retention.validate_retention(retention, roots)
    plans = {"neural": roots["neural"] / "plan.json", "tree": roots["tree"] / "plan.json",
             "export": roots["exports"] / "export_plan.json"}
    paper = _resolve_manifest_path(manifest.get("paper_dir"), "paper_dir")
    verify_v5_paper_build.validate_paper_build(
        bundle / "payload/evidence/paper_build", paper, plans, replay=False
    )
    if digest_file(bundle / "payload/evidence/paper/main.pdf") != digest_file(
            bundle / "payload/evidence/paper_build/main.pdf"):
        raise RuntimeError("Bundled paper PDF differs from the verified clean build")

def validate_bundled_scientific_failure(bundle: Path, export_plan: dict,
                                         row: dict, evidence: dict) -> None:
    key = (row["dataset"], row["model"], row["mode"])
    output = bundle / "payload/exports" / row["output_dir"]
    failure = _sealed_bundle_json(bundle, str((output / "FAILED.json").relative_to(bundle)))
    attempt = next(item for item in export_plan["attempts"]
                   if (item["dataset"], item["model"], item["mode"]) == key)
    stages = {
        "freeze": ("freeze_check", "BN folding/freezing changed outputs beyond the predeclared gate; inspect boundary activations"),
        "fp32_parity": ("onnx_check", "ONNX numerical parity gate failed"),
        "qdq_parity": ("quantization_check", "QDQ validation disagreement gate failed"),
    }
    stage = failure.get("stage")
    if (type(row.get("return_code")) is not int or row["return_code"] != 1 or
            evidence.get("return_code") != 1 or
            evidence.get("status") != "export_subprocess_failed" or
            evidence.get("failure_classification") != "reproduced_scientific_gate" or
            evidence.get("failure_replay_error") is not None or
            failure.get("schema") != 1 or failure.get("status") != "failed" or
            failure.get("publication_gate") is not False or
            failure.get("source_plan_sha256") != export_plan["source_plan_sha256"] or
            failure.get("export_plan_sha256") != export_plan["content_sha256"] or
            failure.get("checkpoint_sha256") != attempt.get("checkpoint_sha256") or
            stage not in stages or (stage == "qdq_parity" and key[2] != "qdq")):
        raise RuntimeError("Bundled failure is not a classified scientific gate result")
    check_name, reason = stages[stage]
    ordered = ["freeze_check", "onnx_check", "quantization_check"]
    diagnostics = failure.get("diagnostics")
    if (failure.get("reason") != f"ContractError: {reason}" or
            not isinstance(diagnostics, dict) or
            set(diagnostics) != set(ordered[:ordered.index(check_name) + 1])):
        raise RuntimeError("Bundled failure numerical stage/diagnostics differ")
    for name, check in diagnostics.items():
        if (not isinstance(check, dict) or type(check.get("allclose")) is not bool or
                check.get("vectors_checked") != 1024 or
                any(type(check.get(field)) not in (int, float) or
                    not math.isfinite(check[field]) for field in
                    ("max_abs_error", "prediction_disagreement_fraction")) or
                check["max_abs_error"] < 0 or
                not 0 <= check["prediction_disagreement_fraction"] <= 1):
            raise RuntimeError("Bundled failure numerical diagnostics are malformed")
        passed = (check["prediction_disagreement_fraction"] <= 0.01 if
                  name == "quantization_check" else
                  check["allclose"] and check["prediction_disagreement_fraction"] == 0)
        if passed is not (name != check_name):
            raise RuntimeError("Bundled failure contradicts the fixed numerical gate")
    partial = dict(evidence["output_files_sha256"])
    failure_sha = partial.pop("FAILED.json", None)
    expected_partial = {"export_policy.json"}
    if stage in ("fp32_parity", "qdq_parity"):
        expected_partial.add("model_fp32.onnx")
    if stage == "qdq_parity":
        expected_partial.add("model_qdq_int8.onnx")
    replay = {"kind": "exact_scientific_failure_replay", "passed": True,
              "export_plan_sha256": export_plan["content_sha256"],
              "failure_sha256": failure_sha,
              "output_files_sha256": evidence["output_files_sha256"]}
    if (set(partial) != expected_partial or failure.get("partial_files_sha256") != partial or
            evidence.get("failure_file") != "FAILED.json" or
            evidence.get("failure_file_sha256") != failure_sha or
            evidence.get("failure_replay") != replay):
        raise RuntimeError("Bundled scientific failure payload/replay differs")
    policy = _sealed_bundle_json(bundle, str((output / "export_policy.json").relative_to(bundle)))
    if (policy.get("export_plan_sha256") != export_plan["content_sha256"] or
            policy.get("checkpoint_sha256") != attempt["checkpoint_sha256"] or
            policy.get("qdq_recipe") != fixed_export_protocol()["qdq_recipe"]):
        raise RuntimeError("Bundled failed attempt used another quantization policy")


def validate_embedded_evidence(bundle: Path, manifest: dict, plan: dict,
                               inventory_by_path: dict[str, dict]) -> None:
    """Cross-bind the evidence copied into the otherwise self-consistent bundle."""
    embedded_plan_path = "payload/evidence/neural/plan.json"
    embedded_plan = _sealed_bundle_json(bundle, embedded_plan_path)
    if embedded_plan != plan:
        raise RuntimeError("Bundled neural plan differs from the formal-run plan")
    sources = plan.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise RuntimeError("Formal neural plan has no frozen source inventory")
    for relative, expected in sources.items():
        source_relative = f"payload/source/spikeids_v5/{relative}"
        if (source_relative not in inventory_by_path or
                digest_file(bundle / source_relative) != expected):
            raise RuntimeError(f"Bundle lacks exact frozen source: {relative}")
    environment = load_json(bundle / "payload/evidence/neural/environment.json")
    if environment != plan.get("environment"):
        raise RuntimeError("Bundled environment record differs from the neural plan")

    neural_fit_path = "payload/evidence/neural/verification_fit.json"
    neural_eval_path = "payload/evidence/neural/verification_evaluate.json"
    neural_independent = _sealed_bundle_json(
        bundle, "payload/evidence/neural/independent_verification.json"
    )
    if (neural_independent.get("passed") is not True or
            neural_independent.get("kind") !=
            "independent_formal_neural_and_statistics_verification" or
            neural_independent.get("plan_sha256") != plan["content_sha256"] or
            neural_independent.get("prediction_artifacts_checked") != 440 or
            neural_independent.get("checkpoints_checked") != 440 or
            neural_independent.get("verification_fit_sha256") !=
            digest_file(bundle / neural_fit_path) or
            neural_independent.get("verification_evaluate_sha256") !=
            digest_file(bundle / neural_eval_path)):
        raise RuntimeError("Bundled independent neural verification is stale or incomplete")
    statistics = neural_independent.get("statistics", {})
    if (statistics.get("difference_report_sha256") != digest_file(
            bundle / "payload/evidence/neural/stats_report_globecom.json") or
            statistics.get("equivalence_report_sha256") != digest_file(
                bundle / "payload/evidence/neural/equivalence_v5.json") or
            statistics.get("difference_hypotheses") != 14 or
            statistics.get("equivalence_hypotheses") != 8):
        raise RuntimeError("Bundled independent statistics verification is stale or incomplete")

    tree_plan_path = "payload/evidence/tree/plan.json"
    tree_fit_path = "payload/evidence/tree/verification_fit.json"
    tree_results_path = "payload/evidence/tree/results.json"
    tree_plan = _sealed_bundle_json(bundle, tree_plan_path)
    tree_independent = _sealed_bundle_json(
        bundle, "payload/evidence/tree/independent_verification.json"
    )
    neural_binding = {
        "path": str(_resolve_manifest_path(manifest.get("formal_run"), "formal_run") / "plan.json"),
        "sha256": digest_file(bundle / "payload/evidence/neural/plan.json"),
        "content_sha256": plan["content_sha256"],
    }
    acceptance = _sealed_bundle_json(bundle, "payload/evidence/data/data_acceptance.json")
    acceptance_binding = {
        "path": str(_resolve_manifest_path(manifest.get("data_acceptance"), "data_acceptance")),
        "sha256": digest_file(bundle / "payload/evidence/data/data_acceptance.json"),
        "content_sha256": acceptance["content_sha256"],
    }
    if (tree_plan.get("neural_plan") != neural_binding or
            tree_independent.get("neural_plan") != neural_binding or
            tree_plan.get("data_acceptance") != acceptance_binding or
            tree_independent.get("data_acceptance") != acceptance_binding or
            tree_independent.get("test_exposure_sha256") != digest_file(
                bundle / "payload/evidence/tree/test_exposure.json")):
        raise RuntimeError("Bundled tree neural/data/test-exposure binding differs")
    tree_root = _resolve_manifest_path(manifest.get("formal_tree_run"), "formal_tree_run")
    tree_execution_files = set()
    execution_ids = set()
    for dataset in ("nslkdd", "unsw"):
        for kind, seeds in (("random_forest", range(20)), ("xgboost", [0])):
            for seed in seeds:
                for execution in ("primary", "replica"):
                    stem = f"{execution}/{dataset}/{kind}/seed_{seed}"
                    record_relative = f"payload/evidence/tree/{stem}.json"
                    ledger_relative = f"payload/evidence/tree/{stem}.ledger.json"
                    tree_execution_files.update((record_relative, ledger_relative))
                    record = _sealed_bundle_json(bundle, record_relative)
                    ledger = _sealed_bundle_json(bundle, ledger_relative)
                    verified = tree_independent.get("models", {}).get(dataset, {}).get(
                        kind, {}).get(str(seed), {}).get(execution, {})
                    identity = verified.get("execution_identity", {})
                    execution_id = identity.get("execution_id")
                    if (not isinstance(execution_id, str) or len(execution_id) != 32 or
                            set(execution_id) - set("0123456789abcdefABCDEF") or
                            execution_id in execution_ids or
                            identity != {"execution_id": execution_id, "execution": execution,
                                         "record_path": str(tree_root / f"{stem}.json"),
                                         "artifact_path": str(tree_root / f"{stem}.joblib")} or
                            record.get("execution_identity") != identity or
                            ledger.get("execution_identity") != identity or
                            ledger.get("ledger_kind") != "tree_execution_ledger" or
                            ledger.get("run_dir") != str(tree_root) or
                            verified.get("record_sha256") != digest_file(bundle / record_relative) or
                            verified.get("execution_ledger_sha256") != digest_file(bundle / ledger_relative) or
                            record.get("execution_ledger_sha256") != verified.get("execution_ledger_sha256") or
                            record.get("execution_ledger_content_sha256") != ledger.get("content_sha256")):
                        raise RuntimeError("Bundled tree execution identity/ledger differs")
                    execution_ids.add(execution_id)
    actual_execution_files = {name for name in inventory_by_path
                              if name.startswith(("payload/evidence/tree/primary/",
                                                  "payload/evidence/tree/replica/"))}
    if tree_execution_files != actual_execution_files:
        raise RuntimeError("Bundled tree execution evidence set is incomplete or unexpected")
    if (manifest.get("tree_plan_sha256") != tree_plan.get("content_sha256") or
            tree_independent.get("passed") is not True or
            tree_independent.get("kind") != "independent_formal_tree_verification" or
            tree_independent.get("tree_plan_sha256") != tree_plan.get("content_sha256") or
            tree_independent.get("tree_results_sha256") !=
            digest_file(bundle / tree_results_path) or
            tree_independent.get("tree_fit_verification_sha256") !=
            digest_file(bundle / tree_fit_path)):
        raise RuntimeError("Bundled independent tree verification is stale or incomplete")
    for dataset in ("nslkdd", "unsw"):
        for kind in ("random_forest", "xgboost"):
            relative = f"payload/tree_models/{dataset}/{kind}/seed_0.joblib"
            evidence = tree_independent.get("models", {}).get(dataset, {}).get(
                kind, {}
            ).get("0", {}).get("primary", {})
            if (relative not in inventory_by_path or
                    evidence.get("artifact_sha256") !=
                    inventory_by_path[relative].get("sha256")):
                raise RuntimeError(
                    f"Bundled tree model differs from independent report: {dataset}/{kind}"
                )
    rf_onnx = tree_independent.get("rf_onnx")
    if (not isinstance(rf_onnx, list) or len(rf_onnx) != 2 or
            {item.get("dataset") for item in rf_onnx if isinstance(item, dict)} !=
            {"nslkdd", "unsw"}):
        raise RuntimeError("Independent RF ONNX evidence matrix is incomplete")
    for evidence in rf_onnx:
        if not isinstance(evidence, dict):
            raise RuntimeError("Malformed independent RF ONNX evidence")
        onnx_dataset = evidence.get("dataset")
        if evidence.get("onnx") != f"onnx/rf_{onnx_dataset}_seed_0.onnx":
            raise RuntimeError(f"Independent RF ONNX path changed: {onnx_dataset}")
        relative = (
            f"payload/tree_models/{onnx_dataset}/random_forest/"
            f"{Path(str(evidence.get('onnx'))).name}"
        )
        if (relative not in inventory_by_path or
                evidence.get("onnx_sha256") !=
                inventory_by_path[relative].get("sha256")):
            raise RuntimeError(
                f"Bundled RF ONNX differs from independent report: {onnx_dataset}"
            )
    expected_tree_payloads = {
        f"payload/tree_models/{dataset}/{kind}/seed_0.joblib"
        for dataset in ("nslkdd", "unsw")
        for kind in ("random_forest", "xgboost")
    } | {
        f"payload/tree_models/{dataset}/random_forest/rf_{dataset}_seed_0.onnx"
        for dataset in ("nslkdd", "unsw")
    }
    actual_tree_payloads = {
        relative for relative in inventory_by_path
        if relative.startswith("payload/tree_models/")
    }
    if actual_tree_payloads != expected_tree_payloads:
        raise RuntimeError("Bundled tree-model payload set is incomplete or unexpected")

    audit = _sealed_bundle_json(bundle, "payload/evidence/data/data_audit.json")
    if (audit.get("raw_source_audit_passed") is not True or
            audit.get("data_acceptance_passed") is not False or
            audit.get("audit_implementation_sha256") != sources.get("audit_data.py") or
            audit.get("data_loader_sha256") != sources.get("data_loaders.py")):
        raise RuntimeError("Bundled data audit is failed or bound to different source")
    validate_data_acceptance_evidence(
        bundle, manifest, plan, audit, inventory_by_path
    )

    export_summary = _sealed_bundle_json(
        bundle, "payload/evidence/exports/summary.json"
    )
    export_plan = validate_bundled_export_plan(bundle, manifest, plan, export_summary)
    bundled_export_summary = "payload/exports/summary.json"
    if (bundled_export_summary not in inventory_by_path or
            digest_file(bundle / bundled_export_summary) !=
            digest_file(bundle / "payload/evidence/exports/summary.json")):
        raise RuntimeError("Bundled export summary copies differ")
    attempts = export_summary.get("attempts")
    expected_attempts = {(dataset, model, mode) for dataset, model in FORMAL_JOBS
                         for mode in ("fp32", "qdq")}
    ordered_attempts = [(dataset, model, mode) for dataset, model in FORMAL_JOBS
                        for mode in ("fp32", "qdq")]
    observed_attempts: set[tuple[str, str, str]] = set()
    expected_export_files = {"payload/exports/summary.json", "payload/exports/export_plan.json"}
    fp32_passed = 0
    qdq_passed = 0
    if (export_summary.get("source_plan_sha256") != plan["content_sha256"] or
            export_summary.get("deployment_seed") != 0 or
            export_summary.get("fold_bn") is not True or
            export_summary.get("fp32_atol") != 1e-6 or
            export_summary.get("fp32_rtol") != 1e-5 or
            export_summary.get("fp32_max_prediction_disagreement") != 0.0 or
            export_summary.get("fp32_passed") != len(FORMAL_JOBS) or
            export_summary.get("fp32_total") != len(FORMAL_JOBS) or
            export_summary.get("qdq_total") != len(FORMAL_JOBS) or
            export_summary.get("validation_samples") != 1024 or
            export_summary.get("calibration_samples") != 1000 or
            export_summary.get("int8_max_prediction_disagreement") != 0.01 or
            any(type(export_summary.get(name)) is not int for name in
                ("deployment_seed", "fp32_passed", "fp32_total", "qdq_passed",
                 "qdq_total", "validation_samples", "calibration_samples")) or
            any(type(export_summary.get(name)) is not float for name in
                ("fp32_atol", "fp32_rtol", "fp32_max_prediction_disagreement",
                 "int8_max_prediction_disagreement")) or
            type(export_summary.get("all_gates_passed")) is not bool or
            not isinstance(attempts, list) or len(attempts) != 2 * len(FORMAL_JOBS)):
        raise RuntimeError("Bundled export matrix is incomplete or belongs to another plan")
    if [(row.get("dataset"), row.get("model"), row.get("mode"))
            for row in attempts if isinstance(row, dict)] != ordered_attempts:
        raise RuntimeError("Bundled export matrix order differs from frozen plan")
    for row in attempts:
        if not isinstance(row, dict):
            raise RuntimeError("Malformed bundled export attempt")
        key = (row.get("dataset"), row.get("model"), row.get("mode"))
        if row.get("export_plan_sha256") != export_plan["content_sha256"]:
            raise RuntimeError("Bundled export attempt belongs to another export plan")
        if (key not in expected_attempts or key in observed_attempts or
                type(row.get("passed")) is not bool or
                type(row.get("return_code")) is not int or
                row["return_code"] != (0 if row["passed"] else 1) or
                type(row.get("elapsed_seconds")) not in (int, float) or
                not math.isfinite(row["elapsed_seconds"]) or row["elapsed_seconds"] < 0):
            raise RuntimeError(f"Unexpected/duplicate bundled export attempt: {key}")
        observed_attempts.add(key)
        expected_dir = f"{key[0]}/{key[1]}/{key[2]}"
        expected_evidence = f"{expected_dir}/runner_validation.json"
        expected_log = f"logs/{key[0]}_{key[1]}_{key[2]}.log"
        if (row.get("output_dir") != expected_dir or
                row.get("evidence") != expected_evidence or row.get("log") != expected_log):
            raise RuntimeError(f"Unsafe bundled export path: {key}")
        evidence_relative = f"payload/exports/{expected_evidence}"
        log_relative = f"payload/exports/{expected_log}"
        expected_export_files.update((evidence_relative, log_relative))
        if (evidence_relative not in inventory_by_path or
                log_relative not in inventory_by_path or
                digest_file(bundle / evidence_relative) != row.get("evidence_sha256") or
                digest_file(bundle / log_relative) != row.get("log_sha256")):
            raise RuntimeError(f"Bundled export evidence/log changed: {key}")
        evidence = _sealed_bundle_json(bundle, evidence_relative)
        if (evidence.get("source_plan_sha256") != plan["content_sha256"] or
                evidence.get("export_plan_sha256") != export_plan["content_sha256"] or
                (evidence.get("dataset"), evidence.get("model"),
                 evidence.get("mode")) != key or
                evidence.get("publication_gate") is not row.get("passed")):
            raise RuntimeError(f"Bundled export evidence identity differs: {key}")
        output_files = evidence.get("output_files_sha256")
        if not isinstance(output_files, dict):
            raise RuntimeError(f"Bundled export output inventory is missing: {key}")
        for name, expected_sha256 in output_files.items():
            if (not isinstance(name, str) or not name or Path(name).name != name or
                    not isinstance(expected_sha256, str)):
                raise RuntimeError(f"Unsafe bundled export output name: {key}/{name}")
            relative = f"payload/exports/{expected_dir}/{name}"
            expected_export_files.add(relative)
            if (relative not in inventory_by_path or
                    inventory_by_path[relative].get("sha256") != expected_sha256):
                raise RuntimeError(f"Bundled export payload changed: {key}/{name}")
        if row.get("passed"):
            if (row.get("return_code") != 0 or
                    evidence.get("status") != "independently_validated"):
                raise RuntimeError(f"Passing export lacks validated success status: {key}")
            report_relative = f"payload/exports/{expected_dir}/export_report.json"
            if (report_relative not in inventory_by_path or
                    evidence.get("export_report_sha256") !=
                    inventory_by_path[report_relative].get("sha256")):
                raise RuntimeError(f"Bundled export report changed: {key}")
            report = _sealed_bundle_json(bundle, report_relative)
            if report.get("export_plan_sha256") != export_plan["content_sha256"]:
                raise RuntimeError("Bundled export report belongs to another frozen plan")
            files_sha256 = report.get("files_sha256")
            expected_payloads = {
                "export_policy.json", "validation_vectors.npz", "preprocessing.json",
                "calibration_rows.json", "model_fp32.onnx",
            }
            if key[2] == "qdq":
                expected_payloads.add("model_qdq_int8.onnx")
            if (not isinstance(files_sha256, dict) or
                    set(files_sha256) != expected_payloads or
                    set(output_files) != expected_payloads | {"export_report.json"} or
                    any(output_files.get(name) != expected_sha256
                        for name, expected_sha256 in files_sha256.items())):
                raise RuntimeError(f"Bundled export report payload binding differs: {key}")
            checkpoint_check = evidence.get("checkpoint_check", {})
            fp32_check = evidence.get("fp32_check", {})
            if (checkpoint_check.get("allclose") is not True or
                    checkpoint_check.get("max_abs_error") != 0.0 or
                    checkpoint_check.get("prediction_disagreement_fraction") != 0.0 or
                    checkpoint_check.get("vectors_checked") != 1024 or
                    fp32_check.get("allclose") is not True or
                    fp32_check.get("prediction_disagreement_fraction") != 0.0 or
                    fp32_check.get("vectors_checked") != 1024):
                raise RuntimeError(f"Bundled independent FP32 evidence is incomplete: {key}")
            if key[2] == "qdq":
                qdq_check = evidence.get("qdq_check", {})
                if (qdq_check.get("vectors_checked") != 1024 or
                        qdq_check.get("prediction_disagreement_fraction", 2.0) > 0.01 or
                        not {"QuantizeLinear", "DequantizeLinear"}.issubset(
                            set(evidence.get("qdq_operators", []))) or
                        type(evidence.get("qdq_int8_initializer_count")) is not int or
                        evidence["qdq_int8_initializer_count"] <= 0):
                    raise RuntimeError(f"Bundled QDQ evidence is incomplete: {key}")
                qdq_passed += 1
            else:
                if (evidence.get("qdq_check") is not None or
                        evidence.get("qdq_operators") is not None or
                        evidence.get("qdq_int8_initializer_count") is not None):
                    raise RuntimeError(f"FP32 evidence contains a QDQ claim: {key}")
                fp32_passed += 1
        else:
            validate_bundled_scientific_failure(bundle, export_plan, row, evidence)
    if observed_attempts != expected_attempts:
        raise RuntimeError("Bundled export attempt matrix is incomplete")
    if (export_summary.get("fp32_passed") != fp32_passed or
            export_summary.get("qdq_passed") != qdq_passed or
            export_summary.get("all_gates_passed") is not
            (fp32_passed == qdq_passed == len(FORMAL_JOBS))):
        raise RuntimeError("Bundled export pass counts/all-gates flag are stale")
    actual_export_files = {
        path.relative_to(bundle).as_posix()
        for path in (bundle / "payload/exports").rglob("*") if path.is_file()
    }
    if actual_export_files != expected_export_files:
        raise RuntimeError("Bundled export tree has missing or unbound payloads")

    paper_check = _sealed_bundle_json(
        bundle, "payload/evidence/neural/paper_numeric_check.json"
    )
    if (paper_check.get("numeric_consistency_passed") is not True or
            paper_check.get("strict_heuristic_scan_passed") is not True):
        raise RuntimeError("Bundled strict paper check has not passed")
    result_provenance = _sealed_bundle_json(
        bundle, "payload/evidence/paper/result_macros_v5.provenance.json"
    )
    export_provenance = _sealed_bundle_json(
        bundle, "payload/evidence/paper/export_macros_v5.provenance.json"
    )
    if (result_provenance.get("plan_sha256") != plan["content_sha256"] or
            result_provenance.get("tree_plan_sha256") != tree_plan["content_sha256"] or
            result_provenance.get("macro_sha256") != digest_file(
                bundle / "payload/evidence/paper/result_macros_v5.tex") or
            export_provenance.get("plan_sha256") != plan["content_sha256"] or
            export_provenance.get("export_plan_sha256") != export_plan["content_sha256"] or
            export_provenance.get("export_summary_sha256") != digest_file(
                bundle / "payload/evidence/exports/summary.json") or
            export_provenance.get("macro_sha256") != digest_file(
                bundle / "payload/evidence/paper/export_macros_v5.tex")):
        raise RuntimeError("Bundled paper macro provenance is stale")


def validate_execution_gate(formal_run: Path, bundle: Path) -> tuple[dict, dict]:
    """Verify the formal barrier and every file in the immutable bundle."""
    formal_run = Path(formal_run)
    if formal_run.is_symlink() or not formal_run.is_dir():
        raise RuntimeError(f"Formal run is missing or symlinked: {formal_run}")
    formal_run = formal_run.resolve()
    bundle = Path(bundle)
    if bundle.is_symlink() or not bundle.is_dir():
        raise RuntimeError(f"Bundle is missing or symlinked: {bundle}")
    bundle = bundle.resolve()
    plan_path = formal_run / "plan.json"
    verification_path = formal_run / "verification_evaluate.json"
    plan = load_json(plan_path)
    verification = load_json(verification_path)
    check_seal(plan, plan_path)
    check_seal(verification, verification_path)
    if (plan.get("protocol_role") != "planned_benchmark" or
            plan.get("seeds") != list(range(20)) or
            plan.get("deployment_seed") != 0):
        raise RuntimeError("Formal neural plan is not the fixed full 20-seed benchmark")
    if (verification.get("passed") is not True or
            verification.get("plan_sha256") != plan.get("content_sha256")):
        raise RuntimeError("Formal neural evaluation barrier has not passed or is stale")

    manifest_path = bundle / "BUNDLE_MANIFEST.json"
    if manifest_path.lstat().st_nlink != 1:
        raise RuntimeError("Hardlinked bundle manifest is forbidden")
    manifest = load_json(manifest_path)
    check_seal(manifest, manifest_path)
    if (manifest.get("schema") != 1 or
            manifest.get("kind") != "spikeids_v5_plan_addressed_model_bundle"):
        raise RuntimeError("Unsupported artifact-bundle manifest")
    if (manifest.get("plan_sha256") != plan["content_sha256"] or
            bundle.name != plan["content_sha256"]):
        raise RuntimeError("Artifact bundle path/manifest and formal plan do not agree")
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Artifact bundle has no file inventory")
    seen: set[str] = set()
    inventory_by_path: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Malformed artifact-bundle file record")
        relative = row.get("path")
        if (not isinstance(relative, str) or not relative or relative in seen or
                Path(relative).is_absolute() or ".." in Path(relative).parts or
                Path(relative).as_posix() != relative or relative == "BUNDLE_MANIFEST.json"):
            raise RuntimeError(f"Unsafe/duplicate bundle path: {relative!r}")
        seen.add(relative)
        inventory_by_path[relative] = row
        path = bundle / relative
        if (not path.is_file() or path.is_symlink() or
                path.lstat().st_nlink != 1):
            raise RuntimeError(f"Missing or symlinked bundle file: {relative}")
        if path.stat().st_size != row.get("bytes") or digest_file(path) != row.get("sha256"):
            raise RuntimeError(f"Artifact bundle file changed: {relative}")
        live_prefixes = (
            "payload/checkpoints/", "payload/evidence/neural/",
            "payload/evidence/tree/", "payload/evidence/exports/", "payload/evidence/paper_build/",
            "payload/evidence/data/", "payload/evidence/paper/",
            "payload/tree_models/", "payload/exports/", "payload/preprocessing/",
        )
        if relative.startswith(live_prefixes):
            source_display = row.get("source")
            if not isinstance(source_display, str) or not source_display:
                raise RuntimeError(f"Bundle file omits its live source: {relative}")
            source = Path(source_display)
            if not source.is_absolute():
                source = ROOT / source
            expected_source = expected_live_source(relative, manifest, plan)
            if (not source.is_file() or source.is_symlink() or
                    source.lstat().st_nlink != 1 or
                    expected_source is None or source.resolve() != expected_source or
                    source.stat().st_size != row.get("bytes") or
                    digest_file(source) != row.get("sha256")):
                raise RuntimeError(f"Live formal/tree/export source differs: {relative}")
    actual = set()
    for path in bundle.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"Symlink is forbidden in artifact bundle: {path}")
        if path.is_file() and path.name != "BUNDLE_MANIFEST.json":
            actual.add(path.relative_to(bundle).as_posix())
    if actual != seen:
        raise RuntimeError("Artifact bundle inventory is incomplete or lists absent files")
    if not REQUIRED_BUNDLE_PATHS.issubset(seen):
        missing = sorted(REQUIRED_BUNDLE_PATHS - seen)
        raise RuntimeError(f"Artifact bundle lacks required evidence: {missing}")
    validate_bundled_lifecycle_provenance(bundle, manifest, inventory_by_path)
    validate_bundled_resource_evidence(bundle, plan)
    validate_bundled_release_inputs(bundle, manifest, plan)
    validate_embedded_evidence(bundle, manifest, plan, inventory_by_path)
    formal_display = manifest.get("formal_run")
    if not isinstance(formal_display, str) or not formal_display:
        raise RuntimeError("Artifact bundle omits its formal run path")
    displayed_path = Path(formal_display)
    if not displayed_path.is_absolute():
        displayed_path = ROOT / displayed_path
    if displayed_path.resolve() != formal_run:
        raise RuntimeError("Artifact bundle refers to another formal run directory")
    for field in ("formal_tree_run", "export_run"):
        display = manifest.get(field)
        if not isinstance(display, str) or not display:
            raise RuntimeError(f"Artifact bundle omits {field}")
        path = Path(display)
        if not path.is_absolute():
            path = ROOT / path
        if not path.resolve().is_dir():
            raise RuntimeError(f"Artifact bundle {field} is missing: {path}")
    if (manifest.get("full_all_seed_evidence_in_formal_runs") is not True or
            manifest.get("large_payload_intended_for_git") is not False):
        raise RuntimeError("Artifact bundle retention/version-control policy is missing")
    selected = manifest.get("selected_models")
    if not isinstance(selected, list) or len(selected) != len(FORMAL_JOBS):
        raise RuntimeError("Artifact bundle must select exactly one checkpoint per formal job")
    observed_models: set[tuple[str, str]] = set()
    neural_independent = _sealed_bundle_json(
        bundle, "payload/evidence/neural/independent_verification.json"
    )
    for model in selected:
        if not isinstance(model, dict):
            raise RuntimeError("Malformed selected-model record")
        key = (model.get("dataset"), model.get("model"))
        if key not in FORMAL_JOBS or key in observed_models or model.get("seed") != 0:
            raise RuntimeError(f"Unexpected or duplicate selected model: {key}")
        observed_models.add(key)
        relative = model.get("checkpoint")
        if (not isinstance(relative, str) or
                relative != f"payload/checkpoints/{key[0]}/{key[1]}/seed_0.pt" or
                relative not in inventory_by_path):
            raise RuntimeError(f"Selected checkpoint path is missing or unsafe: {key}")
        row = inventory_by_path[relative]
        job_id = f"{key[0]}_{key[1]}"
        checkpoint_evidence = (
            neural_independent.get("checkpoints", {})
            .get(job_id, {}).get("results", {}).get("0", {})
        )
        expected_formal_path = f"results/{job_id}/runs/{key[1]}_seed_0.pt"
        if (model.get("checkpoint_sha256") != row.get("sha256") or
                checkpoint_evidence.get("path") != expected_formal_path or
                checkpoint_evidence.get("artifact_sha256") != row.get("sha256")):
            raise RuntimeError(f"Selected checkpoint digest differs from inventory: {key}")
        for name in ("best_state_sha256", "final_state_sha256", "data_fingerprint"):
            value = model.get(name)
            if not isinstance(value, str) or len(value) != 64:
                raise RuntimeError(f"Selected model lacks {name}: {key}")
        if (checkpoint_evidence.get("best_state_sha256") !=
                model.get("best_state_sha256") or
                checkpoint_evidence.get("final_state_sha256") !=
                model.get("final_state_sha256")):
            raise RuntimeError(f"Selected checkpoint semantics differ from verifier: {key}")
        if type(model.get("best_epoch")) is not int or model["best_epoch"] < 1:
            raise RuntimeError(f"Selected model has invalid best epoch: {key}")
        result_relative = f"payload/evidence/neural/results/{key[0]}_{key[1]}.json"
        if result_relative not in inventory_by_path:
            raise RuntimeError(f"Bundle lacks selected model result evidence: {key}")
        result = _sealed_bundle_json(bundle, result_relative)
        fit_rows = [item for item in result.get("fit_runs", [])
                    if isinstance(item, dict) and item.get("seed") == 0]
        if (len(fit_rows) != 1 or result.get("dataset") != key[0] or
                result.get("kind") != key[1] or
                result.get("data_fingerprint") != model.get("data_fingerprint") or
                fit_rows[0].get("best_state_sha256") != model.get("best_state_sha256") or
                fit_rows[0].get("final_state_sha256") != model.get("final_state_sha256") or
                fit_rows[0].get("best_epoch") != model.get("best_epoch")):
            raise RuntimeError(f"Selected model metadata differs from result evidence: {key}")
    if observed_models != set(FORMAL_JOBS):
        raise RuntimeError("Artifact bundle selected-model matrix is incomplete")
    expected_checkpoints = {
        f"payload/checkpoints/{dataset}/{model}/seed_0.pt"
        for dataset, model in FORMAL_JOBS
    }
    actual_checkpoints = {
        relative for relative in inventory_by_path
        if relative.startswith("payload/checkpoints/")
    }
    if actual_checkpoints != expected_checkpoints:
        raise RuntimeError("Artifact bundle checkpoint payload set is incomplete or unexpected")
    return verification, manifest


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                          allow_nan=False) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                                              dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def add(entries: list[dict], source: str, destination: str, category: str,
        reason: str, replacement: str | None, required: bool = True) -> None:
    path = ROOT / source
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return
    entries.append({"source": source, "destination": destination,
                    "category": category, "reason": reason,
                    "replacement": replacement})


def build_plan(preserve_result_names: set[str] | None = None) -> list[dict]:
    preserve_result_names = set() if preserve_result_names is None else preserve_result_names
    entries: list[dict] = []
    legacy_reason = ("Pre-v5 ML workflow or result is not authoritative for current claims; "
                     "known paths include test-selected checkpoints and/or fit-provenance leakage.")
    replacement = "spikeids_v5/README.md"
    add(entries, "README.md", "archive/pre_v5_non_authoritative/root/README_v4.md",
        "pre_v5_non_authoritative", legacy_reason, replacement)
    add(entries, "Makefile", "archive/pre_v5_non_authoritative/root/Makefile",
        "pre_v5_non_authoritative", legacy_reason, replacement)
    for name in ("configs", "src", "tests", "models"):
        add(entries, name, f"archive/pre_v5_non_authoritative/{name}",
            "pre_v5_non_authoritative", legacy_reason, replacement)

    for path in sorted((ROOT / "scripts").iterdir()):
        if path.is_dir():
            add(entries, f"scripts/{path.name}",
                f"archive/pre_v5_non_authoritative/scripts/{path.name}",
                "pre_v5_non_authoritative",
                "Generated caches or legacy script subtrees are not active version-5 entry points.",
                replacement)
            continue
        if not path.is_file():
            continue
        if path.name in HARDWARE_SCRIPTS:
            add(entries, f"scripts/{path.name}", f"archive/historical_hardware/scripts/{path.name}",
                "historical_hardware_not_v5_bound",
                "Historical board/toolchain utility is preserved but is not checkpoint-bound v5 deployment evidence.",
                "spikeids_v5/EXPORT_PROTOCOL.md")
        else:
            add(entries, f"scripts/{path.name}", f"archive/pre_v5_non_authoritative/scripts/{path.name}",
                "pre_v5_non_authoritative", legacy_reason, replacement)

    add(entries, "firmware", "archive/historical_hardware/firmware",
        "historical_hardware_not_v5_bound",
        "Representative and historical firmware is preserved but is not checkpoint-bound v5 deployment evidence.",
        "spikeids_v5/deployment_gate.py")
    add(entries, "docs", "archive/historical_docs/docs", "historical_documentation",
        "Historical design/review documents may cite pre-v5 numbers and are not current evidence.",
        "README.md")
    for source, destination in (
        ("paper/aicas", "archive/historical_papers/aicas"),
        ("paper/preprint_v3", "archive/historical_papers/preprint_v3"),
        ("paper/main.tex", "archive/historical_papers/v1/main.tex"),
        ("paper/main.pdf", "archive/historical_papers/v1/main.pdf"),
        ("paper/references.bib", "archive/historical_papers/v1/references.bib"),
    ):
        add(entries, source, destination, "historical_paper",
            "Superseded manuscript retained for provenance; it is not the version-5 paper.",
            "paper/globecom/main.tex")
    add(entries, "paper/globecom/result_macros.tex",
        "archive/pre_v5_non_authoritative/paper/globecom/result_macros.tex",
        "pre_v5_non_authoritative", "Hand-maintained pre-v5 result macros contain stale values.",
        "paper/globecom/result_macros_v5.tex")

    for path in sorted((ROOT / "results").iterdir()):
        if path.name in preserve_result_names:
            continue
        relative = f"results/{path.name}"
        if path.name.startswith("v5_"):
            add(entries, relative, f"archive/v5_nonformal_validation/results/{path.name}",
                "v5_nonformal_validation",
                "Version-5 smoke, benchmark, or partial-run evidence is useful for engineering validation but is not the formal paper run.",
                "the formal run recorded in the plan-addressed artifact bundle")
            continue
        hardware = path.name.startswith("n6_") or path.name in HARDWARE_RESULTS
        if hardware:
            add(entries, relative, f"archive/historical_hardware/results/{path.name}",
                "historical_hardware_not_v5_bound",
                "Historical measurement/context retained, but it is not bound to a v5 checkpoint-to-binary chain.",
                "spikeids_v5/EXPORT_PROTOCOL.md")
        else:
            add(entries, relative, f"archive/pre_v5_non_authoritative/results/{path.name}",
                "pre_v5_non_authoritative", legacy_reason, replacement)

    for source, destination, category in (
        ("SetupSTM32CubeProgrammer_linux_64.zip", "archive/local_toolchain_installers/SetupSTM32CubeProgrammer_linux_64.zip", "local_toolchain_installer"),
        ("stedgeai-lin.zip", "archive/local_toolchain_installers/stedgeai-lin.zip", "local_toolchain_installer"),
        ("spikeids_v5_codex_handoff.zip", "archive/local_handoffs/spikeids_v5_codex_handoff.zip", "local_handoff_package"),
        ("spikeids_v5_codex_handoff(1).zip", "archive/local_handoffs/spikeids_v5_codex_handoff(1).zip", "local_handoff_package"),
        ("spikeids_v5_execution_evidence_20260920.zip", "archive/local_handoffs/spikeids_v5_execution_evidence_20260920.zip", "local_handoff_package"),
        ("st_ai_output", "archive/historical_hardware/local_workspaces/st_ai_output", "historical_hardware_not_v5_bound"),
        ("st_ai_ws", "archive/historical_hardware/local_workspaces/st_ai_ws", "historical_hardware_not_v5_bound"),
        ("ai_runner.log", "archive/historical_hardware/local_workspaces/ai_runner.log", "historical_hardware_not_v5_bound"),
        ("reviewer_comment.md", "archive/historical_docs/reviewer_comment.md", "historical_documentation"),
    ):
        add(entries, source, destination, category,
            "Local source/tooling/history moved out of the repository root; classification is explicit in the manifest.",
            None, required=False)
    return entries


def inventory(entries: list[dict]) -> list[dict]:
    records = []
    for entry in entries:
        source = ROOT / entry["source"]
        if source.is_symlink():
            raise RuntimeError(f"Refusing to archive a symlinked source: {source}")
        if source.is_dir():
            symlinks = [path for path in source.rglob("*") if path.is_symlink()]
            if symlinks:
                raise RuntimeError(f"Refusing to archive a tree containing a symlink: {symlinks[0]}")
        files = [source] if source.is_file() else sorted(path for path in source.rglob("*") if path.is_file())
        for path in files:
            if path.is_symlink() or path.lstat().st_nlink != 1:
                raise RuntimeError(f"Refusing to archive a symlinked/hardlinked file: {path}")
            suffix = Path(entry["destination"])
            if source.is_dir():
                suffix /= path.relative_to(source)
            records.append({
                "original_path": path.relative_to(ROOT).as_posix(),
                "archived_path": suffix.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": digest_file(path),
                "category": entry["category"],
                "reason": entry["reason"],
                "replacement": entry["replacement"],
            })
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--formal-run", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.bundle.is_symlink():
        raise RuntimeError(f"Bundle path must not be a symlink: {args.bundle}")
    formal_run, bundle = args.formal_run.resolve(), args.bundle.resolve()
    verification, bundle_manifest = validate_execution_gate(formal_run, bundle)

    preserve_result_names: set[str] = set()
    candidates = [bundle_manifest.get("formal_run"), bundle_manifest.get("formal_tree_run"),
                  bundle_manifest.get("export_run")]
    candidates.extend(row.get("source") for row in bundle_manifest.get("files", [])
                      if isinstance(row, dict))
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        parts = Path(candidate).parts
        if len(parts) >= 2 and parts[0] == "results":
            preserve_result_names.add(parts[1])
    if formal_run.parent == ROOT / "results":
        preserve_result_names.add(formal_run.name)

    entries = build_plan(preserve_result_names)
    destinations = [entry["destination"] for entry in entries]
    if len(destinations) != len(set(destinations)):
        raise RuntimeError("Duplicate archive destination")
    for entry in entries:
        destination = ROOT / entry["destination"]
        if destination.exists():
            raise FileExistsError(destination)
    records = inventory(entries)
    print(f"Archive plan: {len(entries)} path moves, {len(records)} files, "
          f"{sum(row['bytes'] for row in records) / 1024**2:.1f} MiB")
    if not args.execute:
        for entry in entries:
            print(f"{entry['source']} -> {entry['destination']} [{entry['category']}]")
        return

    completed: list[tuple[Path, Path]] = []
    archive_manifest = ROOT / "archive/MANIFEST.json"
    if archive_manifest.exists():
        raise FileExistsError(archive_manifest)
    try:
        for entry in entries:
            source, destination = ROOT / entry["source"], ROOT / entry["destination"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
            completed.append((source, destination))
        for row in records:
            destination = ROOT / row["archived_path"]
            if (not destination.is_file() or destination.is_symlink() or
                    destination.stat().st_size != row["bytes"] or
                    digest_file(destination) != row["sha256"]):
                raise RuntimeError(f"Post-move archive verification failed: {destination}")
        manifest_body = {
            "schema": 1,
            "kind": "pre_v5_and_historical_archive_manifest",
            "formal_plan_sha256": verification["plan_sha256"],
            "artifact_bundle": bundle.relative_to(ROOT).as_posix() if bundle.is_relative_to(ROOT) else str(bundle),
            "artifact_bundle_manifest_sha256": digest_file(bundle / "BUNDLE_MANIFEST.json"),
            "artifact_bundle_file_count": len(bundle_manifest["files"]),
            "archive_tool_provenance": archive_tool_provenance(),
            "bundle_replay": ARCHIVE_REPLAY_BLOCKER,
            "records": records,
            "record_count": len(records),
            "total_bytes": sum(row["bytes"] for row in records),
            "deletion_performed": False,
            "recovery": "Move archived_path back to original_path after verifying SHA-256.",
        }
        write_json(archive_manifest,
                   {**manifest_body, "content_sha256": json_digest(manifest_body)})
    except Exception:
        if archive_manifest.exists():
            archive_manifest.unlink()
        for source, destination in reversed(completed):
            source.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and not source.exists():
                os.replace(destination, source)
        raise
    print("Archive completed without deletion; wrote archive/MANIFEST.json")


if __name__ == "__main__":
    main()
