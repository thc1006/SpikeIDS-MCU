#!/usr/bin/env python3
"""Add-only, one-shot external registration for the frozen numerical exporter.

The original neural directory is strictly read-only. This adapter routes only
the historical disclosure/registration interfaces; it does not change the
numerical exporter, its row selection, models, quantizer or tolerances. Actual
wrapper argv and explicitly delegated algorithm argv are distinct evidence.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import os
from pathlib import Path
import platform
import stat
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "spikeids_v5")]
from tools import run_v5_exports as legacy
from contracts import check_seal, digest, json_bytes, load_json, loads_json, require, seal, sha256

SELF = Path(__file__).resolve()
CONTROLLER = ROOT / "tools/run_v5_export_stage.py"
REGISTRY_ROOT = ROOT / "results/v5_export_registry"
_LEGACY_SOURCES = legacy._source_paths
_BUILDER_ACTIVE = False
_RUNTIME_ACTIVE = False


def equal(left, right):
    return json_bytes(left) == json_bytes(right)


def canonical(path: Path, *, directory=False, file=False) -> Path:
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts and path == path.resolve() and
            not path.is_symlink() and not any(p.is_symlink() for p in path.parents),
            f"Canonical unaliased absolute path required: {path}")
    if directory:
        require(path.is_dir(), f"Real directory required: {path}")
    if file:
        legacy._regular_file(path)
    return path


def source_paths() -> list[Path]:
    return sorted(set([*_LEGACY_SOURCES(), SELF, CONTROLLER,
                       ROOT / "tools/export_v5_science.py"]))


def _fsync_dir(path):
    descriptor = os.open(canonical(path, directory=True), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_once(path, value):
    path = canonical(path)
    canonical(path.parent, directory=True)
    with path.open("xb") as stream:
        stream.write(json_bytes(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_dir(path.parent)


def _snapshot_stat(status):
    return {"device": status.st_dev, "inode": status.st_ino, "mode": status.st_mode,
            "links": status.st_nlink, "bytes": status.st_size,
            "mtime_ns": status.st_mtime_ns, "ctime_ns": status.st_ctime_ns}


def _record(path):
    """Parse and hash the same FD; return the controller's exact snapshot schema."""
    path = canonical(path, file=True)
    before = _snapshot_stat(path.lstat())
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        require(_snapshot_stat(os.fstat(descriptor)) == before, "Record changed while opening")
        chunks = []
        while block := os.read(descriptor, 1024 * 1024):
            chunks.append(block)
        require(_snapshot_stat(os.fstat(descriptor)) == before, "Record changed while reading")
    finally:
        os.close(descriptor)
    require(_snapshot_stat(path.lstat()) == before and stat.S_ISREG(before["mode"]) and
            before["links"] == 1, "Record pathname changed while reading")
    payload = b"".join(chunks)
    value = loads_json(payload, str(path))
    check_seal(value)
    return value, {**before, "sha256": hashlib.sha256(payload).hexdigest()}


def _assert_pins(pins):
    for name, expected in pins.items():
        path = canonical(Path(name), file=True)
        require(equal(_snapshot_stat(path.stat()), {k: v for k, v in expected.items() if k != "sha256"}),
                f"External execution evidence changed: {path}")


def _process_identity(pid):
    require(type(pid) is int and pid > 0, "Invalid process identifier")
    text = Path(f"/proc/{pid}/stat").read_text()
    ticks = int(text[text.rfind(")") + 2:].split()[19])
    result = {"pid": pid, "start_ticks": ticks,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "cmdline": Path(f"/proc/{pid}/cmdline").read_bytes().rstrip(b"\0").decode().split("\0"),
        "cwd": os.readlink(f"/proc/{pid}/cwd"), "exe": os.readlink(f"/proc/{pid}/exe"),
        "cgroup": next(line.split("::", 1)[1] for line in
            Path(f"/proc/{pid}/cgroup").read_text().splitlines() if line.startswith("0::"))}
    later = Path(f"/proc/{pid}/stat").read_text()
    require(int(later[later.rfind(")") + 2:].split()[19]) == ticks, "PID reused during capture")
    return result


