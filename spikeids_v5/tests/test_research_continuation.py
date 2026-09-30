"""New orchestrator tests, without real scopes/GPU/training or real data writes.

Delegated acceptance/OS calls are explicit fixtures; seals, filesystem snapshots,
freshness, formal plan parsing, resource replay and orchestration remain real.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("research_continuation_test", ROOT / "tools/continue_v5_research.py")
q = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(q)


def publish(path, value):
    q.contracts.write_json(path, q.seal({key: item for key, item in value.items() if key != "content_sha256"}))


def resources(path="/test.scope"):
    return {"path": path, "memory.max": q.data.MEMORY_BYTES, "memory.swap.max": 0,
            "memory.swap.current": 0, "memory.current": 100, "memory.peak": 200,
            "memory.events": {"oom": 0, "oom_kill": 0, "oom_group_kill": 0}}


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    work = tmp_path / "data_controller"
    work.mkdir()
    python = str(ROOT / ".venv/bin/python")
    predecessor = {"work_dir": str(work), "cache_root_a": str(tmp_path / "a"),
                   "cache_root_b": str(tmp_path / "b"), "raw_audit": str(tmp_path / "audit.json"),
                   "acceptance": str(work / "data_acceptance.json"), "python": python,
                   "python_realpath": str(Path(python).resolve())}
    publish(work / "plan.json", predecessor)
    predecessor = q.record(work / "plan.json")
    publish(work / "run_started.json", {"pid": 1234})
    identity = {"pid": 1234, "start_ticks": 777, "boot_id": "boot-1", "cwd": str(ROOT),
                "exe": predecessor["python_realpath"], "cgroup": "/original.scope",
                "cmdline": [python, str(ROOT / "tools/continue_v5_data_phase.py"), "run", "--plan", str(work / "plan.json")]}
    state = {"process": copy.deepcopy(identity)}
    monkeypatch.setattr(q.data, "load_plan", lambda path: q.data.stable_record(path))
    monkeypatch.setattr(q.data, "assert_pins", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(q.data, "boot_id", lambda: "boot-1")
    monkeypatch.setattr(q.data, "process_identity", lambda _pid: copy.deepcopy(state["process"]))
    monkeypatch.setattr(q, "unit_status", lambda name: {"name": name, "LoadState": "not-found"})
    test_report = tmp_path / "tests.xml"
    test_report.write_text('<testsuite tests="1" failures="0" errors="0"><testcase name="fixture"/></testsuite>')
    review = tmp_path / "review.json"
    publish(review, {"schema": 1, "kind": "spikeids_v5_research_continuation_review", "passed": True,
                     "sources": {str(path): q.snapshot(path)["sha256"] for path in q.extra_sources()},
                     "test_report": {"path": str(test_report), "sha256": q.snapshot(test_report)["sha256"]}})
    history = tmp_path / "history.md"
    history.write_text("Synthetic prior-exposure disclosure, not formal evidence.\n")
    args = argparse.Namespace(data_plan=work / "plan.json", data_pid=1234, service_unit="new-research.service",
                              work_dir=tmp_path / "research", profiles_dir=tmp_path / "profiles",
                              workers_dir=tmp_path / "workers", run_dir=tmp_path / "formal",
                              review_record=review, test_report=test_report, exposure_history=history)
    path = q.freeze(args)
    plan = q.load_plan(path)[0]
    return SimpleNamespace(path=path, plan=plan, state=state, args=args, predecessor=predecessor)


def test_freeze_load_and_exact_sources(frozen):
    assert q.load_plan(frozen.path)[0]["stages"] == list(q.STAGES)
    changed = q.record(frozen.path)
    changed["pins"].pop(str(q.extra_sources()[0]))
    publish(frozen.path, changed)
    with pytest.raises(Exception, match="inventory"):
        q.load_plan(frozen.path)


@pytest.mark.parametrize("change", ["start_ticks", "boot_id", "cmdline"])
def test_predecessor_reuse_rejected(frozen, change):
    frozen.state["process"][change] = {"start_ticks": 778, "boot_id": "boot-other", "cmdline": ["other"]}[change]
    with pytest.raises(Exception, match="PID"):
        q.predecessor_ended(frozen.plan)


def test_missing_parent_completion_never_inferred(frozen, monkeypatch):
    frozen.state["process"] = None
    with pytest.raises(Exception, match="without a completion"):
        q.wait_for_data(frozen.plan)
    publish(Path(frozen.predecessor["work_dir"]) / "failed.json", {"passed": False})
    with pytest.raises(Exception, match="failed"):
        q.wait_for_data(frozen.plan)


@pytest.mark.parametrize("role", ["profiles_dir", "workers_dir", "run_dir"])
def test_existing_outputs_rejected_before_any_stage(frozen, monkeypatch, role):
    Path(frozen.plan[role]).mkdir()
    monkeypatch.setattr(q, "controller", lambda *_args: {"process": {"pid": os.getpid()}})
    monkeypatch.setattr(q, "wait_for_data", lambda *_args: pytest.fail("must reject existing output first"))
    with pytest.raises(Exception, match="Fresh"):
        q.run(frozen.path)
    assert q.record(Path(frozen.plan["work_dir"]) / "failed.json")["automatic_retry"] is False


def test_second_controller_cannot_poison_existing_run(frozen, monkeypatch):
    work = Path(frozen.plan["work_dir"])
    q.data.write_new(work / "run_started.json", q.seal({"owner": "first"}))
    monkeypatch.setattr(q, "controller", lambda *_args: {"process": {"pid": os.getpid()}})
    with pytest.raises(Exception):
        q.run(frozen.path)
    assert not (work / "failed.json").exists()
    assert q.record(work / "run_started.json")["owner"] == "first"


def test_stale_review_is_rejected(frozen):
    frozen.args.test_report.write_text('<testsuite><testcase><failure/></testcase></testsuite>')
    with pytest.raises(Exception):
        q.review_gate(frozen.args.review_record, frozen.args.test_report)


@pytest.mark.parametrize("left,right", [(False, 0), (True, 1), (80, 80.0), ({"a": False}, {"a": 0})])
def test_typed_json_contract(left, right):
    assert not q.typed_equal(left, right)


def test_merge_cannot_replace_commitment(tmp_path):
    item = tmp_path / "bytes"
    item.write_bytes(b"first")
    pins = {str(item): q.snapshot(item)}
    q.merge_pins(pins, dict(pins))
    item.write_bytes(b"second")
    with pytest.raises(Exception, match="replace"):
        q.merge_pins(pins, {str(item): q.snapshot(item)})


@pytest.mark.parametrize("unit", ["new.scope", "new.service"])
def test_unit_properties_are_kind_specific(monkeypatch, unit):
    keys = q.UNIT_PROPERTIES if unit.endswith("scope") else q.SERVICE_PROPERTIES
    monkeypatch.setattr(q.subprocess, "run", lambda *_args, **_kwargs:
                        SimpleNamespace(stdout="\n".join(f"{key}=" for key in keys)))
    assert set(q.unit_status(unit)) == set(keys) | {"name"}


def test_missing_service_fields_not_silently_defaulted(monkeypatch):
    monkeypatch.setattr(q.subprocess, "run", lambda *_args, **_kwargs:
                        SimpleNamespace(stdout="\n".join(f"{key}=" for key in q.UNIT_PROPERTIES)))
    with pytest.raises(Exception, match="Incomplete"):
        q.unit_status("new.service")


@pytest.mark.parametrize("before,after", [(False, False), (0, 1), (1, 0), (0, False), (-1, -1)])
def test_host_oom_types_and_deltas_rejected(before, after):
    with pytest.raises(Exception, match="OOM"):
        q.check_oom({"initial_host_oom_kill": before, "final_host_oom_kill": after})


def test_historical_host_oom_is_not_new_failure():
    q.check_oom({"initial_host_oom_kill": 123, "final_host_oom_kill": 123})


def test_low_disk_rejected(frozen, monkeypatch):
    monkeypatch.setattr(q.shutil, "disk_usage", lambda _path: SimpleNamespace(free=q.FLOOR_BYTES - 1))
    with pytest.raises(Exception, match="50-GiB"):
        q.disk_preflight(frozen.plan)


@pytest.fixture
def formal_fixture(frozen, monkeypatch):
    run = Path(frozen.plan["run_dir"])
    run.mkdir()
    workers = Path(frozen.plan["workers_dir"])
    workers.mkdir()
    binding = {"synthetic_accepted_data": True}
    publish(workers / "qualification_plan.json", {"data_evidence": binding})
    form = {"schema": q.contracts.SCHEMA, "sources": q.contracts.sources(), "seeds": list(range(20)),
            "protocol_role": "planned_benchmark", "environment": {"selected": True},
            "execution": {"workers": 4, "unit": "independent job", "seed_order": "ascending within job",
                          "resource_note": "worker count is hardware-specific and must pass replica verification"},
            "alpha": .05, "equivalence_margin_pp": 1.0, "deployment_seed": 0, "data_evidence": binding,
            "margin_status": "frozen numerical-equivalence sensitivity margin before formal test evaluation; not historical preregistration and not an empirically established practical-importance threshold",
            "prior_test_exposure": "unknown outside this run directory; disclose historical exploration",
            "training_policy": {"loss_weighting": "sqrt_inverse_fit_only_v1", "checkpoint_policy": "fixed_final_epoch_v1", "validation_role": "diagnostic_only"},
            "jobs": [{"id": d + "_" + m, "dataset": d, "model": m,
                      "cache": str(Path(frozen.predecessor["cache_root_a"]) / d),
                      "hyperparameters": q.expected_hyperparameters(d, m, "single", 1)}
                     for d in q.contracts.DATASETS for m in q.contracts.ARMS[d]],
            "difference_family": [f"{d}:relu_vs_{a}:{m}" for d in q.contracts.DATASETS for a in q.contracts.ARMS[d] if a != "relu" for m in q.contracts.METRICS],
            "equivalence_family": [f"{d}:{m}" for d in q.contracts.DATASETS for m in q.contracts.METRICS],
            "resource_limits": {"maximum_process_tree_rss_bytes": 14*1024**3, "require_bounded_cgroup": True,
                                "maximum_cgroup_memory_bytes": q.data.MEMORY_BYTES, "maximum_sample_gap_seconds": 15.0,
                                "maximum_gpu_memory_used_mib": 15360, "maximum_gpu_temperature_c": 80,
                                "require_zero_swap_io": False, "require_zero_oom_kills": True,
                                "host_swap_scope": "host context only when workload cgroup is enforced; not attributed to this run"}}
    publish(run / "plan.json", form)
    monkeypatch.setattr(q.suite, "validate_plan_data_evidence", lambda _plan: None)
    monkeypatch.setattr(q, "selected_runtime", lambda _plan: ("single", 1, 4, {"selected": True}))
    return frozen, form


def test_formal_exact_440_contract(formal_fixture):
    frozen, _form = formal_fixture
    formal = q.validate_formal(frozen.plan)
    assert sum(len(job["hyperparameters"]["seeds"]) for job in formal["jobs"]) * 2 == 440


@pytest.mark.parametrize("attack", ["compile", "bool_seed", "float_epoch", "deployment", "cgroup", "swap", "epochs",
                                   "test_margin", "prior", "data", "environment", "workers", "seed_count"])
def test_formal_coordinated_reseal_rejected(formal_fixture, attack):
    frozen, form = formal_fixture
    if attack == "compile": form["jobs"][0]["hyperparameters"]["compile"] = 0
    elif attack == "bool_seed": form["jobs"][0]["hyperparameters"]["seeds"][0] = False
    elif attack == "float_epoch": form["jobs"][0]["hyperparameters"]["epochs"] = 80.0
    elif attack == "deployment": form["deployment_seed"] = False
    elif attack == "cgroup": form["resource_limits"]["require_bounded_cgroup"] = 1
    elif attack == "swap": form["resource_limits"]["require_zero_swap_io"] = 0
    elif attack == "epochs": form["jobs"][0]["hyperparameters"]["epochs"] = 1
    elif attack == "test_margin": form["margin_status"] = "historically preregistered"
    elif attack == "prior": form.pop("prior_test_exposure")
    elif attack == "data": form["data_evidence"] = {"foreign": True}
    elif attack == "environment": form["environment"]["selected"] = 1
    elif attack == "workers": form["execution"]["workers"] = 1
    elif attack == "seed_count": form["seeds"] = [0]
    publish(Path(frozen.plan["run_dir"]) / "plan.json", form)
    with pytest.raises(Exception):
        q.validate_formal(frozen.plan)


def test_commands_exact_training_roles(frozen, monkeypatch):
    monkeypatch.setattr(q, "selected_runtime", lambda _plan: ("single", 1, 4, {}))
    cmd = q.command(frozen.plan, "freeze_formal")
    assert cmd[cmd.index("--seeds") + 1:cmd.index("--delta")] == list(map(str, range(20)))
    assert q.command(frozen.plan, "fit_primary")[2] == "fit"
    assert q.command(frozen.plan, "fit_replica")[2] == "verify"
    assert q.command(frozen.plan, "evaluate")[2] == "evaluate"
    assert q.STAGES.count("fit_replica") == q.STAGES.count("evaluate") == 1
    assert q.STAGES.index("fit_replica") < q.STAGES.index("validate_fit") < q.STAGES.index("evaluate")
    assert q.STAGES.index("statistics") < q.STAGES.index("equivalence") < q.STAGES.index("independent")


def make_partial(tmp_path, monkeypatch, actions):
    import test_resource_evidence as fixture
    fixture.isolated_process_tree.__wrapped__(monkeypatch)
    monkeypatch.setattr(q.suite, "cgroup_sample", fixture.bounded)
    monkeypatch.setattr(q.suite, "_host_sample", lambda: {
        "vmstat": {"pswpin": 0, "pswpout": 0, "oom_kill": 0},
        "mem_available_bytes": 10**9, "swap_free_bytes": 10**9})
    protocol = fixture.plan()
    for action in actions:
        with q.suite.resource_monitor(tmp_path, action, protocol, 1):
            pass
    return protocol


@pytest.mark.parametrize("actions", [("fit",), ("fit", "verify")])
def test_real_partial_resource_replay(tmp_path, monkeypatch, actions):
    protocol = make_partial(tmp_path, monkeypatch, actions)
    assert q.partial_resources(tmp_path, protocol, actions)["full_resource_acceptance"] is False


@pytest.mark.parametrize("attack", ["missing", "extra_raw", "failed", "raw_hash", "oom"])
def test_partial_resources_corruption_rejected(tmp_path, monkeypatch, attack):
    protocol = make_partial(tmp_path, monkeypatch, ("fit",))
    report_path = tmp_path / "resource_fit_001.json"
    report = q.record(report_path)
    if attack == "missing": report_path.unlink()
    elif attack == "extra_raw": (tmp_path / "resource_orphan.jsonl").write_bytes(b"x")
    elif attack == "failed": report["telemetry_passed"] = False
    elif attack == "raw_hash": report["raw_samples"]["sha256"] = "0"*64
    elif attack == "oom": report["vmstat_delta"]["oom_kill"] = 1
    if attack not in ("missing", "extra_raw"):
        publish(report_path, report)
    with pytest.raises(Exception):
        q.partial_resources(tmp_path, protocol, ("fit",))


@pytest.mark.parametrize("attack", ["extra_file", "extra_dir", "mutation", "restore", "link"])
def test_artifact_boundary_rejects_late_changes(tmp_path, attack):
    item = tmp_path / "checkpoint.pt"
    item.write_bytes(b"opaque bytes")
    boundary = q.artifact_boundary(tmp_path)
    q.assert_boundary(boundary)
    if attack == "extra_file": (tmp_path / "unexpected").write_bytes(b"x")
    elif attack == "extra_dir": (tmp_path / "unexpected").mkdir()
    elif attack in ("mutation", "restore"):
        item.write_bytes(b"changed")
        if attack == "restore": item.write_bytes(b"opaque bytes")
    elif attack == "link": (tmp_path / "alias").symlink_to(item)
    with pytest.raises(Exception):
        q.assert_boundary(boundary, full=False)


def test_boundary_allows_only_declared_report(tmp_path):
    (tmp_path / "checkpoint.pt").write_bytes(b"opaque")
    boundary = q.artifact_boundary(tmp_path)
    (tmp_path / "stats_report_globecom.json").write_bytes(b"synthetic")
    q.assert_boundary(boundary, ("stats_report_globecom.json",))
    with pytest.raises(Exception):
        q.assert_boundary(boundary)


def synthetic_orchestration(frozen, monkeypatch, failing=None):
    """Only OS/scientific stage execution is mocked; run's durable state is real."""
    work, run = Path(frozen.plan["work_dir"]), Path(frozen.plan["run_dir"])
    owner = {"process": {"pid": os.getpid()}}
    visited = []
    monkeypatch.setattr(q, "controller", lambda *_args: owner)
    monkeypatch.setattr(q, "wait_for_data", lambda _plan: None)
    monkeypatch.setattr(q.neural, "read_plan", lambda _run: {"content_sha256": "f"*64})

    def stage_execution(plan, stage):
        visited.append(stage)
        receipt = {"stage": stage, "passed": stage != failing, "result": {}}
        paths = []
        if stage == failing:
            q.data.write_new(work / f"{stage}_exit.json", q.seal(receipt))
            raise q.data.evidence.VerificationError("synthetic actual child failure")
        if stage == "validate_data":
            receipt["result"]["cache_checks"] = {}  # Explicitly mocked delegated data proof.
        if stage == "recover_acceptance":
            target = Path(plan["recovery"]["acceptance"])
            publish(target, {"fixture": "complete fresh replay delegated to synthetic stage"})
            paths.append(target)
        if stage in ("profiles", "workers"):
            root = Path(plan[f"{stage}_dir"])
            root.mkdir()
            publish(root / "qualification_plan.json", {"fixture": True})
            (root / "fit.pt").write_bytes(b"synthetic opaque checkpoint")
            publish(root / "qualification.json", {"mode": stage, "passed": True, "artifacts": q.qualification._artifacts(root)})
        if stage in ("verify_profiles", "verify_workers"):
            root = Path(plan[f"{stage.removeprefix('verify_')}_dir"])
            paths.extend([root / "qualification_plan.json", root / "qualification.json"])
        if stage == "freeze_formal":
            run.mkdir()
            publish(run / "plan.json", {"fixture": True})
        if stage == "validate_evaluate":
            receipt["result"]["artifact_boundary"] = q.artifact_boundary(run)
        if stage == "statistics":
            publish(run / "stats_report_globecom.json", {"fixture": True})
            paths.append(run / "stats_report_globecom.json")
        if stage == "equivalence":
            publish(run / "equivalence_v5.json", {"fixture": True})
            (run / "equivalence_v5.md").write_text("synthetic report")
            paths.extend([run / "equivalence_v5.json", run / "equivalence_v5.md"])
        if stage == "independent":
            publish(run / "independent_verification.json", {
                "kind": "independent_formal_neural_and_statistics_verification", "passed": True,
                "plan_sha256": "f"*64, "prediction_artifacts_checked": 440, "checkpoints_checked": 440})
            paths.append(run / "independent_verification.json")
        q.data.write_new(work / f"{stage}_exit.json", q.seal(receipt))
        paths.append(work / f"{stage}_exit.json")
        return receipt, {str(path): q.snapshot(path) for path in paths}

    monkeypatch.setattr(q, "run_stage", stage_execution)
    return visited


