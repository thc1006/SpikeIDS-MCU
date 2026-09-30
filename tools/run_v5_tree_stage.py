#!/usr/bin/env python3
"""One-shot tree phase after an explicit post-run and adapter review.

All processes share ONE 16-GiB/no-swap service cgroup. The original neural
inputs stay immutable. A completion record is not an observed service exit;
the launching owner must separately observe the actual systemd-run exit.
No export-matrix, manuscript, release, retry, adoption, or reboot continuation.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "spikeids_v5")]
from tools import continue_v5_data_phase as data
from tools import continue_v5_research as research
from tools import tree_v5_runtime as adapter
import contracts
import evidence
import resource_evidence
import suite

require, seal = contracts.require, contracts.seal
SELF = Path(__file__).resolve()
PACKAGES = ("numpy", "pandas", "pyarrow", "torch", "scikit-learn", "scipy",
            "statsmodels", "joblib", "xgboost", "onnx", "onnxruntime", "skl2onnx")
ENVIRONMENT = {"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "16", "OPENBLAS_NUM_THREADS": "1",
               "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"}
REVIEW_ROLES = {"postrun_lifecycle", "postrun_science", "tree_preflight", "tree_controller"}
SCOPE = "formal_84_tree_fits_evaluation_rf_onnx_and_independent_verification"


def sources():
    # Include the complete local helper closure, not just the two new entrypoints.
    return (SELF, *(ROOT / "tools" / name for name in (
        "tree_v5_runtime.py", "continue_v5_data_phase.py", "continue_v5_research.py",
        "qualify_v5_performance.py", "v5_retention.py", "verify_v5_data.py",
        "verify_v5_neural.py", "verify_v5_tree.py")))


def runtime():
    return {name: importlib.metadata.version(name) for name in PACKAGES}


def binding_for(review_path, complete_path, review):
    return {"kind": "reviewed_tree_execution_adapter", "schema": 1,
            "sources": {str(p): snapshot(p)["sha256"] for p in sources()},
            "review": {"path": str(review_path), "sha256": snapshot(review_path)["sha256"],
                       "content_sha256": review["content_sha256"]},
            "completion": {"path": str(complete_path), "sha256": snapshot(complete_path)["sha256"]},
            "policy": adapter.adapter_policy()}


def snapshot(path):
    return data.evidence._file_snapshot(Path(path))


def record(path):
    return data.stable_record(Path(path))[0]


def equal(left, right):
    return contracts.json_bytes(left) == contracts.json_bytes(right)


def junit_check(path):
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    require(cases and all(not list(case.iter("failure")) and
                         not list(case.iter("error")) and
                         not list(case.iter("skipped")) for case in cases),
            "Review tests contain a failure, error, skip, or no test cases")
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    require(suites and all(int(item.get(field, "0")) == 0
                           for item in suites for field in ("failures", "errors", "skipped")),
            "Review JUnit summary failed")
    return len(cases)


def review_gate(path, complete_path):
    value, captured_review = data.stable_record(path)
    reviewed_sources = {str(p): snapshot(p) for p in sources()}
    require(value.get("kind") == "spikeids_v5_postrun_tree_launch_review" and
            type(value.get("schema")) is int and value["schema"] == 1 and
            value.get("passed") is True and value.get("unresolved_tree_blockers") == [] and
            value.get("completion") == {"path": str(complete_path),
                                         "sha256": snapshot(complete_path)["sha256"]} and
            value.get("sources") == {p: pin["sha256"] for p, pin in reviewed_sources.items()},
            "Post-run/adapter review does not authorize this exact tree implementation")
    pins = {str(path): captured_review, **reviewed_sources}
    tests, reviews = value.get("tests"), value.get("reviews")
    supporting = value.get("supporting_evidence", [])
    require(isinstance(tests, list) and len(tests) >= 2 and
            isinstance(reviews, list) and len(reviews) == len(REVIEW_ROLES) and
            isinstance(supporting, list) and
            {row.get("role") for row in reviews if isinstance(row, dict)} == REVIEW_ROLES,
            "Full regression, adapter/controller tests and independent reviews are required")
    seen = set()
    for row in [*tests, *reviews, *supporting]:
        require(isinstance(row, dict) and isinstance(row.get("path"), str),
                "Invalid review evidence row")
        target = Path(row["path"])
        require(target.is_absolute() and str(target) not in seen,
                "Repeated/non-absolute review evidence")
        captured = snapshot(target)
        require(captured["sha256"] == row.get("sha256"), "Review evidence changed")
        if row in tests:
            require(type(row.get("tests")) is int and row["tests"] == junit_check(target),
                    "Review test case count differs")
            require(type(row.get("observed_exit_code")) is int and
                    row["observed_exit_code"] == 0, "Review lacks owner-observed successful test exit")
        seen.add(str(target)); pins[str(target)] = captured
    require(max(item["tests"] for item in tests) >= 859, "Full regression coverage is missing")
    data.assert_snapshots(pins)
    return value, pins


def inherited_source_pins(complete_path, completed, formal):
    """Preserve historical source commitments, not freshly accepted current bytes."""
    research_path = complete_path.parent / "plan.json"
    previous, previous_pin = data.stable_record(research_path)
    require(equal(completed["consumed_evidence"].get(str(research_path)), previous_pin) and
            previous.get("kind") == "spikeids_v5_research_continuation_plan" and
            previous.get("content_sha256") == completed.get("plan_sha256"),
            "Historical research source commitments are not bound to completion")
    data_path = Path(previous["data_plan"])
    original, original_pin = data.stable_record(data_path)
    require(equal(previous.get("data_plan_snapshot"), original_pin) and
            original.get("content_sha256") == previous.get("data_plan_sha256") and
            original.get("kind") == "spikeids_v5_data_continuation_plan",
            "Historical data source commitments changed")
    pins = {str(research_path): previous_pin, str(data_path): original_pin}
    for old_plan in (previous, original):
        for value, committed in old_plan["pins"].items():
            path = Path(value)
            if path.suffix == ".py":
                require(path.is_absolute() and path.resolve() == path and
                        path.is_relative_to(ROOT), "Foreign historical source commitment")
                research.merge_pins(pins, {value: committed})
    require(set(formal["sources"]) == {p.name for p in (ROOT / "spikeids_v5").glob("*.py")},
            "Frozen scientific source inventory changed")
    for name, digest in formal["sources"].items():
        value = str(ROOT / "spikeids_v5" / name)
        require(value in pins and pins[value]["sha256"] == digest,
                "Scientific source lacks its original commitment")
    for path in sources()[2:-1]:
        require(str(path) in pins, "Existing helper lacks its historical source commitment")
    data.assert_snapshots(pins)
    return pins


def predecessor(complete_path, neural_run):
    completed, captured_complete = data.stable_record(complete_path)
    require(completed.get("kind") == "spikeids_v5_research_continuation_complete" and
            completed.get("passed") is True and
            completed.get("terminal_scope") == "independently_verified_neural_and_statistics" and
            not (complete_path.parent / "failed.json").exists(),
            "Neural predecessor is incomplete or failed")
    formal = evidence.read_plan(neural_run)
    require(completed.get("formal_plan_sha256") == formal["content_sha256"] and
            formal.get("seeds") == list(range(20)) and len(formal.get("jobs", [])) == 11 and
            formal.get("protocol_role") == "planned_benchmark", "Wrong formal neural predecessor")
    independent, captured_independent = data.stable_record(neural_run / "independent_verification.json")
    require(independent.get("passed") is True and
            independent.get("plan_sha256") == formal["content_sha256"] and
            all(type(independent.get(key)) is int and independent[key] == count
                for key, count in (("checkpoints_checked", 440),
                                   ("prediction_artifacts_checked", 440), ("executions_checked", 22))),
            "Independent neural coverage is incomplete")
    pins = dict(completed["consumed_evidence"])
    require(str(neural_run / "plan.json") in pins and
            str(neural_run / "independent_verification.json") in pins,
            "Completion lacks mandatory neural commitments")
    research.merge_pins(pins, {str(complete_path): captured_complete,
                             str(neural_run / "independent_verification.json"): captured_independent})
    research.merge_pins(pins, inherited_source_pins(complete_path, completed, formal))
    data.assert_snapshots(pins)
    return formal, pins


def freeze(args):
    neural_run, complete_path, review_path = (Path(args.neural_run).absolute(),
                                            Path(args.completion).absolute(),
                                            Path(args.review_record).absolute())
    work, tree = data.new_path(Path(args.work_dir)), data.new_path(Path(args.tree_run))
    data.nonoverlap([work, tree, neural_run, complete_path.parent, review_path.parent])
    require(re.fullmatch(r"spikeids-v5-tree-[A-Za-z0-9_-]+\.service", args.service_unit),
            "Invalid tree service unit")
    require(research.unit_status(args.service_unit)["LoadState"] == "not-found",
            "Tree service already exists")
    require(shutil.disk_usage(ROOT).free >= research.FLOOR_BYTES, "Insufficient disk reserve")
    temp = research.temporary_runtime(Path(args.tmp_dir).absolute(), fresh=True)
    require({key: os.environ.get(key) for key in ENVIRONMENT} == ENVIRONMENT,
            "Explicit tree thread/hash environment must be set before interpreter startup")
    review, review_pins = review_gate(review_path, complete_path)
    formal, pins = predecessor(complete_path, neural_run)
    research.merge_pins(pins, review_pins)
    for target in (*sources(), ROOT / "tools/verify_v5_tree.py"):
        research.merge_pins(pins, {str(target): snapshot(target)})
    binding = binding_for(review_path, complete_path, review)
    cache = Path(formal["data_evidence"]["accepted_cache_root"])
    tree_plan = adapter.build_tree_plan(cache, neural_run, binding)
    boundary = research.artifact_boundary(neural_run)
    research.merge_pins(pins, boundary["pins"])
    current = {"schema": 1, "kind": "spikeids_v5_tree_stage_plan", "scope": SCOPE,
               "plan_path": str(work / "plan.json"), "work_dir": str(work), "tree_run": str(tree),
               "neural_run": str(neural_run), "cache_root": str(cache), "completion": str(complete_path),
               "review_record": str(review_path), "service_unit": args.service_unit,
               "python": sys.executable, "python_realpath": str(Path(sys.executable).resolve()),
               "python_version": sys.version, "runtime": runtime(), "boot_id": data.boot_id(),
               "environment": dict(ENVIRONMENT),
               "temporary_runtime": temp, "adapter_binding": binding, "tree_plan": tree_plan,
               "input_pins": pins, "neural_boundary": boundary,
               "created_at": data.utc_now(), "automatic_retry": False,
               "test_results_must_not_change_fixed_policy": True}
    data.assert_snapshots(pins)
    research.assert_boundary(boundary, full=False)
    work.mkdir(mode=0o700)
    data.write_new(work / "plan.json", seal(current))
    return {"plan": str(work / "plan.json"), "tree_run": str(tree), "passed": True}


def check_inputs(plan, *, full):
    require(plan.get("runtime") == runtime() and plan.get("python_version") == sys.version and
            plan.get("python") == sys.executable and plan.get("python_realpath") == str(Path(sys.executable).resolve()) and
            plan.get("boot_id") == data.boot_id(), "Runtime/boot changed; no adoption or reboot resume")
    require(plan.get("environment") == ENVIRONMENT and
            {key: os.environ.get(key) for key in ENVIRONMENT} == ENVIRONMENT,
            "Frozen tree thread/hash environment changed")
    require(equal(plan["temporary_runtime"], research.temporary_runtime(Path(plan["temporary_runtime"]["path"]))),
            "Temporary runtime identity changed")
    require(plan.get("automatic_retry") is False and plan.get("scope") == SCOPE,
            "Tree execution scope or retry policy changed")
    require(set(plan["tree_plan"]["sources"]) ==
            {p.name for p in (ROOT / "spikeids_v5").glob("*.py")},
            "Scientific source inventory changed during the tree stage")
    data.assert_snapshots(plan["input_pins"], full=full)
    research.assert_boundary(plan["neural_boundary"], full=False)
    require(shutil.disk_usage(ROOT).free >= research.FLOOR_BYTES, "Disk reserve exhausted")


def load_plan(path):
    plan, captured = data.stable_record(path)
    require(plan.get("kind") == "spikeids_v5_tree_stage_plan" and
            type(plan.get("schema")) is int and plan["schema"] == 1 and
            plan.get("plan_path") == str(path), "Wrong tree-stage plan identity")
    check_inputs(plan, full=True)
    validate_plan_contract(plan)
    data.assert_snapshots({str(path): captured})
    return plan, captured


def validate_plan_contract(plan):
    """Reconstruct mandatory commitments; a self-consistent edited seal is insufficient."""
    work, tree, neural_run, completed_path, review_path = (Path(plan[key]) for key in
        ("work_dir", "tree_run", "neural_run", "completion", "review_record"))
    require(Path(plan["plan_path"]) == work / "plan.json" and
            all(p.is_absolute() and p.resolve() == p for p in
                (work, tree, neural_run, completed_path, review_path)) and
            work.parent == tree.parent == ROOT / "results" and
            re.fullmatch(r"spikeids-v5-tree-[A-Za-z0-9_-]+\.service", plan["service_unit"]) and
            plan.get("test_results_must_not_change_fixed_policy") is True,
            "Invalid tree stage paths, service or fixed-policy declaration")
    data.nonoverlap([work, tree, neural_run, completed_path.parent, review_path.parent])
    review, review_pins = review_gate(review_path, completed_path)
    formal, expected = predecessor(completed_path, neural_run)
    research.merge_pins(expected, review_pins)
    for target in (*sources(), ROOT / "tools/verify_v5_tree.py"):
        research.merge_pins(expected, {str(target): snapshot(target)})
    boundary = plan["neural_boundary"]
    require(boundary.get("root") == str(neural_run) and
            len(boundary.get("files", [])) == len(set(boundary.get("files", []))) and
            set(boundary.get("pins", {})) == {str(neural_run / name) for name in boundary["files"]},
            "Incomplete mandatory neural artifact boundary")
    research.assert_boundary(boundary)
    research.merge_pins(expected, boundary["pins"])
    require(equal(expected, plan["input_pins"]), "Mandatory tree-stage input pins are missing or changed")
    binding = binding_for(review_path, completed_path, review)
    require(equal(binding, plan["adapter_binding"]) and
            plan["cache_root"] == formal["data_evidence"]["accepted_cache_root"],
            "Adapter binding or accepted cache root changed")
    preview = adapter.build_tree_plan(Path(plan["cache_root"]), neural_run, binding)
    require(equal(preview, plan["tree_plan"]), "Frozen tree policy differs before fitting or test exposure")


def controller(plan):
    actual = research.unit_status(plan["service_unit"])
    identity = data.process_identity(os.getpid())
    require(actual["LoadState"] == "loaded" and actual["ActiveState"] == "active" and
            actual["Type"] == "exec" and actual["Restart"] == "no" and actual["RemainAfterExit"] == "no" and
            actual["KillMode"] == "control-group" and int(actual["MainPID"]) == os.getpid() and
            actual["MemoryMax"] == str(data.MEMORY_BYTES) and actual["MemorySwapMax"] == "0" and
            re.fullmatch("[0-9a-f]{32}", actual["InvocationID"]), "Incorrect service identity or aggregate resource limits")
    require(identity is not None and identity["cgroup"] == actual["ControlGroup"] and
            identity["cmdline"] == [plan["python"], str(SELF), "run", "--plan", plan["plan_path"]] and
            identity["cwd"] == str(ROOT) and identity["exe"] == plan["python_realpath"],
            "Tree controller process differs from the exact frozen invocation")
    return {"service": actual, "process": identity}


def run(path):
    plan, plan_snapshot = load_plan(path)
    work, tree = Path(plan["work_dir"]), Path(plan["tree_run"])
    owner = controller(plan)
    data.new_path(tree)
    data.write_new(work / "run_started.json", seal({"plan_sha256": plan["content_sha256"],
                   "controller": owner, "started_at": data.utc_now()}))
    inputs = {str(path): plan_snapshot, str(work / "run_started.json"): snapshot(work / "run_started.json")}
    initial_oom = research.host_oom()
    initial_cgroup = data.cgroup_sample(owner["process"]["cgroup"])
    stage = "tree_fit_and_evaluate"
    try:
        data.check_resources(initial_cgroup)
        with suite.resource_monitor(work, "run", plan["tree_plan"]) as resource_health:
            def health():
                resource_health()
                check_inputs(plan, full=False)
                data.assert_snapshots(inputs, full=False)
                require(data.process_identity(os.getpid()) == owner["process"], "Controller identity changed")
                require(research.host_oom() == initial_oom, "Host OOM changed")

            health()
            print(json.dumps({"stage": stage, "status": "starting", "time": data.utc_now()}), flush=True)
            adapter.run_tree(Path(plan["cache_root"]), Path(plan["neural_run"]), tree,
                             plan["adapter_binding"], health)
            require(equal(record(tree / "plan.json"), plan["tree_plan"]), "Actual tree plan differs from frozen preview")
            health()
            validated_models = adapter.validate_models(tree)
            tree_boundary = research.artifact_boundary(tree)
            data.write_new(work / "tree_operation_complete.json", seal({
                "plan_sha256": plan["content_sha256"], "passed": True,
                "execution_mode": "in_process_under_the_recorded_service",
                "operating_system_exit_code": None, "models": validated_models,
                "completed_at": data.utc_now(), "artifact_boundary": tree_boundary}))
            inputs[str(work / "tree_operation_complete.json")] = snapshot(work / "tree_operation_complete.json")
            stage = "independent_tree_verification"
            print(json.dumps({"stage": stage, "status": "starting", "time": data.utc_now()}), flush=True)
            log = work / "independent.log"
            argv = [plan["python"], str(ROOT / "tools/verify_v5_tree.py"), "--tree-run-dir", str(tree),
                    "--neural-run-dir", plan["neural_run"]]
            with log.open("xb") as stream:
                child = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False)
                stream.flush(); os.fsync(stream.fileno())
            log_pin = snapshot(log)
            data.write_new(work / "independent_exit.json", seal({"plan_sha256": plan["content_sha256"],
                           "command": argv, "return_code": child.returncode, "finished_at": data.utc_now(),
                           "log": log_pin}))
            research.merge_pins(inputs, {str(log): log_pin,
                                str(work / "independent_exit.json"): snapshot(work / "independent_exit.json")})
            require(type(child.returncode) is int and child.returncode == 0, "Independent tree verifier failed")
            checked, checked_pin = data.stable_record(tree / "independent_verification.json")
            research.merge_pins(inputs, {str(tree / "independent_verification.json"): checked_pin})
            require(checked.get("kind") == "independent_formal_tree_verification" and
                    checked.get("passed") is True and checked.get("tree_plan_sha256") == plan["tree_plan"]["content_sha256"],
                    "Independent tree verification scope differs")
            research.assert_boundary(tree_boundary, ("independent_verification.json",))
            adapter.validate_models(tree)
            health()
        stage = "final_closure"
        resource_pins = {str(p): snapshot(p) for p in sorted(work.glob("resource_*"))}
        resources = resource_evidence.validate_resource_reports(work, plan["tree_plan"])
        require(set(resource_pins) == {str(p) for p in resources}, "Unexpected or incomplete resource inventory")
        research.merge_pins(inputs, resource_pins)
        data.assert_snapshots(inputs)
        check_inputs(plan, full=True)
        data.assert_snapshots(inputs)
        final_cgroup = data.cgroup_sample(owner["process"]["cgroup"])
        data.check_resources(final_cgroup)
        require(research.host_oom() == initial_oom, "Host OOM changed during full tree phase")
        require(controller(plan)["process"] == owner["process"], "Controller replaced before closure")
        final_tree = research.artifact_boundary(tree)
        require(set(final_tree["files"]) == set(tree_boundary["files"]) | {"independent_verification.json"},
                "Unexpected final tree artifacts")
        research.assert_boundary(tree_boundary, ("independent_verification.json",), full=False)
        data.assert_snapshots(inputs)
        check_inputs(plan, full=False)
        require(set(work.glob("resource_*")) == set(resources), "Resource inventory changed after replay")
        final_cgroup = data.cgroup_sample(owner["process"]["cgroup"])
        data.check_resources(final_cgroup)
        final_oom = research.host_oom()
        require(final_oom == initial_oom, "Host OOM changed at tree publication boundary")
        research.assert_boundary(final_tree, full=False)
        data.assert_snapshots(inputs, full=False)
        result = seal({"schema": 1, "kind": "spikeids_v5_tree_stage_complete", "passed": True,
                       "plan_sha256": plan["content_sha256"], "tree_plan_sha256": plan["tree_plan"]["content_sha256"],
                       "scope": SCOPE, "controller": owner, "initial_cgroup": initial_cgroup,
                       "final_cgroup": final_cgroup, "initial_host_oom_kill": initial_oom,
                       "final_host_oom_kill": final_oom, "artifact_boundary": final_tree,
                       "consumed_evidence": inputs, "resource_evidence": resource_pins,
                       "finished_at": data.utc_now(), "operating_system_exit_code": None,
                       "exit_observation": "The launching owner must separately observe the actual service exit.",
                       "not_accepted": ["neural_export_matrix", "paper", "release", "board_deployment", "energy"]})
        data.write_new(work / "complete.json", result)
        print(json.dumps({"stage": "complete", "passed": True, "receipt": str(work / "complete.json")}), flush=True)
        return result
    except BaseException as exc:
        data.write_new(work / "failed.json", seal({"schema": 1, "kind": "spikeids_v5_tree_stage_failure",
                       "plan_sha256": plan["content_sha256"], "stage": stage, "passed": False,
                       "error": repr(exc), "automatic_retry": False, "finished_at": data.utc_now()}))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="action", required=True)
    frozen = sub.add_parser("freeze", allow_abbrev=False)
    for name in ("neural-run", "completion", "review-record", "work-dir", "tree-run", "tmp-dir"):
        frozen.add_argument("--" + name, type=Path, required=True)
    frozen.add_argument("--service-unit", required=True)
    execution = sub.add_parser("run", allow_abbrev=False)
    execution.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "freeze":
        print(json.dumps(freeze(args)), flush=True)
    else:
        run(args.plan.absolute())


if __name__ == "__main__":
    main()
