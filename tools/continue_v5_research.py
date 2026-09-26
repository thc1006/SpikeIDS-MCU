#!/usr/bin/env python3
"""One-shot reviewed data -> 60+66 fit-only qualification -> 440 neural fits.

Terminal scope: evaluated neural primary/replica and independently checked
statistics. No tree, export, paper, release, hardware, retries, or reboot resume.
Requires a dedicated Type=exec/simple systemd user service with Restart=no.
The non-child data runner's OS exit code is NOT inferred: completion relies on
its original process ending and its bound, actual child exit receipts.
An explicit freeze-recovery action separately permits one fresh full acceptance
after a preserved SIGBUS, with unknown historical parent start ticks disclosed.
Recovery requires a pinned, empty, external NVMe TMPDIR at interpreter startup.
"""
from __future__ import annotations

import argparse
import ast
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "spikeids_v5"))
from tools import continue_v5_data_phase as data
from tools import qualify_v5_performance as qualification
from tools.v5_retention import _inventory
import contracts
import evidence as neural
import resource_evidence
import suite

require, seal = data.require, data.evidence.seal
STAGES = ("validate_data", "profiles", "verify_profiles", "workers", "verify_workers",
          "freeze_formal", "validate_formal", "fit_primary", "fit_replica", "validate_fit",
          "evaluate", "validate_evaluate", "statistics", "equivalence", "independent")
FLOOR_BYTES = 50 * 1024**3
UNAUTOMATED = ["tree_baselines", "export_prior_declaration_and_22_exports", "paper", "release", "hardware"]
PARTIAL_COVERAGE_ERROR = "Resource evidence must cover one full run or all three distinct stages"
UNIT_PROPERTIES = (*data.SCOPE_PROPERTIES, "KillMode", "BindsTo", "After")
SERVICE_PROPERTIES = (*UNIT_PROPERTIES, "MainPID", "Restart", "RemainAfterExit", "Type")
RECOVERY_MODE = "manual_full_acceptance_after_sigbus"


def stages(plan):
    return ("recover_acceptance", *STAGES) if plan.get("mode") == RECOVERY_MODE else STAGES


def data_context(plan):
    """Unsealed invocation parameters; never rewrite/reseal the old data plan."""
    context = dict(record(plan["data_plan"]))
    context.pop("content_sha256")
    if plan.get("mode") == RECOVERY_MODE:
        context["acceptance"] = plan["recovery"]["acceptance"]
    return context


def mount_record(path):
    candidates = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        before, after = line.split(" - ", 1)
        fields, tail = before.split(), after.split()
        mount = Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[4]))
        if path.is_relative_to(mount):
            candidates.append((len(mount.parts), {"mountpoint": str(mount), "device": fields[2],
                                                 "filesystem": tail[0], "source": tail[1]}))
    require(candidates, "Cannot determine temporary filesystem mount")
    return max(candidates, key=lambda item: item[0])[1]


def temporary_runtime(path, *, fresh=False):
    path = Path(path).absolute()
    identity = data.directory_identity(path)
    require(path.resolve() == path and not path.is_relative_to(ROOT) and not path.is_relative_to(Path("/tmp")),
            "Recovery TMPDIR must be canonical, outside repository and /tmp")
    mount = mount_record(path)
    require(mount["filesystem"] not in ("tmpfs", "ramfs") and mount["source"].startswith("/dev/nvme") and
            path.stat().st_dev == ROOT.stat().st_dev, "Recovery TMPDIR must use the workstation NVMe filesystem")
    require(os.environ.get("TMPDIR") == str(path), "Process TMPDIR differs from frozen recovery runtime")
    require(Path(data.tempfile.gettempdir()) == path, "Python temporary-directory cache differs from recovery TMPDIR")
    if fresh:
        require(not any(path.iterdir()), "Recovery TMPDIR must start as a fresh empty directory")
    return {"path": str(path), "identity": identity, "mount": mount, "environment": {"TMPDIR": str(path)}}


def snapshot(path):
    return data.evidence._file_snapshot(Path(path))


def record(path):
    return data.stable_record(Path(path))[0]