def _identity_shape(value):
    require(isinstance(value, dict) and set(value) ==
            {"pid", "start_ticks", "boot_id", "cmdline", "cwd", "exe", "cgroup"} and
            type(value["pid"]) is int and value["pid"] > 0 and
            type(value["start_ticks"]) is int and value["start_ticks"] > 0 and
            all(isinstance(value[k], str) and value[k] for k in ("boot_id", "cwd", "exe", "cgroup")) and
            isinstance(value["cmdline"], list) and all(isinstance(v, str) for v in value["cmdline"]),
            "Malformed immutable process identity")


def make_provenance(argv: list[str], parameters: dict) -> dict:
    require(isinstance(argv, list) and all(isinstance(v, str) for v in argv) and
            isinstance(parameters, dict) and set(parameters) == {"run_dir", "output_root", "controller_plan"},
            "Malformed actual controller provenance")
    for value in parameters.values():
        require(isinstance(value, str), "Provenance paths must be strings")
        canonical(Path(value))
    expected = [sys.executable, str(CONTROLLER), "run", "--plan", parameters["controller_plan"]]
    require(argv == expected and Path.cwd() == ROOT, "Not the exact external controller run invocation")
    return {"schema": 1, "kind": "spikeids_v5_external_export_runner_provenance",
        "tool": {"path": str(CONTROLLER), "source_sha256": sha256(canonical(CONTROLLER, file=True))},
        "invocation": {"argv": argv, "cwd": str(ROOT), "parameters": parameters},
        "python": {"executable": sys.executable, "realpath": str(Path(sys.executable).resolve()),
                   "sha256": sha256(Path(sys.executable).resolve()), "version": sys.version},
        "platform": platform.platform(),
        "packages": {name: importlib.metadata.version(name) for name in legacy.EXPORT_RUNNER_PACKAGES},
        "delegated_plan_builder": {"path": str(Path(legacy.__file__).resolve()),
            "source_sha256": sha256(Path(legacy.__file__).resolve()),
            "scope": "in-process plan builder only; not an executed legacy CLI"}}


def _validate_provenance(value, run, output, controller):
    expected_parameters = {"run_dir": str(run), "output_root": str(output), "controller_plan": str(controller)}
    require(isinstance(value, dict) and equal(value.get("invocation", {}).get("parameters"), expected_parameters),
            "External controller provenance belongs to another plan")
    require(equal(value, make_provenance(value["invocation"]["argv"], expected_parameters)),
            "External controller source/runtime/provenance changed")


def registry_directory(run_dir, neural_plan_sha256):
    run = canonical(Path(run_dir), directory=True)
    require(isinstance(neural_plan_sha256, str) and len(neural_plan_sha256) == 64 and
            all(c in "0123456789abcdef" for c in neural_plan_sha256), "Invalid neural plan seal")
    return canonical(REGISTRY_ROOT) / digest({"neural_run": str(run), "neural_plan_sha256": neural_plan_sha256})


def _no_legacy_registration(run):
    require(not (run / "export_registration.json").exists() and
            not (run / "export_registration.json").is_symlink(),
            "A legacy neural-side export registration already exists; no second matrix")


