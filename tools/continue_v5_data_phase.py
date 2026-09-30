#!/usr/bin/env python3
"""One-shot, fail-closed A -> fresh B -> independent data acceptance continuation.

The owner of the already-running A command must record its actual exec return
code. Scope disappearance and complete metadata are never substitutes for that
receipt. No training, retries, overwrite, process killing, or environment edits.
Linux/systemd/cgroup-v2 only; scientific validation is delegated to pinned tools.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import verify_v5_data as evidence

require = evidence.require
MEMORY_BYTES = 16 * 1024**3
PHASES = ("check_a", "prepare_b", "check_b", "acceptance")
SCOPE_PROPERTIES = ("LoadState", "ActiveState", "SubState", "Result", "InvocationID",
                    "ControlGroup", "MemoryMax", "MemorySwapMax")
RUNTIME_PROBE = (
    "import importlib.metadata,json,sys;"
    "print(json.dumps({'python':sys.version,'executable':sys.executable,"
    "'packages':{n:importlib.metadata.version(n) for n in "
    "['numpy','pandas','scikit-learn','pyarrow','torch']}}))"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_new(path: Path, value: dict) -> None:
    """Publish a complete file atomically, with Linux RENAME_NOREPLACE."""
    evidence._real_directory(path.parent)
    require(not path.exists() and not path.is_symlink(), f"Fresh output required: {path}")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(temporary), -100, os.fsencode(path), 1) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(path))
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def stable_record(path: Path) -> tuple[dict, dict]:
    before = evidence._file_snapshot(path)
    value = evidence.check_seal(evidence.load_json(path))
    require(evidence._file_snapshot(path) == before, f"Evidence changed while loading: {path}")
    return value, before


def directory_identity(path: Path) -> dict:
    real, status = evidence._real_directory(path)
    return {"path": str(real), "device": status.st_dev, "inode": status.st_ino}


def new_path(path: Path) -> Path:
    path = path.absolute()
    require(path.resolve(strict=False) == path, f"Noncanonical output path: {path}")
    evidence._real_directory(path.parent)
    require(not path.exists() and not path.is_symlink(), f"Fresh path required: {path}")
    return path


def nonoverlap(paths: list[Path]) -> None:
    for index, left in enumerate(paths):
        for right in paths[index + 1:]:
            require(not left.is_relative_to(right) and not right.is_relative_to(left),
                    f"Data/work roots overlap or alias: {left}, {right}")


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def process_identity(pid: int) -> dict | None:
    try:
        stat_text = Path(f"/proc/{pid}/stat").read_text()
        start_ticks = int(stat_text[stat_text.rfind(")") + 2:].split()[19])
        command = Path(f"/proc/{pid}/cmdline").read_bytes().rstrip(b"\0").decode().split("\0")
        cgroup = next(row.split("::", 1)[1] for row in
                      Path(f"/proc/{pid}/cgroup").read_text().splitlines() if row.startswith("0::"))
        result = {"pid": pid, "start_ticks": start_ticks, "boot_id": boot_id(),
                  "cmdline": command, "cwd": os.readlink(f"/proc/{pid}/cwd"),
                  "exe": os.readlink(f"/proc/{pid}/exe"), "cgroup": cgroup}
        later = Path(f"/proc/{pid}/stat").read_text()
        require(int(later[later.rfind(")") + 2:].split()[19]) == start_ticks,
                "PID changed during identity capture")
        return result
    except FileNotFoundError:
        return None


def scope_status(name: str) -> dict:
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.scope", name) is not None,
            "Invalid scope unit name")
    command = ["systemctl", "--user", "show", name]
    for key in SCOPE_PROPERTIES:
        command.extend(("-p", key))
    result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    require(result.returncode == 0, f"Cannot inspect scope {name}: {result.stderr.strip()}")
    values = dict(row.split("=", 1) for row in result.stdout.splitlines() if "=" in row)
    require(set(values) == set(SCOPE_PROPERTIES), "Scope inspection is incomplete")
    return {"name": name, **values}


def cgroup_sample(path: str) -> dict:
    relative = Path(path.lstrip("/"))
    require(path.startswith("/") and ".." not in relative.parts, "Invalid cgroup path")
    root = Path("/sys/fs/cgroup") / relative
    names = ("memory.max", "memory.swap.max", "memory.swap.current", "memory.current", "memory.peak")
    values = {name: int((root / name).read_text().strip()) for name in names}
    values["memory.events"] = {
        name: int(value) for name, value in
        (line.split() for line in (root / "memory.events").read_text().splitlines())
    }
    return {"path": path, **values}


def check_resources(sample: dict) -> None:
    require(all(type(sample.get(key)) is int for key in
                ("memory.max", "memory.swap.max", "memory.swap.current", "memory.current", "memory.peak")),
            "Resource counters must be exact integers, not booleans/floats")
    require(sample.get("memory.max") == MEMORY_BYTES and
            sample.get("memory.swap.max") == 0 and sample.get("memory.swap.current") == 0,
            "Data phase lacks the frozen 16-GiB/zero-swap cgroup bounds")
    events = sample.get("memory.events", {})
    require(all(type(events.get(key)) is int and events[key] == 0
                for key in ("oom", "oom_kill", "oom_group_kill")),
            "Data phase observed an OOM event; no retry is permitted")
    require(0 <= sample.get("memory.current", -1) <= MEMORY_BYTES and
            0 <= sample.get("memory.peak", -1) <= MEMORY_BYTES,
            "Data phase exceeded its memory bound")


def runtime(python: str) -> dict:
    result = subprocess.run([python, "-c", RUNTIME_PROBE], cwd=ROOT, capture_output=True,
                            text=True, timeout=60, check=True)
    return json.loads(result.stdout)


def package_inventory() -> list[str]:
    return [str(path) for path in sorted((ROOT / "spikeids_v5").glob("*.py"))]


def mandatory_inputs(raw_audit: Path, python: str, python_realpath: str) -> tuple[list[Path], list[tuple]]:
    """Derive required pins from trusted code/raw audit, never the plan's pin list."""
    package = ROOT / "spikeids_v5"
    audit, records, _ = evidence._load_raw_audit(raw_audit, package)
    provenance = package / "audit/iot23_provenance.json"
    evidence._load_iot_provenance(provenance, audit, package, ROOT)
    paths = [Path(value) for value in package_inventory()]
    paths += [Path(__file__).resolve(), Path(evidence.__file__).resolve(),
              ROOT / "tools/verify_iot23_provenance.py", raw_audit, provenance,
              Path(python_realpath), Path(python).parent.parent / "pyvenv.cfg"]
    raw_bindings = []
    for record in records.values():
        paths.append(evidence._contained_file(package, record["record"]["source_spec"]))
        for row in record["record"]["files"]:
            source = evidence._contained_file(ROOT / "data", row["path"])
            paths.append(source)
            raw_bindings.append((source, row))
    paths.extend(evidence._contained_file(ROOT / "data/iot23_origin", row["path"])
                 for row in records["iot23"]["source_spec"].get("origin_shards", []))
    return sorted(set(paths)), raw_bindings