def typed_equal(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def merge_pins(target, additions):
    for key, value in additions.items():
        require(key not in target or typed_equal(target[key], value), "A later receipt tried to replace an existing commitment")
        target[key] = value
    return target


def host_oom():
    value = suite._host_sample()["vmstat"]["oom_kill"]
    require(type(value) is int and value >= 0, "Invalid host OOM counter")
    return value


def check_oom(receipt):
    before, after = receipt["initial_host_oom_kill"], receipt["final_host_oom_kill"]
    require(type(before) is int and type(after) is int and before >= 0 and after == before,
            "Host OOM counter changed during research stage")


def artifact_boundary(root):
    """No model deserialization; bind the exact pre-existing scientific bytes."""
    files = _inventory(root)
    directories = sorted(str(Path(directory).relative_to(root)) for directory, _dirs, _files in os.walk(root))
    captured = {str(path): snapshot(path) for path in files.values()}
    require(set(_inventory(root)) == set(files), "Scientific artifact inventory raced its snapshot")
    return {"root": str(root), "files": list(files), "directories": directories, "pins": captured}


def assert_boundary(boundary, additions=(), *, full=True):
    root = Path(boundary["root"])
    require(set(_inventory(root)) == set(boundary["files"]) | set(additions) and
            sorted(str(Path(directory).relative_to(root)) for directory, _dirs, _files in os.walk(root)) == boundary["directories"],
            "Scientific artifact inventory changed outside the stage contract")
    data.assert_snapshots(boundary["pins"], full=full)


def retain_qualifications(plan, commitments):
    """Retain the previously verified selection evidence; never execute a fit."""
    boundaries = []
    for role in ("profiles", "workers"):
        root = Path(plan[f"{role}_dir"])
        boundary = artifact_boundary(root)
        report_path = root / "qualification.json"
        plan_path = root / "qualification_plan.json"
        require(all(str(path) in commitments and typed_equal(commitments[str(path)], boundary["pins"][str(path)])
                    for path in (report_path, plan_path)), "Previously accepted qualification report/plan changed")
        report = record(report_path)
        require(report.get("mode") == role and report.get("passed") is True and
                typed_equal(report.get("artifacts"), qualification._artifacts(root)),
                "Retained qualification artifacts differ from their verified report")
        assert_boundary(boundary)
        merge_pins(commitments, boundary["pins"])
        boundaries.append(boundary)
    return boundaries


def unit_status(name):
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.(service|scope)", name), "Invalid unit name")
    properties = SERVICE_PROPERTIES if name.endswith(".service") else UNIT_PROPERTIES
    result = subprocess.run(["systemctl", "--user", "show", name,
                             *[v for key in properties for v in ("-p", key)]],
                            capture_output=True, text=True, timeout=15, check=True)
    rows = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    require(set(rows) == set(properties), "Incomplete unit inspection")
    return {"name": name, **rows}


def controller(plan, expected=None):
    unit = unit_status(plan["service_unit"])
    require(unit["LoadState"] == "loaded" and unit["ActiveState"] == "active" and
            unit["Type"] in ("exec", "simple") and unit["Restart"] == "no" and
            unit["RemainAfterExit"] == "no" and unit["KillMode"] == "control-group" and
            re.fullmatch(r"[0-9a-f]{32}", unit["InvocationID"]), "Controller service policy differs")
    identity = data.process_identity(int(unit["MainPID"]))
    require(identity is not None and identity["cgroup"] == unit["ControlGroup"] and
            identity["cmdline"] == [plan["python"], str(Path(__file__).resolve()), "run", "--plan", plan["plan_path"]] and
            identity["cwd"] == str(ROOT) and identity["exe"] == plan["python_realpath"],
            "Controller process/command differs")
    actual = {"process": identity, "invocation_id": unit["InvocationID"], "unit": unit["name"]}
    require(expected is None or actual == expected, "Controller invocation was replaced")
    return actual


def extra_sources():
    return [Path(__file__).resolve(), ROOT / "tools/continue_v5_data_phase.py",
            ROOT / "tools/qualify_v5_performance.py", ROOT / "tools/v5_retention.py",
            ROOT / "tools/verify_v5_neural.py", ROOT / "spikeids_v5/tests/test_research_continuation.py"]


def runtime():
    return {name: importlib.metadata.version(name) for name in
            ("numpy", "pandas", "pyarrow", "torch", "scikit-learn", "scipy", "statsmodels")}


def review_gate(review_path, test_path):
    review = record(review_path)
    expected = {str(path): snapshot(path)["sha256"] for path in extra_sources()}
    require(review.get("kind") == "spikeids_v5_research_continuation_review" and
            review.get("schema") == 1 and review.get("passed") is True and
            review.get("sources") == expected and review.get("test_report") ==
            {"path": str(test_path), "sha256": snapshot(test_path)["sha256"]},
            "Independent review/test receipt is missing or stale")
    tree = ET.parse(test_path).getroot()
    cases = list(tree.iter("testcase"))
    require(cases and not any(list(tree.iter(tag)) for tag in ("failure", "error", "skipped")) and
            all(int(node.get(key, "0")) == 0 for node in tree.iter("testsuite")
                for key in ("failures", "errors", "skipped")), "Reviewed test report did not fully pass")


def check_sources(plan, *, full=True):
    # load_plan/freeze establish the predecessor's mandatory inventories. The
    # exact predecessor file is pinned; cheap polling must not rehash all IoT
    # parquet shards merely to parse that already-bound plan again.
    predecessor, before = data.stable_record(Path(plan["data_plan"]))
    require(before == plan["data_plan_snapshot"] and predecessor["content_sha256"] == plan["data_plan_sha256"],
            "Predecessor data plan changed")
    data.assert_pins(predecessor, full=full)
    require(runtime() == plan["runtime"] and data.boot_id() == plan["data_process"]["boot_id"],
            "Research runtime/boot changed")
    data.assert_snapshots(plan["pins"], full=full)
    for value, identity in plan["directories"].items():
        require(data.directory_identity(Path(value)) == identity, "Output parent directory changed")
    if plan.get("mode") == RECOVERY_MODE:
        require(temporary_runtime(plan["temporary_runtime"]["path"]) == plan["temporary_runtime"],
                "Frozen temporary runtime changed")
        for target in (Path(predecessor["acceptance"]), Path(predecessor["work_dir"]) / "complete.json"):
            require(not target.exists() and not target.is_symlink(), "An old acceptance/complete output appeared during recovery")
    return predecessor


def freeze(args):
    predecessor, predecessor_snapshot = data.load_plan(args.data_plan.absolute())
    data.assert_pins(predecessor)
    recovery = getattr(args, "action", "freeze") == "freeze-recovery"
    recovery_evidence = None
    if recovery:
        recovery_evidence = failed_data_prefix(predecessor, args.data_plan.absolute(), args.data_pid)
        identity = {"pid": args.data_pid, "start_ticks": None, "boot_id": data.boot_id(),
                    "historical_full_process_identity_available": False}
        temp_runtime = temporary_runtime(args.runtime_tmp_dir, fresh=True)
    else:
        identity = data.process_identity(args.data_pid)
        require(identity is not None, "Original data continuation must still be alive at freeze")
        argv = identity["cmdline"]
        require(identity["cwd"] == str(ROOT) and identity["exe"] == predecessor["python_realpath"] and
                len(argv) == 5 and (ROOT / argv[1]).resolve() == ROOT / "tools/continue_v5_data_phase.py" and
                argv[2:4] == ["run", "--plan"] and (ROOT / argv[4]).resolve() == args.data_plan.absolute(),
                "Predecessor PID is not the selected data continuation")
        require(record(Path(predecessor["work_dir"]) / "run_started.json")["pid"] == identity["pid"],
                "Data predecessor launch receipt names another process")
    require(args.service_unit.endswith(".service") and unit_status(args.service_unit)["LoadState"] == "not-found",
            "Research requires a fresh service unit")
    roots = {key: data.new_path(getattr(args, key)) for key in
             ("work_dir", "profiles_dir", "workers_dir", "run_dir")}
    data.nonoverlap([*roots.values(), Path(predecessor["work_dir"]),
                     Path(predecessor["cache_root_a"]), Path(predecessor["cache_root_b"]), ROOT / "data"])
    if recovery:
        data.nonoverlap([Path(temp_runtime["path"]), *roots.values(), Path(predecessor["work_dir"]),
                         Path(predecessor["cache_root_a"]), Path(predecessor["cache_root_b"])])
    review, tests, exposure = (getattr(args, key).absolute() for key in ("review_record", "test_report", "exposure_history"))
    review_gate(review, tests)
    paths = [*extra_sources(), review, tests, exposure,
             args.data_plan.absolute(), Path(predecessor["work_dir"]) / "run_started.json"]
    pins = {str(path): snapshot(path) for path in paths}
    if recovery:
        merge_pins(pins, recovery_evidence["pins"])
    plan = {"schema": 1, "kind": "spikeids_v5_research_continuation_plan", "root": str(ROOT),
            **{key: str(value) for key, value in roots.items()}, "plan_path": str(roots["work_dir"] / "plan.json"),
            "service_unit": args.service_unit, "data_plan": str(args.data_plan.absolute()),
            "data_plan_snapshot": predecessor_snapshot, "data_plan_sha256": predecessor["content_sha256"],
            "data_process": identity, "python": predecessor["python"], "python_realpath": predecessor["python_realpath"],
            "review_record": str(review), "test_report": str(tests), "exposure_history": str(exposure),
            "pins": pins, "runtime": runtime(), "stages": list(("recover_acceptance", *STAGES) if recovery else STAGES),
            "mode": RECOVERY_MODE if recovery else "await_live_data", "automatic_retry": False,
            "disk_free_floor_bytes": FLOOR_BYTES, "memory_bytes": data.MEMORY_BYTES, "swap_bytes": 0,
            "terminal_scope": "independently_verified_neural_and_statistics", "unautomated": UNAUTOMATED,
            "directories": {str(path.parent): data.directory_identity(path.parent) for path in roots.values()},
            "created_at": data.utc_now()}
    if recovery:
        plan["recovery"] = {"acceptance": str(roots["work_dir"] / "data_acceptance.json"),
                            "basis": "explicit fresh full replay; old SIGBUS failure preserved; no inherited acceptance",
                            "cache_checks": recovery_evidence["cache_checks"],
                            "preserved_failure": recovery_evidence["failure"], "parent_os_return_code": None}
        plan["temporary_runtime"] = temp_runtime
    check_sources(plan)
    require(data.process_identity(args.data_pid) == (None if recovery else identity), "Data PID changed during freeze")
    for value in roots.values():
        data.new_path(value)
    roots["work_dir"].mkdir(mode=0o700)
    plan["directories"][str(roots["work_dir"])] = data.directory_identity(roots["work_dir"])
    data.assert_snapshots(pins, full=False)
    data.write_new(Path(plan["plan_path"]), seal(plan))
    return Path(plan["plan_path"])


def load_plan(path):
    plan, observed = data.stable_record(Path(path).absolute())
    require(plan.get("schema") == 1 and plan.get("kind") == "spikeids_v5_research_continuation_plan" and
            plan.get("root") == str(ROOT) and plan.get("mode") in ("await_live_data", RECOVERY_MODE) and
            plan.get("stages") == list(stages(plan)) and
            plan.get("automatic_retry") is False and plan.get("unautomated") == UNAUTOMATED and
            plan.get("terminal_scope") == "independently_verified_neural_and_statistics" and
            type(plan.get("disk_free_floor_bytes")) is int and plan["disk_free_floor_bytes"] == FLOOR_BYTES and
            type(plan.get("memory_bytes")) is int and plan["memory_bytes"] == data.MEMORY_BYTES and
            type(plan.get("swap_bytes")) is int and plan["swap_bytes"] == 0 and
            plan.get("plan_path") == str(Path(path).absolute()) == str(Path(plan["work_dir"]) / "plan.json"),
            "Research plan contract differs")
    predecessor, _predecessor_snapshot = data.load_plan(Path(plan["data_plan"]))
    required = {*map(str, extra_sources()), plan["review_record"], plan["test_report"], plan["exposure_history"],
                plan["data_plan"], str(Path(predecessor["work_dir"]) / "run_started.json")}
    if plan["mode"] == RECOVERY_MODE:
        required.update(failed_prefix_paths(predecessor))
        require(plan["recovery"]["acceptance"] == str(Path(plan["work_dir"]) / "data_acceptance.json") and
                plan["recovery"].get("parent_os_return_code", "missing") is None and
                plan["data_process"].get("historical_full_process_identity_available") is False and
                plan["data_process"]["start_ticks"] is None, "Recovery completion/identity contract differs")
    require(set(plan["pins"]) == required, "Mandatory research source/review inventory differs")
    roots = [Path(plan[key]) for key in ("work_dir", "profiles_dir", "workers_dir", "run_dir")]
    data.nonoverlap([*roots, Path(predecessor["work_dir"]), Path(predecessor["cache_root_a"]),
                     Path(predecessor["cache_root_b"]), ROOT / "data"])
    if plan["mode"] == RECOVERY_MODE:
        data.nonoverlap([Path(plan["temporary_runtime"]["path"]), *roots, Path(predecessor["work_dir"]),
                         Path(predecessor["cache_root_a"]), Path(predecessor["cache_root_b"])])
    directories = {str(item.parent) for item in roots} | {plan["work_dir"]}
    require(set(plan["directories"]) == directories, "Mandatory directory inventory differs")
    require(type(plan["data_process"].get("pid")) is int and
            (plan["mode"] == RECOVERY_MODE or type(plan["data_process"].get("start_ticks")) is int),
            "Data process identity types differ")
    check_sources(plan, full=False)
    return plan, observed


def expected_data_evidence(predecessor):
    work = Path(predecessor["work_dir"])
    names = {"plan.json", "run_started.json", "a_completion.json", "a_exit.json", "data_acceptance.json"}
    for phase in data.PHASES:
        names.update((f"{phase}_started.json", f"{phase}_exit.json", f"{phase}_scope.log"))
        if phase in ("prepare_b", "acceptance"):
            names.add(f"{phase}.log")
    return {str(work / name) for name in names}


def failed_prefix_paths(predecessor):
    work = Path(predecessor["work_dir"])
    paths = (expected_data_evidence(predecessor) - {predecessor["acceptance"]}) | {str(work / "failed.json")}
    for role in ("a", "b"):
        paths.update(str(Path(predecessor[f"cache_root_{role}"]) / f"{dataset}.lock") for dataset in data.evidence.DATASETS)
        paths.update(str(Path(predecessor[f"cache_root_{role}"]) / dataset / name)
                     for dataset in data.evidence.DATASETS for name in data.evidence.EXPECTED_CACHE_FILES | {"metadata.json"})
    return paths


def failed_data_prefix(predecessor, plan_path, parent_pid):
    """Authenticate only the successful build prefix, retaining the failed replay."""
    work = Path(predecessor["work_dir"])
    data.assert_pins(predecessor)
    require(predecessor["a_exit_record"] == str(work / "a_exit.json") and
            predecessor["acceptance"] == str(work / "data_acceptance.json") and plan_path == work / "plan.json",
            "Recovery expects the canonical original data evidence paths")
    require(type(parent_pid) is int and parent_pid > 0 and data.process_identity(parent_pid) is None,
            "Failed predecessor parent PID must be absent; historical start ticks are unavailable")
    require(not (work / "complete.json").exists() and not (work / "complete.json").is_symlink() and
            not Path(predecessor["acceptance"]).exists() and not Path(predecessor["acceptance"]).is_symlink(),
            "Recovery cannot adopt an old complete or partial acceptance output")
    started = record(work / "run_started.json")
    require(type(started.get("pid")) is int and started["pid"] == parent_pid and
            started.get("plan_sha256") == predecessor["content_sha256"], "Failed predecessor launch binding differs")
    failure = record(work / "failed.json")
    require(type(failure.get("schema")) is int and failure["schema"] == 1 and
            failure.get("kind") == "spikeids_v5_data_continuation_failure" and failure.get("stage") == "acceptance" and
            failure.get("passed") is False and failure.get("automatic_retry") is False and
            failure.get("training_started") is False and failure.get("plan_sha256") == predecessor["content_sha256"],
            "Recovery requires the preserved failed acceptance attempt")
    required = failed_prefix_paths(predecessor)
    pins = {path: snapshot(Path(path)) for path in sorted(required)}
    owner_receipt, _owner_snapshot = data.load_a_receipt(predecessor)
    require(data._a_ended(predecessor)[0], "Original A process/scope is still live or was replaced")
    a_completion = record(work / "a_completion.json")
    require(typed_equal(a_completion.get("receipt"), owner_receipt), "A completion differs from successful owner receipt")
    data.check_resources(a_completion["last_observed_cgroup"])
    require(a_completion["last_observed_cgroup"]["path"] == predecessor["a_scope"]["ControlGroup"],
            "A last-observed resource sample has a foreign scope")
    checks = {}
    invocations = {predecessor["a_scope"]["InvocationID"]}
    executions = {(predecessor["a_process"]["boot_id"], predecessor["a_process"]["pid"], predecessor["a_process"]["start_ticks"])}
    for phase in data.PHASES:
        receipt = record(work / f"{phase}_exit.json")
        ticket = record(work / f"{phase}_started.json")
        name = data.scope_name(predecessor, phase)
        require(type(receipt.get("schema")) is int and receipt["schema"] == 1 and
                receipt.get("kind") == "spikeids_v5_data_phase_exit" and receipt.get("phase") == phase and
                receipt.get("plan_sha256") == predecessor["content_sha256"] and
                ticket.get("phase") == phase and ticket.get("scope") == name and
                ticket.get("plan_sha256") == predecessor["content_sha256"] and receipt["scope"]["name"] == name and
                re.fullmatch(r"[0-9a-f]{32}", receipt["scope"]["InvocationID"]), "Recovery prefix phase identity differs")
        expected_rc = -7 if phase == "acceptance" else 0
        require(type(receipt.get("return_code")) is int and receipt["return_code"] == expected_rc and
                receipt.get("passed") is (phase != "acceptance"), "Recovery accepts only the observed SIGBUS after three successful phases")
        data.validate_worker_identity(receipt["worker"], predecessor, plan_path, phase)
        invocation = receipt["scope"]["InvocationID"]
        execution = tuple(receipt["worker"][key] for key in ("boot_id", "pid", "start_ticks"))
        require(invocation not in invocations and execution not in executions, "Recovery prefix reused a scope invocation or process execution")
        invocations.add(invocation)
        executions.add(execution)
        require(data.process_identity(receipt["worker"]["pid"]) is None, "An old data worker is still alive or its PID reused")
        for key in ("initial_cgroup", "final_cgroup"):
            data.check_resources(receipt[key])
            require(receipt[key]["path"] == receipt["worker"]["cgroup"] == receipt["scope"]["ControlGroup"],
                    "Recovery prefix resource identity differs")
        unit = data.scope_status(name)
        allowed_results = ("success", "", "exit-code", "signal") if phase == "acceptance" else ("success", "")
        require(unit["LoadState"] == "not-found" or (unit["ActiveState"] == "inactive" and
                unit["InvocationID"] == receipt["scope"]["InvocationID"] and unit["Result"] in allowed_results),
                "Old data phase scope is live or replaced")
        if phase in ("check_a", "check_b"):
            checked = receipt["cache_check"]
            role = phase[-1]
            require(checked.get("passed") is True and checked.get("role") == role and
                    checked.get("root") == predecessor[f"cache_root_{role}"] and
                    set(checked.get("datasets", {})) == set(data.evidence.DATASETS), "Recovery cache-check scope differs")
            data.assert_cache_unchanged(checked)
            checks[role] = checked
        else:
            require(receipt.get("command") == data.phase_command(predecessor, phase) and
                    receipt.get("log_sha256") == pins[str(work / f"{phase}.log")]["sha256"],
                    "Preserved data command/log differs")
    data.assert_snapshots(pins)
    for checked in checks.values():
        data.assert_cache_stat_unchanged(checked)
    data.assert_pins(predecessor, full=False)
    return {"pins": pins, "cache_checks": checks, "failure": {"path": str(work / "failed.json"),
            "content_sha256": failure["content_sha256"], "acceptance_return_code": -7}}


def predecessor_ended(plan):
    current = data.process_identity(plan["data_process"]["pid"])
    if plan.get("mode") == RECOVERY_MODE:
        require(current is None, "Failed predecessor PID still exists or was reused")
        return True
    require(current is None or current == plan["data_process"], "Data PID reused or identity changed")
    return current is None


def validate_data(plan):
    if plan.get("mode") == RECOVERY_MODE:
        return validate_recovered_data(plan)
    predecessor = check_sources(plan)
    work = Path(predecessor["work_dir"])
    require(predecessor_ended(plan), "Data predecessor is still alive")
    require(not (work / "failed.json").exists(), "Data predecessor failed")
    completed, completion_snapshot = data.stable_record(work / "complete.json")
    require(completed.get("kind") == "spikeids_v5_data_continuation_complete" and completed.get("schema") == 1 and
            completed.get("plan_sha256") == predecessor["content_sha256"] and completed.get("passed") is True and
            completed.get("training_started") is False and
            set(completed.get("consumed_evidence", {})) == expected_data_evidence(predecessor),
            "Data completion omits mandatory evidence")
    pins = completed["consumed_evidence"]
    data.assert_snapshots(pins)
    data.load_a_receipt(predecessor)
    checks = {}
    for phase in data.PHASES:
        receipt = record(work / f"{phase}_exit.json")
        name = data.scope_name(predecessor, phase)
        ticket = record(work / f"{phase}_started.json")
        require(receipt.get("kind") == "spikeids_v5_data_phase_exit" and receipt.get("schema") == 1 and
                receipt.get("plan_sha256") == predecessor["content_sha256"] and receipt.get("phase") == phase and
                receipt.get("passed") is True and type(receipt.get("return_code")) is int and receipt["return_code"] == 0 and
                ticket.get("plan_sha256") == predecessor["content_sha256"] and ticket.get("phase") == phase and
                ticket.get("scope") == name and receipt["scope"]["name"] == name and
                re.fullmatch(r"[0-9a-f]{32}", receipt["scope"]["InvocationID"]), "Data phase exit proof differs")
        data.validate_worker_identity(receipt["worker"], predecessor, Path(plan["data_plan"]), phase)
        for key in ("initial_cgroup", "final_cgroup"):
            data.check_resources(receipt[key])
            require(receipt[key]["path"] == receipt["worker"]["cgroup"] == receipt["scope"]["ControlGroup"],
                    "Data scope/resource identity differs")
        unit = data.scope_status(name)
        require(unit["LoadState"] == "not-found" or (unit["ActiveState"] == "inactive" and
                unit["Result"] == "success" and unit["InvocationID"] == receipt["scope"]["InvocationID"]),
                "Data phase scope is not completed")
        if phase in ("check_a", "check_b"):
            checks[phase[-1]] = receipt["cache_check"]
            require(checks[phase[-1]].get("passed") is True and checks[phase[-1]].get("role") == phase[-1] and
                    checks[phase[-1]].get("root") == predecessor[f"cache_root_{phase[-1]}"] and
                    set(checks[phase[-1]].get("datasets", {})) == set(data.evidence.DATASETS), "Data cache gate differs")
            data.assert_cache_unchanged(checks[phase[-1]])
        else:
            require(receipt.get("command") == data.phase_command(predecessor, phase) and
                    receipt.get("log_sha256") == pins[str(work / f"{phase}.log")]["sha256"], "Data child command/log differs")
    accepted = data.check_acceptance(predecessor, checks["a"], checks["b"])
    require(completed.get("data_acceptance") == accepted, "Data completion acceptance binding differs")
    pins = {**pins, str(work / "complete.json"): completion_snapshot}
    for checked in checks.values():
        pins.update({str(Path(checked["root"]) / relative):
                     {**checked["stability"][relative], "sha256": item["sha256"]}
                     for relative, item in checked["inventory"].items()})
    data.assert_snapshots(pins)
    for checked in checks.values():
        data.assert_cache_stat_unchanged(checked)
    check_sources(plan, full=False)
    return {"pins": pins, "cache_checks": checks, "acceptance": accepted,
            "predecessor_parent_os_return_code": None,
            "completion_basis": "original process ended; complete receipt and actual per-phase child exits verified"}


def validate_recovered_data(plan):
    predecessor = check_sources(plan)
    proof = failed_data_prefix(predecessor, Path(plan["data_plan"]), plan["data_process"]["pid"])
    require(typed_equal(proof["cache_checks"], plan["recovery"]["cache_checks"]) and
            typed_equal(proof["failure"], plan["recovery"]["preserved_failure"]), "Preserved recovery prefix changed")
    work = Path(plan["work_dir"])
    receipt = record(work / "recover_acceptance_exit.json")
    owner = record(work / "run_started.json")["controller"]
    validate_stage_receipt(plan, "recover_acceptance", receipt, owner)
    accepted = data.check_acceptance(data_context(plan), proof["cache_checks"]["a"], proof["cache_checks"]["b"])
    require(typed_equal(receipt["result"]["pins"][accepted["path"]], accepted["snapshot"]),
            "Fresh acceptance changed after its successful verifier scope")
    pins = dict(proof["pins"])
    merge_pins(pins, {accepted["path"]: accepted["snapshot"]})
    merge_pins(pins, {str(work / name): snapshot(work / name) for name in
                     ("recover_acceptance_started.json", "recover_acceptance_exit.json", "recover_acceptance_scope.log", "recover_acceptance.log")})
    data.assert_snapshots(pins)
    for checked in proof["cache_checks"].values():
        data.assert_cache_stat_unchanged(checked)
    check_sources(plan, full=False)
    return {"kind": "explicit_fresh_acceptance_after_preserved_sigbus_failure", "pins": pins,
            "cache_checks": proof["cache_checks"], "acceptance": accepted,
            "predecessor_parent_os_return_code": None,
            "completion_basis": "old failure retained; original parent PID absent with unknown historical start ticks; new full verifier scope exited zero"}


def partial_resources(run, formal, actions):
    """Pin-bound prefix replay, NOT full resource acceptance; no forged future trace."""
    require(actions in (("fit",), ("fit", "verify")), "Invalid partial resource coverage")
    expected = {run / f"resource_{action}_001.json" for action in actions}
    raw = {path.with_suffix(".jsonl") for path in expected}
    require(set(run.glob("resource_*.json")) == expected and set(run.glob("resource_*.jsonl")) == raw,
            "Partial resource inventory differs")
    paths = expected | raw | {Path(resource_evidence.__file__).resolve(), ROOT / "spikeids_v5/contracts.py"}
    pins = {str(path): snapshot(path) for path in paths}
    tree = ast.parse(Path(resource_evidence.__file__).read_text())
    sites = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call) and
             isinstance(node.func, ast.Name) and node.func.id == "require" and len(node.args) >= 2 and
             isinstance(node.args[1], ast.Constant) and node.args[1].value == PARTIAL_COVERAGE_ERROR]
    require(len(sites) == 1, "Frozen resource API coverage site changed")
    try:
        resource_evidence.validate_resource_reports(run, formal)
    except contracts.ContractError as exc:
        trace, matched = exc.__traceback__, False
        while trace:
            matched |= trace.tb_frame.f_code is resource_evidence.validate_resource_reports.__code__ and trace.tb_lineno == sites[0]
            trace = trace.tb_next
        require(str(exc) == PARTIAL_COVERAGE_ERROR and matched,
                f"Partial resource numerical replay failed: {exc}")
    else:
        raise data.evidence.VerificationError("Partial resource replay unexpectedly accepted full coverage")
    require(set(run.glob("resource_*.jsonl")) == raw and set(run.glob("resource_*.json")) == expected,
            "Resource inventory changed during partial replay")
    data.assert_snapshots(pins)
    return {"pins": pins, "partial_actions": list(actions), "full_resource_acceptance": False}