def test_full_one_shot_sequence_with_explicit_delegated_stage_fixtures(frozen, monkeypatch):
    visited = synthetic_orchestration(frozen, monkeypatch)
    report = q.run(frozen.path)
    assert visited == list(q.STAGES)
    assert report["passed"] is True and report["terminal_scope"] == "independently_verified_neural_and_statistics"
    assert report["unautomated"] == q.UNAUTOMATED
    assert not (Path(frozen.plan["work_dir"]) / "failed.json").exists()
    before = q.snapshot(Path(frozen.plan["work_dir"]) / "complete.json")
    with pytest.raises(Exception):
        q.run(frozen.path)
    assert visited == list(q.STAGES)
    assert before == q.snapshot(Path(frozen.plan["work_dir"]) / "complete.json")
    assert not (Path(frozen.plan["work_dir"]) / "failed.json").exists()


@pytest.mark.parametrize("failing", q.STAGES)
def test_each_stage_failure_stops_without_retry_or_publication(frozen, monkeypatch, failing):
    visited = synthetic_orchestration(frozen, monkeypatch, failing)
    with pytest.raises(Exception, match="synthetic actual child failure"):
        q.run(frozen.path)
    assert visited == list(q.STAGES[:q.STAGES.index(failing) + 1])
    work = Path(frozen.plan["work_dir"])
    failed = q.record(work / "failed.json")
    assert failed["stage"] == failing and failed["passed"] is False and failed["automatic_retry"] is False
    assert not (work / "complete.json").exists()
    original = q.snapshot(work / "failed.json")
    with pytest.raises(Exception):
        q.run(frozen.path)
    assert q.snapshot(work / "failed.json") == original