def assert_snapshots(snapshots: dict, *, full: bool = True) -> None:
    for value, expected in snapshots.items():
        actual = (evidence._file_snapshot(Path(value)) if full else
                  evidence._stability_record(evidence._regular_file(Path(value))))
        compared = expected if full else {key: item for key, item in expected.items() if key != "sha256"}
        require(actual == compared, f"Consumed phase evidence changed: {value}")


def assert_pins(plan: dict, *, full: bool = True) -> None:
    require(boot_id() == plan["a_process"]["boot_id"], "Boot identity changed")
    require(package_inventory() == plan["package_inventory"], "Producer source inventory changed")
    require(str(Path(plan["python"]).resolve()) == plan["python_realpath"],
            "Python executable symlink target changed")
    for role, expected in plan["directories"].items():
        require(directory_identity(Path(expected["path"])) == expected,
                f"Pinned directory identity changed: {role}")
    for value, expected in plan["pins"].items():
        path = Path(value)
        if full:
            actual = evidence._file_snapshot(path)
        else:
            actual = evidence._stability_record(evidence._regular_file(path))
            expected = {key: item for key, item in expected.items() if key != "sha256"}
        require(actual == expected, f"Pinned input/source changed: {path}")
    if full:
        require(runtime(plan["python"]) == plan["runtime"], "Python/dependency runtime changed")