def selected_runtime(plan):
    profile = qualification.verify_qualification(Path(plan["profiles_dir"]))
    workers = qualification.verify_qualification(Path(plan["workers_dir"]))
    pp, wp = (record(Path(plan[key]) / "qualification_plan.json") for key in ("profiles_dir", "workers_dir"))
    predecessor = data_context(plan)
    for candidate in (pp, wp):
        require(candidate["cache_root"] == predecessor["cache_root_a"] and
                candidate["raw_audit"] == predecessor["raw_audit"] and candidate["data_acceptance"] == predecessor["acceptance"],
                "Performance qualification used a different accepted dataset")
    require(typed_equal(pp["data_evidence"], wp["data_evidence"]), "Qualification data bindings differ")
    require(profile["mode"] == "profiles" and workers["mode"] == "workers" and
            wp["selected_profile"] == profile["fastest_measured"]["profile"] and
            wp["profile_qualification"]["root"] == plan["profiles_dir"], "Qualification selection cross-binding differs")
    optimizer, threads = profile["fastest_measured"]["profile"].split(":")
    require(typed_equal(pp["environments"][threads], wp["environments"][threads]), "Qualification environments differ")
    return optimizer, int(threads), workers["fastest_measured"]["workers"], wp["environments"][threads]


def expected_hyperparameters(dataset, model, optimizer, threads):
    return {"dataset": dataset, "model": model, "seeds": list(range(20)),
            "epochs": 40 if dataset == "iot23" else 80, "batch_size": 1024 if dataset == "iot23" else 512,
            "eval_batch_size": 4096, "eval_every": 10, "checkpoint_every": 10, "hidden": 256,
            "levels": 4, "qcfs_formula": "shifted_v1", "lr": .001, "weight_decay": .00001,
            "device": "cuda", "optimizer": optimizer, "threads": threads, "data_placement": "gpu", "compile": False,
            "vram_reserve_gib": 2.0, "loss_weighting": "sqrt_inverse_fit_only_v1", "checkpoint_policy": "fixed_final_epoch_v1"}