@pytest.mark.parametrize("stage", ["validate_data", "verify_profiles", "verify_workers", "validate_formal", "validate_fit", "validate_evaluate"])
def test_internal_results_cannot_be_empty(frozen, stage):
    with pytest.raises(Exception):
        q.validate_gate_result(frozen.plan, stage, {})


def test_internal_formal_receipt_inventory_is_exact(formal_fixture):
    frozen, _form = formal_fixture
    run = Path(frozen.plan["run_dir"])
    publish(run / "environment.json", {"fixture": True})
    result = {"formal_plan_sha256": q.record(run / "plan.json")["content_sha256"],
              "pins": {str(run / name): q.snapshot(run / name) for name in ("plan.json", "environment.json")}}
    q.validate_gate_result(frozen.plan, "validate_formal", result)
    result["pins"].pop(str(run / "environment.json"))
    with pytest.raises(Exception, match="inventory"):
        q.validate_gate_result(frozen.plan, "validate_formal", result)


def retained_fixture(tmp_path):
    plan, commitments = {}, {}
    for role in ("profiles", "workers"):
        root = tmp_path / role
        root.mkdir()
        plan[f"{role}_dir"] = str(root)
        publish(root / "qualification_plan.json", {"fixture": True})
        (root / "fit.pt").write_bytes(b"retained checkpoint bytes")
        publish(root / "qualification.json", {"mode": role, "passed": True, "artifacts": q.qualification._artifacts(root)})
        commitments.update({str(root / name): q.snapshot(root / name) for name in ("qualification.json", "qualification_plan.json")})
    return plan, commitments