@contextlib.contextmanager
def _builder_context(run, output, exposure, controller, provenance, recorded_inputs=None):
    """Route exactly one old disclosure path; all recorded paths remain truthful."""
    global _BUILDER_ACTIVE
    require(not _BUILDER_ACTIVE, "Nested external plan builders are forbidden")
    _BUILDER_ACTIVE = True
    original = (legacy._binding, legacy.validate_prior_exposure,
                legacy.validate_tool_provenance, legacy._source_paths)
    source_set = {str(p) for p in source_paths()}
    routed = run / "export_prior_exposure.json"

    def binding(path):
        path = exposure if Path(path) == routed else canonical(Path(path), file=True)
        if recorded_inputs is not None and str(path) not in source_set:
            require(str(path) in recorded_inputs, f"Missing mandatory external export input: {path}")
            value = recorded_inputs[str(path)]
            legacy._check_binding(value, rehash=False)
            return value
        return original[0](path)

    def disclosure(path, neural):
        return original[1](exposure if Path(path) == routed else path, neural)

    def provenance_check(value, tool, packages, *args, **kwargs):
        if Path(tool).resolve() == Path(legacy.__file__).resolve():
            require(equal(value, provenance) and tuple(packages) == legacy.EXPORT_RUNNER_PACKAGES and
                    not args and not kwargs, "Unexpected legacy plan provenance call")
            _validate_provenance(value, run, output, controller)
        else:
            original[2](value, tool, packages, *args, **kwargs)
    try:
        legacy._binding, legacy.validate_prior_exposure = binding, disclosure
        legacy.validate_tool_provenance, legacy._source_paths = provenance_check, source_paths
        yield
    finally:
        (legacy._binding, legacy.validate_prior_exposure,
         legacy.validate_tool_provenance, legacy._source_paths) = original
        _BUILDER_ACTIVE = False


def _build(run, output, exposure, controller, provenance, neural, recorded_inputs=None):
    run, output = canonical(run, directory=True), canonical(output)
    exposure, controller = canonical(exposure, file=True), canonical(controller, file=True)
    _no_legacy_registration(run)
    require(output != run and not output.is_relative_to(run) and not run.is_relative_to(output) and
            not exposure.is_relative_to(run) and not controller.is_relative_to(run) and
            not exposure.is_relative_to(output) and not controller.is_relative_to(output),
            "External control paths overlap immutable neural/output roots")
    _validate_provenance(provenance, run, output, controller)
    controller_value, _ = _record(controller)
    require(type(controller_value.get("schema")) is int and controller_value["schema"] == 1 and
            controller_value.get("kind") == "spikeids_v5_export_stage_plan" and
            controller_value.get("plan_path") == str(controller) and
            controller_value.get("neural_run") == str(run) and
            controller_value.get("export_root") == str(output) and
            controller_value.get("prior_exposure") == str(exposure) and
            controller_value.get("formal_plan_sha256") == neural["content_sha256"] and
            equal(controller_value.get("protocol"), legacy.fixed_export_protocol()) and
            controller_value.get("automatic_retry") is False,
            "External controller plan is not bound to this fixed export matrix")
    with _builder_context(run, output, exposure, controller, provenance, recorded_inputs):
        core = legacy.build_export_plan(run, output, neural, provenance)
        controller_binding = legacy._binding(controller)
    require(str(controller) not in {row["path"] for row in core["inputs"]}, "Controller input collision")
    core["inputs"] = sorted([*core["inputs"], controller_binding], key=lambda row: row["path"])
    core["execution_adapter"] = {
        "schema": 1, "kind": "spikeids_v5_external_export_registration_runtime",
        "controller_plan": controller_binding,
        "registry_directory": str(registry_directory(run, neural["content_sha256"])),
        "registration_policy": "exclusive canonical neural-path-and-plan claim; partial claims never adopted",
        "worker_policy": "only live registration creator direct children; one original and at most one negative replay",
        "replay_output": "replays/{dataset}/{model}/{mode}; verification only; never adopts successful retries"}
    core.pop("content_sha256", None)
    result = seal(core)
    for row in [*result["inputs"], *result["sources"]]:
        legacy._check_binding(row, rehash=False)
    return result


def build_plan(run_dir, output_root, prior_exposure_path, controller_plan_path, runner_provenance):
    run = canonical(Path(run_dir), directory=True)
    output = canonical(Path(output_root))
    require(not output.exists(), "Export output namespace must be fresh")
    canonical(output.parent, directory=True)
    neural = legacy.read_plan(run)
    return _build(run, output, Path(prior_exposure_path), Path(controller_plan_path), runner_provenance, neural)


