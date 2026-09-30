"""One manifest, bounded GPU workers, global fit -> independent repeat -> test barrier.

No remote writes, package installation, process killing, or historical-result reuse.
Command failures propagate. Every job's complete output is logged.  Concurrency
is frozen in the plan and occurs only across independent jobs; seeds within a
job retain their exact declared order.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import contextlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import threading
import time
from contracts import *
from data_loaders import prepare, open_cache
from evidence import read_plan, load_fit, load_result
from resource_evidence import cgroup_sample, cgroup_violations, process_scope_violations

DATA_ACCEPTANCE_CHECKS = {
    "inventory_complete", "seals_valid", "code_binding_valid", "shapes_valid",
    "dtypes_valid", "finite_values", "canonical_zero", "id_accounting_exact",
    "class_support_complete", "multiplicity_valid", "exclusion_reasons_valid",
    "zero_group_overlap", "zero_final_fp32_overlap",
    "raw_model_view_fingerprint_valid", "frozen_partition_and_closure_replayed", "all_passed",
}
DATA_ACCEPTANCE_LIMITATIONS = {
    "capture_generalization_established", "device_generalization_established",
    "time_generalization_established", "upstream_preprocessing_verified",
    "external_authenticity_verified",
}


def _sealed_evidence_file(path: Path, label: str) -> tuple[Path, dict, str]:
    absolute = Path(path).absolute()
    require(absolute.resolve() == absolute and absolute.is_file() and
            not absolute.is_symlink() and absolute.stat().st_nlink == 1,
            f"{label} must be a regular, non-symlink, non-hardlinked canonical file")
    record = load_json(absolute)
    check_seal(record)
    return absolute, record, sha256(absolute)


def load_data_acceptance(raw_audit_path: Path, acceptance_path: Path,
                         cache_root: Path) -> tuple[dict, dict]:
    raw_path, raw, raw_sha = _sealed_evidence_file(raw_audit_path, "Raw audit")
    acceptance_file, acceptance, acceptance_sha = _sealed_evidence_file(
        acceptance_path, "Data acceptance report",
    )
    require(raw.get("raw_source_audit_passed") is True and
            raw.get("data_acceptance_passed") is False,
            "Raw-source audit scope/status is invalid")
    require(acceptance.get("kind") == "spikeids_v5_data_acceptance" and
            acceptance.get("acceptance_schema") == 1 and
            acceptance.get("data_acceptance_passed") is True and
            acceptance.get("two_distinct_fresh_roots") is True and
            acceptance.get("byte_identical_rebuilds") is True,
            "Independent data acceptance has not passed")
    require(set(acceptance.get("datasets", {})) == set(DATASETS),
            "Data acceptance dataset set is incomplete")
    for dataset in DATASETS:
        checks = acceptance["datasets"][dataset].get("semantic_checks", {})
        require(set(checks) == DATA_ACCEPTANCE_CHECKS and
                all(value is True for value in checks.values()),
                f"Data acceptance semantic gate set is incomplete: {dataset}")
    require(set(acceptance.get("limitations", {})) == DATA_ACCEPTANCE_LIMITATIONS and
            all(value is False for value in acceptance["limitations"].values()),
            "Data acceptance limitation boundary is missing or overclaimed")
    raw_binding = acceptance.get("raw_audit", {})
    require(raw_binding.get("path") == str(raw_path) and
            raw_binding.get("sha256") == raw_sha and
            raw_binding.get("content_sha256") == raw["content_sha256"] and
            raw_binding.get("audit_implementation_sha256") ==
            raw["audit_implementation_sha256"] and
            raw_binding.get("raw_source_audit_passed") is True,
            "Data acceptance does not bind the selected raw audit")
    verifier = acceptance.get("independent_verifier", {})
    verifier_path = Path(verifier.get("path", "")).absolute()
    require(verifier_path.resolve() == verifier_path and verifier_path.is_file() and
            verifier_path == (PACKAGE.parent/"tools"/"verify_v5_data.py").resolve() and
            not verifier_path.is_symlink() and verifier_path.stat().st_nlink == 1 and
            verifier.get("sha256") == sha256(verifier_path),
            "Independent data verifier source binding is stale")
    root = Path(cache_root).resolve()
    require(raw.get("audit_implementation_sha256") == sha256(PACKAGE/"audit_data.py") and
            raw.get("data_loader_sha256") == sha256(PACKAGE/"data_loaders.py") and
            acceptance.get("producer") == {
                "path": str((PACKAGE/"data_loaders.py").resolve()),
                "sha256": sha256(PACKAGE/"data_loaders.py")},
            "Raw audit or acceptance is bound to stale producer code")
    upstream = acceptance.get("upstream_provenance", {})
    upstream_path, upstream_record, upstream_sha = _sealed_evidence_file(
        Path(upstream.get("path", "")), "IoT provenance report")
    require(upstream.get("sha256") == upstream_sha and
            upstream.get("content_sha256") == upstream_record["content_sha256"] and
            upstream.get("comparison_passed") is True and
            upstream_record.get("comparison_passed") is True,
            "IoT provenance binding is stale or incomplete")
    binding = {
        "raw_audit": {"path": str(raw_path), "sha256": raw_sha,
                      "content_sha256": raw["content_sha256"]},
        "data_acceptance": {"path": str(acceptance_file), "sha256": acceptance_sha,
                            "content_sha256": acceptance["content_sha256"]},
        "independent_verifier": verifier,
        "upstream_provenance": upstream,
        "accepted_cache_root": str(root),
    }
    return acceptance, binding


def validate_plan_data_evidence(plan: dict) -> None:
    binding = plan.get("data_evidence")
    require(isinstance(binding, dict), "Frozen plan lacks data evidence")
    if binding.get("status") == "nonformal_fixture_bypass":
        require(plan.get("protocol_role") == "smoke_only" and
                binding.get("paper_finalization_allowed") is False,
                "Nonformal data-evidence bypass escaped smoke scope")
        return
    _, current_binding = load_data_acceptance(
        Path(binding["raw_audit"]["path"]),
        Path(binding["data_acceptance"]["path"]),
        Path(binding["accepted_cache_root"]),
    )
    require(current_binding == binding,
            "Frozen data evidence no longer matches current accepted inputs")
    raw_path, raw, raw_sha = _sealed_evidence_file(
        Path(binding["raw_audit"]["path"]), "Frozen raw audit",
    )
    acceptance_path, acceptance, acceptance_sha = _sealed_evidence_file(
        Path(binding["data_acceptance"]["path"]), "Frozen data acceptance",
    )
    require(binding["raw_audit"] == {
                "path": str(raw_path), "sha256": raw_sha,
                "content_sha256": raw["content_sha256"],
            } and binding["data_acceptance"] == {
                "path": str(acceptance_path), "sha256": acceptance_sha,
                "content_sha256": acceptance["content_sha256"],
            } and acceptance.get("data_acceptance_passed") is True,
            "Frozen data evidence changed after plan creation")
    verifier = binding.get("independent_verifier", {})
    verifier_path = Path(verifier.get("path", "")).absolute()
    require(verifier_path.resolve() == verifier_path and verifier_path.is_file() and
            verifier.get("sha256") == sha256(verifier_path),
            "Frozen independent data verifier changed after plan creation")


def _integer_fields(path: Path, names: set[str]) -> dict[str, int]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.replace(":", "").split()
        if fields and fields[0] in names:
            values[fields[0]] = int(fields[1])
    return values


def _process_tree(root_pid: int) -> list[dict]:
    rows = {}
    for status in Path("/proc").glob("[0-9]*/status"):
        try:
            fields = _integer_fields(status, {"Pid", "PPid", "VmRSS"})
            pid = fields["Pid"]
            stat_text = status.with_name("stat").read_text(encoding="utf-8")
            tail = stat_text[stat_text.rfind(")") + 2:].split()
            start_ticks = int(tail[19])
            cmdline = status.with_name("cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", errors="backslashreplace").strip()
            groups = status.with_name("cgroup").read_text().splitlines()
            cgroup = next((line[3:] for line in groups if line.startswith("0::")), None)
            rows[pid] = {"pid": pid, "ppid": fields.get("PPid", 0),
                         "rss_bytes": fields.get("VmRSS", 0) * 1024,
                         "start_ticks": start_ticks, "cmdline": cmdline, "cgroup": cgroup}
        except (FileNotFoundError, PermissionError, ProcessLookupError, KeyError,
                ValueError, IndexError):
            continue
    descendants = {root_pid}
    while True:
        expanded = descendants | {pid for pid, row in rows.items()
                                  if row["ppid"] in descendants}
        if expanded == descendants:
            break
        descendants = expanded
    return [rows[pid] for pid in sorted(descendants) if pid in rows]


def _pid_start_ticks(pid: int) -> int | None:
    """Return a Linux process identity component, not merely its reusable PID."""
    try:
        stat_text = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
        tail = stat_text[stat_text.rfind(")") + 2:].split()
        return int(tail[19])
    except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError, IndexError):
        return None


def _host_sample() -> dict:
    mem = _integer_fields(Path("/proc/meminfo"), {"MemAvailable", "SwapFree"})
    vm = _integer_fields(Path("/proc/vmstat"), {"pswpin", "pswpout", "oom_kill"})
    pressure = {name: (Path("/proc/pressure") / name).read_text(encoding="utf-8").strip()
                for name in ("cpu", "memory", "io")}
    return {"mem_available_bytes": mem["MemAvailable"] * 1024,
            "swap_free_bytes": mem["SwapFree"] * 1024,
            "vmstat": vm, "pressure": pressure,
            "loadavg": Path("/proc/loadavg").read_text(encoding="ascii").strip()}


def _gpu_sample() -> dict:
    query = [
        "nvidia-smi",
        "--query-gpu=uuid,utilization.gpu,memory.used,memory.total,power.draw,temperature.gpu,clocks.sm,pstate,clocks_event_reasons.active",
        "--format=csv,noheader,nounits",
    ]
    result = subprocess.run(query, capture_output=True, text=True, check=True, timeout=5)
    rows = result.stdout.strip().splitlines()
    require(len(rows) == 1, "Formal telemetry requires exactly one visible GPU")
    values = [value.strip() for value in rows[0].split(",")]
    require(len(values) == 9, "Unexpected nvidia-smi GPU telemetry schema")
    apps = subprocess.run([
        "nvidia-smi", "--query-compute-apps=pid,used_memory",
        "--format=csv,noheader,nounits",
    ], capture_output=True, text=True, check=True, timeout=5)
    compute = []
    for line in apps.stdout.strip().splitlines():
        pid, memory = [value.strip() for value in line.split(",")]
        compute.append({"pid": int(pid), "memory_used_mib": float(memory)})
    return {
        "uuid": values[0], "utilization_pct": float(values[1]),
        "memory_used_mib": float(values[2]), "memory_total_mib": float(values[3]),
        "power_w": float(values[4]), "temperature_c": float(values[5]),
        "sm_clock_mhz": float(values[6]), "pstate": values[7],
        "clock_event_reasons_active": values[8], "compute_processes": compute,
    }


@contextlib.contextmanager
def resource_monitor(run_dir: Path, action: str, plan: dict,
                     interval_seconds: float = 1.0):
    require(interval_seconds > 0, "Telemetry interval must be positive")
    index = 1
    while ((run_dir / f"resource_{action}_{index:03d}.json").exists() or
           (run_dir / f"resource_{action}_{index:03d}.jsonl").exists()):
        index += 1
    report_path = run_dir / f"resource_{action}_{index:03d}.json"
    raw_path = run_dir / f"resource_{action}_{index:03d}.jsonl"
    require(not report_path.exists() and not raw_path.exists(),
            "Telemetry output already exists")
    expected_cuda = any(job.get("hyperparameters", {}).get("device") == "cuda"
                        for job in plan.get("jobs", []))
    stop = threading.Event()
    started = time.monotonic()
    state = {"samples": 0, "peak_rss": 0, "min_available": 2**63,
             "min_swap": 2**63, "errors": [], "foreign_gpu_pids": set(),
             "foreign_gpu_identities": set(), "unknown_gpu_counts": {},
             "owned_process_identities": set(), "gpu": [], "cgroup": [], "sample_times": []}
    sampling_lock = threading.Lock()
    limits = plan.get("resource_limits", {})

    def sample_once_unlocked(stream, boundary: str) -> None:
        sample = {"elapsed_seconds": time.monotonic() - started,
                  "boundary": boundary}
        state["sample_times"].append(sample["elapsed_seconds"])
        try:
            processes = _process_tree(os.getpid())
            for row in processes:
                state["owned_process_identities"].add((row["pid"], row["start_ticks"]))
            host = _host_sample()
            cgroup = cgroup_sample()
            state["cgroup"].append(cgroup)
            sample["cgroup"] = cgroup
            require(not cgroup_violations([state["cgroup"][0], cgroup], limits),
                    "Cgroup resource contract failed; use a fresh bounded memory scope")
            require(not process_scope_violations(processes, cgroup, limits),
                    "A sampled process escaped the workload cgroup")
            require(not limits.get("require_bounded_cgroup") or
                    any(row['pid'] == os.getpid() for row in processes),
                    "The resource monitor's own process membership is missing")
            if "first_vmstat" not in state:
                state["first_vmstat"] = dict(host["vmstat"])
            state["last_vmstat"] = dict(host["vmstat"])
            gpu = _gpu_sample() if expected_cuda else None
            if gpu is not None:
                unknown = set()
                for row in gpu["compute_processes"]:
                    pid = row["pid"]
                    start_ticks = _pid_start_ticks(pid)
                    row["start_ticks"] = start_ticks
                    if (pid, start_ticks) not in state["owned_process_identities"]:
                        identity = f"{pid}:{start_ticks if start_ticks is not None else 'unavailable'}"
                        unknown.add(identity)
                state["unknown_gpu_counts"] = {
                    identity: state["unknown_gpu_counts"].get(identity, 0) + 1
                    for identity in unknown
                }
                persistent = {identity for identity, count in
                              state["unknown_gpu_counts"].items() if count >= 2}
                # An external compute process already present before this
                # action, or still present after it, is not a child-start race.
                if boundary in ("baseline", "final"):
                    persistent.update(unknown)
                state["foreign_gpu_identities"].update(persistent)
                state["foreign_gpu_pids"].update(
                    int(identity.split(":", 1)[0]) for identity in persistent
                )
                state["gpu"].append(gpu)
            sample.update({"processes": processes, "host": host, "gpu": gpu})
            state["peak_rss"] = max(state["peak_rss"],
                                    sum(row["rss_bytes"] for row in processes))
            state["min_available"] = min(state["min_available"],
                                          host["mem_available_bytes"])
            state["min_swap"] = min(state["min_swap"], host["swap_free_bytes"])
        except Exception as exc:
            error = f"{type(exc).__name__}:{exc}"
            state["errors"].append(error)
            sample["sampling_error"] = error
        stream.write(json.dumps(sample, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        state["samples"] += 1

    def sample_once(stream, boundary: str) -> None:
        with sampling_lock:
            sample_once_unlocked(stream, boundary)

    def current_violations() -> list[str]:
        violations = cgroup_violations(state["cgroup"], limits)
        if "maximum_sample_gap_seconds" in limits:
            gap = limits["maximum_sample_gap_seconds"]
            times = state["sample_times"]
            if (interval_seconds > gap or (times and (
                    times[0] > gap or time.monotonic() - started - times[-1] > gap or
                    any(b - a > gap for a, b in zip(times, times[1:]))))):
                violations.append("sampling_gap_limit")
        if state["peak_rss"] > limits.get("maximum_process_tree_rss_bytes", 0):
            violations.append("process_tree_rss_limit")
        initial, final = state.get("first_vmstat", {}), state.get("last_vmstat", {})
        delta = {key: final.get(key, 0) - initial.get(key, 0)
                 for key in ("pswpin", "pswpout", "oom_kill")}
        if limits.get("require_zero_swap_io", False) and (delta["pswpin"] or delta["pswpout"]):
            violations.append("host_swap_io")
        if limits.get("require_zero_oom_kills", False) and delta["oom_kill"]:
            violations.append("host_oom_kill")
        if state["gpu"]:
            if max(row["memory_used_mib"] for row in state["gpu"]) > limits.get("maximum_gpu_memory_used_mib", 0):
                violations.append("gpu_memory_limit")
            if max(row["temperature_c"] for row in state["gpu"]) > limits.get("maximum_gpu_temperature_c", 0):
                violations.append("gpu_temperature_limit")
        return violations

    def phase_healthcheck() -> None:
        # Synchronous pre-barrier sample: an already observed failed resource
        # condition cannot be followed by another phase or the opening of test.
        with sampling_lock:
            sample_once_unlocked(stream, "periodic")
            require(not state["errors"] and not state["foreign_gpu_pids"] and
                    not current_violations(),
                    "Resource telemetry failed closed at phase boundary")

    stream = raw_path.open("x", encoding="utf-8")
    def sample_loop() -> None:
        try:
            while not stop.wait(interval_seconds):
                sample_once(stream, "periodic")
        except Exception as exc:
            state["errors"].append(f"sampler_thread:{type(exc).__name__}:{exc}")

    thread = None
    completed = False
    try:
        # The action cannot begin before its baseline is persisted.  Sampling
        # at exit closes the tail blind spot even for actions shorter than one
        # interval, and host counters account for between-sample swap/OOM events.
        sample_once(stream, "baseline")
        require(not state["errors"] and not state["foreign_gpu_pids"] and
                not current_violations(),
                "Resource telemetry failed closed during baseline")
        thread = threading.Thread(target=sample_loop, name="resource-monitor", daemon=True)
        thread.start()
        yield phase_healthcheck
        completed = True
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=15)
        if thread is not None and thread.is_alive():
            state["errors"].append("sampling_thread_did_not_stop")
        else:
            try:
                sample_once(stream, "final")
            except Exception as exc:
                state["errors"].append(f"final_sample:{type(exc).__name__}:{exc}")
            finally:
                stream.close()
        gpu_samples = state["gpu"]
        first_vmstat = state.get("first_vmstat", {})
        last_vmstat = state.get("last_vmstat", {})
        vmstat_delta = {key: last_vmstat.get(key, 0) - first_vmstat.get(key, 0)
                        for key in ("pswpin", "pswpout", "oom_kill")}
        violations = current_violations()
        telemetry_passed = bool(
            completed and state["samples"] > 0 and not state["errors"] and
            not state["foreign_gpu_pids"] and not violations and
            (not expected_cuda or gpu_samples)
        )
        report = {
            "schema": SCHEMA, "kind": "spikeids_v5_resource_telemetry",
            "plan_sha256": plan["content_sha256"], "action": action,
            "completed": completed, "telemetry_passed": telemetry_passed,
            "interval_seconds": interval_seconds, "samples": state["samples"],
            "duration_seconds": time.monotonic() - started, "platform": platform.platform(),
            "raw_samples": {"path": raw_path.name, "sha256": sha256(raw_path)},
            "peak_process_tree_rss_bytes": state["peak_rss"],
            "minimum_host_available_bytes": (state["min_available"]
                                              if state["samples"] else None),
            "minimum_swap_free_bytes": (state["min_swap"] if state["samples"] else None),
            "sampling_errors": state["errors"],
            "resource_limit_violations": violations,
            "resource_limits": limits, "vmstat_delta": vmstat_delta,
            "foreign_gpu_pids": sorted(state["foreign_gpu_pids"]),
            "foreign_gpu_process_identities": sorted(state["foreign_gpu_identities"]),
            "gpu_expected": expected_cuda, "gpu_samples": len(gpu_samples),
        }
        if gpu_samples:
            report["gpu_uuid"] = sorted({row["uuid"] for row in gpu_samples})
            for key in ("utilization_pct", "memory_used_mib", "power_w",
                        "temperature_c", "sm_clock_mhz"):
                values = [row[key] for row in gpu_samples]
                report["gpu_" + key] = {"mean": sum(values) / len(values),
                                        "max": max(values), "min": min(values)}
        write_json(report_path, seal(report))
        require(raw_path.is_file() and raw_path.stat().st_nlink == 1 and
                report_path.is_file() and report_path.stat().st_nlink == 1,
                "Telemetry evidence must not be symlinked or hardlinked")
        if completed:
            require(telemetry_passed,
                    f"Resource telemetry failed closed; inspect {report_path}")


def run_command(command, log: Path):
    log.parent.mkdir(parents=True,exist_ok=True)
    print("Running:", " ".join(map(str,command)),flush=True)
    with log.open("a",encoding="utf-8") as f:
        f.write("\nCOMMAND: "+repr(command)+"\n"); f.flush()
        result=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,check=False)
    require(result.returncode==0,f"Command failed with exit {result.returncode}; full log: {log}")


def common_parser(p):
    p.add_argument("--run-dir",type=Path,required=True)


def make_parser():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    sub=p.add_subparsers(dest="action",required=True)
    prep=sub.add_parser("prepare",allow_abbrev=False)
    prep.add_argument("--data-dir",type=Path,required=True)
    prep.add_argument("--cache-root",type=Path,required=True)
    prep.add_argument("--source-spec-dir",type=Path)
    prep.add_argument("--raw-audit",type=Path)
    prep.add_argument("--nonformal-fixture-source-bypass",action="store_true",
                      help="Tests only; allows unpinned synthetic fixture sources")
    prep.add_argument("--chunksize",type=int,default=65536)
    freeze=sub.add_parser("freeze",allow_abbrev=False);common_parser(freeze)
    freeze.add_argument("--cache-root",type=Path,required=True)
    freeze.add_argument("--raw-audit",type=Path)
    freeze.add_argument("--data-acceptance",type=Path)
    freeze.add_argument("--nonformal-fixture-evidence-bypass",action="store_true",
                        help="Tests only; requires --smoke-epochs and can never create a benchmark plan")
    freeze.add_argument("--device",choices=("cuda","cpu"),default="cuda")
    freeze.add_argument("--optimizer",choices=("single","foreach","fused"),default="single")
    freeze.add_argument("--threads",type=int,default=4)
    freeze.add_argument("--workers",type=int,default=1,
                        help="Concurrent independent GPU jobs; frozen into the execution plan")
    freeze.add_argument("--seeds",nargs="+",type=int,default=list(range(20)))
    freeze.add_argument("--delta",type=float,default=1.)
    freeze.add_argument("--alpha",type=float,default=.05)
    # This explicit testing protocol can never pass a paper-finalization gate.
    freeze.add_argument("--smoke-epochs",type=int)
    freeze.add_argument("--bounded-memory",action="store_true",
                        help="Also require a dedicated 16 GiB/no-swap cgroup for smoke runs; formal runs always require it")
    for name in ("fit","verify","evaluate","run"):
        common_parser(sub.add_parser(name,allow_abbrev=False))
    return p


def freeze(args):
    from stats_tests import validate_alpha
    validate_alpha(args.alpha)
    require(args.delta>0 and args.delta<float('inf'),"Invalid equivalence margin")
    require(args.threads>=1 and 1 <= args.workers <= 8 and args.seeds and len(args.seeds)==len(set(args.seeds)) and
            len(args.seeds)<=100 and all(0<=s<2**32 for s in args.seeds),"Invalid threads/seeds")
    require(args.smoke_epochs is None or args.smoke_epochs>=1,"Invalid smoke budget")
    require(not args.nonformal_fixture_evidence_bypass or args.smoke_epochs is not None,
            "Data-evidence bypass is restricted to explicit smoke fixtures")
    if args.nonformal_fixture_evidence_bypass:
        acceptance = None
        data_evidence = {"status": "nonformal_fixture_bypass",
                         "paper_finalization_allowed": False}
    else:
        require(args.raw_audit is not None and args.data_acceptance is not None,
                "Formal freeze requires raw audit and independent data acceptance")
        acceptance, data_evidence = load_data_acceptance(
            args.raw_audit, args.data_acceptance, args.cache_root,
        )
    run_dir=args.run_dir.resolve()
    require(not run_dir.exists(),"Freeze requires a fresh directory; never overwrites an existing protocol")
    run_dir.mkdir(parents=True)
    env_file=run_dir/"environment.json"
    run_command([sys.executable,str(PACKAGE/"experiment_all.py"),"--probe","--device",args.device,
                 "--threads",str(args.threads),"--output",str(env_file)],run_dir/"logs"/"environment.log")
    env=load_json(env_file)
    if args.device == "cuda" and args.smoke_epochs is None:
        require(float(env["gpu_runtime"]["power.limit"]) == 165.0 and
                float(env["gpu_runtime"]["power.default_limit"]) == 165.0,
                "Formal CUDA benchmark requires the workstation safe/default 165 W power limit")
    jobs=[]
    for dataset in DATASETS:
        cache=(args.cache_root/dataset).resolve()
        meta,_=open_cache(cache)
        require(meta["dataset"]==dataset,"Wrong cache directory")
        if acceptance is not None:
            accepted = acceptance["datasets"][dataset]
            require(accepted.get("data_fingerprint") == meta["data_fingerprint"] and
                    accepted.get("raw_rows") == meta["raw_rows"] and
                    accepted.get("counts") == meta["counts"] and
                    accepted.get("features") == meta["features"] and
                    accepted.get("class_names") == meta["class_names"] and
                    accepted.get("raw_model_view_sha256") ==
                    meta["raw_model_view_sha256"],
                    f"Accepted data semantics differ from selected {dataset} cache")
            matching = [record for record in accepted.get("rebuilds", [])
                        if record.get("resolved_root") == str(cache)]
            require(len(matching) == 1 and
                    matching[0].get("metadata_sha256") == sha256(cache/"metadata.json") and
                    matching[0].get("data_fingerprint") == meta["data_fingerprint"] and
                    matching[0].get("files_sha256") == meta["files_sha256"],
                    f"Selected {dataset} cache is not one accepted rebuild")
        for arm in ARMS[dataset]:
            h={"dataset":dataset,"model":arm,"seeds":sorted(args.seeds),
               "epochs":args.smoke_epochs or (40 if dataset=="iot23" else 80),
               "batch_size":1024 if dataset=="iot23" else 512,"eval_batch_size":4096,
               "eval_every":10,"checkpoint_every":10,"hidden":256,"levels":4,"qcfs_formula":"shifted_v1",
               "lr":.001,"weight_decay":.00001,"device":args.device,"optimizer":args.optimizer,
               "threads":args.threads,"data_placement":"gpu" if args.device=="cuda" else "cpu","compile":False,
               "vram_reserve_gib":2.0,
               "loss_weighting":"sqrt_inverse_fit_only_v1",
               "checkpoint_policy":"fixed_final_epoch_v1"}
            jobs.append({"id":dataset+"_"+arm,"dataset":dataset,"model":arm,"cache":str(cache),
                         "data_fingerprint":meta["data_fingerprint"],"hyperparameters":h})
    plan={"schema":SCHEMA,"seeds":sorted(args.seeds),"jobs":jobs,"sources":sources(),"environment":env,
          "execution":{"workers":args.workers,"unit":"independent job","seed_order":"ascending within job",
                       "resource_note":"worker count is hardware-specific and must pass replica verification"},
          "resource_limits":{"maximum_process_tree_rss_bytes":14*1024**3,
                             "require_bounded_cgroup":args.smoke_epochs is None or args.bounded_memory,
                             "maximum_cgroup_memory_bytes":16*1024**3,
                             "maximum_sample_gap_seconds":15.0,
                             "maximum_gpu_memory_used_mib":15360,
                             "maximum_gpu_temperature_c":80,
                             "require_zero_swap_io":args.smoke_epochs is not None and not args.bounded_memory,
                             "host_swap_scope":"host context only when workload cgroup is enforced; not attributed to this run",
                             "require_zero_oom_kills":True},
          "alpha":args.alpha,"equivalence_margin_pp":args.delta,
          "difference_family":[f"{d}:relu_vs_{a}:{m}" for d in DATASETS for a in ARMS[d] if a!="relu" for m in METRICS],
          "equivalence_family":[f"{d}:{m}" for d in DATASETS for m in METRICS],
          "protocol_role":"smoke_only" if args.smoke_epochs else "planned_benchmark",
          "margin_status":(
              "frozen numerical-equivalence sensitivity margin before formal test evaluation; "
              "not historical preregistration and not an empirically established practical-importance threshold"
          ),
          "prior_test_exposure":"unknown outside this run directory; disclose historical exploration",
          "data_evidence":data_evidence,
          "training_policy":{"loss_weighting":"sqrt_inverse_fit_only_v1",
                             "checkpoint_policy":"fixed_final_epoch_v1",
                             "validation_role":"diagnostic_only"},
          "deployment_seed":0 if 0 in args.seeds else min(args.seeds)}
    write_json(run_dir/"plan.json",seal(plan))
    print("Frozen",run_dir/"plan.json",flush=True)


def job_command(job, output, stage, run_dir, execution):
    command=[sys.executable,str(PACKAGE/"experiment_all.py"),"--cache",job["cache"],"--output",str(output),"--stage",stage]
    for key,value in job["hyperparameters"].items():
        flag="--"+key.replace('_','-')
        if isinstance(value,bool):
            if value: command.append(flag)
        elif isinstance(value,list): command.extend([flag,*map(str,value)])
        else: command.extend([flag,str(value)])
    command.extend(["--formal-plan", str(run_dir/"plan.json"), "--formal-execution", execution])
    if stage == "evaluate":
        command.extend(["--fit-verification", str(run_dir/"verification_fit.json")])
    if output.exists() or output.with_suffix("").exists(): command.append("--resume")
    return command


def _fit_job(run_dir,plan,job,replica):
    destination=run_dir/("replicas" if replica else "results")
    output=destination/f"{job['id']}.json"
    run_command(job_command(job,output,"fit",run_dir,"replica" if replica else "primary"),
                run_dir/"logs"/f"{'replica_' if replica else ''}{job['id']}_fit.log")
    return job["id"],load_fit(output,job,plan)


def all_fits(run_dir,plan,replica=False):
    workers=plan.get("execution",{}).get("workers",1)
    require(type(workers) is int and 1 <= workers <= 8,"Invalid frozen execution worker count")
    if workers==1:
        for job in plan["jobs"]:_fit_job(run_dir,plan,job,replica)
        return
    # Each child has an isolated output/checkpoint/log namespace.  Exceptions
    # are re-raised by future.result(), so one failed worker fails the barrier.
    with ThreadPoolExecutor(max_workers=workers,thread_name_prefix="gpu-job") as pool:
        futures=[pool.submit(_fit_job,run_dir,plan,job,replica) for job in plan["jobs"]]
        for future in futures:future.result()


def verify_training(run_dir,plan):
    # Check all primary fits BEFORE spending time on the second independent execution.
    primary={j["id"]:load_fit(run_dir/"results"/f"{j['id']}.json",j,plan) for j in plan["jobs"]}
    all_fits(run_dir,plan,replica=True)
    jobs={}
    for job in plan["jobs"]:
        a=primary[job["id"]];b=load_fit(run_dir/"replicas"/f"{job['id']}.json",job,plan)
        require(a["fingerprint"]==b["fingerprint"] and a["training_digest"]==b["training_digest"],
                f"Independent training differs for {job['id']}; test evaluation remains blocked")
        jobs[job["id"]]=a["training_digest"]
    write_json(run_dir/"verification_fit.json",seal({"plan_sha256":plan["content_sha256"],"passed":True,"jobs":jobs,
        "scope":"two independent initializations/training executions on the recorded stack; not cross-platform proof"}))


def _evaluate_job(run_dir,plan,job):
    results=[]
    for folder in ("results","replicas"):
        output=run_dir/folder/f"{job['id']}.json"
        run_command(job_command(job,output,"evaluate",run_dir,"primary" if folder=="results" else "replica"),
                    run_dir/"logs"/f"{folder}_{job['id']}_evaluate.log")
        results.append(load_result(output,job,plan))
    require(results[0]["scientific_digest"]==results[1]["scientific_digest"],f"Test predictions differ: {job['id']}")
    return job["id"],results[0]["scientific_digest"]


def evaluate(run_dir,plan):
    v=load_json(run_dir/"verification_fit.json");check_seal(v)
    require(v["passed"] and v["plan_sha256"]==plan["content_sha256"],"Full training verification not passed")
    for job in plan["jobs"]:
        for folder in ("results","replicas"):
            r=load_fit(run_dir/folder/f"{job['id']}.json",job,plan)
            require(v["jobs"].get(job["id"])==r["training_digest"],"Training verification stale")
    # Global barrier: no test metric in this suite until ALL 22 job executions passed fit verification.
    workers=plan.get("execution",{}).get("workers",1)
    require(type(workers) is int and 1 <= workers <= 8,"Invalid frozen execution worker count")
    if workers==1:
        pairs=[_evaluate_job(run_dir,plan,job) for job in plan["jobs"]]
    else:
        with ThreadPoolExecutor(max_workers=workers,thread_name_prefix="gpu-eval") as pool:
            futures=[pool.submit(_evaluate_job,run_dir,plan,job) for job in plan["jobs"]]
            pairs=[future.result() for future in futures]
    jobs=dict(pairs)
    write_json(run_dir/"verification_evaluate.json",seal({"plan_sha256":plan["content_sha256"],"passed":True,"jobs":jobs,
           "scope":"per-seed states, logits, probabilities, predictions, and independently recomputed metrics"}))


def main():
    args=make_parser().parse_args()
    if args.action=="prepare":
        require((args.nonformal_fixture_source_bypass and
                 args.source_spec_dir is None and args.raw_audit is None) or
                (not args.nonformal_fixture_source_bypass and
                 args.source_spec_dir is not None and args.raw_audit is not None),
                "Preparation requires pinned source specs and raw audit unless the explicit nonformal fixture bypass is set")
        for d in DATASETS:
            spec=args.source_spec_dir/(d+".json") if args.source_spec_dir else None
            meta,_=prepare(d,args.data_dir,args.cache_root/d,chunksize=args.chunksize,
                           source_spec=spec,raw_audit=args.raw_audit)
            print(d,meta["counts"],meta["data_fingerprint"],flush=True)
        return
    if args.action=="freeze": freeze(args);return
    run_dir=args.run_dir.resolve()
    with file_lock(run_dir/"pipeline.lock"):
        plan=read_plan(run_dir)
        validate_plan_data_evidence(plan)
        with resource_monitor(run_dir,args.action,plan) as resource_healthcheck:
            if args.action in ("fit","run"): all_fits(run_dir,plan)
            resource_healthcheck()
            if args.action in ("verify","run"): verify_training(run_dir,plan)
            resource_healthcheck()
            if args.action in ("evaluate","run"): evaluate(run_dir,plan)
            resource_healthcheck()

if __name__=="__main__":
    try: main()
    except (ValueError,RuntimeError,FileNotFoundError) as e:
        print("ERROR:",e,file=sys.stderr);raise SystemExit(2) from e