def validate_formal(plan):
    run = Path(plan["run_dir"])
    formal = neural.read_plan(run)
    suite.validate_plan_data_evidence(formal)
    optimizer, threads, workers, environment = selected_runtime(plan)
    require(formal["seeds"] == list(range(20)) and all(type(seed) is int for seed in formal["seeds"]) and
            formal["protocol_role"] == "planned_benchmark" and typed_equal(formal["environment"], environment) and
            typed_equal(formal["execution"], {"workers": workers, "unit": "independent job", "seed_order": "ascending within job",
                "resource_note": "worker count is hardware-specific and must pass replica verification"}) and
            type(formal["alpha"]) is float and formal["alpha"] == .05 and
            type(formal["equivalence_margin_pp"]) is float and formal["equivalence_margin_pp"] == 1.0 and
            type(formal["deployment_seed"]) is int and formal["deployment_seed"] == 0 and
            formal.get("margin_status") == ("frozen numerical-equivalence sensitivity margin before formal test evaluation; "
                "not historical preregistration and not an empirically established practical-importance threshold") and
            formal.get("prior_test_exposure") == "unknown outside this run directory; disclose historical exploration" and
            formal["training_policy"] == {"loss_weighting": "sqrt_inverse_fit_only_v1",
                "checkpoint_policy": "fixed_final_epoch_v1", "validation_role": "diagnostic_only"},
            "Formal policy/runtime differs from the measured full experiment")
    predecessor = data_context(plan)
    expected_binding = record(Path(plan["workers_dir"]) / "qualification_plan.json")["data_evidence"]
    require(typed_equal(formal["data_evidence"], expected_binding), "Formal accepted-data binding differs from selected qualification")
    expected = [(d, m) for d in contracts.DATASETS for m in contracts.ARMS[d]]
    require([(j["dataset"], j["model"]) for j in formal["jobs"]] == expected, "Formal ordered 11-arm matrix differs")
    for job in formal["jobs"]:
        require(typed_equal(job["hyperparameters"], expected_hyperparameters(job["dataset"], job["model"], optimizer, threads)) and
                job["cache"] == str(Path(predecessor["cache_root_a"]) / job["dataset"]), "Formal hyperparameters/cache differ")
    limits = formal["resource_limits"]
    require(typed_equal(limits, {"maximum_process_tree_rss_bytes": 14*1024**3, "require_bounded_cgroup": True,
            "maximum_cgroup_memory_bytes": data.MEMORY_BYTES, "maximum_sample_gap_seconds": 15.0,
            "maximum_gpu_memory_used_mib": 15360, "maximum_gpu_temperature_c": 80, "require_zero_swap_io": False,
            "host_swap_scope": "host context only when workload cgroup is enforced; not attributed to this run",
            "require_zero_oom_kills": True}), "Formal resource limits differ")
    return formal