def _validate_plan(plan, neural, *, rehash):
    check_seal(plan)
    require(type(rehash) is bool and type(plan.get("schema")) is int and plan["schema"] == 1 and
            plan.get("kind") == "spikeids_v5_export_plan" and
            plan.get("source_plan_sha256") == neural["content_sha256"], "Wrong external export plan")
    run, output = canonical(Path(plan["run_dir"]), directory=True), canonical(Path(plan["output_root"]))
    _no_legacy_registration(run)
    require(equal(neural, load_json(run / "plan.json")), "Neural plan differs on disk")
    sources, inputs = plan["sources"], plan["inputs"]
    require([row["path"] for row in sources] == [str(p) for p in source_paths()], "External source closure differs")
    require(len({row["path"] for row in inputs}) == len(inputs), "Duplicate export input")
    for row in [*inputs, *sources]:
        canonical(Path(row["path"]), file=True)
        legacy._check_binding(row, rehash=rehash or row in sources)
    controller = Path(plan["execution_adapter"]["controller_plan"]["path"])
    exposure = Path(plan["prior_exposure"]["binding"]["path"])
    rebuilt = _build(run, output, exposure, controller, plan["tool_provenance"], neural,
        None if rehash else {row["path"]: row for row in inputs})
    require(equal(rebuilt, plan), "External plan differs from mandatory input/policy reconstruction")
    for row in [*inputs, *sources]:
        legacy._check_binding(row, rehash=False)


def _claim_body(plan, creator):
    return {"schema": 1, "kind": "spikeids_v5_external_export_claim",
        "neural_run": plan["run_dir"], "source_plan_sha256": plan["source_plan_sha256"],
        "output_root": plan["output_root"], "export_plan_sha256": plan["content_sha256"],
        "controller_plan": plan["execution_adapter"]["controller_plan"], "creator": creator,
        "no_retry_or_adoption": True}


def _registration_body(plan, claim_binding):
    return {"schema": 1, "kind": "spikeids_v5_external_export_registration",
        "source_plan_sha256": plan["source_plan_sha256"],
        "export_plan_path": str(Path(plan["output_root"]) / "export_plan.json"),
        "export_plan_sha256": plan["content_sha256"],
        "export_plan_file_sha256": hashlib.sha256(json_bytes(plan) + b"\n").hexdigest(),
        "claim": claim_binding}


def register(plan):
    """One exclusive sticky registry claim precedes any persisted export plan."""
    run, output = Path(plan["run_dir"]), canonical(Path(plan["output_root"]))
    _validate_plan(plan, legacy.read_plan(run), rehash=True)
    require(not output.exists(), "No adoption of an existing export output")
    creator = _process_identity(os.getpid())
    require(creator["cmdline"] == plan["tool_provenance"]["invocation"]["argv"] and
            creator["cwd"] == str(ROOT) and creator["exe"] == str(Path(sys.executable).resolve()),
            "Registration must be made by the actual declared controller process")
    registry = canonical(REGISTRY_ROOT)
    canonical(registry.parent, directory=True)
    registry.mkdir(mode=0o700, exist_ok=True)
    canonical(registry, directory=True)
    _fsync_dir(registry.parent)
    directory = registry_directory(run, plan["source_plan_sha256"])
    directory.mkdir(mode=0o700, exist_ok=False)
    _fsync_dir(registry)
    # Never remove a partial claim, even if any subsequent operation fails.
    _write_once(directory / "claim.json", seal(_claim_body(plan, creator)))
    output.mkdir(mode=0o700, exist_ok=False)
    _fsync_dir(output.parent)
    _write_once(output / "export_plan.json", plan)
    claim_binding = legacy._binding(directory / "claim.json")
    _write_once(directory / "registration.json", seal(_registration_body(plan, claim_binding)))


def registration_files(plan):
    directory = registry_directory(Path(plan["run_dir"]), plan["source_plan_sha256"])
    require(str(directory) == plan["execution_adapter"]["registry_directory"], "Wrong registry key")
    return [directory / "claim.json", directory / "registration.json"]