def test_retention_preserves_all_qualification_bytes(tmp_path):
    plan, commitments = retained_fixture(tmp_path)
    boundaries = q.retain_qualifications(plan, commitments)
    assert len(commitments) == 6 and len(boundaries) == 2
    for boundary in boundaries:
        q.assert_boundary(boundary, full=False)


@pytest.mark.parametrize("attack", ["delete", "mutate", "extra", "reseal_report"])
def test_late_qualification_corruption_prevents_completion(tmp_path, attack):
    plan, commitments = retained_fixture(tmp_path)
    root = Path(plan["workers_dir"])
    if attack == "delete": (root / "fit.pt").unlink()
    elif attack == "mutate": (root / "fit.pt").write_bytes(b"changed")
    elif attack == "extra": (root / "extra.pt").write_bytes(b"unreported")
    elif attack == "reseal_report":
        (root / "fit.pt").write_bytes(b"changed")
        report = q.record(root / "qualification.json")
        report["artifacts"] = q.qualification._artifacts(root)
        publish(root / "qualification.json", report)
    with pytest.raises(Exception):
        q.retain_qualifications(plan, commitments)


def test_qualification_post_hash_endpoint_detects_new_changes(tmp_path):
    plan, commitments = retained_fixture(tmp_path)
    boundaries = q.retain_qualifications(plan, commitments)
    (Path(plan["profiles_dir"]) / "extra_empty_dir").mkdir()
    with pytest.raises(Exception, match="inventory"):
        q.assert_boundary(boundaries[0], full=False)