def _expected_a_command(identity: dict, args) -> None:
    command = identity["cmdline"]
    require(identity["cwd"] == str(ROOT) and len(command) >= 3 and
            (ROOT / command[1]).resolve() == ROOT / "spikeids_v5/suite.py" and
            command[2] == "prepare", "A PID is not the expected repository prepare command")
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False, exit_on_error=False)
    for name in ("data-dir", "cache-root", "raw-audit", "source-spec-dir"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--chunksize", type=int, default=65536)
    try:
        options = parser.parse_args(command[3:])
    except (SystemExit, argparse.ArgumentError) as exc:
        raise evidence.VerificationError("A prepare command is not canonical/formal") from exc
    expected = {"data_dir": ROOT / "data", "cache_root": args.cache_root_a,
                "raw_audit": args.raw_audit, "source_spec_dir": ROOT / "spikeids_v5/audit/source_specs"}
    require(options.chunksize == 65536 and all((ROOT / getattr(options, key)).resolve() == value
                                             for key, value in expected.items()),
            "A PID command does not bind the selected inputs/outputs")


def freeze(args) -> Path:
    args.raw_audit = args.raw_audit.absolute()
    args.cache_root_a, _ = evidence._real_directory(args.cache_root_a.absolute())
    args.cache_root_b = new_path(args.cache_root_b)
    work = new_path(args.work_dir)
    nonoverlap([args.cache_root_a, args.cache_root_b, work, ROOT / "data"])
    receipt = args.a_exit_record.absolute()
    require(receipt.parent == work and receipt.name == "a_exit.json",
            "Owner exit receipt must be the fresh work-dir/a_exit.json")
    identity = process_identity(args.a_pid)
    require(identity is not None, "A original process must be alive when freezing")
    _expected_a_command(identity, args)
    scope = scope_status(args.a_scope)
    require(scope["LoadState"] == "loaded" and scope["ActiveState"] == "active" and
            re.fullmatch(r"[0-9a-f]{32}", scope["InvocationID"]) is not None and
            scope["MemoryMax"] == str(MEMORY_BYTES) and scope["MemorySwapMax"] == "0" and
            identity["cgroup"] == scope["ControlGroup"],
            "A scope identity/bounds do not match its original process")
    sample = cgroup_sample(scope["ControlGroup"])
    check_resources(sample)
    python = str(Path(args.python).absolute())
    python_realpath = str(Path(python).resolve())
    require(identity["exe"] == python_realpath, "A and B Python executables differ")
    provenance = ROOT / "spikeids_v5/audit/iot23_provenance.json"
    paths, raw_bindings = mandatory_inputs(args.raw_audit, python, python_realpath)
    pins = {str(path): evidence._file_snapshot(path) for path in paths}
    require(all(pins[str(path)]["sha256"] == row["sha256"] and
                pins[str(path)]["bytes"] == row["bytes"] for path, row in raw_bindings),
            "Current raw sources differ from the selected raw audit")
    plan = {"kind": "spikeids_v5_data_continuation_plan", "schema": 1,
            "created_at": utc_now(), "root": str(ROOT), "work_dir": str(work),
            "cache_root_a": str(args.cache_root_a), "cache_root_b": str(args.cache_root_b),
            "raw_audit": str(args.raw_audit), "iot_provenance": str(provenance),
            "a_exit_record": str(receipt), "acceptance": str(work / "data_acceptance.json"),
            "a_process": identity, "a_scope": scope, "a_cgroup_initial": sample,
            "python": python, "python_realpath": python_realpath, "runtime": runtime(python),
            "package_inventory": package_inventory(), "pins": pins,
            "directories": {"a": directory_identity(args.cache_root_a),
                            "b_parent": directory_identity(args.cache_root_b.parent),
                            "data": directory_identity(ROOT / "data"),
                            "repository": directory_identity(ROOT)},
            "memory_bytes": MEMORY_BYTES, "swap_bytes": 0, "phases": list(PHASES),
            "automatic_retry": False, "training_authorized": False}
    require(process_identity(args.a_pid) == identity, "A process identity changed during freeze")
    require(scope_status(args.a_scope)["InvocationID"] == scope["InvocationID"],
            "A scope invocation changed during freeze")
    assert_pins(plan)
    new_path(args.cache_root_b)
    work.mkdir(mode=0o700)
    plan["directories"]["work"] = directory_identity(work)
    path = work / "plan.json"
    write_new(path, evidence.seal(plan))
    return path


def load_plan(path: Path) -> tuple[dict, dict]:
    plan, snapshot = stable_record(path.absolute())
    require(plan.get("kind") == "spikeids_v5_data_continuation_plan" and plan.get("schema") == 1 and
            plan.get("root") == str(ROOT) and plan.get("phases") == list(PHASES) and
            plan.get("memory_bytes") == MEMORY_BYTES and plan.get("swap_bytes") == 0 and
            plan.get("automatic_retry") is False and plan.get("training_authorized") is False,
            "Continuation plan contract differs")
    work = Path(plan["work_dir"])
    require(path.absolute() == work / "plan.json" and
            Path(plan["a_exit_record"]) == work / "a_exit.json" and
            Path(plan["acceptance"]) == work / "data_acceptance.json",
            "Continuation evidence paths are not canonical")
    nonoverlap([Path(plan["cache_root_a"]), Path(plan["cache_root_b"]), work, ROOT / "data"])
    require(type(plan["a_process"]["pid"]) is int and plan["a_process"]["pid"] > 0 and
            type(plan["a_process"]["start_ticks"]) is int and plan["a_process"]["start_ticks"] > 0,
            "Malformed A process identity")
    require(type(plan["schema"]) is int and type(plan["memory_bytes"]) is int and
            type(plan["swap_bytes"]) is int and
            plan["iot_provenance"] == str(ROOT / "spikeids_v5/audit/iot23_provenance.json"),
            "Plan policy types/provenance path differ")
    paths, raw_bindings = mandatory_inputs(Path(plan["raw_audit"]), plan["python"], plan["python_realpath"])
    require(set(plan["pins"]) == {str(item) for item in paths} and
            plan["package_inventory"] == package_inventory(), "Mandatory pin inventory differs")
    require(all(plan["pins"][str(item)]["sha256"] == row["sha256"] and
                plan["pins"][str(item)]["bytes"] == row["bytes"] for item, row in raw_bindings),
            "Pinned raw inputs differ from the raw audit")
    directories = {"a": Path(plan["cache_root_a"]), "b_parent": Path(plan["cache_root_b"]).parent,
                   "data": ROOT / "data", "repository": ROOT, "work": work}
    require(set(plan["directories"]) == set(directories) and all(
            plan["directories"][role] == directory_identity(directory) for role, directory in directories.items()),
            "Mandatory directory identity inventory differs")
    _expected_a_command(plan["a_process"], argparse.Namespace(
        cache_root_a=Path(plan["cache_root_a"]), raw_audit=Path(plan["raw_audit"])))
    require(plan["a_process"]["exe"] == plan["python_realpath"] and
            plan["a_process"]["cgroup"] == plan["a_scope"]["ControlGroup"] and
            re.fullmatch(r"[0-9a-f]{32}", plan["a_scope"]["InvocationID"]) is not None,
            "Frozen A process/scope/Python bindings differ")
    check_resources(plan["a_cgroup_initial"])
    return plan, snapshot


def _a_ended(plan: dict, *, allow_failed_scope: bool = False) -> tuple[bool, dict, dict | None]:
    require(boot_id() == plan["a_process"]["boot_id"], "Boot identity changed")
    process = process_identity(plan["a_process"]["pid"])
    if process is not None:
        require(process == plan["a_process"], "A PID was reused or its identity changed")
    scope = scope_status(plan["a_scope"]["name"])
    present = scope["LoadState"] != "not-found"
    if present:
        require(scope["InvocationID"] == plan["a_scope"]["InvocationID"],
                "A scope invocation was replaced")
        require(allow_failed_scope or scope["Result"] in ("success", ""), "A systemd scope failed")
    require(not (process is not None and not present), "A process escaped/disappeared from its scope")
    sample = None
    if present and scope["ActiveState"] in ("active", "activating", "deactivating"):
        require(scope["ControlGroup"] == plan["a_scope"]["ControlGroup"], "A cgroup path changed")
        try:
            sample = cgroup_sample(scope["ControlGroup"])
            check_resources(sample)
        except FileNotFoundError:
            # A legitimate exit can remove the cgroup between its status read
            # and counter read. Recheck *both* identities, never infer success.
            after_process = process_identity(plan["a_process"]["pid"])
            after_scope = scope_status(plan["a_scope"]["name"])
            require(after_process is None and after_scope["LoadState"] == "not-found",
                    "A cgroup vanished without original process/scope completion")
            return True, after_scope, None
    ended = process is None and (not present or scope["ActiveState"] in ("inactive", "failed"))
    return ended, scope, sample


def record_a_exit(path: Path, return_code: int) -> Path:
    plan, plan_snapshot = load_plan(path)
    require(type(return_code) is int, "Owner return code must be an integer, not bool")
    ended, scope, _sample = _a_ended(plan, allow_failed_scope=True)
    require(ended, "Cannot record A completion while its process or scope is still alive")
    require(return_code != 0 or scope["LoadState"] == "not-found" or scope["Result"] in ("success", ""),
            "A zero exit code contradicts its failed scope")
    require(evidence._file_snapshot(path) == plan_snapshot, "Plan changed during owner receipt")
    receipt = evidence.seal({"kind": "spikeids_v5_owner_exec_exit_receipt", "schema": 1,
                            "plan_sha256": plan["content_sha256"], "a_process": plan["a_process"],
                            "a_scope_invocation_id": plan["a_scope"]["InvocationID"],
                            "return_code": return_code, "recorded_at": utc_now(),
                            "scope_after_exit": scope,
                            "source": "owner_observed_exec_return_code_not_inferred_from_artifacts"})
    target = Path(plan["a_exit_record"])
    write_new(target, receipt)
    return target


def load_a_receipt(plan: dict) -> tuple[dict, dict]:
    receipt, snapshot = stable_record(Path(plan["a_exit_record"]))
    require(receipt.get("kind") == "spikeids_v5_owner_exec_exit_receipt" and receipt.get("schema") == 1 and
            receipt.get("plan_sha256") == plan["content_sha256"] and
            receipt.get("a_process") == plan["a_process"] and
            receipt.get("a_scope_invocation_id") == plan["a_scope"]["InvocationID"] and
            receipt.get("source") == "owner_observed_exec_return_code_not_inferred_from_artifacts" and
            type(receipt.get("return_code")) is int,
            "Owner A-exit receipt identity/type/source differs")
    require(receipt["return_code"] == 0, "Owner observed A failure; continuation is forbidden")
    return receipt, snapshot


def wait_for_a(plan: dict, *, poll_seconds: float = 5.0) -> tuple[dict, dict]:
    last_sample = plan["a_cgroup_initial"]
    while True:
        assert_pins(plan, full=False)
        ended, scope, sample = _a_ended(plan)
        if sample is not None:
            last_sample = sample
        exists = Path(plan["a_exit_record"]).exists()
        if exists:
            receipt, snapshot = load_a_receipt(plan)
            require(ended, "A exit receipt appeared before actual process/scope completion")
            return {"receipt": receipt, "scope_after_exit": scope,
                    "last_observed_cgroup": last_sample,
                    "note": "Owner receipt proves exec status; last sample is not a final removed-cgroup measurement"}, snapshot
        print(json.dumps({"phase": "waiting_a", "status": "awaiting_owner_exit_receipt" if ended else
                          "original_process_or_scope_running", "time": utc_now()}), flush=True)
        time.sleep(poll_seconds)


def _raw_records(plan: dict) -> tuple[dict, dict, int]:
    audit, records, audit_mtime = evidence._load_raw_audit(Path(plan["raw_audit"]), ROOT / "spikeids_v5")
    audit_binding = {"path": plan["raw_audit"], "sha256": evidence.sha256(Path(plan["raw_audit"])),
                     "content_sha256": audit["content_sha256"],
                     "audit_implementation_sha256": audit["audit_implementation_sha256"]}
    for raw in records.values():
        raw["record"]["_audit_data_loader_sha256"] = audit["data_loader_sha256"]
        raw["raw_audit_binding"] = audit_binding
    return audit, records, audit_mtime


def check_cache_root(plan: dict, role: str) -> dict:
    """Actual producer open plus independent structural checks; not raw acceptance."""
    root = Path(plan[f"cache_root_{role}"])
    root_id = directory_identity(root)
    _audit, records, audit_mtime = _raw_records(plan)
    before = evidence._cache_root_stability(root, after_ns=audit_mtime)
    inventory = evidence._cache_root_inventory(root, after_ns=audit_mtime)
    sys.path.insert(0, str(ROOT / "spikeids_v5"))
    from data_loaders import open_cache
    datasets = {}
    for name in evidence.DATASETS:
        producer_metadata, producer_arrays = open_cache(root / name)
        metadata, arrays, summary = evidence._validate_one_cache(root, name, records[name], ROOT / "spikeids_v5")
        require(metadata == producer_metadata, f"Producer/independent metadata differs: {role}/{name}")
        datasets[name] = summary
        del arrays, producer_arrays
    require(evidence._cache_root_stability(root, after_ns=audit_mtime) == before and
            evidence._cache_root_inventory(root, after_ns=audit_mtime) == inventory and
            directory_identity(root) == root_id,
            f"Cache changed during structural checks: {role}")
    return {"role": role, "root": str(root), "root_identity": root_id, "datasets": datasets,
            "inventory": inventory, "stability": before, "audit_mtime_ns": audit_mtime,
            "passed": True, "full_raw_acceptance": False}


def assert_cache_unchanged(result: dict) -> None:
    root = Path(result["root"])
    require(directory_identity(root) == result["root_identity"] and
            evidence._cache_root_stability(root, after_ns=result["audit_mtime_ns"]) == result["stability"] and
            evidence._cache_root_inventory(root, after_ns=result["audit_mtime_ns"]) == result["inventory"],
            f"Previously checked cache changed: {root}")


def assert_cache_stat_unchanged(result: dict) -> None:
    root = Path(result["root"])
    require(directory_identity(root) == result["root_identity"] and
            evidence._cache_root_stability(root, after_ns=result["audit_mtime_ns"]) == result["stability"],
            f"Previously checked cache changed during end checks: {root}")


def phase_command(plan: dict, phase: str) -> list[str]:
    if phase == "prepare_b":
        return [plan["python"], str(ROOT / "spikeids_v5/suite.py"), "prepare",
                "--data-dir", str(ROOT / "data"), "--cache-root", plan["cache_root_b"],
                "--raw-audit", plan["raw_audit"], "--source-spec-dir",
                str(ROOT / "spikeids_v5/audit/source_specs"), "--chunksize", "65536"]
    require(phase == "acceptance", "Unexpected command-producing continuation phase")
    return [plan["python"], str(ROOT / "tools/verify_v5_data.py"), "--raw-audit", plan["raw_audit"],
            "--iot-provenance", plan["iot_provenance"], "--cache-root-a", plan["cache_root_a"],
            "--cache-root-b", plan["cache_root_b"], "--output", plan["acceptance"]]


def scope_name(plan: dict, phase: str) -> str:
    require(phase in PHASES, "Unknown data continuation phase")
    return f"spikeids-data-{plan['content_sha256'][:20]}-{phase.replace('_', '-')}.scope"


def worker_command(plan: dict, plan_path: Path, phase: str) -> list[str]:
    return [plan["python"], str(Path(__file__).resolve()), "_scope-worker",
            "--plan", str(plan_path), "--phase", phase]


def validate_worker_identity(worker: dict, plan: dict, plan_path: Path, phase: str) -> None:
    require(set(worker) == {"pid", "start_ticks", "boot_id", "cmdline", "cwd", "exe", "cgroup"} and
            type(worker.get("pid")) is int and worker["pid"] > 0 and
            type(worker.get("start_ticks")) is int and worker["start_ticks"] > 0 and
            worker["pid"] != plan["a_process"]["pid"] and
            worker["boot_id"] == plan["a_process"]["boot_id"] and
            worker["cmdline"] == worker_command(plan, plan_path, phase) and
            worker["cwd"] == str(ROOT) and worker["exe"] == plan["python_realpath"],
            f"{phase} worker process identity/command differs")


def phase_worker(plan_path: Path, phase: str) -> int:
    plan, plan_snapshot = load_plan(plan_path)
    require(phase in PHASES, "Invalid scope worker phase")
    work = Path(plan["work_dir"])
    ticket, ticket_snapshot = stable_record(work / f"{phase}_started.json")
    require(ticket.get("plan_sha256") == plan["content_sha256"] and ticket.get("phase") == phase and
            ticket.get("scope") == scope_name(plan, phase), "Scope worker lacks its exact one-shot phase ticket")
    _receipt, receipt_snapshot = load_a_receipt(plan)
    started, started_snapshot = stable_record(work / "run_started.json")
    require(started.get("plan_sha256") == plan["content_sha256"], "Scope worker lacks an active parent run")
    target = work / f"{phase}_exit.json"
    new_path(target)
    current = process_identity(os.getpid())
    require(current is not None, "Cannot capture scope worker identity")
    validate_worker_identity(current, plan, plan_path, phase)
    scope = scope_status(scope_name(plan, phase))
    require(scope["LoadState"] == "loaded" and scope["ActiveState"] == "active" and
            current["cgroup"] == scope["ControlGroup"] and scope["InvocationID"],
            "Worker is not in its intended fresh systemd scope")
    initial = cgroup_sample(current["cgroup"])
    report = {"kind": "spikeids_v5_data_phase_exit", "schema": 1,
              "plan_sha256": plan["content_sha256"], "phase": phase,
              "scope": scope, "worker": current, "initial_cgroup": initial,
              "started_at": utc_now(), "passed": False, "return_code": None}
    code = 1
    try:
        check_resources(initial)
        assert_pins(plan)
        if phase in ("check_a", "check_b"):
            report["cache_check"] = check_cache_root(plan, phase[-1])
            report["return_code"] = 0
        else:
            command = phase_command(plan, phase)
            report["command"] = command
            with (work / f"{phase}.log").open("xb") as stream:
                completed = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                           check=False)
                stream.flush()
                os.fsync(stream.fileno())
            report["return_code"] = completed.returncode
            report["log_sha256"] = evidence.sha256(work / f"{phase}.log")
            require(completed.returncode == 0, f"{phase} command failed with {completed.returncode}")
        assert_pins(plan)
        assert_snapshots({str(plan_path): plan_snapshot, str(work / f"{phase}_started.json"): ticket_snapshot,
                          str(work / "run_started.json"): started_snapshot,
                          plan["a_exit_record"]: receipt_snapshot})
        require(process_identity(os.getpid()) == current, "Scope worker identity/cgroup changed")
        final = cgroup_sample(current["cgroup"])
        check_resources(final)
        report["final_cgroup"] = final
        report["passed"] = True
        code = 0
    except BaseException as exc:
        report["error"] = repr(exc)
        try:
            report["final_cgroup"] = cgroup_sample(current["cgroup"])
        except OSError as resource_error:
            report["resource_error"] = repr(resource_error)
    report["finished_at"] = utc_now()
    write_new(target, evidence.seal(report))
    return code