def validate_fit(plan):
    run = Path(plan["run_dir"])
    formal = validate_formal(plan)
    gate = record(run / "verification_fit.json")
    partial = partial_resources(run, formal, ("fit", "verify"))
    neural.validate_global_fit_barrier(run, formal, gate)
    count, paths = 0, [run / "verification_fit.json"]
    require(not (run / "verification_evaluate.json").exists(), "Test opened before independent fit gate")
    for job in formal["jobs"]:
        for folder in ("results", "replicas"):
            path = run / folder / f"{job['id']}.json"
            current = neural.load_fit(path, job, formal)
            require(current["status"] == "fit_complete" and current["per_seed"] == [], "Formal fit already opened test")
            manifest = record(path.with_suffix("") / "manifest.json")
            require(all(type(manifest.get(key)) is int and manifest[key] == 0
                        for key in ("test_sessions_started", "test_sessions_completed")),
                    "Live fit ledger has already opened test")
            count += len(current["fit_runs"])
            paths.extend(path.with_suffix("") / name for name in ("fit_evidence.json", "fit_manifest.json"))
            paths.extend(path.with_suffix("") / "runs" / f"{job['model']}_seed_{seed}.pt" for seed in range(20))
    require(count == 440, "Independent fit gate did not inspect exactly 440 fits")
    return {"fit_count": count, "pins": {**partial["pins"], **{str(path): snapshot(path) for path in paths}}}


def command(plan, stage):
    predecessor = data_context(plan)
    python, run = plan["python"], plan["run_dir"]
    if stage == "recover_acceptance":
        require(plan.get("mode") == RECOVERY_MODE, "Acceptance recovery was not explicitly frozen")
        return data.phase_command(predecessor, "acceptance")
    if stage == "profiles":
        return [python, str(ROOT / "tools/qualify_v5_performance.py"), "profiles", "--cache-root", predecessor["cache_root_a"],
                "--raw-audit", predecessor["raw_audit"], "--data-acceptance", predecessor["acceptance"], "--work-dir", plan["profiles_dir"]]
    if stage == "workers":
        return [python, str(ROOT / "tools/qualify_v5_performance.py"), "workers", "--profile-qualification", plan["profiles_dir"],
                "--work-dir", plan["workers_dir"]]
    if stage == "freeze_formal":
        optimizer, threads, workers, _environment = selected_runtime(plan)
        return [python, str(ROOT / "spikeids_v5/suite.py"), "freeze", "--cache-root", predecessor["cache_root_a"],
                "--raw-audit", predecessor["raw_audit"], "--data-acceptance", predecessor["acceptance"],
                "--run-dir", run, "--device", "cuda", "--optimizer", optimizer, "--threads", str(threads),
                "--workers", str(workers), "--seeds", *map(str, range(20)), "--delta", "1", "--alpha", "0.05"]
    if stage in ("fit_primary", "fit_replica", "evaluate"):
        return [python, str(ROOT / "spikeids_v5/suite.py"),
                {"fit_primary": "fit", "fit_replica": "verify", "evaluate": "evaluate"}[stage], "--run-dir", run]
    scripts = {"statistics": "spikeids_v5/run_globecom_stats.py", "equivalence": "spikeids_v5/run_v4_equivalence.py",
               "independent": "tools/verify_v5_neural.py"}
    require(stage in scripts, "No external command for this gate")
    return [python, str(ROOT / scripts[stage]), "--run-dir", run]


