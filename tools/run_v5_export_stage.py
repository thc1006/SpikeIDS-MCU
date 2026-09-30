#!/usr/bin/env python3
"""Reviewed, one-shot neural export stage; never edits accepted predecessors.

A successfully completed matrix may contain reproduced scientific negatives.
Controller exit 0 means execution/verification completed, NOT all parity gates
passed. Infrastructure, independent-validator, or evidence failures stop the
matrix immediately and preserve the partial namespace. No automatic retries.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "spikeids_v5")]
from tools import run_v5_tree_stage as tree
from tools import run_v5_exports as legacy
from tools import export_v5_runtime as adapter
from tools import export_v5_science as science

data, research = tree.data, tree.research
require, seal, equal = tree.require, tree.seal, tree.equal
snapshot, record = tree.snapshot, tree.record
SELF = Path(__file__).resolve()
SCOPE = "fixed_22_neural_export_attempts_with_independent_validation_or_exact_failure_replay"
ENVIRONMENT = {"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
               "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"}
ROLES = {"export_lifecycle", "export_science", "export_controller"}
RESOURCE_PLAN = seal({"protocol_role": "planned_benchmark", "jobs": [], "resource_limits": {
    "host_swap_scope": "host context only; workload cgroup swap must remain disabled",
    "maximum_cgroup_memory_bytes": 16 * 1024**3,
    "maximum_process_tree_rss_bytes": 14 * 1024**3,
    "maximum_sample_gap_seconds": 15.0, "require_bounded_cgroup": True,
    "require_zero_oom_kills": True, "require_zero_swap_io": False}})


def sources():
    return sorted(set([SELF, *tree.sources(), *adapter.source_paths()]))


def accepted_predecessor(path):
    """Use old commitments, never bless freshly observed replacement bytes."""
    accepted, pin = data.stable_record(path)
    require(accepted.get("kind") == "spikeids_v5_tree_postrun_acceptance" and
            type(accepted.get("schema")) is int and accepted["schema"] == 1 and
            accepted.get("passed") is True and accepted.get("unresolved_tree_blockers") == [] and
            type(accepted.get("owner_observed_service_return_code")) is int and
            accepted["owner_observed_service_return_code"] == 0,
            "Tree post-run acceptance did not pass")
    pins = dict(accepted["review_evidence"])
    research.merge_pins(pins, {str(path): pin})
    data.assert_snapshots(pins)
    plans = [Path(p) for p in pins if Path(p).name == "plan.json"]
    require(len(plans) == 1, "Ambiguous accepted tree controller plan")
    previous, previous_pin = data.stable_record(plans[0])
    complete_path = plans[0].parent / "complete.json"
    done, done_pin = data.stable_record(complete_path)
    require(previous.get("kind") == "spikeids_v5_tree_stage_plan" and
            done.get("kind") == "spikeids_v5_tree_stage_complete" and done.get("passed") is True and
            done.get("scope") == tree.SCOPE and
            previous["content_sha256"] == done["plan_sha256"] == accepted["plan_sha256"] and
            accepted["controller_completion_sha256"] == done["content_sha256"] and
            accepted["tree_plan_sha256"] == done["tree_plan_sha256"] and
            not (complete_path.parent / "failed.json").exists(), "Tree predecessor identity changed")
    require(previous_pin["sha256"] == accepted["input_plan_file_sha256"] and
            equal(accepted["tree_artifact_boundary"], done["artifact_boundary"]) and
            equal(accepted["unchanged_neural_boundary"], previous["neural_boundary"]),
            "Accepted predecessor boundaries differ")
    research.merge_pins(pins, {str(plans[0]): previous_pin, str(complete_path): done_pin})
    research.merge_pins(pins, previous["input_pins"])
    research.merge_pins(pins, done["consumed_evidence"])
    formal, historical = tree.predecessor(Path(previous["completion"]), Path(previous["neural_run"]))
    research.merge_pins(pins, historical)
    boundaries = [accepted["unchanged_neural_boundary"], accepted["tree_artifact_boundary"]]
    require([b["root"] for b in boundaries] == [previous["neural_run"], previous["tree_run"]],
            "Predecessor roots differ")
    for boundary in boundaries:
        research.assert_boundary(boundary)
        research.merge_pins(pins, boundary["pins"])
    data.assert_snapshots(pins)
    return formal, previous["neural_run"], pins, boundaries


def review_gate(path, acceptance_path):
    review, captured = data.stable_record(path)
    current_sources = {str(p): snapshot(p) for p in sources()}
    require(review.get("kind") == "spikeids_v5_export_launch_review" and
            type(review.get("schema")) is int and review["schema"] == 1 and
            review.get("passed") is True and review.get("unresolved_export_blockers") == [] and
            review.get("predecessor") == {"path": str(acceptance_path),
                "sha256": snapshot(acceptance_path)["sha256"]} and
            review.get("sources") == {p: v["sha256"] for p, v in current_sources.items()},
            "Review does not authorize this exact export implementation/predecessor")
    reviews, tests = review.get("reviews"), review.get("tests")
    require(isinstance(reviews, list) and len(reviews) == len(ROLES) and
            {r.get("role") for r in reviews} == ROLES and isinstance(tests, list) and len(tests) >= 2,
            "Independent reviews and full/focused regressions are required")
    pins = {str(path): captured, **current_sources}
    seen = set()
    for row in [*reviews, *tests, *review.get("supporting_evidence", [])]:
        target = Path(row["path"])
        require(target.is_absolute() and str(target) not in seen, "Duplicate/nonabsolute review evidence")
        captured = snapshot(target)
        require(captured["sha256"] == row.get("sha256"), "Review evidence changed")
        if row in tests:
            require(type(row.get("tests")) is int and row["tests"] == tree.junit_check(target) and
                    type(row.get("observed_exit_code")) is int and row["observed_exit_code"] == 0,
                    "Test count, no-skip gate, or actual exit differs")
        seen.add(str(target)); pins[str(target)] = captured
    require(max(r["tests"] for r in tests) >= 901, "Complete regression evidence is missing")
    data.assert_snapshots(pins)
    return review, pins


def freeze(args):
    accepted_path, review_path, exposure = (Path(value).absolute() for value in
        (args.tree_acceptance, args.review_record, args.prior_exposure))
    work, output = data.new_path(args.work_dir), data.new_path(args.export_root)
    require(work.parent == output.parent == ROOT / "results", "Stage roots must be canonical results children")
    require(re.fullmatch(r"spikeids-v5-export-[A-Za-z0-9_-]+\.service", args.service_unit) and
            research.unit_status(args.service_unit)["LoadState"] == "not-found", "Service is not fresh")
    temp = research.temporary_runtime(Path(args.tmp_dir).absolute(), fresh=True)
    require({k: os.environ.get(k) for k in ENVIRONMENT} == ENVIRONMENT, "Set thread/hash environment before startup")
    formal, neural, pins, boundaries = accepted_predecessor(accepted_path)
    _, reviewed = review_gate(review_path, accepted_path)
    research.merge_pins(pins, reviewed)
    for path in (exposure, Path(sys.executable).resolve()):
        research.merge_pins(pins, {str(path): snapshot(path)})
    legacy.validate_prior_exposure(exposure, formal)
    data.nonoverlap([work, output, Path(neural), Path(boundaries[1]["root"]), review_path.parent])
    require(shutil.disk_usage(ROOT).free >= research.FLOOR_BYTES, "Disk reserve insufficient")
    current = {"schema": 1, "kind": "spikeids_v5_export_stage_plan", "scope": SCOPE,
        "plan_path": str(work / "plan.json"), "work_dir": str(work), "export_root": str(output),
        "neural_run": neural, "tree_acceptance": str(accepted_path), "review_record": str(review_path),
        "prior_exposure": str(exposure), "service_unit": args.service_unit,
        "python": sys.executable, "python_realpath": str(Path(sys.executable).resolve()),
        "python_version": sys.version, "runtime": tree.runtime(), "boot_id": data.boot_id(),
        "environment": ENVIRONMENT, "temporary_runtime": temp, "input_pins": pins,
        "predecessor_boundaries": boundaries, "resource_plan": RESOURCE_PLAN,
        "protocol": legacy.fixed_export_protocol(), "formal_plan_sha256": formal["content_sha256"],
        "automatic_retry": False, "outcome_policy": "scientific negatives retained; infrastructure stops immediately",
        "created_at": data.utc_now()}
    data.assert_snapshots(pins)
    for boundary in boundaries:
        research.assert_boundary(boundary, full=False)
    work.mkdir(mode=0o700)
    data.write_new(work / "plan.json", seal(current))
    return {"plan": str(work / "plan.json"), "passed": True, "no_export_attempt_started": True}


def check_inputs(plan, *, full):
    require(plan.get("scope") == SCOPE and plan.get("automatic_retry") is False and
            equal(plan.get("protocol"), legacy.fixed_export_protocol()) and
            equal(plan.get("resource_plan"), RESOURCE_PLAN), "Fixed export policy changed")
    require(plan.get("runtime") == tree.runtime() and plan.get("python_version") == sys.version and
            plan.get("python") == sys.executable and plan.get("python_realpath") == str(Path(sys.executable).resolve()) and
            plan.get("boot_id") == data.boot_id(), "Runtime/boot changed; no adoption")
    require(plan.get("environment") == ENVIRONMENT and
            {k: os.environ.get(k) for k in ENVIRONMENT} == ENVIRONMENT, "Thread/hash environment changed")
    require(equal(plan["temporary_runtime"], research.temporary_runtime(Path(plan["temporary_runtime"]["path"]))),
            "Temporary runtime changed")
    formal = tree.evidence.read_plan(Path(plan["neural_run"]))
    require(formal["content_sha256"] == plan["formal_plan_sha256"], "Neural identity changed")
    data.assert_snapshots(plan["input_pins"], full=full)
    for boundary in plan["predecessor_boundaries"]:
        research.assert_boundary(boundary, full=False)
    require(shutil.disk_usage(ROOT).free >= research.FLOOR_BYTES, "Disk reserve exhausted")


def load_plan(path):
    plan, pin = data.stable_record(path)
    require(plan.get("kind") == "spikeids_v5_export_stage_plan" and type(plan.get("schema")) is int and
            plan["schema"] == 1 and plan.get("plan_path") == str(path), "Wrong stage plan")
    for key in ("plan_path", "work_dir", "export_root", "neural_run", "tree_acceptance", "review_record", "prior_exposure"):
        target = Path(plan[key])
        require(target.is_absolute() and target.resolve() == target, "Noncanonical stage path")
    work, output = Path(plan["work_dir"]), Path(plan["export_root"])
    require(path == work / "plan.json" and work.parent == output.parent == ROOT / "results" and
            re.fullmatch(r"spikeids-v5-export-[A-Za-z0-9_-]+\.service", plan["service_unit"]), "Wrong stage namespace")
    formal, neural, expected, boundaries = accepted_predecessor(Path(plan["tree_acceptance"]))
    _, reviewed = review_gate(Path(plan["review_record"]), Path(plan["tree_acceptance"]))
    research.merge_pins(expected, reviewed)
    for target in (Path(plan["prior_exposure"]), Path(sys.executable).resolve()):
        research.merge_pins(expected, {str(target): snapshot(target)})
    require(neural == plan["neural_run"] and formal["content_sha256"] == plan["formal_plan_sha256"] and
            equal(boundaries, plan["predecessor_boundaries"]) and equal(expected, plan["input_pins"]),
            "Stage omitted or changed mandatory predecessor/review/source pins")
    legacy.validate_prior_exposure(Path(plan["prior_exposure"]), formal)
    data.nonoverlap([work, output, Path(neural), Path(boundaries[1]["root"]), Path(plan["review_record"]).parent])
    check_inputs(plan, full=True)
    data.assert_snapshots({str(path): pin})
    return plan, pin


def controller(plan):
    actual = research.unit_status(plan["service_unit"])
    identity = data.process_identity(os.getpid())
    require(actual["LoadState"] == "loaded" and actual["ActiveState"] == "active" and
            actual["Type"] == "exec" and actual["Restart"] == "no" and actual["RemainAfterExit"] == "no" and
            actual["KillMode"] == "control-group" and int(actual["MainPID"]) == os.getpid() and
            actual["MemoryMax"] == str(data.MEMORY_BYTES) and actual["MemorySwapMax"] == "0" and
            re.fullmatch("[0-9a-f]{32}", actual["InvocationID"]), "Wrong aggregate cgroup/service identity")
    require(identity is not None and identity["cgroup"] == actual["ControlGroup"] and
            identity["cmdline"] == [plan["python"], str(SELF), "run", "--plan", plan["plan_path"]] and
            identity["cwd"] == str(ROOT) and identity["exe"] == plan["python_realpath"], "Wrong controller process")
    return {"service": actual, "process": identity}


def child_run(plan, export_plan, dataset, model, mode, *, replay=False):
    key = f"{dataset}_{model}_{mode}" + ("_replay" if replay else "")
    folder = Path(plan["work_dir"]) / "attempts"
    folder.mkdir(exist_ok=True)
    log = folder / f"{key}.log"
    command = adapter.worker_invocation(Path(plan["export_root"]), dataset, model, mode, replay=replay)
    started = time.perf_counter()
    with log.open("xb") as stream:
        result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False)
        stream.flush(); os.fsync(stream.fileno())
    elapsed = time.perf_counter() - started
    captured = snapshot(log)
    receipt = folder / f"{key}_exit.json"
    data.write_new(receipt, seal({"schema": 1, "kind": "observed_export_worker_exit",
        "controller_plan_sha256": plan["content_sha256"], "export_plan_sha256": export_plan["content_sha256"],
        "actual_os_command": command, "actual_return_code": result.returncode,
        "elapsed_seconds": elapsed, "replay": replay, "log": {"path": str(log), **captured},
        "finished_at": data.utc_now()}))
    pins = {str(log): captured, str(receipt): snapshot(receipt)}
    # Save the actual OS result even if the worker died before its own receipt.
    worker_pins = adapter.validate_worker_receipt(Path(plan["export_root"]), dataset, model, mode,
                                                   result.returncode, replay=replay)
    research.merge_pins(pins, worker_pins)
    return result.returncode, elapsed, command, pins


def inventory_from_boundary(boundary):
    root = Path(boundary["root"])
    require(all(Path(name).parent == Path(".") for name in boundary["files"]), "Unexpected nested export payload")
    return {name: boundary["pins"][str(root / name)]["sha256"] for name in boundary["files"]}


def assert_output_inventory(root, pins):
    """No late additions may enter the completion by a fresh full-tree hash."""
    root = Path(root)
    require(root.is_absolute() and root.resolve() == root and root.is_dir(), "Noncanonical export root")
    expected = {str(Path(p).relative_to(root)) for p in pins if Path(p).is_relative_to(root)}
    directories = {"."}
    for name in expected:
        directories.update(str(p) for p in Path(name).parents)
    actual, actual_dirs = set(), set()
    for parent, children, files in os.walk(root, followlinks=False):
        directory = Path(parent)
        require(not directory.is_symlink() and directory.resolve() == directory, "Aliased export directory")
        actual_dirs.add(str(directory.relative_to(root)))
        for child in children:
            require(not (directory / child).is_symlink(), "Aliased child export directory")
        for name in files:
            path = directory / name
            value = path.lstat()
            require(stat.S_ISREG(value.st_mode) and value.st_nlink == 1, "Nonregular/aliased export artifact")
            actual.add(str(path.relative_to(root)))
    require(actual == expected and actual_dirs == directories, "Unplanned export artifact/directory inventory")


def verify_one(plan, export_plan, formal, dataset, model, mode, child_code, command, health):
    """Capture BEFORE validation; a later read must never replace these pins."""
    output = Path(plan["export_root"]) / dataset / model / mode
    require(output.is_dir(), "Worker did not produce a complete/failed attempt directory")
    before = research.artifact_boundary(output)
    inventory = inventory_from_boundary(before)
    require("runner_validation.json" not in inventory, "Attempt already has validation; no adoption")
    extras, pins = [], {}
    if type(child_code) is int and child_code == 0:
        require("export_report.json" in inventory and "FAILED.json" not in inventory, "Contradictory success artifacts")
        audit_dir = Path(plan["export_root"]) / "independent_audits" / dataset / model / mode
        with adapter.scoped_runtime(export_plan):
            checked = science.validate_attempt(run_dir=Path(plan["neural_run"]), output_dir=output,
                plan=formal, dataset=dataset, model=model, mode=mode, validation_samples=1024,
                calibration_samples=1000, int8_max_disagreement=0.01, audit_dir=audit_dir)
        require(checked.get("publication_gate") is True and checked.get("status") == "independently_validated" and
                checked.get("export_plan_sha256") == export_plan["content_sha256"] and
                (checked.get("dataset"), checked.get("model"), checked.get("mode")) == (dataset, model, mode),
                "Independent scientific validator did not accept this exact attempt")
        scientific = checked["scientific_adapter"]
        audit_boundary = research.artifact_boundary(audit_dir)
        require(scientific.get("audit_dir") == str(audit_dir) and
                scientific.get("source_sha256") == snapshot(Path(science.__file__))["sha256"] and
                scientific.get("files_sha256") == inventory_from_boundary(audit_boundary) and
                scientific.get("report") == str(audit_dir / "scientific_validation.json") and
                scientific.get("report_sha256") == scientific["files_sha256"]["scientific_validation.json"],
                "Scientific replay evidence changed after its validation")
        extras.append(audit_boundary)
        passed = True
    else:
        original = legacy.scientific_failure(output, export_plan, dataset, model, mode, child_code)
        research.assert_boundary(before)
        health()
        rc, _, replay_command, replay_pins = child_run(plan, export_plan, dataset, model, mode, replay=True)
        research.merge_pins(pins, replay_pins)
        replay_dir = Path(plan["export_root"]) / "replays" / dataset / model / mode
        require(type(rc) is int and rc == child_code == 1, "Failure replay changed return code or succeeded")
        reproduced_boundary = research.artifact_boundary(replay_dir)
        reproduced = legacy.scientific_failure(replay_dir, export_plan, dataset, model, mode, rc)
        require(equal(original, reproduced) and inventory_from_boundary(reproduced_boundary) == inventory,
                "Failure replay differs in identity, exact diagnostics, or graph/policy bytes")
        research.assert_boundary(reproduced_boundary)
        extras.append(reproduced_boundary)
        checked = {"schema": 1, "status": "export_subprocess_failed", "publication_gate": False,
            "source_plan_sha256": formal["content_sha256"], "export_plan_sha256": export_plan["content_sha256"],
            "dataset": dataset, "model": model, "mode": mode, "return_code": child_code,
            "failure_classification": "reproduced_scientific_gate", "failure_file": "FAILED.json",
            "failure_file_sha256": inventory["FAILED.json"], "failure_replay_error": None,
            "failure_replay": {"kind": "exact_scientific_failure_replay", "passed": True,
                "export_plan_sha256": export_plan["content_sha256"], "failure_sha256": inventory["FAILED.json"],
                "output_files_sha256": inventory, "retained_directory": str(replay_dir),
                "actual_os_command": replay_command, "actual_return_code": rc}}
        passed = False
    research.assert_boundary(before)
    health()
    # Never fresh-rebind bytes after validation. Existing commitment survives.
    evidence_path = output / "runner_validation.json"
    data.write_new(evidence_path, seal({**checked, "tool_provenance": export_plan["tool_provenance"],
        "exporter_invocation": command, "output_files_sha256": inventory,
        "prevalidation_artifact_boundary": before}))
    research.assert_boundary(before, ("runner_validation.json",))
    research.merge_pins(pins, before["pins"])
    research.merge_pins(pins, {str(evidence_path): snapshot(evidence_path)})
    final = {**before, "files": sorted([*before["files"], "runner_validation.json"]),
             "pins": {**before["pins"], str(evidence_path): pins[str(evidence_path)]}}
    research.assert_boundary(final)
    for boundary in extras:
        research.merge_pins(pins, boundary["pins"])
    return passed, final, extras, pins


def summary_for(export_plan, rows):
    expected = [(d, m, q) for d, m in legacy.JOBS for q in ("fp32", "qdq")]
    require([(r["dataset"], r["model"], r["mode"]) for r in rows] == expected and
            all(type(r["passed"]) is bool and type(r["return_code"]) is int and
                r["return_code"] == (0 if r["passed"] else 1) for r in rows), "Matrix is incomplete/unclassified")
    counts = {mode: sum(r["passed"] for r in rows if r["mode"] == mode) for mode in ("fp32", "qdq")}
    return seal({"schema": 1, "kind": "spikeids_v5_external_export_matrix_summary",
        "source_plan_sha256": export_plan["source_plan_sha256"], "export_plan_sha256": export_plan["content_sha256"],
        **{k: export_plan["protocol"][k] for k in ("deployment_seed", "fold_bn", "fp32_atol", "fp32_rtol",
            "fp32_max_prediction_disagreement", "int8_max_prediction_disagreement", "validation_samples", "calibration_samples")},
        "attempts": rows, "fp32_passed": counts["fp32"], "qdq_passed": counts["qdq"],
        "fp32_total": 11, "qdq_total": 11, "all_gates_passed": counts["fp32"] == counts["qdq"] == 11,
        "matrix_execution_complete": True, "tool_provenance": export_plan["tool_provenance"],
        "scope": "sampled CPU ONNX parity; not NPU, board, latency or energy",
        "exit_semantics": "controller 0 means matrix execution complete; parity failures remain failures"})


def run(path):
    plan, plan_pin = load_plan(path)
    work, output = Path(plan["work_dir"]), Path(plan["export_root"])
    require(set(work.iterdir()) == {path}, "Stage already started or contains unplanned prior evidence")
    owner = controller(plan)
    data.new_path(output)
    data.write_new(work / "run_started.json", seal({"plan_sha256": plan["content_sha256"],
        "controller": owner, "started_at": data.utc_now()}))
    pins = dict(plan["input_pins"])
    research.merge_pins(pins, {str(path): plan_pin,
        str(work / "run_started.json"): snapshot(work / "run_started.json")})
    boundaries, rows = [], []
    initial_oom, initial_cgroup = research.host_oom(), data.cgroup_sample(owner["process"]["cgroup"])
    stage = "register_fixed_matrix"
    try:
        data.check_resources(initial_cgroup)
        formal = tree.evidence.read_plan(Path(plan["neural_run"]))
        provenance = adapter.make_provenance([sys.executable, *sys.argv], {
            "run_dir": plan["neural_run"], "output_root": str(output), "controller_plan": str(path)})
        export_plan = adapter.build_plan(Path(plan["neural_run"]), output,
            Path(plan["prior_exposure"]), path, provenance)
        adapter.register(export_plan)
        require(equal(adapter.load_plan(output, formal), export_plan), "Registration differs before attempt 1")
        export_pin = snapshot(output / "export_plan.json")
        research.merge_pins(pins, {str(output / "export_plan.json"): export_pin})
        research.merge_pins(pins, adapter.registration_pins(export_plan))
        assert_output_inventory(output, pins)
        telemetry_plan = seal({**{k: v for k, v in RESOURCE_PLAN.items() if k != "content_sha256"},
            "controller_plan_sha256": plan["content_sha256"], "export_plan_sha256": export_plan["content_sha256"],
            "controller": owner})
        data.write_new(work / "telemetry_plan.json", telemetry_plan)
        research.merge_pins(pins, {str(work / "telemetry_plan.json"): snapshot(work / "telemetry_plan.json")})
        with tree.suite.resource_monitor(work, "run", telemetry_plan) as resource_health:
            def health():
                resource_health()
                check_inputs(plan, full=False)
                data.assert_snapshots(pins, full=False)
                for boundary in boundaries:
                    research.assert_boundary(boundary, full=False)
                require(equal(adapter.load_plan(output, formal, rehash=False), export_plan), "Export registration changed")
                require(data.process_identity(os.getpid()) == owner["process"] and research.host_oom() == initial_oom,
                        "Controller identity or host OOM changed")
            for dataset, model in legacy.JOBS:
                for mode in ("fp32", "qdq"):
                    stage = f"{dataset}/{model}/{mode}"
                    health()
                    assert_output_inventory(output, pins)
                    print(json.dumps({"stage": stage, "status": "starting", "time": data.utc_now()}), flush=True)
                    code, elapsed, command, child_pins = child_run(plan, export_plan, dataset, model, mode)
                    research.merge_pins(pins, child_pins)
                    health()
                    passed, boundary, extra, validated_pins = verify_one(plan, export_plan, formal,
                        dataset, model, mode, code, command, health)
                    research.merge_pins(pins, validated_pins)
                    boundaries.extend([boundary, *extra])
                    assert_output_inventory(output, pins)
                    evidence_path = Path(boundary["root"]) / "runner_validation.json"
                    log = work / "attempts" / f"{dataset}_{model}_{mode}.log"
                    rows.append({"dataset": dataset, "model": model, "mode": mode, "passed": passed,
                        "return_code": code, "elapsed_seconds": elapsed, "export_plan_sha256": export_plan["content_sha256"],
                        "output_dir": f"{dataset}/{model}/{mode}", "evidence": str(evidence_path.relative_to(output)),
                        "evidence_sha256": pins[str(evidence_path)]["sha256"],
                        "log": str(log), "log_sha256": pins[str(log)]["sha256"]})
                    health()
                    print(json.dumps({"stage": stage, "parity_passed": passed,
                                      "classified_outcomes": len(rows)}), flush=True)
        stage = "final_closure"
        resource_pins = {str(p): snapshot(p) for p in sorted(work.glob("resource_*"))}
        resources = tree.resource_evidence.validate_resource_reports(work, telemetry_plan)
        require(set(resource_pins) == {str(p) for p in resources}, "Resource inventory differs")
        research.merge_pins(pins, resource_pins)
        require(equal(adapter.load_plan(output, formal), export_plan), "Final export plan changed")
        for boundary in boundaries:
            research.assert_boundary(boundary)
        data.assert_snapshots(pins)
        check_inputs(plan, full=True)
        assert_output_inventory(output, pins)
        assert_output_inventory(work, pins)
        final_before = research.artifact_boundary(output)
        research.merge_pins(pins, final_before["pins"])
        summary = summary_for(export_plan, rows)
        data.write_new(output / "summary.json", summary)
        research.assert_boundary(final_before, ("summary.json",))
        final = {**final_before, "files": sorted([*final_before["files"], "summary.json"]),
            "pins": {**final_before["pins"], str(output / "summary.json"): snapshot(output / "summary.json")}}
        research.merge_pins(pins, final["pins"])
        data.assert_snapshots(pins)
        check_inputs(plan, full=False)
        require(set(work.glob("resource_*")) == set(resources), "Late resource inventory mutation")
        final_cgroup, final_oom = data.cgroup_sample(owner["process"]["cgroup"]), research.host_oom()
        data.check_resources(final_cgroup)
        require(final_oom == initial_oom and controller(plan)["process"] == owner["process"], "Late OOM/process mutation")
        research.assert_boundary(final, full=False)
        for boundary in plan["predecessor_boundaries"]:
            research.assert_boundary(boundary, full=False)
        data.assert_snapshots(pins, full=False)
        assert_output_inventory(output, pins)
        assert_output_inventory(work, pins)
        complete = seal({"schema": 1, "kind": "spikeids_v5_export_stage_complete", "passed": True,
            "scope": SCOPE, "plan_sha256": plan["content_sha256"], "export_plan_sha256": export_plan["content_sha256"],
            "matrix_execution_complete": True, "all_parity_gates_passed": summary["all_gates_passed"],
            "controller": owner, "initial_cgroup": initial_cgroup, "final_cgroup": final_cgroup,
            "initial_host_oom_kill": initial_oom, "final_host_oom_kill": final_oom,
            "artifact_boundary": final, "consumed_evidence": pins, "resource_evidence": resource_pins,
            "telemetry_plan_sha256": telemetry_plan["content_sha256"],
            "operating_system_exit_code": None, "finished_at": data.utc_now(),
            "exit_observation": "Owner must separately observe the actual service exit.",
            "requires_postrun_adversarial_review": True,
            "not_accepted": ["publication", "release", "board_deployment", "NPU_placement", "energy"]})
        data.write_new(work / "complete.json", complete)
        print(json.dumps({"stage": "complete", "matrix_execution_complete": True,
                          "all_parity_gates_passed": summary["all_gates_passed"]}), flush=True)
        return complete
    except BaseException as exc:
        data.write_new(work / "failed.json", seal({"schema": 1, "kind": "spikeids_v5_export_stage_failure",
            "plan_sha256": plan["content_sha256"], "stage": stage, "passed": False, "error": repr(exc),
            "classified_attempts": rows, "unexecuted_matrix_entries_are_not_successes": True,
            "automatic_retry": False, "finished_at": data.utc_now()}))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="action", required=True)
    frozen = sub.add_parser("freeze", allow_abbrev=False)
    for name in ("tree-acceptance", "review-record", "prior-exposure", "work-dir", "export-root", "tmp-dir"):
        frozen.add_argument("--" + name, required=True, type=Path)
    frozen.add_argument("--service-unit", required=True)
    execution = sub.add_parser("run", allow_abbrev=False)
    execution.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args()
    if args.action == "freeze":
        print(json.dumps(freeze(args)), flush=True)
    else:
        run(args.plan.absolute())


if __name__ == "__main__":
    main()