def run_phase(plan: dict, plan_path: Path, phase: str) -> dict:
    name = scope_name(plan, phase)
    require(scope_status(name)["LoadState"] == "not-found", "Continuation scope name already exists")
    work = Path(plan["work_dir"])
    new_path(work / f"{phase}_exit.json")
    write_new(work / f"{phase}_started.json", evidence.seal({"plan_sha256": plan["content_sha256"],
              "phase": phase, "scope": name, "started_at": utc_now()}))
    snapshots = {str(work / f"{phase}_started.json"): evidence._file_snapshot(work / f"{phase}_started.json")}
    command = ["systemd-run", "--user", "--scope", "--quiet", "--unit", name,
               "-p", f"MemoryMax={MEMORY_BYTES}", "-p", "MemorySwapMax=0",
               *worker_command(plan, plan_path, phase)]
    with (work / f"{phase}_scope.log").open("xb") as stream:
        completed = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False)
        stream.flush()
        os.fsync(stream.fileno())
    require(completed.returncode == 0, f"{phase} scope failed: rc={completed.returncode}")
    report, snapshot = stable_record(work / f"{phase}_exit.json")
    snapshots[str(work / f"{phase}_exit.json")] = snapshot
    snapshots[str(work / f"{phase}_scope.log")] = evidence._file_snapshot(work / f"{phase}_scope.log")
    require(report.get("kind") == "spikeids_v5_data_phase_exit" and report.get("schema") == 1 and
            report.get("plan_sha256") == plan["content_sha256"] and report.get("phase") == phase and
            report.get("passed") is True and type(report.get("return_code")) is int and
            report["return_code"] == 0 and report.get("scope", {}).get("name") == name and
            re.fullmatch(r"[0-9a-f]{32}", report.get("scope", {}).get("InvocationID", "")) is not None,
            f"{phase} worker completion evidence is invalid")
    check_resources(report["initial_cgroup"])
    check_resources(report["final_cgroup"])
    validate_worker_identity(report.get("worker", {}), plan, plan_path, phase)
    ended_scope = scope_status(name)
    require(ended_scope["LoadState"] == "not-found" or
            (ended_scope["InvocationID"] == report["scope"]["InvocationID"] and
             ended_scope["ActiveState"] == "inactive" and ended_scope["Result"] in ("success", "")),
            f"{phase} scope still has processes, failed, or was replaced")
    require(report["worker"]["boot_id"] == plan["a_process"]["boot_id"] and
            report["worker"]["cgroup"] == report["scope"]["ControlGroup"] ==
            report["initial_cgroup"]["path"] == report["final_cgroup"]["path"],
            f"{phase} scope/worker resource bindings differ")
    if phase in ("prepare_b", "acceptance"):
        snapshots[str(work / f"{phase}.log")] = evidence._file_snapshot(work / f"{phase}.log")
        require(report.get("command") == phase_command(plan, phase) and
                report.get("log_sha256") == snapshots[str(work / f"{phase}.log")]["sha256"],
                f"{phase} command/log evidence differs")
    else:
        result = report.get("cache_check", {})
        require(result.get("passed") is True and result.get("role") == phase[-1] and
                result.get("root") == plan[f"cache_root_{phase[-1]}"] and
                set(result.get("datasets", {})) == set(evidence.DATASETS),
                f"{phase} structural result is incomplete")
    assert_pins(plan)
    assert_snapshots(snapshots)
    return {**report, "consumed_evidence": snapshots}