def _registration(plan):
    claim_path, registration_path = registration_files(plan)
    directory = canonical(claim_path.parent, directory=True)
    require(sorted(p.name for p in directory.iterdir()) == ["claim.json", "registration.json"],
            "Incomplete or extra external registry evidence; no partial-claim adoption")
    claim, claim_pin = _record(claim_path)
    registration, registration_pin = _record(registration_path)
    _identity_shape(claim.get("creator"))
    require(equal(claim, seal(_claim_body(plan, claim["creator"]))) and
            claim["creator"]["cmdline"] == plan["tool_provenance"]["invocation"]["argv"] and
            claim["creator"]["cwd"] == str(ROOT) and
            claim["creator"]["exe"] == str(Path(sys.executable).resolve()), "Registry claim identity differs")
    claim_binding = {"path": str(claim_path), "sha256": claim_pin["sha256"], "stat": {
        "device": claim_pin["device"], "inode": claim_pin["inode"], "size": claim_pin["bytes"],
        "mtime_ns": claim_pin["mtime_ns"], "ctime_ns": claim_pin["ctime_ns"]}}
    require(equal(registration, seal(_registration_body(plan, claim_binding))), "External registration differs")
    pins = {str(claim_path): claim_pin, str(registration_path): registration_pin}
    _assert_pins(pins)
    return claim, pins


def registration_pins(plan):
    return _registration(plan)[1]


def load_plan(output_root, neural_plan, *, rehash=True):
    root = canonical(Path(output_root), directory=True)
    path = root / "export_plan.json"
    plan, pin = _record(path)
    require(plan.get("output_root") == str(root), "External export plan belongs to another output root")
    _validate_plan(plan, neural_plan, rehash=rehash)
    _, pins = _registration(plan)
    require(pin["sha256"] == hashlib.sha256(json_bytes(plan) + b"\n").hexdigest(),
            "Export plan is not the originally registered canonical bytes")
    for binding in [*plan["inputs"], *plan["sources"]]:
        legacy._check_binding(binding, rehash=False)
    _assert_pins({str(path): pin, **pins})
    return plan


@contextlib.contextmanager
def scoped_runtime(plan=None):
    """Explicit read-only external-registration consumer; no numerical patches."""
    global _RUNTIME_ACTIVE
    require(not _RUNTIME_ACTIVE, "Nested external consumer contexts are forbidden")
    original = legacy.load_export_plan
    _RUNTIME_ACTIVE = True
    def loader(root, neural, *, rehash=True):
        value = load_plan(root, neural, rehash=rehash)
        require(plan is None or equal(value, plan), "Scoped external export plan changed")
        return value
    try:
        legacy.load_export_plan = loader
        yield
    finally:
        legacy.load_export_plan = original
        _RUNTIME_ACTIVE = False


def _worker_key(dataset, model, mode, replay):
    require((dataset, model) in legacy.JOBS and mode in ("fp32", "qdq") and type(replay) is bool,
            "Worker is outside the fixed 22-attempt matrix")
    return f"{dataset}_{model}_{mode}" + ("_replay" if replay else "")


def worker_invocation(export_root, dataset, model, mode, replay=False):
    _worker_key(dataset, model, mode, replay)
    root = canonical(Path(export_root))
    return [sys.executable, str(SELF), "run", "--export-root", str(root), "--dataset", dataset,
            "--model", model, "--mode", mode, *(["--replay"] if replay else [])]


def worker_receipt_path(export_root, dataset, model, mode, replay=False):
    return canonical(Path(export_root)) / "worker_receipts" / (_worker_key(dataset, model, mode, replay) + ".json")


def _worker_claim_path(root, dataset, model, mode, replay):
    return canonical(Path(root)) / "worker_claims" / (_worker_key(dataset, model, mode, replay) + ".json")


def _worker_output(root, dataset, model, mode, replay):
    _worker_key(dataset, model, mode, replay)
    return canonical(Path(root)) / ("replays" if replay else "") / dataset / model / mode


def _delegated(plan, dataset, model, mode, replay):
    root = Path(plan["output_root"])
    return legacy.exporter_invocation(Path(plan["run_dir"]), _worker_output(root, dataset, model, mode, replay),
        dataset, model, mode, 1024, 1000, 0.01, export_plan_path=root / "export_plan.json")