@pytest.fixture
def recovery(frozen, tmp_path, monkeypatch):
    """Complete real file inventories; raw semantics/OS identities are isolated fixtures."""
    import test_data_continuation as old_fixture
    work = Path(frozen.predecessor["work_dir"])
    original = dict(frozen.predecessor)
    original.update(a_exit_record=str(work / "a_exit.json"), iot_provenance=str(q.ROOT / "spikeids_v5/audit/iot23_provenance.json"),
                    a_process={"pid": 111, "boot_id": "boot-1", "start_ticks": 100},
                    a_scope={"name": "original-a.scope", "InvocationID": "a"*32, "ControlGroup": "/test.scope"})
    Path(original["raw_audit"]).write_text("synthetic audited raw binding")
    original["pins"] = {str(path): q.snapshot(path) for path in
                        (q.ROOT / "tools/verify_v5_data.py", q.ROOT / "spikeids_v5/data_loaders.py",
                         Path(original["raw_audit"]), Path(original["iot_provenance"]))}
    publish(work / "plan.json", original)
    original = q.record(work / "plan.json")
    publish(work / "run_started.json", {"pid": 1234, "plan_sha256": original["content_sha256"]})
    publish(work / "a_exit.json", {"schema": 1, "kind": "spikeids_v5_owner_exec_exit_receipt",
            "plan_sha256": original["content_sha256"], "a_process": original["a_process"],
            "a_scope_invocation_id": original["a_scope"]["InvocationID"], "return_code": 0,
            "source": "owner_observed_exec_return_code_not_inferred_from_artifacts"})
    publish(work / "a_completion.json", {"receipt": q.record(work / "a_exit.json"),
            "scope_after_exit": {"LoadState": "not-found"}, "last_observed_cgroup": resources(),
            "note": "Last observed is not a final removed-scope measurement"})
    checked = {}
    for role in ("a", "b"):
        root = Path(original[f"cache_root_{role}"])
        root.mkdir()
        for dataset in q.data.evidence.DATASETS:
            (root / f"{dataset}.lock").write_bytes(b"0")
            (root / dataset).mkdir()
            for name in q.data.evidence.EXPECTED_CACHE_FILES | {"metadata.json"}:
                (root / dataset / name).write_bytes(f"opaque {dataset}/{name}".encode())
        checked[role] = {"role": role, "root": str(root), "root_identity": q.data.directory_identity(root),
                         "audit_mtime_ns": 0, "passed": True,
                         "inventory": q.data.evidence._cache_root_inventory(root, after_ns=0),
                         "stability": q.data.evidence._cache_root_stability(root, after_ns=0),
                         "datasets": {name: old_fixture._summary(name) for name in q.data.evidence.DATASETS}}
    for index, phase in enumerate(q.data.PHASES):
        name = q.data.scope_name(original, phase)
        scope = {"name": name, "LoadState": "loaded", "ActiveState": "active", "InvocationID": f"{index+1:x}"*32,
                 "ControlGroup": "/test.scope"}
        worker = {"pid": 2000 + index, "start_ticks": 9000 + index, "boot_id": "boot-1", "cwd": str(q.ROOT),
                  "exe": original["python_realpath"], "cgroup": "/test.scope",
                  "cmdline": q.data.worker_command(original, work / "plan.json", phase)}
        publish(work / f"{phase}_started.json", {"phase": phase, "scope": name, "plan_sha256": original["content_sha256"]})
        receipt = {"schema": 1, "kind": "spikeids_v5_data_phase_exit", "phase": phase,
                   "plan_sha256": original["content_sha256"], "scope": scope, "worker": worker,
                   "initial_cgroup": resources(), "final_cgroup": resources(),
                   "passed": phase != "acceptance", "return_code": -7 if phase == "acceptance" else 0}
        if phase.startswith("check_"):
            receipt["cache_check"] = checked[phase[-1]]
        else:
            (work / f"{phase}.log").write_bytes(b"")
            receipt.update(command=q.data.phase_command(original, phase), log_sha256=q.snapshot(work / f"{phase}.log")["sha256"])
        (work / f"{phase}_scope.log").write_bytes(b"synthetic scope log")
        publish(work / f"{phase}_exit.json", receipt)
    publish(work / "failed.json", {"kind": "spikeids_v5_data_continuation_failure", "schema": 1,
            "stage": "acceptance", "plan_sha256": original["content_sha256"], "passed": False,
            "automatic_retry": False, "training_started": False, "error": "acceptance scope failed"})
    frozen.state["process"] = None
    monkeypatch.setattr(q.data, "scope_status", lambda name: {"name": name, "LoadState": "not-found"})
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("TMPDIR", str(runtime))
    monkeypatch.setattr(q.data.tempfile, "tempdir", None)
    # Tests may themselves run under /tmp; isolate the machine mount selection
    # separately while exercising its real gate in dedicated tests below.
    monkeypatch.setattr(q, "temporary_runtime", lambda path, **kwargs: {
        "path": str(path), "identity": q.data.directory_identity(Path(path)),
        "mount": {"source": "/dev/nvme-fixture", "filesystem": "ext4"}, "environment": {"TMPDIR": str(path)}})
    args = copy.copy(frozen.args)
    args.action = "freeze-recovery"
    args.runtime_tmp_dir = runtime
    args.work_dir = tmp_path / "recovered_research"
    args.profiles_dir = tmp_path / "recovered_profiles"
    args.workers_dir = tmp_path / "recovered_workers"
    args.run_dir = tmp_path / "recovered_formal"
    frozen.predecessor = original
    return SimpleNamespace(original=original, args=args, state=frozen.state, checked=checked)