def check_acceptance(plan: dict, a_check: dict, b_check: dict) -> dict:
    report, snapshot = stable_record(Path(plan["acceptance"]))
    expected = set(evidence.SEMANTIC_CHECK_KEYS) | {"all_passed"}
    require(report.get("kind") == "spikeids_v5_data_acceptance" and report.get("acceptance_schema") == 1 and
            report.get("data_acceptance_passed") is True and report.get("byte_identical_rebuilds") is True and
            report.get("two_distinct_fresh_roots") is True and set(report.get("datasets", {})) == set(evidence.DATASETS),
            "Independent data acceptance did not pass its exact scope")
    for dataset, item in report["datasets"].items():
        checks = item.get("semantic_checks", {})
        require(set(checks) == expected and all(value is True for value in checks.values()),
                f"Independent semantic gates incomplete: {dataset}")
        require([row["resolved_root"] for row in item["rebuilds"]] ==
                [str(Path(plan[f"cache_root_{role}"]) / dataset) for role in ("a", "b")],
                f"Acceptance names different rebuild roots: {dataset}")
        for key in ("data_fingerprint", "raw_rows", "counts", "features", "class_names",
                    "realized_pattern_fractions", "raw_model_view_sha256"):
            require(item.get(key) == a_check["datasets"][dataset][key] == b_check["datasets"][dataset][key],
                    f"Acceptance/cache summary differs: {dataset}/{key}")
    require(report["independent_verifier"] ==
            {"path": str(ROOT / "tools/verify_v5_data.py"),
             "sha256": plan["pins"][str(ROOT / "tools/verify_v5_data.py")]["sha256"]} and
            report["raw_audit"]["path"] == plan["raw_audit"] and
            report["raw_audit"]["sha256"] == plan["pins"][plan["raw_audit"]]["sha256"] and
            report.get("producer") == {"path": str(ROOT / "spikeids_v5/data_loaders.py"),
                "sha256": plan["pins"][str(ROOT / "spikeids_v5/data_loaders.py")]["sha256"]} and
            report.get("upstream_provenance", {}).get("path") == plan["iot_provenance"] and
            report["upstream_provenance"]["sha256"] == plan["pins"][plan["iot_provenance"]]["sha256"],
            "Acceptance producer/raw/verifier identity differs")
    limitations = {"capture_generalization_established", "device_generalization_established",
                   "time_generalization_established", "upstream_preprocessing_verified",
                   "external_authenticity_verified"}
    require(set(report.get("limitations", {})) == limitations and
            all(value is False for value in report["limitations"].values()),
            "Acceptance limitations were omitted or overclaimed")
    return {"path": plan["acceptance"], "snapshot": snapshot,
            "content_sha256": report["content_sha256"]}