def _worker_claim_body(plan, dataset, model, mode, replay, identity, creator):
    return {"schema": 1, "kind": "spikeids_v5_external_export_worker_claim",
        "export_plan_sha256": plan["content_sha256"], "source_plan_sha256": plan["source_plan_sha256"],
        "dataset": dataset, "model": model, "mode": mode, "replay": replay,
        "output_dir": str(_worker_output(Path(plan["output_root"]), dataset, model, mode, replay)),
        "actual_os_argv": worker_invocation(Path(plan["output_root"]), dataset, model, mode, replay),
        "delegated_algorithm_argv": _delegated(plan, dataset, model, mode, replay),
        "worker_identity": identity, "registered_parent": creator, "parent_pid": creator["pid"],
        "no_retry_or_adoption": True}


def validate_worker_receipt(export_root, dataset, model, mode, return_code, replay=False):
    """Called immediately after true subprocess exit; returns original FD pins."""
    require(type(return_code) is int and return_code in (0, 1), "Worker did not finish normally (0 or 1)")
    root = canonical(Path(export_root), directory=True)
    preliminary, _ = _record(root / "export_plan.json")
    neural = legacy.read_plan(Path(preliminary["run_dir"]))
    plan = load_plan(root, neural, rehash=False)
    registration, registry_pins = _registration(plan)
    claim_path, receipt_path = (_worker_claim_path(root, dataset, model, mode, replay),
                               worker_receipt_path(root, dataset, model, mode, replay))
    claim, claim_pin = _record(claim_path)
    receipt, receipt_pin = _record(receipt_path)
    identity = claim.get("worker_identity")
    _identity_shape(identity)
    creator = registration["creator"]
    require(identity["pid"] != creator["pid"] and identity["boot_id"] == creator["boot_id"] and
            identity["cgroup"] == creator["cgroup"] and identity["cwd"] == str(ROOT) and
            identity["exe"] == str(Path(sys.executable).resolve()) and
            identity["cmdline"] == worker_invocation(root, dataset, model, mode, replay),
            "Worker identity is not the registered controller's direct execution")
    require(equal(claim, seal(_worker_claim_body(plan, dataset, model, mode, replay, identity, creator))),
            "Worker claim argv, parent, plan, or matrix member differs")
    expected_keys = {"schema", "kind", "claim", "export_plan_sha256", "actual_os_argv",
        "delegated_algorithm_argv", "return_code", "outcome", "error", "elapsed_ns", "content_sha256"}
    require(set(receipt) == expected_keys and type(receipt["schema"]) is int and receipt["schema"] == 1 and
            receipt["kind"] == "spikeids_v5_external_export_worker_receipt" and
            type(receipt["return_code"]) is int and receipt["return_code"] == return_code and
            type(receipt["elapsed_ns"]) is int and receipt["elapsed_ns"] > 0 and
            equal(receipt["claim"], {"path": str(claim_path), "snapshot": claim_pin}) and
            receipt["export_plan_sha256"] == plan["content_sha256"] and
            receipt["actual_os_argv"] == claim["actual_os_argv"] and
            receipt["delegated_algorithm_argv"] == claim["delegated_algorithm_argv"] and
            receipt["outcome"] == ("algorithm_returned" if return_code == 0 else "algorithm_raised") and
            (receipt["error"] is None if return_code == 0 else
             isinstance(receipt["error"], str) and bool(receipt["error"])),
            "Worker receipt disagrees with actual OS exit, original claim, or delegated call")
    pins = {**registry_pins, str(claim_path): claim_pin, str(receipt_path): receipt_pin}
    _assert_pins(pins)
    return pins


