#!/usr/bin/env python3
"""Explicit one-shot engineering continuation, not a retry of the failed matrix.

Retains all three original attempts unchanged; only the unexecuted nineteen may
be exported. All twenty-two payloads receive new independent numerical review.
Old source, artifacts, failed markers and registry are never changed. A completed
execution with negative scientific gates is not a deployment or publication pass.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "spikeids_v5")]
from tools import run_v5_export_stage as old
from tools import export_v5_runtime as original_runtime
from tools import export_v5_build_identity as builds
from tools import export_v5_continuation_runtime as workers
from tools import export_v5_continuation_science as science

data, research, tree = old.data, old.research, old.tree
require, seal, equal, snapshot = old.require, old.seal, old.equal, old.snapshot
SELF = Path(__file__).resolve()
SCOPE = "explicit_engineering_continuation_retaining_three_original_attempts_and_executing_only_nineteen_unstarted"
ENVIRONMENT, RESOURCE_PLAN = old.ENVIRONMENT, old.RESOURCE_PLAN
ROLES = {"continuation_lifecycle", "continuation_science", "continuation_controller"}


def sources():
    return sorted(set([*old.sources(), SELF, workers.SELF, builds.SELF, *science.source_paths()]))


def write_record(path, body):
    """Hold the exact intended record, not a late freshly blessed replacement."""
    value = seal(body)
    data.write_new(path, value)
    actual, pin = original_runtime._record(path)
    require(equal(actual, value), "Published continuation record changed")
    data.assert_snapshots({str(path): pin}, full=False)
    return value, pin


def assert_boundary(boundary, plan):
    """Retain only explicitly named legacy lock exclusions, not arbitrary *.lock."""
    research.assert_boundary(boundary,full=False)
    root = Path(boundary["root"])
    permitted_locks = set()
    if str(root) == plan["neural_run"]:
        neural = old.record(root/"plan.json")
        permitted_locks = {"pipeline.lock",*(f"{execution}/{job['id']}.lock"
            for execution in ("results","replicas") for job in neural["jobs"])}
    elif str(root) == plan["predecessor_boundaries"][1]["root"]:
        permitted_locks = {"pipeline.lock"}
    actual = {str((Path(parent)/name).relative_to(root)) for parent,_,names in os.walk(root) for name in names}
    expected = set(boundary["files"])
    require(expected <= actual and actual <= expected | permitted_locks,
            "Unplanned artifact including a non-allowlisted lock file")


def history(path, *, full):
    value, pin = original_runtime._record(path)
    require(value.get("kind") == "spikeids_v5_failed_export_history_freeze" and
        type(value.get("schema")) is int and value["schema"] == 1 and
        value.get("diagnosis_confirmed") is True and value.get("scientific_acceptance") is False and
        value.get("matrix_execution_complete") is False and value.get("automatic_retry") is False and
        type(value.get("owner_actual_return_code")) is int and value["owner_actual_return_code"] == 1 and
        type(value.get("third_worker_return_code")) is int and value["third_worker_return_code"] == 0 and
        type(value.get("unstarted_attempts")) is int and value["unstarted_attempts"] == 19,
        "Only the preserved, diagnosed three-attempt failed execution can be continued")
    pins = dict(value["input_pins"])
    research.merge_pins(pins, {str(path): pin})
    require(len(value["preserved_boundaries"]) == 4 and len(value["unchanged_predecessor_boundaries"]) == 2,
            "Missing immutable history or accepted predecessor roots")
    original_work, original_output, original_owner, registry = [Path(b["root"]) for b in value["preserved_boundaries"]]
    original_plan, original_pin = original_runtime._record(original_work / "plan.json")
    export, export_pin = original_runtime._record(original_output / "export_plan.json")
    require(original_plan["content_sha256"] == value["original_controller_plan_sha256"] and
        export["content_sha256"] == value["original_export_plan_sha256"] and
        original_plan["export_root"] == str(original_output) and
        export["source_plan_sha256"] == original_plan["formal_plan_sha256"] and
        equal(value["unchanged_predecessor_boundaries"],original_plan["predecessor_boundaries"]) and
        all(p in pins and equal(pins[p],v) for p,v in original_plan["input_pins"].items()) and
        export["execution_adapter"]["registry_directory"] == str(registry) and
        not (original_work / "complete.json").exists() and not (original_owner / "completion_link.json").exists(),
        "Historical execution identity changed or is falsely complete")
    research.merge_pins(pins, {str(original_work / "plan.json"): original_pin,
                             str(original_output / "export_plan.json"): export_pin})
    failed, failure_pin = original_runtime._record(original_work / "failed.json")
    owner, owner_pin = original_runtime._record(original_owner / "observed_exit.json")
    require(failed.get("stage") == "nslkdd/qcfs/fp32" and
        failed.get("error") == "ContractError('Export policy mismatch: torch')" and
        failed.get("plan_sha256") == original_plan["content_sha256"] and failed.get("passed") is False and
        failed.get("automatic_retry") is False and equal(failed.get("classified_attempts"), value["classified_prefix"]) and
        owner.get("plan_sha256") == original_plan["content_sha256"] and
        type(owner.get("actual_return_code")) is int and owner["actual_return_code"] == 1,
        "History must retain the actual infrastructure failure and original owner exit")
    research.merge_pins(pins, {str(original_work / "failed.json"): failure_pin,
                             str(original_owner / "observed_exit.json"): owner_pin})
    started = old.record(original_work / "run_started.json")
    require(data.process_identity(started["controller"]["process"]["pid"]) != started["controller"]["process"],
            "Original owner is still executing")
    require([(a["dataset"],a["model"],a["mode"]) for a in export["attempts"]] ==
        [(d,m,q) for d,m in old.legacy.JOBS for q in ("fp32","qdq")] and
        equal(export["protocol"], old.legacy.fixed_export_protocol()), "Original fixed matrix or numerical policy differs")
    prefix = failed["classified_attempts"]
    require([(a["dataset"],a["model"],a["mode"]) for a in prefix] ==
        [(a["dataset"],a["model"],a["mode"]) for a in export["attempts"][:2]] and
        all(a.get("passed") is False and type(a.get("return_code")) is int and a["return_code"] == 1 for a in prefix),
        "The retained classified prefix is not the original two negatives")
    for a in export["attempts"][3:]:
        d,m,q = a["dataset"],a["model"],a["mode"]
        forbidden = [original_output/d/m/q,original_output/"replays"/d/m/q,
                     original_output/"independent_audits"/d/m/q]
        for suffix in ("","_replay"):
            key = f"{d}_{m}_{q}"+suffix
            forbidden += [original_output/folder/(key+".json") for folder in ("worker_claims","worker_receipts")]
            forbidden += [original_work/"attempts"/(key+ending) for ending in (".log","_exit.json")]
        require(all(not p.exists() and not p.is_symlink() for p in forbidden),
                "An allegedly unstarted suffix attempt already has original execution evidence")
    for boundary in [*value["preserved_boundaries"], *value["unchanged_predecessor_boundaries"]]:
        require(all(p in pins and equal(pins[p], v) for p,v in boundary["pins"].items()),
                "History boundary was not committed in the diagnostic record")
        assert_boundary(boundary,original_plan)
    data.assert_snapshots(pins, full=full)
    return value, original_plan, export, pins


def review(path, history_path):
    value, pin = original_runtime._record(path)
    current = {str(p):snapshot(p) for p in sources()}
    hist, hist_pin = original_runtime._record(history_path)
    require(value.get("kind") == "spikeids_v5_export_continuation_launch_review" and
        type(value.get("schema")) is int and value["schema"] == 1 and value.get("passed") is True and
        value.get("unresolved_blockers") == [] and value.get("scope") == SCOPE and
        value.get("history") == {"path":str(history_path),"sha256":hist_pin["sha256"],
                                  "content_sha256":hist["content_sha256"]} and
        value.get("sources") == {p:v["sha256"] for p,v in current.items()}, "Review is not bound to this continuation")
    require(isinstance(value.get("reviews"),list) and len(value["reviews"]) == len(ROLES) and
        {r.get("role") for r in value["reviews"]} == ROLES and len(value.get("tests",[])) >= 2,
        "Independent lifecycle, science and controller reviews are required")
    pins = {str(path):pin, **current}
    seen = set()
    for row in [*value["reviews"], *value["tests"], *value.get("supporting_evidence",[])]:
        target = original_runtime.canonical(Path(row["path"]),file=True)
        require(str(target) not in seen, "Duplicate reviewed artifact")
        seen.add(str(target))
        captured = snapshot(target)
        require(captured["sha256"] == row["sha256"], "Reviewed artifact changed")
        if row in value["tests"]:
            require(type(row.get("observed_return_code")) is int and row["observed_return_code"] == 0,
                    "No actually observed passing test execution")
            require(tree.junit_check(target) == row["tests_passed"], "Passing test count differs")
        research.merge_pins(pins,{str(target):captured})
    data.assert_snapshots(pins)
    return pins


def history_build(value, export, identity):
    """A recovery may separate version roles, never silently change the build."""
    pair = identity["packages"]["torch"]
    require(equal(value["torch_version_roles"],{"distribution":pair["distribution_version"],
        "module":pair["module_version"]}),"Continuation changed the originally observed Torch build pair")
    builds.validate_distribution_versions(export["tool_provenance"]["packages"],identity)
    for attempt in export["attempts"][:3]:
        payload = Path(export["output_root"])/attempt["dataset"]/attempt["model"]/attempt["mode"]
        policy = old.record(payload/"export_policy.json")
        builds.validate_policy_versions(policy,identity,provenance_packages=export["tool_provenance"]["packages"])


def freeze(args):
    path = original_runtime.canonical(Path(args.failure_history).absolute(),file=True)
    value, original, export, pins = history(path,full=True)
    require(value["content_sha256"] == args.expected_history_sha256, "History differs from explicit diagnosis seal")
    review_path = original_runtime.canonical(Path(args.review_record).absolute(),file=True)
    research.merge_pins(pins,review(review_path,path))
    work, output = data.new_path(args.work_dir), data.new_path(args.export_root)
    require(work.parent == output.parent == ROOT / "results" and
        re.fullmatch(r"spikeids-v5-export-cont-[A-Za-z0-9_-]+\.service",args.service_unit) and
        research.unit_status(args.service_unit)["LoadState"] == "not-found", "Nonfresh continuation namespace/service")
    successor = workers.registry_directory(export["content_sha256"])
    require(not successor.exists() and not successor.is_symlink(),"Successor authority was already claimed; no second continuation")
    roots = [Path(b["root"]) for b in [*value["preserved_boundaries"],*value["unchanged_predecessor_boundaries"]]]
    data.nonoverlap([work,output,review_path.parent,*roots])
    temp = research.temporary_runtime(Path(args.tmp_dir).absolute(),fresh=True)
    require({k:os.environ.get(k) for k in ENVIRONMENT} == ENVIRONMENT, "Startup environment differs")
    research.merge_pins(pins,{str(Path(sys.executable).resolve()):snapshot(Path(sys.executable).resolve())})
    identity = builds.capture_build_identity()
    history_build(value,export,identity)
    current = {"schema":1,"kind":"spikeids_v5_export_continuation_plan","scope":SCOPE,
        "plan_path":str(work/"plan.json"),"work_dir":str(work),"export_root":str(output),
        "neural_run":original["neural_run"],"formal_plan_sha256":original["formal_plan_sha256"],
        "original_controller_plan":original["plan_path"],"original_export_plan":str(Path(export["output_root"])/"export_plan.json"),
        "original_controller_plan_sha256":original["content_sha256"],"original_export_plan_sha256":export["content_sha256"],
        "failure_history":str(path),"history_sha256":value["content_sha256"],"review_record":str(review_path),
        "source_pins":{str(p):pins[str(p)] for p in sources()},"input_pins":pins,
        "preserved_boundaries":value["preserved_boundaries"],"predecessor_boundaries":value["unchanged_predecessor_boundaries"],
        "build_identity":identity,"protocol":old.legacy.fixed_export_protocol(),
        "retained_attempts":export["attempts"][:3],"remaining_attempts":export["attempts"][3:],
        "python":sys.executable,"python_realpath":str(Path(sys.executable).resolve()),"python_version":sys.version,
        "boot_id":data.boot_id(),"environment":ENVIRONMENT,"temporary_runtime":temp,
        "service_unit":args.service_unit,"resource_plan":RESOURCE_PLAN,"automatic_retry":False,
        "amendment":"Post-outcome engineering continuation; no new matrix, no re-export of retained three, no numerical policy change",
        "created_at":data.utc_now()}
    data.assert_snapshots(pins)
    work.mkdir(mode=0o700)
    original_runtime._fsync_dir(work.parent)
    result,pin = write_record(work/"plan.json",current)
    return {"plan":str(work/"plan.json"),"plan_sha256":result["content_sha256"],"no_export_started":True,
            "input_pins":len(pins)}


def load_plan(path, *, full=True):
    path = original_runtime.canonical(Path(path),file=True)
    plan,pin = original_runtime._record(path)
    require(type(plan.get("schema")) is int and plan["schema"] == 1 and
        plan.get("kind") == "spikeids_v5_export_continuation_plan" and plan.get("scope") == SCOPE and
        plan.get("plan_path") == str(path) and path == Path(plan["work_dir"])/"plan.json" and
        plan.get("automatic_retry") is False, "Wrong explicit continuation plan")
    value, original, export, expected = history(Path(plan["failure_history"]),full=False)
    require(plan["history_sha256"] == value["content_sha256"] and
        plan["original_controller_plan"] == original["plan_path"] and
        plan["original_controller_plan_sha256"] == original["content_sha256"] and
        plan["original_export_plan"] == str(Path(export["output_root"])/"export_plan.json") and
        plan["original_export_plan_sha256"] == export["content_sha256"] and
        plan["neural_run"] == original["neural_run"] and plan["formal_plan_sha256"] == original["formal_plan_sha256"] and
        equal(plan["retained_attempts"],export["attempts"][:3]) and
        equal(plan["remaining_attempts"],export["attempts"][3:]) and
        equal(plan["preserved_boundaries"],value["preserved_boundaries"]) and
        equal(plan["predecessor_boundaries"],value["unchanged_predecessor_boundaries"]),
        "Continuation omitted or changed retained history/mandatory fixed suffix")
    research.merge_pins(expected,review(Path(plan["review_record"]),Path(plan["failure_history"])))
    research.merge_pins(expected,{str(Path(sys.executable).resolve()):snapshot(Path(sys.executable).resolve())})
    require(equal(expected,plan["input_pins"]) and
        equal(plan["source_pins"],{str(p):expected[str(p)] for p in sources()}), "Continuation input/source closure differs")
    roots = [Path(b["root"]) for b in [*plan["preserved_boundaries"],*plan["predecessor_boundaries"]]]
    work,output = Path(plan["work_dir"]),Path(plan["export_root"])
    require(work.parent == output.parent == ROOT/"results" and
        re.fullmatch(r"spikeids-v5-export-cont-[A-Za-z0-9_-]+\.service",plan["service_unit"]), "Wrong roots/service")
    data.nonoverlap([work,output,Path(plan["review_record"]).parent,*roots])
    check_inputs(plan,full=full)
    data.assert_snapshots({str(path):pin},full=False)
    return plan,pin


def check_inputs(plan, *, full):
    require(plan["python"] == sys.executable and plan["python_realpath"] == str(Path(sys.executable).resolve()) and
        plan["python_version"] == sys.version and plan["boot_id"] == data.boot_id() and
        equal(plan["environment"],ENVIRONMENT) and {k:os.environ.get(k) for k in ENVIRONMENT} == ENVIRONMENT and
        equal(plan["protocol"],old.legacy.fixed_export_protocol()) and equal(plan["resource_plan"],RESOURCE_PLAN),
        "Frozen runtime or scientific/resource policy changed")
    require(equal(plan["temporary_runtime"],research.temporary_runtime(Path(plan["temporary_runtime"]["path"]))),
            "Scratch runtime changed")
    builds.validate_build_identity(plan["build_identity"])
    history_build(old.record(Path(plan["failure_history"])),old.record(Path(plan["original_export_plan"])),
                  plan["build_identity"])
    data.assert_snapshots(plan["input_pins"],full=full)
    for boundary in [*plan["preserved_boundaries"],*plan["predecessor_boundaries"]]:
        assert_boundary(boundary,plan)
    require(shutil.disk_usage(ROOT).free >= research.FLOOR_BYTES,"Disk reserve exhausted")


def controller(plan):
    status, identity = research.unit_status(plan["service_unit"]),data.process_identity(os.getpid())
    require(status["LoadState"] == "loaded" and status["ActiveState"] == "active" and
        status["Type"] == "exec" and status["Restart"] == "no" and status["RemainAfterExit"] == "no" and
        status["KillMode"] == "control-group" and int(status["MainPID"]) == os.getpid() and
        status["MemoryMax"] == str(data.MEMORY_BYTES) and status["MemorySwapMax"] == "0" and
        re.fullmatch("[0-9a-f]{32}",status["InvocationID"]),"Wrong aggregate continuation service")
    require(identity is not None and identity["cgroup"] == status["ControlGroup"] and
        identity["cmdline"] == [plan["python"],str(SELF),"run","--plan",plan["plan_path"]] and
        identity["cwd"] == str(ROOT) and identity["exe"] == plan["python_realpath"],"Wrong continuation controller")
    return {"service":status,"process":identity}


def child_run(plan,dataset,model,mode,*,replay=False):
    folder = Path(plan["work_dir"])/"attempts"
    folder.mkdir(exist_ok=True)
    key = f"{dataset}_{model}_{mode}"+("_replay" if replay else "")
    log = folder/(key+".log")
    command = workers.worker_invocation(Path(plan["plan_path"]),dataset,model,mode,replay=replay)
    began = time.monotonic()
    with log.open("xb") as stream:
        result = subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=False)
        stream.flush(); os.fsync(stream.fileno())
    captured = snapshot(log)
    _,pin = write_record(folder/(key+"_exit.json"),{"schema":1,"kind":"observed_export_continuation_worker_exit",
        "plan_sha256":plan["content_sha256"],"original_export_plan_sha256":plan["original_export_plan_sha256"],
        "actual_os_command":command,"actual_return_code":result.returncode,"replay":replay,
        "elapsed_seconds":time.monotonic()-began,"log":{"path":str(log),**captured},"finished_at":data.utc_now()})
    pins = {str(log):captured,str(folder/(key+"_exit.json")):pin}
    research.merge_pins(pins,workers.validate_worker_receipt(plan,dataset,model,mode,result.returncode,replay=replay))
    return result.returncode,command,pins


def summary(plan,export,rows):
    keys = [(a["dataset"],a["model"],a["mode"]) for a in export["attempts"]]
    require([(r["dataset"],r["model"],r["mode"]) for r in rows] == keys and len(rows) == 22 and
        [r["execution_origin"] for r in rows] == ["retained_original"]*3+["new_suffix"]*19 and
        all(type(r["passed"]) is bool and type(r["return_code"]) is int and
            r["return_code"] == (0 if r["passed"] else 1) for r in rows),"Incomplete or selected continuation matrix")
    return {"schema":1,"kind":"spikeids_v5_continued_export_matrix_summary",
        "plan_sha256":plan["content_sha256"],"original_export_plan_sha256":export["content_sha256"],
        "source_plan_sha256":export["source_plan_sha256"],"matrix_execution_complete":True,
        "retained_original_attempts":3,"new_export_attempts":19,"attempts":rows,
        "fp32_total":11,"qdq_total":11,
        "fp32_passed":sum(r["passed"] for r in rows if r["mode"] == "fp32"),
        "qdq_passed":sum(r["passed"] for r in rows if r["mode"] == "qdq"),
        "all_gates_passed":all(r["passed"] for r in rows),"protocol":export["protocol"],
        "amendment":plan["amendment"],"validation_reexposure":True,
        "scope":"fixed sampled CPU parity only; retained negatives are not infrastructure errors",
        "not_accepted":["paper","release","boards","NPU","energy"]}


def validate_numerical_result(plan, neural, export, row, payload, before, audit_dir, numerical, held):
    """Bind returned validation to its exact retained typed reports and inputs."""
    d,m,q = (row[k] for k in ("dataset","model","mode"))
    failure_stage = None if row["passed"] else old.record(payload/"FAILED.json").get("stage")
    require(row["passed"] or failure_stage in {"freeze","fp32_parity","qdq_parity"},
            "Unclassified numerical failure stage")
    require(numerical.get("passed") is True and numerical.get("diagnosis_only") is True and
        numerical.get("original_parity_passed") is row["passed"] and
        (numerical.get("dataset"),numerical.get("model"),numerical.get("mode")) == (d,m,q) and
        numerical.get("original_export_plan_sha256") == export["content_sha256"] and
        numerical.get("payload_dir") == str(payload) and numerical.get("negative_stage") == failure_stage and
        numerical.get("source_sha256") == plan["source_pins"][str(science.SELF)]["sha256"] and
        numerical.get("build_identity_sha256") == old.legacy.digest(plan["build_identity"]) and
        equal(numerical.get("installed_build_files"),plan["build_identity"]["files"]),
        "Independent numerical result identity or build commitment differs")
    expected_names = {"accepted.json","recomputed.json"}
    if q == "qdq" and (row["passed"] or failure_stage == "qdq_parity"):
        expected_names |= {"model_qdq_rebuilt.onnx","qdq_rebuild.log"}
    artifacts = numerical["artifacts"]
    require(set(artifacts) == {str(audit_dir/name) for name in expected_names},
            "Incomplete or extra independent numerical audit artifacts")
    boundary = research.artifact_boundary(audit_dir)
    require(equal(boundary["pins"],artifacts),"Numerical artifacts changed after validation")
    accepted,ap = original_runtime._record(audit_dir/"accepted.json")
    recomputed,rp = original_runtime._record(audit_dir/"recomputed.json")
    require(equal(ap,artifacts[str(audit_dir/"accepted.json")]) and
        equal(rp,artifacts[str(audit_dir/"recomputed.json")]),"Held audit report bytes changed")
    job = next(j for j in neural["jobs"] if (j["dataset"],j["model"]) == (d,m))
    cache,run = Path(job["cache"]),Path(plan["neural_run"])
    required = {*map(str,science.source_paths()),plan["original_export_plan"],str(run/"plan.json"),
        str(run/"results"/(job["id"]+".json")),str(run/"results"/job["id"]/"runs"/f"{m}_seed_0.pt"),
        str(cache/"metadata.json"),str(cache/"preprocessing.json"),
        *(str(cache/(name+".npy")) for name in ("x_validation","ids_validation","x_fit","ids_fit")),
        *before["pins"]}
    inputs = numerical["inputs"]
    require(set(inputs) == required and all(p in held and equal(held[p],v) for p,v in inputs.items()),
            "Numerical validator omitted or freshly rebound a mandatory input")
    require(type(recomputed.get("schema")) is int and recomputed["schema"] == 1 and
        recomputed.get("kind") == "export_continuation_payload_numerical_recomputation" and
        (recomputed.get("dataset"),recomputed.get("model"),recomputed.get("mode")) == (d,m,q) and
        recomputed.get("original_export_plan_sha256") == export["content_sha256"] and
        recomputed.get("payload_dir") == str(payload) and recomputed.get("diagnosis_only") is True and
        recomputed.get("expected_original_passed") is row["passed"] and
        recomputed.get("retained_failure_stage") == failure_stage and
        recomputed.get("validation_reexposure") is True and
        all(type(recomputed.get(k)) is int and recomputed[k] == 0 for k in
            ("new_export_attempts","new_failure_replays","test_vectors_read")) and
        recomputed.get("build_identity_sha256") == numerical["build_identity_sha256"] and
        equal(recomputed.get("installed_build_files"),numerical["installed_build_files"]) and
        equal(recomputed.get("comparisons"),numerical.get("comparisons")) and
        equal(recomputed.get("selection"),export["datasets"][d]["selection"]),
        "Independent numerical report differs from the returned outcome")
    body = {k:v for k,v in recomputed.items() if k != "content_sha256"}
    require(equal(accepted,seal({**body,"passed":True,"source_sha256":numerical["source_sha256"],
        "input_pins":inputs,"generated_pins":{p:v for p,v in artifacts.items() if p != str(audit_dir/"accepted.json")}})),
        "Published independent acceptance differs from its original computations/pins")
    data.assert_snapshots({**inputs,**artifacts},full=False)
    return boundary


def run(path):
    plan,plan_pin = load_plan(path)
    work,output = Path(plan["work_dir"]),Path(plan["export_root"])
    require(set(work.iterdir()) == {path},"Continuation already started; no reuse")
    data.new_path(output)
    owner = controller(plan)
    pins = dict(plan["input_pins"])
    research.merge_pins(pins,{str(path):plan_pin})
    _,start_pin = write_record(work/"run_started.json",{"schema":1,"plan_sha256":plan["content_sha256"],
        "controller":owner,"started_at":data.utc_now()})
    research.merge_pins(pins,{str(work/"run_started.json"):start_pin})
    rows,boundaries = [],[]
    current = "register_exclusive_successor"
    initial_oom,initial_cgroup = research.host_oom(),data.cgroup_sample(owner["process"]["cgroup"])
    try:
        data.check_resources(initial_cgroup)
        research.merge_pins(pins,workers.register(plan))
        registry_boundary = research.artifact_boundary(workers.registry_directory(plan["original_export_plan_sha256"]))
        require(registry_boundary["files"] == ["claim.json","registration.json"] and
            registry_boundary["directories"] == ["."] and
            all(p in pins and equal(pins[p],v) for p,v in registry_boundary["pins"].items()),
            "Successor registry differs from the original registration commitments")
        boundaries.append(registry_boundary)
        old.assert_output_inventory(output,pins)
        export = old.record(Path(plan["original_export_plan"]))
        neural = tree.evidence.read_plan(Path(plan["neural_run"]))
        telemetry,telemetry_pin = write_record(work/"telemetry_plan.json",{
            **{k:v for k,v in RESOURCE_PLAN.items() if k != "content_sha256"},
            "continuation_plan_sha256":plan["content_sha256"],
            "original_export_plan_sha256":export["content_sha256"],"controller":owner})
        research.merge_pins(pins,{str(work/"telemetry_plan.json"):telemetry_pin})
        with tree.suite.resource_monitor(work,"run",telemetry) as resource_health:
            def health():
                resource_health()
                check_inputs(plan,full=False)
                data.assert_snapshots(pins,full=False)
                for boundary in boundaries: assert_boundary(boundary,plan)
                require(data.process_identity(os.getpid()) == owner["process"] and research.host_oom() == initial_oom,
                        "Continuation owner identity or host OOM changed")
            for number,attempt in enumerate(export["attempts"]):
                d,m,q = (attempt[k] for k in ("dataset","model","mode"))
                current = f"{d}/{m}/{q}"
                health(); old.assert_output_inventory(output,pins)
                print(json.dumps({"stage":current,"retained_original":number<3,"status":"starting"}),flush=True)
                if number < 3:
                    payload = Path(export["output_root"])/d/m/q
                    rc = 1 if number < 2 else 0
                    original_work = Path(plan["original_controller_plan"]).parent
                    observed = old.record(original_work/"attempts"/f"{d}_{m}_{q}_exit.json")
                    require(type(observed.get("actual_return_code")) is int and observed["actual_return_code"] == rc,
                            "Original worker actual outcome changed")
                    research.merge_pins(pins,original_runtime.validate_worker_receipt(Path(export["output_root"]),d,m,q,rc))
                    command = observed["actual_os_command"]
                else:
                    rc,command,child_pins = child_run(plan,d,m,q)
                    research.merge_pins(pins,child_pins)
                    payload = output/d/m/q
                before = research.artifact_boundary(payload)
                research.merge_pins(pins,before["pins"])
                if rc != 0:
                    original_failure = old.legacy.scientific_failure(payload,export,d,m,q,rc)
                    if number < 3:
                        replay_dir = Path(export["output_root"])/"replays"/d/m/q
                        research.merge_pins(pins,original_runtime.validate_worker_receipt(Path(export["output_root"]),d,m,q,1,replay=True))
                    else:
                        replay_rc,_,replay_pins = child_run(plan,d,m,q,replay=True)
                        require(type(replay_rc) is int and replay_rc == 1,"Scientific negative replay changed OS outcome")
                        research.merge_pins(pins,replay_pins)
                        replay_dir = output/"replays"/d/m/q
                    replay_boundary = research.artifact_boundary(replay_dir)
                    require(equal(original_failure,old.legacy.scientific_failure(replay_dir,export,d,m,q,1)) and
                        {k:v for k,v in old.inventory_from_boundary(before).items() if k != "runner_validation.json"} ==
                        old.inventory_from_boundary(replay_boundary),"Negative replay differs; no scientific acceptance")
                    research.merge_pins(pins,replay_boundary["pins"])
                    boundaries.append(replay_boundary)
                audit_root = work/"numerical_audits"
                audit_root.mkdir(exist_ok=True)
                numeric_row = {"dataset":d,"model":m,"mode":q,"passed":rc==0,"return_code":rc}
                numerical = science.validate_payload(neural_run=Path(plan["neural_run"]),neural_plan=neural,
                    original_export_plan=export,row=numeric_row,
                    payload_dir=payload,audit_dir=audit_root/f"attempt_{number+1:02d}",build_identity=plan["build_identity"])
                audit_boundary = validate_numerical_result(plan,neural,export,numeric_row,payload,before,
                    audit_root/f"attempt_{number+1:02d}",numerical,pins)
                research.merge_pins(pins,numerical["inputs"])
                research.merge_pins(pins,numerical["artifacts"])
                research.assert_boundary(before)
                boundaries.extend([before,audit_boundary])
                receipt_dir = work/"adjudications"
                receipt_dir.mkdir(exist_ok=True)
                receipt_path = receipt_dir/f"attempt_{number+1:02d}.json"
                _,receipt_pin = write_record(receipt_path,{"schema":1,"kind":"continued_export_attempt_adjudication",
                    "plan_sha256":plan["content_sha256"],"original_export_plan_sha256":export["content_sha256"],
                    "payload_boundary":before,"numerical_audit_boundary":audit_boundary,"numerical_result":numerical,
                    "actual_worker_command":command,"actual_return_code":rc,"no_new_export":number<3})
                research.merge_pins(pins,{str(receipt_path):receipt_pin})
                rows.append({"dataset":d,"model":m,"mode":q,"passed":rc==0,"return_code":rc,
                    "execution_origin":"retained_original" if number<3 else "new_suffix",
                    "payload_dir":str(payload),"adjudication":str(receipt_path),"adjudication_sha256":receipt_pin["sha256"],
                    "negative_stage":numerical.get("negative_stage")})
                health(); old.assert_output_inventory(output,pins)
                print(json.dumps({"classified_outcomes":len(rows),"parity_passed":rc==0}),flush=True)
        current = "final_evidence_closure"
        resource_pins = {str(p):snapshot(p) for p in sorted(work.glob("resource_*"))}
        resource_paths = tree.resource_evidence.validate_resource_reports(work,telemetry)
        require(set(resource_pins) == {str(p) for p in resource_paths},"Resource inventory differs")
        research.merge_pins(pins,resource_pins)
        check_inputs(plan,full=True); data.assert_snapshots(pins)
        for boundary in [*boundaries,*plan["preserved_boundaries"],*plan["predecessor_boundaries"]]:
            assert_boundary(boundary,plan)
        old.assert_output_inventory(output,pins); old.assert_output_inventory(work,pins)
        matrix,matrix_pin = write_record(work/"summary.json",summary(plan,export,rows))
        research.merge_pins(pins,{str(work/"summary.json"):matrix_pin})
        final_boundary = research.artifact_boundary(output)
        require(all(equal(pins[p],v) for p,v in final_boundary["pins"].items()),"Late uncommitted artifact")
        final_cgroup = data.cgroup_sample(owner["process"]["cgroup"])
        data.check_resources(final_cgroup)
        require(research.host_oom() == initial_oom and controller(plan)["process"] == owner["process"],"Late resource/owner change")
        check_inputs(plan,full=False); data.assert_snapshots(pins,full=False)
        old.assert_output_inventory(output,pins); old.assert_output_inventory(work,pins)
        # Explicit inventory checks are AFTER the final helper returns; do not
        # let an endpoint addition be admitted before publication of complete.
        for boundary in [*boundaries,*plan["preserved_boundaries"],*plan["predecessor_boundaries"]]:
            assert_boundary(boundary,plan)
        done,done_pin = write_record(work/"complete.json",{"schema":1,"kind":"spikeids_v5_export_continuation_complete",
            "scope":SCOPE,"passed":True,"plan_sha256":plan["content_sha256"],
            "original_export_plan_sha256":export["content_sha256"],"matrix_execution_complete":True,
            "all_parity_gates_passed":matrix["all_gates_passed"],"controller":owner,
            "artifact_boundary":final_boundary,"consumed_evidence":pins,"resource_evidence":resource_pins,
            "successor_registry_boundary":registry_boundary,
            "initial_cgroup":initial_cgroup,"final_cgroup":final_cgroup,"host_oom_kill":initial_oom,
            "telemetry_plan_sha256":telemetry["content_sha256"],"operating_system_exit_code":None,
            "requires_postrun_adversarial_review":True,"finished_at":data.utc_now(),
            "not_accepted":["paper","release","boards","NPU","energy"]})
        data.assert_snapshots({**pins,str(work/"complete.json"):done_pin},full=False)
        check_inputs(plan,full=False)
        old.assert_output_inventory(work,{**pins,str(work/"complete.json"):done_pin})
        old.assert_output_inventory(output,pins)
        for boundary in [*boundaries,*plan["preserved_boundaries"],*plan["predecessor_boundaries"]]:
            assert_boundary(boundary,plan)
        # Recheck every held file after the last helper and inventory walk.
        # A marker alone is never success if a late mutation makes us exit nonzero.
        # Installed files may legitimately be hardlinked and have their own
        # snapshot domain; they cannot disappear from this final endpoint.
        builds._end_stats(plan["build_identity"]["files"])
        data.assert_snapshots({**pins,str(work/"complete.json"):done_pin},full=False)
        print(json.dumps({"matrix_execution_complete":True,"all_parity_gates_passed":matrix["all_gates_passed"]}),flush=True)
        return done
    except BaseException as exc:
        write_record(work/"failed.json",{"schema":1,"kind":"spikeids_v5_export_continuation_failure",
            "plan_sha256":plan["content_sha256"],"stage":current,"passed":False,"error":repr(exc),
            "classified_attempts":rows,"automatic_retry":False,"finished_at":data.utc_now()})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    sub = parser.add_subparsers(dest="action",required=True)
    setup = sub.add_parser("freeze",allow_abbrev=False)
    for name in ("failure-history","review-record","work-dir","export-root","tmp-dir"):
        setup.add_argument("--"+name,type=Path,required=True)
    setup.add_argument("--expected-history-sha256",required=True)
    setup.add_argument("--service-unit",required=True)
    start = sub.add_parser("run",allow_abbrev=False)
    start.add_argument("--plan",type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(freeze(args)),flush=True) if args.action == "freeze" else run(args.plan.absolute())


if __name__ == "__main__": main()