def gate(plan, stage):
    run = Path(plan["run_dir"])
    if stage == "validate_data":
        return validate_data(plan)
    if stage in ("verify_profiles", "verify_workers"):
        root = Path(plan["profiles_dir"] if stage == "verify_profiles" else plan["workers_dir"])
        report = qualification.verify_qualification(root)
        require(report["mode"] == stage.removeprefix("verify_"), "Wrong qualification mode")
        return {"selected": report["fastest_measured"], "pins": {
            str(root / name): snapshot(root / name) for name in ("qualification_plan.json", "qualification.json")}}
    if stage == "validate_formal":
        formal = validate_formal(plan)
        return {"formal_plan_sha256": formal["content_sha256"], "pins": {
            str(run / name): snapshot(run / name) for name in ("plan.json", "environment.json")}}
    if stage == "validate_fit":
        return validate_fit(plan)
    if stage == "validate_evaluate":
        formal, results = neural.verified_suite(run)
        require(formal == validate_formal(plan) and sum(len(v["per_seed"]) for v in results.values()) == 220,
                "Evaluated formal scope differs")
        files = resource_evidence.validate_resource_reports(run, formal)
        files += [run / "verification_fit.json", run / "verification_evaluate.json"]
        return {"primary_test_records": 220, "total_test_records": 440,
                "pins": {str(path): snapshot(path) for path in files}}
    raise data.evidence.VerificationError(f"Unknown validation gate: {stage}")


def stage_name(plan, stage):
    require(stage in stages(plan), "Unknown research stage")
    return f"spikeids-research-{plan['content_sha256'][:16]}-{stage.replace('_', '-')}.scope"


def worker_argv(plan, stage):
    return [plan["python"], str(Path(__file__).resolve()), "_worker", "--plan", plan["plan_path"], "--stage", stage]


def validate_worker(plan, stage, receipt, *, complete=True):
    worker, scope = receipt["worker"], receipt["scope"]
    require(set(worker) == {"pid", "start_ticks", "boot_id", "cmdline", "cwd", "exe", "cgroup"} and
            type(worker["pid"]) is int and worker["pid"] > 0 and type(worker["start_ticks"]) is int and worker["start_ticks"] > 0 and
            worker["boot_id"] == plan["data_process"]["boot_id"] and worker["cmdline"] == worker_argv(plan, stage) and
            worker["cwd"] == str(ROOT) and worker["exe"] == plan["python_realpath"] and
            scope["name"] == stage_name(plan, stage) and scope["ActiveState"] == "active" and
            re.fullmatch(r"[0-9a-f]{32}", scope["InvocationID"]) and
            plan["service_unit"] in scope["BindsTo"].split() and plan["service_unit"] in scope["After"].split(),
            "Worker process/scope/controller dependencies differ")
    for key in (("initial_cgroup", "final_cgroup") if complete else ("initial_cgroup",)):
        data.check_resources(receipt[key])
        require(receipt[key]["path"] == worker["cgroup"] == scope["ControlGroup"], "Worker resource scope differs")
    if complete:
        check_oom(receipt)


def validate_stage_receipt(plan, stage, receipt, owner):
    require(type(receipt.get("schema")) is int and receipt["schema"] == 1 and
            receipt.get("kind") == "spikeids_v5_research_stage_exit" and
            receipt.get("plan_sha256") == plan["content_sha256"] and receipt.get("stage") == stage and
            receipt.get("controller") == owner and receipt.get("passed") is True and
            type(receipt.get("return_code")) is int and receipt["return_code"] == 0,
            "Research stage did not provide a genuine successful exit")
    validate_worker(plan, stage, receipt)
    internal = stage.startswith(("validate_", "verify_"))
    expected_logs = set() if internal else {str(Path(plan["work_dir"]) / f"{stage}.log")}
    require(set(receipt["evidence"]) == expected_logs, "Stage child log inventory differs")
    if internal:
        require("command" not in receipt and isinstance(receipt.get("result"), dict), "Internal gate receipt differs")
        validate_gate_result(plan, stage, receipt["result"])
    else:
        require(receipt.get("command") == command(plan, stage), "Research child command differs or is missing")
        if stage == "recover_acceptance":
            target = plan["recovery"]["acceptance"]
            result = receipt.get("result", {})
            require(set(result) == {"acceptance_output", "pins"} and result["acceptance_output"] == target and
                    set(result["pins"]) == {target}, "Fresh acceptance output proof is missing or redirected")
            data.assert_snapshots(result["pins"], full=False)


def validate_gate_result(plan, stage, result):
    """Cheap mandatory result contracts; numerical replay runs inside the worker."""
    run = Path(plan["run_dir"])
    pins = result.get("pins")
    require(isinstance(pins, dict), "Internal gate omitted immutable evidence pins")
    if stage == "validate_data":
        predecessor = record(plan["data_plan"])
        checks = result.get("cache_checks", {})
        recovery = plan.get("mode") == RECOVERY_MODE
        basis = ("old failure retained; original parent PID absent with unknown historical start ticks; new full verifier scope exited zero"
                 if recovery else "original process ended; complete receipt and actual per-phase child exits verified")
        require(set(checks) == {"a", "b"} and result.get("predecessor_parent_os_return_code", "missing") is None and
                result.get("completion_basis") == basis,
                "Internal data result scope differs")
        if recovery:
            require(result.get("kind") == "explicit_fresh_acceptance_after_preserved_sigbus_failure",
                    "Recovery result must explicitly preserve the failed predecessor claim")
            expected = failed_prefix_paths(predecessor) | {plan["recovery"]["acceptance"]}
            expected.update(str(Path(plan["work_dir"]) / name) for name in
                            ("recover_acceptance_started.json", "recover_acceptance_exit.json", "recover_acceptance_scope.log", "recover_acceptance.log"))
            accepted = data.check_acceptance(data_context(plan), checks["a"], checks["b"])
        else:
            expected = expected_data_evidence(predecessor) | {str(Path(predecessor["work_dir"]) / "complete.json")}
            accepted = record(Path(predecessor["work_dir"]) / "complete.json")["data_acceptance"]
        for role, checked in checks.items():
            require(checked.get("root") == predecessor[f"cache_root_{role}"] and checked.get("role") == role and
                    checked.get("passed") is True, "Internal cache result binding differs")
            data.assert_cache_stat_unchanged(checked)
            expected.update(str(Path(checked["root"]) / relative) for relative in checked["inventory"])
        require(typed_equal(result["acceptance"], accepted),
                "Internal data acceptance receipt differs")
    elif stage in ("verify_profiles", "verify_workers"):
        root = Path(plan["profiles_dir"] if stage == "verify_profiles" else plan["workers_dir"])
        expected = {str(root / name) for name in ("qualification_plan.json", "qualification.json")}
        require(typed_equal(result.get("selected"), record(root / "qualification.json")["fastest_measured"]),
                "Internal qualification selection differs")
    elif stage == "validate_formal":
        expected = {str(run / name) for name in ("plan.json", "environment.json")}
        require(result.get("formal_plan_sha256") == record(run / "plan.json")["content_sha256"], "Internal formal plan binding differs")
    elif stage == "validate_fit":
        require(type(result.get("fit_count")) is int and result["fit_count"] == 440, "Internal fit count differs")
        expected = {str(run / f"resource_{action}_001.{suffix}") for action in ("fit", "verify") for suffix in ("json", "jsonl")}
        expected.add(str(run / "verification_fit.json"))
        expected.update((str(Path(resource_evidence.__file__).resolve()), str(ROOT / "spikeids_v5/contracts.py")))
        for dataset in contracts.DATASETS:
            for model in contracts.ARMS[dataset]:
                for folder in ("results", "replicas"):
                    base = run / folder / f"{dataset}_{model}"
                    expected.update(str(base / name) for name in ("fit_evidence.json", "fit_manifest.json"))
                    expected.update(str(base / "runs" / f"{model}_seed_{seed}.pt") for seed in range(20))
    elif stage == "validate_evaluate":
        require(type(result.get("primary_test_records")) is int and result["primary_test_records"] == 220 and
                type(result.get("total_test_records")) is int and result["total_test_records"] == 440,
                "Internal test record count differs")
        boundary = result["artifact_boundary"]
        require(boundary["root"] == str(run), "Internal evaluated inventory root differs")
        assert_boundary(boundary, full=False)
        expected = {str(run / relative) for relative in boundary["files"]}
        require(set(boundary["pins"]) == expected, "Internal evaluated inventory pins differ")
    else:
        raise data.evidence.VerificationError("Unexpected internal result stage")
    require(set(pins) == expected, "Internal gate evidence inventory differs")