def test_manual_recovery_freeze_preserves_failure_and_full_cache_inventory(recovery):
    old_work = Path(recovery.original["work_dir"])
    before = q.snapshot(old_work / "failed.json")
    path = q.freeze(recovery.args)
    plan = q.load_plan(path)[0]
    assert plan["mode"] == q.RECOVERY_MODE and q.stages(plan)[0] == "recover_acceptance"
    assert plan["data_process"]["start_ticks"] is None
    assert plan["recovery"]["parent_os_return_code"] is None
    assert q.snapshot(old_work / "failed.json") == before and not (old_work / "complete.json").exists()
    assert not Path(recovery.original["acceptance"]).exists()
    assert all(str(Path(recovery.original[f"cache_root_{role}"]) / f"{name}.lock") in plan["pins"]
               for role in ("a", "b") for name in q.data.evidence.DATASETS)
    for stage in ("recover_acceptance", "profiles"):
        argv = q.command(plan, stage)
        assert plan["recovery"]["acceptance"] in argv and recovery.original["acceptance"] not in argv


@pytest.mark.parametrize("attack", ["false_exit", "zero_exit", "other_exit", "bad_prefix", "old_output", "old_complete",
                                   "owner_failure", "worker_live", "cache_change", "scope_failed", "resource_oom",
                                   "duplicate_invocation", "original_a_invocation", "duplicate_execution"])