def run(plan_path: Path) -> dict:
    plan_path = plan_path.absolute()
    plan, plan_snapshot = load_plan(plan_path)
    work = Path(plan["work_dir"])
    # Atomic exclusive publication is both the one-shot and concurrent-run guard.
    write_new(work / "run_started.json", evidence.seal({"plan_sha256": plan["content_sha256"],
                                                       "started_at": utc_now(), "pid": os.getpid()}))
    consumed = {str(work / "run_started.json"): evidence._file_snapshot(work / "run_started.json")}

    def phase_run(phase: str) -> dict:
        report = run_phase(plan, plan_path, phase)
        require(isinstance(report.get("consumed_evidence"), dict) and report["consumed_evidence"],
                "Phase did not return its consumed evidence bindings")
        consumed.update(report["consumed_evidence"])
        return report
    stage = "preflight"
    try:
        assert_pins(plan)
        new_path(Path(plan["cache_root_b"]))
        new_path(Path(plan["acceptance"]))
        stage = "waiting_for_original_a_and_owner_receipt"
        completion, receipt_snapshot = wait_for_a(plan)
        write_new(work / "a_completion.json", evidence.seal(completion))
        consumed[str(work / "a_completion.json")] = evidence._file_snapshot(work / "a_completion.json")
        assert_pins(plan)
        require(evidence._file_snapshot(plan_path) == plan_snapshot, "Plan changed while waiting for A")
        stage = "check_a"
        a_check = phase_run(stage)["cache_check"]
        new_path(Path(plan["cache_root_b"]))
        new_path(Path(plan["acceptance"]))
        Path(plan["cache_root_b"]).mkdir(mode=0o700)
        b_identity = directory_identity(Path(plan["cache_root_b"]))
        require((b_identity["device"], b_identity["inode"]) !=
                (a_check["root_identity"]["device"], a_check["root_identity"]["inode"]),
                "A and B directory identities alias")
        stage = "prepare_b"
        phase_run(stage)
        require(directory_identity(Path(plan["cache_root_b"])) == b_identity,
                "Fresh B root was replaced during preparation")
        assert_cache_unchanged(a_check)
        stage = "check_b"
        b_check = phase_run(stage)["cache_check"]
        assert_cache_unchanged(a_check)
        new_path(Path(plan["acceptance"]))
        stage = "acceptance"
        phase_run(stage)
        accepted = check_acceptance(plan, a_check, b_check)
        assert_pins(plan)
        assert_cache_unchanged(a_check)
        assert_cache_unchanged(b_check)
        require(evidence._file_snapshot(plan_path) == plan_snapshot and
                evidence._file_snapshot(Path(plan["a_exit_record"])) == receipt_snapshot and
                evidence._file_snapshot(Path(plan["acceptance"])) == accepted["snapshot"],
                "Plan/owner receipt/acceptance changed before final completion")
        consumed.update({str(plan_path): plan_snapshot, plan["a_exit_record"]: receipt_snapshot,
                         plan["acceptance"]: accepted["snapshot"]})
        assert_snapshots(consumed)
        # All expensive hashing precedes this final, cheap identity/stat pass.
        # ctime/inode/size/inventory catch even mutations whose bytes were restored.
        assert_cache_stat_unchanged(a_check)
        assert_cache_stat_unchanged(b_check)
        assert_snapshots(consumed, full=False)
        assert_pins(plan, full=False)
        result = evidence.seal({"kind": "spikeids_v5_data_continuation_complete", "schema": 1,
                                "plan_sha256": plan["content_sha256"], "passed": True,
                                "data_acceptance": accepted, "training_started": False,
                                "consumed_evidence": consumed,
                                "finished_at": utc_now()})
        write_new(work / "complete.json", result)
        return result
    except BaseException as exc:
        write_new(work / "failed.json", evidence.seal({"kind": "spikeids_v5_data_continuation_failure",
                  "schema": 1, "plan_sha256": plan["content_sha256"], "stage": stage,
                  "passed": False, "error": repr(exc), "automatic_retry": False,
                  "training_started": False, "finished_at": utc_now()}))
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="action", required=True)
    frozen = commands.add_parser("freeze", allow_abbrev=False)
    frozen.add_argument("--a-pid", required=True, type=int)
    frozen.add_argument("--a-scope", required=True)
    frozen.add_argument("--a-exit-record", required=True, type=Path)
    frozen.add_argument("--raw-audit", required=True, type=Path)
    frozen.add_argument("--cache-root-a", required=True, type=Path)
    frozen.add_argument("--cache-root-b", required=True, type=Path)
    frozen.add_argument("--work-dir", required=True, type=Path)
    frozen.add_argument("--python", default=str(ROOT / ".venv/bin/python"))
    continuation = commands.add_parser("run", allow_abbrev=False)
    continuation.add_argument("--plan", required=True, type=Path)
    owner = commands.add_parser("record-a-exit", allow_abbrev=False)
    owner.add_argument("--plan", required=True, type=Path)
    owner.add_argument("--return-code", required=True, type=int)
    worker = commands.add_parser("_scope-worker", allow_abbrev=False)
    worker.add_argument("--plan", required=True, type=Path)
    worker.add_argument("--phase", required=True, choices=PHASES)
    args = parser.parse_args()
    if args.action == "freeze":
        print(freeze(args), flush=True)
    elif args.action == "record-a-exit":
        print(record_a_exit(args.plan, args.return_code), flush=True)
    elif args.action == "_scope-worker":
        raise SystemExit(phase_worker(args.plan.absolute(), args.phase))
    else:
        print(json.dumps(run(args.plan), sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
