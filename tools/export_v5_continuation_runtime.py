#!/usr/bin/env python3
"""One exclusive successor for the diagnosed three-attempt export interruption.

The original plan and first three attempts are read-only. Only its exact
nineteen-attempt suffix can invoke the unchanged numerical exporter. OS argv
and delegated algorithm argv are recorded separately; no historical CLI is
fabricated and no original scientific plan is edited or resealed.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "spikeids_v5")]
from tools import export_v5_runtime as original
from tools import export_v5_build_identity as builds
from contracts import check_seal, require, seal, sha256

SELF = Path(__file__).resolve()
CONTROLLER = ROOT / "tools/continue_v5_exports.py"
REGISTRY_ROOT = ROOT / "results/v5_export_successor_registry"
canonical, equal = original.canonical, original.equal
_record, _write_once, _fsync_dir = original._record, original._write_once, original._fsync_dir
_assert_pins, _process_identity = original._assert_pins, original._process_identity
legacy = original.legacy


def _controller_api():
    from tools import continue_v5_exports
    return continue_v5_exports


def source_paths():
    return _controller_api().sources()


def _merge_pins(*collections):
    pins = {}
    for collection in collections:
        for path, value in collection.items():
            require(path not in pins or equal(pins[path], value), f"Previously held commitment changed: {path}")
            pins[path] = value
    return pins


def registry_directory(original_export_plan_sha256):
    require(type(original_export_plan_sha256) is str and
            re.fullmatch(r"[0-9a-f]{64}", original_export_plan_sha256) is not None,
            "Invalid original export plan seal")
    return canonical(REGISTRY_ROOT) / original_export_plan_sha256


def _original_plan(plan):
    """Keep the original immutable plan object; validate exact matrix membership."""
    require(type(plan.get("schema")) is int and plan["schema"] == 1 and
            plan.get("kind") == "spikeids_v5_export_continuation_plan" and
            plan.get("automatic_retry") is False, "Wrong continuation plan")
    check_seal(plan)
    path = canonical(Path(plan["original_export_plan"]), file=True)
    export, pin = _record(path)
    require(str(path) in plan["input_pins"] and equal(plan["input_pins"][str(path)], pin) and
            export["content_sha256"] == plan["original_export_plan_sha256"] and
            export["run_dir"] == plan["neural_run"] and
            export["source_plan_sha256"] == plan["formal_plan_sha256"] and
            type(export.get("schema")) is int and export["schema"] == 1 and
            export.get("kind") == "spikeids_v5_export_plan" and
            path == Path(export["output_root"]) / "export_plan.json",
            "Original scientific plan commitment differs")
    keys = [(a["dataset"], a["model"], a["mode"]) for a in export["attempts"]]
    require(keys == [(d, m, q) for d, m in legacy.JOBS for q in ("fp32", "qdq")] and
            len(keys) == 22 and equal(plan["retained_attempts"], export["attempts"][:3]) and
            equal(plan["remaining_attempts"], export["attempts"][3:]) and
            equal(plan["protocol"], export["protocol"]) and
            equal(export["protocol"], legacy.fixed_export_protocol()),
            "Continuation must retain the original three and execute only the exact nineteen")
    builds.validate_distribution_versions(export["tool_provenance"]["packages"], plan["build_identity"])
    _assert_pins({str(path): pin})
    return export, {str(path): pin}


def load_plan(plan_path, *, full=True):
    """Controller owns complete source/history review; no registry is needed yet.

    Package snapshots remain nested in build_identity: uv package hardlinks must
    not be flattened into the ordinary single-link scientific input pin map.
    """
    require(type(full) is bool, "Invalid continuation validation mode")
    path = canonical(Path(plan_path), file=True)
    plan, pin = _controller_api().load_plan(path, full=full)
    require(plan["plan_path"] == str(path), "Wrong continuation plan path")
    _, pins = _original_plan(plan)
    pins[str(path)] = pin
    _assert_pins(pins)
    return plan, pins


def _owner_shape(plan, owner):
    require(type(owner) is dict and set(owner) == {"service", "process"}, "Missing registered owner")
    identity, service = owner["process"], owner["service"]
    original._identity_shape(identity)
    require(identity["cmdline"] == [plan["python"], str(CONTROLLER), "run", "--plan", plan["plan_path"]] and
            identity["cwd"] == str(ROOT) and identity["exe"] == plan["python_realpath"] and
            identity["boot_id"] == plan["boot_id"] and
            type(service) is dict and service.get("name") == plan["service_unit"] and
            service.get("LoadState") == "loaded" and service.get("ActiveState") == "active" and
            service.get("Type") == "exec" and service.get("Restart") == "no" and
            service.get("RemainAfterExit") == "no" and service.get("KillMode") == "control-group" and
            service.get("MainPID") == str(identity["pid"]) and
            service.get("MemoryMax") == str(16 * 1024**3) and service.get("MemorySwapMax") == "0" and
            service.get("ControlGroup") == identity["cgroup"] and
            type(service.get("InvocationID")) is str and
            re.fullmatch(r"[0-9a-f]{32}", service["InvocationID"]) is not None,
            "Registered creator is not the exact bounded continuation service")


def _claim_body(plan, owner):
    return {"schema": 1, "kind": "spikeids_v5_export_successor_claim",
        "continuation_plan_sha256": plan["content_sha256"], "continuation_plan": plan["plan_path"],
        "original_export_plan_sha256": plan["original_export_plan_sha256"],
        "original_export_plan": plan["original_export_plan"], "history_sha256": plan["history_sha256"],
        "neural_run": plan["neural_run"], "output_root": plan["export_root"],
        "remaining_attempts": plan["remaining_attempts"], "retained_attempts": plan["retained_attempts"],
        "creator": owner, "no_retry_or_adoption": True}


def _registration_body(plan, claim_pin, plan_pin):
    return {"schema": 1, "kind": "spikeids_v5_export_successor_registration",
        "original_export_plan_sha256": plan["original_export_plan_sha256"],
        "continuation_plan_sha256": plan["content_sha256"],
        "claim": {"path": str(registry_directory(plan["original_export_plan_sha256"]) / "claim.json"),
                  "snapshot": claim_pin},
        "continuation_plan": {"path": plan["plan_path"], "snapshot": plan_pin},
        "output_root": plan["export_root"], "automatic_retry": False}


def register(plan):
    actual, inputs = load_plan(Path(plan["plan_path"]), full=False)
    require(equal(plan, actual), "Registering a different continuation plan")
    output = canonical(Path(plan["export_root"]))
    canonical(output.parent, directory=True)
    require(not output.exists() and not output.is_symlink(), "Successor output already exists; no adoption")
    owner = _controller_api().controller(plan)
    _owner_shape(plan, owner)
    require(equal(_process_identity(os.getpid()), owner["process"]), "Not the actual live controller")
    registry = canonical(REGISTRY_ROOT)
    registry.mkdir(mode=0o700, exist_ok=True)
    canonical(registry, directory=True)
    _fsync_dir(registry.parent)
    directory = registry_directory(plan["original_export_plan_sha256"])
    directory.mkdir(mode=0o700, exist_ok=False)
    _fsync_dir(registry)
    # The claim is sticky even if a subsequent write, fsync or mkdir fails.
    claim_path, registration_path = directory / "claim.json", directory / "registration.json"
    intended = seal(_claim_body(plan, owner))
    _write_once(claim_path, intended)
    actual_claim, claim_pin = _record(claim_path)
    require(equal(actual_claim, intended), "Successor claim changed while publishing")
    output.mkdir(mode=0o700, exist_ok=False)
    _fsync_dir(output.parent)
    intended_registration = seal(_registration_body(plan, claim_pin, inputs[plan["plan_path"]]))
    _write_once(registration_path, intended_registration)
    actual_registration, registration_pin = _record(registration_path)
    require(equal(actual_registration, intended_registration), "Successor registration changed while publishing")
    pins = _merge_pins(inputs, {str(claim_path): claim_pin, str(registration_path): registration_pin})
    _assert_pins(plan["input_pins"])
    _assert_pins(pins)
    require(not list(output.iterdir()), "Foreign output appeared during registration")
    return pins


def _registration(plan):
    directory = canonical(registry_directory(plan["original_export_plan_sha256"]), directory=True)
    require(sorted(p.name for p in directory.iterdir()) == ["claim.json", "registration.json"],
            "Incomplete or extra successor registry evidence; partial claims cannot be adopted")
    claim_path, registration_path = directory / "claim.json", directory / "registration.json"
    claim, claim_pin = _record(claim_path)
    registration, registration_pin = _record(registration_path)
    _owner_shape(plan, claim.get("creator"))
    require(equal(claim, seal(_claim_body(plan, claim["creator"]))), "Successor claim differs")
    current, plan_pin = _record(Path(plan["plan_path"]))
    require(equal(current, plan) and
            equal(registration, seal(_registration_body(plan, claim_pin, plan_pin))),
            "Successor registration or originally registered plan bytes changed")
    pins = {str(claim_path): claim_pin, str(registration_path): registration_pin, plan["plan_path"]: plan_pin}
    _assert_pins(pins)
    return claim, pins


def registration_pins(plan):
    return _registration(plan)[1]


def _key(dataset, model, mode, replay):
    require(type(replay) is bool and
            (dataset, model, mode) in [(d, m, q) for d, m in legacy.JOBS for q in ("fp32", "qdq")][3:],
            "Only nineteen unstarted attempts are authorized; retained first three cannot be re-exported")
    return f"{dataset}_{model}_{mode}" + ("_replay" if replay else "")


def worker_invocation(plan_path, dataset, model, mode, replay=False):
    _key(dataset, model, mode, replay)
    return [sys.executable, str(SELF), "run", "--continuation-plan", str(canonical(Path(plan_path))),
            "--dataset", dataset, "--model", model, "--mode", mode, *(["--replay"] if replay else [])]


def worker_receipt_path(plan, dataset, model, mode, replay=False):
    return canonical(Path(plan["export_root"])) / "worker_receipts" / (_key(dataset, model, mode, replay) + ".json")


def _worker_claim_path(plan, dataset, model, mode, replay):
    return canonical(Path(plan["export_root"])) / "worker_claims" / (_key(dataset, model, mode, replay) + ".json")


def _worker_output(plan, dataset, model, mode, replay):
    _key(dataset, model, mode, replay)
    return canonical(Path(plan["export_root"])) / ("replays" if replay else "") / dataset / model / mode


def _delegated(plan, dataset, model, mode, replay):
    return legacy.exporter_invocation(Path(plan["neural_run"]), _worker_output(plan, dataset, model, mode, replay),
        dataset, model, mode, 1024, 1000, 0.01, export_plan_path=Path(plan["original_export_plan"]))


def _worker_claim_body(plan, dataset, model, mode, replay, identity, owner):
    return {"schema": 1, "kind": "spikeids_v5_continued_export_worker_claim",
        "continuation_plan_sha256": plan["content_sha256"],
        "original_export_plan_sha256": plan["original_export_plan_sha256"],
        "dataset": dataset, "model": model, "mode": mode, "replay": replay,
        "output_dir": str(_worker_output(plan, dataset, model, mode, replay)),
        "actual_os_argv": worker_invocation(Path(plan["plan_path"]), dataset, model, mode, replay),
        "delegated_algorithm_argv": _delegated(plan, dataset, model, mode, replay),
        "worker_identity": identity, "registered_parent": owner, "parent_pid": owner["process"]["pid"],
        "no_retry_or_adoption": True}


def validate_worker_receipt(plan, dataset, model, mode, return_code, replay=False):
    require(type(return_code) is int and return_code in (0, 1), "Worker did not finish normally (0 or 1)")
    _key(dataset, model, mode, replay)
    current, inputs = load_plan(Path(plan["plan_path"]), full=False)
    require(equal(current, plan), "Worker receipt belongs to another continuation")
    registration, registry_pins = _registration(plan)
    owner = registration["creator"]
    creator = owner["process"]
    claim_path = _worker_claim_path(plan, dataset, model, mode, replay)
    receipt_path = worker_receipt_path(plan, dataset, model, mode, replay)
    claim, claim_pin = _record(claim_path)
    receipt, receipt_pin = _record(receipt_path)
    identity = claim.get("worker_identity")
    original._identity_shape(identity)
    require(identity["pid"] != creator["pid"] and identity["boot_id"] == creator["boot_id"] and
            identity["cgroup"] == creator["cgroup"] and identity["cwd"] == str(ROOT) and
            identity["exe"] == plan["python_realpath"] and identity["cmdline"] ==
            worker_invocation(Path(plan["plan_path"]), dataset, model, mode, replay), "Worker execution identity differs")
    require(equal(claim, seal(_worker_claim_body(plan, dataset, model, mode, replay, identity, owner))),
            "Worker claim argv, parent, plan or suffix member differs")
    expected_keys = {"schema", "kind", "claim", "continuation_plan_sha256", "original_export_plan_sha256",
        "actual_os_argv", "delegated_algorithm_argv", "return_code", "outcome", "error", "elapsed_ns", "content_sha256"}
    require(set(receipt) == expected_keys and type(receipt["schema"]) is int and receipt["schema"] == 1 and
            receipt["kind"] == "spikeids_v5_continued_export_worker_receipt" and
            type(receipt["return_code"]) is int and receipt["return_code"] == return_code and
            type(receipt["elapsed_ns"]) is int and receipt["elapsed_ns"] > 0 and
            equal(receipt["claim"], {"path": str(claim_path), "snapshot": claim_pin}) and
            receipt["continuation_plan_sha256"] == plan["content_sha256"] and
            receipt["original_export_plan_sha256"] == plan["original_export_plan_sha256"] and
            receipt["actual_os_argv"] == claim["actual_os_argv"] and
            receipt["delegated_algorithm_argv"] == claim["delegated_algorithm_argv"] and
            receipt["outcome"] == ("algorithm_returned" if return_code == 0 else "algorithm_raised") and
            (receipt["error"] is None if return_code == 0 else type(receipt["error"]) is str and bool(receipt["error"])),
            "Worker receipt disagrees with actual OS exit, original claim or delegated call")
    pins = _merge_pins(inputs, registry_pins, {str(claim_path): claim_pin, str(receipt_path): receipt_pin})
    _assert_pins(plan["input_pins"])
    _assert_pins(pins)
    return pins


def run_worker(plan_path, dataset, model, mode, replay=False):
    import export_verified as exporter
    _key(dataset, model, mode, replay)
    plan, input_pins = load_plan(plan_path, full=False)  # All gates BEFORE checkpoint/model loading.
    export, original_pins = _original_plan(plan)
    registration, registry_pins = _registration(plan)
    owner, identity = registration["creator"], _process_identity(os.getpid())
    creator = owner["process"]
    actual_argv = [sys.executable, *sys.argv]
    original._identity_shape(identity)
    require(actual_argv == worker_invocation(Path(plan["plan_path"]), dataset, model, mode, replay) and
            identity["cmdline"] == actual_argv and identity["cwd"] == str(ROOT) and
            identity["exe"] == plan["python_realpath"] and identity["boot_id"] == creator["boot_id"] and
            identity["pid"] != creator["pid"] and os.getppid() == creator["pid"] and
            equal(_process_identity(os.getppid()), creator) and identity["cgroup"] == creator["cgroup"],
            "Worker is not the live registered controller's direct child")
    output = canonical(_worker_output(plan, dataset, model, mode, replay))
    require(not output.exists() and not output.is_symlink(), "Worker output already exists; no adoption/retry")
    held = _merge_pins(plan["input_pins"], input_pins, original_pins, registry_pins)
    if replay:
        held = _merge_pins(held, validate_worker_receipt(plan, dataset, model, mode, 1))
        legacy.scientific_failure(_worker_output(plan, dataset, model, mode, False), export, dataset, model, mode, 1)
    root = canonical(Path(plan["export_root"]), directory=True)
    for folder in (root / "worker_claims", root / "worker_receipts"):
        canonical(folder).mkdir(mode=0o700, exist_ok=True)
        canonical(folder, directory=True)
    _fsync_dir(root)
    claim_path = _worker_claim_path(plan, dataset, model, mode, replay)
    receipt_path = worker_receipt_path(plan, dataset, model, mode, replay)
    require(not receipt_path.exists() and not receipt_path.is_symlink(), "Worker receipt already exists")
    intended_claim = seal(_worker_claim_body(plan, dataset, model, mode, replay, identity, owner))
    _write_once(claim_path, intended_claim)
    claim, claim_pin = _record(claim_path)
    require(equal(claim, intended_claim), "Worker claim changed during publication")
    held[str(claim_path)] = claim_pin
    delegated = _delegated(plan, dataset, model, mode, replay)
    neural = legacy.read_plan(Path(plan["neural_run"]))
    require(neural["content_sha256"] == export["source_plan_sha256"], "Wrong neural source plan")
    attempt = next(a for a in export["attempts"] if (a["dataset"], a["model"], a["mode"]) == (dataset, model, mode))
    job = next(j for j in neural["jobs"] if (j["dataset"], j["model"]) == (dataset, model))
    checkpoint = Path(plan["neural_run"]) / "results" / job["id"] / "runs" / f"{model}_seed_0.pt"
    original_context, original_checkpoint, original_argv = exporter.frozen_export_context, exporter.checkpoint_context, sys.argv

    def health():
        current, _ = load_plan(Path(plan["plan_path"]), full=False)
        require(equal(current, plan), "Continuation context changed during algorithm")
        _registration(plan)
        _assert_pins(held)
        require(equal(_process_identity(os.getppid()), creator) and
                equal(_process_identity(os.getpid()), identity), "Live worker/parent identity changed")

    def checkpoint_context(run, data, arm):
        require(Path(run) == Path(plan["neural_run"]) and (data, arm) == (dataset, model),
                "Delegated checkpoint selection differs")
        health()
        require(str(checkpoint) in plan["input_pins"] and
                plan["input_pins"][str(checkpoint)]["sha256"] == attempt["checkpoint_sha256"] and
                sha256(canonical(checkpoint, file=True)) == attempt["checkpoint_sha256"],
                "Checkpoint differs before model loading")
        result = original_checkpoint(run, data, arm)
        require(equal(result[0], neural) and Path(result[-1]) == checkpoint, "Checkpoint loader returned another source")
        return result

    def frozen_context(path, source_plan, data, arm, mode_value, cp):
        require(Path(path) == Path(plan["original_export_plan"]) and equal(source_plan, neural) and
                (data, arm, mode_value) == (dataset, model, mode) and Path(cp) == checkpoint,
                "Delegated original frozen context differs")
        health()
        require(sha256(canonical(checkpoint, file=True)) == attempt["checkpoint_sha256"],
                "Checkpoint changed after model loading")
        return export  # Original object/seal, never a modified plan for the new root.

    started, code, error = time.monotonic_ns(), 0, None
    try:
        exporter.frozen_export_context, exporter.checkpoint_context = frozen_context, checkpoint_context
        sys.argv = delegated[1:]
        exporter.main()
    except BaseException as exc:
        code, error = 1, repr(exc)
        traceback.print_exc()
    finally:
        exporter.frozen_export_context, exporter.checkpoint_context, sys.argv = original_context, original_checkpoint, original_argv
    health()
    receipt = seal({"schema": 1, "kind": "spikeids_v5_continued_export_worker_receipt",
        "claim": {"path": str(claim_path), "snapshot": claim_pin},
        "continuation_plan_sha256": plan["content_sha256"], "original_export_plan_sha256": export["content_sha256"],
        "actual_os_argv": actual_argv, "delegated_algorithm_argv": delegated, "return_code": code,
        "outcome": "algorithm_returned" if code == 0 else "algorithm_raised", "error": error,
        "elapsed_ns": time.monotonic_ns() - started})
    _write_once(receipt_path, receipt)
    actual_receipt, receipt_pin = _record(receipt_path)
    require(equal(actual_receipt, receipt), "Worker receipt changed during publication")
    _assert_pins(_merge_pins(held, {str(receipt_path): receipt_pin}))
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    actions = parser.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run", allow_abbrev=False)
    run.add_argument("--continuation-plan", type=Path, required=True)
    run.add_argument("--dataset", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--mode", choices=("fp32", "qdq"), required=True)
    run.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    return run_worker(args.continuation_plan, args.dataset, args.model, args.mode, args.replay)


if __name__ == "__main__":
    raise SystemExit(main())