def test_manual_recovery_rejects_invalid_preserved_prefix(recovery, monkeypatch, attack):
    old = recovery.original
    work = Path(old["work_dir"])
    if attack in ("false_exit", "zero_exit", "other_exit"):
        row = q.record(work / "acceptance_exit.json")
        row["return_code"] = {"false_exit": False, "zero_exit": 0, "other_exit": -9}[attack]
        publish(work / "acceptance_exit.json", row)
    elif attack == "bad_prefix":
        row = q.record(work / "prepare_b_exit.json"); row["passed"] = False
        publish(work / "prepare_b_exit.json", row)
    elif attack == "old_output": publish(Path(old["acceptance"]), {"passed": True})
    elif attack == "old_complete": publish(work / "complete.json", {"passed": True})
    elif attack == "owner_failure":
        row = q.record(work / "a_exit.json"); row["return_code"] = 1
        publish(work / "a_exit.json", row)
    elif attack == "worker_live":
        monkeypatch.setattr(q.data, "process_identity", lambda pid: {"pid": pid} if pid == 2003 else None)
    elif attack == "cache_change":
        (Path(old["cache_root_b"]) / "unsw/metadata.json").write_bytes(b"changed")
    elif attack == "scope_failed":
        receipt = q.record(work / "prepare_b_exit.json")
        monkeypatch.setattr(q.data, "scope_status", lambda name: {
            **receipt["scope"], "LoadState": "loaded", "ActiveState": "inactive", "Result": "signal"}
            if name == receipt["scope"]["name"] else {"name": name, "LoadState": "not-found"})
    elif attack == "resource_oom":
        row = q.record(work / "acceptance_exit.json"); row["final_cgroup"]["memory.events"]["oom"] = 1
        publish(work / "acceptance_exit.json", row)
    elif attack in ("duplicate_invocation", "original_a_invocation", "duplicate_execution"):
        first = q.record(work / "check_a_exit.json")
        row = q.record(work / "check_b_exit.json")
        if attack == "duplicate_invocation": row["scope"]["InvocationID"] = first["scope"]["InvocationID"]
        elif attack == "original_a_invocation": row["scope"]["InvocationID"] = old["a_scope"]["InvocationID"]
        else:
            for key in ("boot_id", "pid", "start_ticks"):
                row["worker"][key] = first["worker"][key]
        publish(work / "check_b_exit.json", row)
    with pytest.raises(Exception):
        q.freeze(recovery.args)
    assert not recovery.args.work_dir.exists()


def test_recovery_pin_inventory_cannot_drop_failed_evidence(recovery):
    path = q.freeze(recovery.args)
    plan = q.record(path)
    plan["pins"].pop(str(Path(recovery.original["work_dir"]) / "failed.json"))
    publish(path, plan)
    with pytest.raises(Exception, match="inventory"):
        q.load_plan(path)


def test_recovery_original_failure_changes_are_not_adopted(recovery):
    path = q.freeze(recovery.args)
    plan = q.load_plan(path)[0]
    target = Path(recovery.original["work_dir"]) / "failed.json"
    original = q.record(target)
    original["error"] = "changed preserved failure"
    publish(target, original)
    with pytest.raises(Exception, match="changed"):
        q.check_sources(plan, full=False)


def recovered_attempt(recovery):
    """Synthetic new scope receipt, consumed by the real recovered-data gate."""
    import test_data_continuation as old_fixture
    path = q.freeze(recovery.args)
    plan = q.load_plan(path)[0]
    work = Path(plan["work_dir"])
    owner = {"fixture_controller": True}
    publish(work / "run_started.json", {"controller": owner, "plan_sha256": plan["content_sha256"]})
    publish(work / "recover_acceptance_started.json", {"controller": owner, "plan_sha256": plan["content_sha256"], "stage": "recover_acceptance"})
    target = Path(plan["recovery"]["acceptance"])
    publish(target, old_fixture._acceptance(q.data_context(plan)))
    for name in ("recover_acceptance_scope.log", "recover_acceptance.log"):
        (work / name).write_bytes(b"synthetic successful verifier execution")
    receipt = {"schema": 1, "kind": "spikeids_v5_research_stage_exit", "stage": "recover_acceptance",
               "plan_sha256": plan["content_sha256"], "controller": owner, "passed": True, "return_code": 0,
               "command": q.command(plan, "recover_acceptance"),
               "evidence": {str(work / "recover_acceptance.log"): q.snapshot(work / "recover_acceptance.log")},
               "result": {"acceptance_output": str(target), "pins": {str(target): q.snapshot(target)}},
               "worker": {"pid": 9999, "start_ticks": 10000, "boot_id": "boot-1", "exe": plan["python_realpath"],
                          "cwd": str(q.ROOT), "cgroup": "/test.scope", "cmdline": q.worker_argv(plan, "recover_acceptance")},
               "scope": {"name": q.stage_name(plan, "recover_acceptance"), "ActiveState": "active", "InvocationID": "c"*32,
                         "ControlGroup": "/test.scope", "BindsTo": plan["service_unit"], "After": plan["service_unit"]},
               "initial_cgroup": resources(), "final_cgroup": resources(), "initial_host_oom_kill": 0, "final_host_oom_kill": 0}
    publish(work / "recover_acceptance_exit.json", receipt)
    return plan