def run_worker(root, dataset, model, mode, replay=False):
    import export_verified as exporter
    root = canonical(Path(root), directory=True)
    preliminary, _ = _record(root / "export_plan.json")
    neural = legacy.read_plan(Path(preliminary["run_dir"]))
    plan = load_plan(root, neural, rehash=False)  # BEFORE checkpoint_context/model load.
    registration, registration_pin = _registration(plan)
    creator, identity = registration["creator"], _process_identity(os.getpid())
    actual_argv = [sys.executable, *sys.argv]
    require(actual_argv == worker_invocation(root, dataset, model, mode, replay) and
            identity["cmdline"] == actual_argv and identity["cwd"] == str(ROOT) and
            identity["exe"] == str(Path(sys.executable).resolve()) and
            os.getppid() == creator["pid"] and equal(_process_identity(os.getppid()), creator) and
            identity["cgroup"] == creator["cgroup"], "Worker is not the live registered controller's direct child")
    output = canonical(_worker_output(root, dataset, model, mode, replay))
    require(not output.exists(), "Worker output already exists; no replay/adoption")
    if replay:
        # Exactly one replay of a retained original scientific negative, never a success retry.
        validate_worker_receipt(root, dataset, model, mode, 1, replay=False)
        legacy.scientific_failure(_worker_output(root, dataset, model, mode, False), plan,
                                  dataset, model, mode, 1)
    for folder in (root / "worker_claims", root / "worker_receipts"):
        canonical(folder).mkdir(mode=0o700, exist_ok=True)
        canonical(folder, directory=True)
    _fsync_dir(root)
    claim_path = _worker_claim_path(root, dataset, model, mode, replay)
    receipt_path = worker_receipt_path(root, dataset, model, mode, replay)
    require(not receipt_path.exists() and not receipt_path.is_symlink(), "Worker receipt already exists")
    _write_once(claim_path, seal(_worker_claim_body(plan, dataset, model, mode, replay, identity, creator)))
    _, claim_pin = _record(claim_path)
    delegated = _delegated(plan, dataset, model, mode, replay)
    original_context, original_checkpoint, original_argv = (exporter.frozen_export_context,
                                                           exporter.checkpoint_context, sys.argv)
    def checkpoint_context(run_dir, data, arm):
        require(Path(run_dir) == Path(plan["run_dir"]) and (data, arm) == (dataset, model),
                "Delegated checkpoint selection changed")
        require(equal(load_plan(root, neural, rehash=False), plan), "Pre-checkpoint external context changed")
        _assert_pins({**registration_pin, str(claim_path): claim_pin})
        return original_checkpoint(run_dir, data, arm)
    def frozen_context(path, source_plan, data, arm, quantization, checkpoint):
        require(Path(path) == root / "export_plan.json" and equal(source_plan, neural) and
                (data, arm, quantization) == (dataset, model, mode), "Delegated frozen context differs")
        require(equal(load_plan(root, neural, rehash=False), plan), "External context changed after checkpoint load")
        expected = next(a for a in plan["attempts"] if
                        (a["dataset"], a["model"], a["mode"]) == (dataset, model, mode))
        require(sha256(canonical(Path(checkpoint), file=True)) == expected["checkpoint_sha256"],
                "Delegated checkpoint differs from registered seed-0 checkpoint")
        return plan
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
    # Receipt is outside the flat algorithm payload. Absence on crash is a hard infrastructure failure.
    _assert_pins({**registration_pin, str(claim_path): claim_pin})
    require(equal(load_plan(root, neural, rehash=False), plan), "Post-worker external context changed")
    _write_once(receipt_path, seal({"schema": 1, "kind": "spikeids_v5_external_export_worker_receipt",
        "claim": {"path": str(claim_path), "snapshot": claim_pin}, "export_plan_sha256": plan["content_sha256"],
        "actual_os_argv": actual_argv, "delegated_algorithm_argv": delegated, "return_code": code,
        "outcome": "algorithm_returned" if code == 0 else "algorithm_raised", "error": error,
        "elapsed_ns": time.monotonic_ns() - started}))
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    actions = parser.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run", allow_abbrev=False)
    run.add_argument("--export-root", type=Path, required=True)
    run.add_argument("--dataset", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--mode", choices=("fp32", "qdq"), required=True)
    run.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    return run_worker(args.export_root, args.dataset, args.model, args.mode, args.replay)


if __name__ == "__main__":
    raise SystemExit(main())