def disk_preflight(plan):
    require(all(shutil.disk_usage(Path(plan[key]).parent).free >= FLOOR_BYTES for key in
                ("work_dir", "profiles_dir", "workers_dir", "run_dir")), "Less than frozen 50-GiB free-disk safety floor")
    if plan.get("mode") == RECOVERY_MODE:
        require(shutil.disk_usage(plan["temporary_runtime"]["path"]).free >= FLOOR_BYTES,
                "Recovery TMPDIR has less than frozen 50-GiB free-disk safety floor")


def stage_preflight(plan, stage):
    run = Path(plan["run_dir"])
    if stage == "recover_acceptance":
        data.new_path(Path(plan["recovery"]["acceptance"]))
        proof = failed_data_prefix(record(plan["data_plan"]), Path(plan["data_plan"]), plan["data_process"]["pid"])
        require(typed_equal(proof["cache_checks"], plan["recovery"]["cache_checks"]) and
                typed_equal(proof["failure"], plan["recovery"]["preserved_failure"]), "Recovery prefix changed before replay")
    roots = {"profiles": "profiles_dir", "workers": "workers_dir", "freeze_formal": "run_dir"}
    if stage in roots:
        data.new_path(Path(plan[roots[stage]]))
    if stage == "fit_primary":
        for name in ("results", "replicas", "verification_fit.json", "verification_evaluate.json"):
            data.new_path(run / name)
    if stage == "fit_replica":
        data.new_path(run / "replicas")
        data.new_path(run / "verification_fit.json")
        partial_resources(run, neural.read_plan(run), ("fit",))
    if stage == "evaluate":
        data.new_path(run / "verification_evaluate.json")
        validate_fit(plan)
    outputs = {"statistics": ("stats_report_globecom.json",), "equivalence": ("equivalence_v5.json", "equivalence_v5.md"),
               "independent": ("independent_verification.json",)}
    for name in outputs.get(stage, ()):
        data.new_path(run / name)


def chain(plan, stage):
    work = Path(plan["work_dir"])
    started = record(work / "run_started.json")
    expected_controller = started["controller"]
    controller(plan, expected_controller)
    pins = {str(work / "run_started.json"): snapshot(work / "run_started.json")}
    ordered = stages(plan)
    for previous in ordered[:ordered.index(stage)]:
        path = work / f"{previous}_exit.json"
        receipt = record(path)
        require(receipt.get("plan_sha256") == plan["content_sha256"] and receipt.get("stage") == previous and
                receipt.get("passed") is True and type(receipt.get("return_code")) is int and receipt["return_code"] == 0,
                "A preceding research stage has no successful exit receipt")
        merge_pins(pins, {str(path): snapshot(path)})
        merge_pins(pins, receipt.get("evidence", {}))
        merge_pins(pins, receipt.get("result", {}).get("pins", {}))
        for checked in receipt.get("result", {}).get("cache_checks", {}).values():
            data.assert_cache_stat_unchanged(checked)
        boundary = receipt.get("result", {}).get("artifact_boundary")
        if boundary is not None:
            additions = []
            for later in ordered[ordered.index(previous) + 1:ordered.index(stage)]:
                additions.extend({"statistics": ["stats_report_globecom.json"], "equivalence": ["equivalence_v5.json", "equivalence_v5.md"],
                                  "independent": ["independent_verification.json"]}.get(later, []))
            assert_boundary(boundary, additions, full=False)
    data.assert_snapshots(pins, full=False)
    return expected_controller, pins


def worker(plan_path, stage):
    plan, plan_snapshot = load_plan(plan_path)
    work = Path(plan["work_dir"])
    data.new_path(work / f"{stage}_exit.json")
    owner, previous = chain(plan, stage)
    ticket, ticket_snapshot = data.stable_record(work / f"{stage}_started.json")
    require(ticket.get("plan_sha256") == plan["content_sha256"] and ticket.get("stage") == stage and
            ticket.get("controller") == owner, "Stage ticket differs")
    identity = data.process_identity(os.getpid())
    receipt = {"schema": 1, "kind": "spikeids_v5_research_stage_exit", "plan_sha256": plan["content_sha256"],
               "stage": stage, "controller": owner, "worker": identity, "scope": unit_status(stage_name(plan, stage)),
               "initial_cgroup": data.cgroup_sample(identity["cgroup"]), "initial_host_oom_kill": host_oom(),
               "return_code": None, "passed": False,
               "started_at": data.utc_now(), "evidence": {}}
    code = 1
    try:
        validate_worker(plan, stage, receipt, complete=False)
        check_sources(plan)
        disk_preflight(plan)
        stage_preflight(plan, stage)
        readonly = stage in ("validate_formal", "validate_fit", "validate_evaluate", "statistics", "equivalence", "independent")
        boundary = artifact_boundary(Path(plan["run_dir"])) if readonly else None
        if stage.startswith("validate_") or stage.startswith("verify_"):
            receipt["result"] = gate(plan, stage)
            receipt["return_code"] = 0
        else:
            argv = command(plan, stage)
            receipt["command"] = argv
            log = work / f"{stage}.log"
            with log.open("xb") as stream:
                result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False)
                stream.flush(); os.fsync(stream.fileno())
            receipt["return_code"] = result.returncode
            receipt["evidence"][str(log)] = snapshot(log)
            require(type(result.returncode) is int and result.returncode == 0, f"Research child failed: {stage}/{result.returncode}")
            if stage == "recover_acceptance":
                target = Path(plan["recovery"]["acceptance"])
                accepted, captured = data.stable_record(target)
                require(accepted.get("kind") == "spikeids_v5_data_acceptance" and accepted.get("data_acceptance_passed") is True,
                        "Recovered verifier did not publish a passing fresh acceptance")
                receipt["result"] = {"acceptance_output": str(target), "pins": {str(target): captured}}
        additions = {"statistics": ("stats_report_globecom.json",), "equivalence": ("equivalence_v5.json", "equivalence_v5.md"),
                     "independent": ("independent_verification.json",)}.get(stage, ())
        if boundary is not None:
            assert_boundary(boundary, additions)
            # Fit's live JSON/ledgers legitimately mutate at evaluate, while its
            # immutable checkpoints were separately captured by validate_fit.
            if stage in ("validate_evaluate", "statistics", "equivalence", "independent"):
                merge_pins(receipt.setdefault("result", {}).setdefault("pins", {}), boundary["pins"])
            if stage == "validate_evaluate":
                receipt["result"]["artifact_boundary"] = boundary
            for name in additions:
                target = Path(plan["run_dir"]) / name
                receipt.setdefault("result", {}).setdefault("pins", {})[str(target)] = snapshot(target)
        check_sources(plan)
        data.assert_snapshots(previous)
        data.assert_snapshots({plan["plan_path"]: plan_snapshot, str(work / f"{stage}_started.json"): ticket_snapshot})
        require(data.process_identity(os.getpid()) == identity, "Research worker process changed")
        controller(plan, owner)
        receipt["final_cgroup"] = data.cgroup_sample(identity["cgroup"])
        receipt["final_host_oom_kill"] = host_oom()
        validate_worker(plan, stage, receipt)
        data.assert_snapshots(previous, full=False)
        if boundary is not None:
            assert_boundary(boundary, additions, full=False)
        check_sources(plan, full=False)
        data.assert_snapshots(receipt.get("result", {}).get("pins", {}), full=False)
        receipt["passed"], code = True, 0
    except BaseException as exc:
        receipt["error"] = repr(exc)
    receipt["finished_at"] = data.utc_now()
    data.write_new(work / f"{stage}_exit.json", seal(receipt))
    return code