def test_recovered_gate_accepts_fresh_full_scope_and_keeps_failed_history(recovery):
    plan = recovered_attempt(recovery)
    result = q.validate_data(plan)
    q.validate_gate_result(plan, "validate_data", result)
    assert result["kind"] == "explicit_fresh_acceptance_after_preserved_sigbus_failure"
    assert result["acceptance"]["path"] == plan["recovery"]["acceptance"]
    assert result["predecessor_parent_os_return_code"] is None
    assert not Path(recovery.original["acceptance"]).exists()
    assert not (Path(recovery.original["work_dir"]) / "complete.json").exists()


@pytest.mark.parametrize("attack", ["missing_output_pin", "changed_output", "changed_command", "bool_exit", "failed_new_scope", "raw_gate_failure"])
def test_recovery_verifier_must_be_genuine_and_immutable(recovery, attack):
    plan = recovered_attempt(recovery)
    work = Path(plan["work_dir"])
    receipt = q.record(work / "recover_acceptance_exit.json")
    if attack == "missing_output_pin": receipt["result"]["pins"] = {}
    elif attack == "changed_command": receipt["command"][-1] = recovery.original["acceptance"]
    elif attack == "bool_exit": receipt["return_code"] = False
    elif attack == "failed_new_scope": receipt.update(passed=False, return_code=-7)
    elif attack in ("changed_output", "raw_gate_failure"):
        target = Path(plan["recovery"]["acceptance"])
        report = q.record(target)
        if attack == "changed_output": report["undisclosed_change"] = True
        else:
            report["datasets"]["unsw"]["semantic_checks"]["frozen_partition_and_closure_replayed"] = False
        publish(target, report)
        if attack == "raw_gate_failure": receipt["result"]["pins"][str(target)] = q.snapshot(target)
    publish(work / "recover_acceptance_exit.json", receipt)
    with pytest.raises(Exception):
        q.validate_data(plan)


def test_recovery_formal_command_uses_only_new_acceptance(recovery, monkeypatch):
    path = q.freeze(recovery.args)
    plan = q.load_plan(path)[0]
    monkeypatch.setattr(q, "selected_runtime", lambda _plan: ("single", 1, 4, {}))
    argv = q.command(plan, "freeze_formal")
    assert argv[argv.index("--data-acceptance") + 1] == plan["recovery"]["acceptance"]
    assert recovery.original["acceptance"] not in argv


@pytest.mark.parametrize("attack", ["tmpfs", "environment", "python_cache", "nonempty"])
def test_temporary_runtime_rejects_unbound_scratch(tmp_path, monkeypatch, attack):
    # Exercise the actual gate while isolating only the host mount declaration.
    root = tmp_path / "repository"
    root.mkdir()
    target = tmp_path / "scratch"
    target.mkdir()
    monkeypatch.setattr(q, "ROOT", root)
    monkeypatch.setenv("TMPDIR", str(target))
    monkeypatch.setattr(q.data.tempfile, "tempdir", str(target))
    monkeypatch.setattr(q, "mount_record", lambda _path: {"filesystem": "tmpfs" if attack == "tmpfs" else "ext4", "source": "/dev/nvme0n1p2"})
    if attack == "environment": monkeypatch.setenv("TMPDIR", "/tmp")
    elif attack == "python_cache": monkeypatch.setattr(q.data.tempfile, "tempdir", "/tmp")
    elif attack == "nonempty": (target / "stale").write_bytes(b"x")
    with pytest.raises(Exception):
        q.temporary_runtime(target, fresh=True)


def test_recovery_full_sequence_is_explicit_and_never_waits_for_old_success(recovery, monkeypatch):
    path = q.freeze(recovery.args)
    plan = q.load_plan(path)[0]
    value = SimpleNamespace(plan=plan, path=path)
    visited = synthetic_orchestration(value, monkeypatch)
    monkeypatch.setattr(q, "wait_for_data", lambda _plan: pytest.fail("Recovery must not invent/wait for old success"))
    before = q.snapshot(Path(recovery.original["work_dir"]) / "failed.json")
    complete = q.run(path)
    assert complete["mode"] == q.RECOVERY_MODE
    assert visited == ["recover_acceptance", *q.STAGES]
    assert q.snapshot(Path(recovery.original["work_dir"]) / "failed.json") == before
    assert not Path(recovery.original["acceptance"]).exists()


def test_failed_recovery_replay_stops_without_any_qualification(recovery, monkeypatch):
    path = q.freeze(recovery.args)
    plan = q.load_plan(path)[0]
    visited = synthetic_orchestration(SimpleNamespace(plan=plan, path=path), monkeypatch, "recover_acceptance")
    with pytest.raises(Exception, match="synthetic actual child failure"):
        q.run(path)
    assert visited == ["recover_acceptance"]
    assert q.record(Path(plan["work_dir"]) / "failed.json")["stage"] == "recover_acceptance"
    assert not Path(plan["profiles_dir"]).exists() and not (Path(plan["work_dir"]) / "complete.json").exists()


def test_real_nvme_temporary_directory_gate(monkeypatch):
    # Tiny empty directory only; never allocate large files or touch other runs.
    with q.data.tempfile.TemporaryDirectory(prefix="spikeids-tmp-runtime-unit-", dir="/var/tmp") as name:
        monkeypatch.setenv("TMPDIR", name)
        monkeypatch.setattr(q.data.tempfile, "tempdir", None)
        actual = q.temporary_runtime(Path(name), fresh=True)
        assert actual["mount"]["filesystem"] != "tmpfs"
        assert actual["environment"] == {"TMPDIR": name}