def run_stage(plan, stage):
    owner, previous = chain(plan, stage)
    name, work = stage_name(plan, stage), Path(plan["work_dir"])
    require(unit_status(name)["LoadState"] == "not-found", "Research stage scope already exists")
    data.new_path(work / f"{stage}_exit.json")
    initial_host_oom = host_oom()
    data.write_new(work / f"{stage}_started.json", seal({"plan_sha256": plan["content_sha256"],
                   "stage": stage, "controller": owner, "initial_host_oom_kill": initial_host_oom, "started_at": data.utc_now()}))
    ticket_snapshot = snapshot(work / f"{stage}_started.json")
    argv = ["systemd-run", "--user", "--scope", "--quiet", "--unit", name,
            "-p", f"MemoryMax={data.MEMORY_BYTES}", "-p", "MemorySwapMax=0",
            "-p", f"BindsTo={plan['service_unit']}", "-p", f"After={plan['service_unit']}", *worker_argv(plan, stage)]
    with (work / f"{stage}_scope.log").open("xb") as stream:
        result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False)
        stream.flush(); os.fsync(stream.fileno())
    require(type(result.returncode) is int and result.returncode == 0, f"Research scope failed: {stage}/{result.returncode}")
    path = work / f"{stage}_exit.json"
    receipt, captured = data.stable_record(path)
    validate_stage_receipt(plan, stage, receipt, owner)
    ended = unit_status(name)
    require(ended["LoadState"] == "not-found" or (ended["ActiveState"] == "inactive" and
            ended["Result"] == "success" and ended["InvocationID"] == receipt["scope"]["InvocationID"]),
            "Research scope still running/failed/replaced")
    snapshots = {str(path): captured, str(work / f"{stage}_started.json"): ticket_snapshot,
                 str(work / f"{stage}_scope.log"): snapshot(work / f"{stage}_scope.log")}
    merge_pins(snapshots, receipt["evidence"])
    merge_pins(snapshots, receipt.get("result", {}).get("pins", {}))
    check_sources(plan)
    data.assert_snapshots(merge_pins(dict(previous), snapshots))
    controller(plan, owner)
    data.assert_snapshots(merge_pins(dict(previous), snapshots), full=False)
    check_sources(plan, full=False)
    require(host_oom() == initial_host_oom == receipt["initial_host_oom_kill"] == receipt["final_host_oom_kill"],
            "Host OOM counter changed across the complete scope lifecycle")
    return receipt, snapshots


def wait_for_data(plan):
    predecessor = record(plan["data_plan"])
    work = Path(predecessor["work_dir"])
    while True:
        check_sources(plan, full=False)
        require(not (work / "failed.json").exists(), "Data predecessor failed; research cannot continue")
        ended = predecessor_ended(plan)
        if ended:
            require((work / "complete.json").is_file(), "Data predecessor ended without a completion receipt")
            return
        print(json.dumps({"phase": "waiting_data", "status": "original_data_process_running",
                          "pid": plan["data_process"]["pid"], "time": data.utc_now()}), flush=True)
        time.sleep(30)


def run(path):
    plan, plan_snapshot = load_plan(path)
    work = Path(plan["work_dir"])
    owner = controller(plan)
    require(owner["process"]["pid"] == os.getpid(), "Run must be the controller service MainPID")
    data.write_new(work / "run_started.json", seal({"plan_sha256": plan["content_sha256"],
                   "controller": owner, "started_at": data.utc_now()}))
    stage, consumed = "waiting_data", {plan["plan_path"]: plan_snapshot,
                                      str(work / "run_started.json"): snapshot(work / "run_started.json")}
    try:
        for key in ("profiles_dir", "workers_dir", "run_dir"):
            data.new_path(Path(plan[key]))
        check_sources(plan)
        if plan.get("mode") == RECOVERY_MODE:
            stage = "recover_acceptance_preflight"
            stage_preflight(plan, "recover_acceptance")
        else:
            wait_for_data(plan)
        for stage in stages(plan):
            controller(plan, owner); check_sources(plan); data.assert_snapshots(consumed, full=False)
            print(json.dumps({"phase": stage, "status": "starting", "time": data.utc_now()}), flush=True)
            receipt, files = run_stage(plan, stage)
            merge_pins(consumed, files)
            print(json.dumps({"phase": stage, "status": "passed", "time": data.utc_now()}), flush=True)
        independent = record(Path(plan["run_dir"]) / "independent_verification.json")
        formal = neural.read_plan(Path(plan["run_dir"]))
        require(independent.get("kind") == "independent_formal_neural_and_statistics_verification" and
                independent.get("passed") is True and independent.get("plan_sha256") == formal["content_sha256"] and
                independent.get("prediction_artifacts_checked") == 440 and independent.get("checkpoints_checked") == 440,
                "Final independent neural/statistics scope differs")
        for filename in ("stats_report_globecom.json", "equivalence_v5.json", "equivalence_v5.md", "independent_verification.json"):
            target = Path(plan["run_dir"]) / filename
            merge_pins(consumed, {str(target): snapshot(target)})
        qualification_boundaries = retain_qualifications(plan, consumed)
        data.assert_snapshots(consumed)
        check_sources(plan)
        data.assert_snapshots(consumed, full=False)
        for checked in record(work / "validate_data_exit.json")["result"]["cache_checks"].values():
            data.assert_cache_stat_unchanged(checked)
        assert_boundary(record(work / "validate_evaluate_exit.json")["result"]["artifact_boundary"],
                        ("stats_report_globecom.json", "equivalence_v5.json", "equivalence_v5.md", "independent_verification.json"), full=False)
        for boundary in qualification_boundaries:
            assert_boundary(boundary, full=False)
        check_sources(plan, full=False)
        controller(plan, owner)
        result = seal({"schema": 1, "kind": "spikeids_v5_research_continuation_complete", "passed": True,
                       "plan_sha256": plan["content_sha256"], "formal_plan_sha256": formal["content_sha256"],
                       "terminal_scope": plan["terminal_scope"], "unautomated": UNAUTOMATED,
                       "mode": plan["mode"],
                       "consumed_evidence": consumed, "finished_at": data.utc_now()})
        data.write_new(work / "complete.json", result)
        return result
    except BaseException as exc:
        data.write_new(work / "failed.json", seal({"schema": 1, "kind": "spikeids_v5_research_continuation_failure",
                       "plan_sha256": plan["content_sha256"], "stage": stage, "error": repr(exc),
                       "passed": False, "automatic_retry": False, "finished_at": data.utc_now()}))
        raise


def status(path):
    plan, _ = load_plan(path)
    work = Path(plan["work_dir"])
    return {"plan_sha256": plan["content_sha256"], "service": unit_status(plan["service_unit"]),
            "complete": (work / "complete.json").exists(), "failed": (work / "failed.json").exists(),
            "stages": {stage: {"started": (work / f"{stage}_started.json").exists(),
                       "exit_record": record(work / f"{stage}_exit.json") if (work / f"{stage}_exit.json").exists() else None}
                       for stage in stages(plan)}, "scope": "status only; presence is not independent scientific acceptance"}


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="action", required=True)
    for mode in ("freeze", "freeze-recovery"):
        frozen = sub.add_parser(mode, allow_abbrev=False)
        for key in ("data-plan", "work-dir", "profiles-dir", "workers-dir", "run-dir", "review-record", "test-report", "exposure-history"):
            frozen.add_argument("--" + key, type=Path, required=True)
        frozen.add_argument("--data-pid", type=int, required=True)
        frozen.add_argument("--service-unit", required=True)
        if mode == "freeze-recovery":
            frozen.add_argument("--runtime-tmp-dir", type=Path, required=True)
    for action in ("run", "status", "_worker"):
        child = sub.add_parser(action, allow_abbrev=False)
        child.add_argument("--plan", type=Path, required=True)
        if action == "_worker":
            child.add_argument("--stage", choices=("recover_acceptance", *STAGES), required=True)
    args = parser.parse_args()
    if args.action in ("freeze", "freeze-recovery"):
        print(freeze(args), flush=True)
    elif args.action == "_worker":
        raise SystemExit(worker(args.plan.absolute(), args.stage))
    else:
        print(json.dumps(run(args.plan.absolute()) if args.action == "run" else status(args.plan.absolute()), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
