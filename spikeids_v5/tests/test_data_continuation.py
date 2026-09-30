"""Synthetic orchestration tests; subprocess/scientific tool results are explicit fixtures.

No real cache construction, systemd scopes, training, or environment changes.
File seals/snapshots, process identity gates, receipts and orchestration are real.
The delegated scientific verifier has its own non-mocked unit and real-data tests.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("data_continuation_test", ROOT / "tools/continue_v5_data_phase.py")
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def resources(path="/fake/a"):
    return {"path": path, "memory.max": tool.MEMORY_BYTES, "memory.swap.max": 0,
            "memory.swap.current": 0, "memory.current": 100, "memory.peak": 200,
            "memory.events": {"oom": 0, "oom_kill": 0, "oom_group_kill": 0, "max": 0}}


def missing_scope(name):
    return {"name": name, **{key: "" for key in tool.SCOPE_PROPERTIES},
            "LoadState": "not-found", "ActiveState": "inactive"}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    package = repo / "spikeids_v5"
    specs = package / "audit/source_specs"
    specs.mkdir(parents=True)
    (repo / "tools").mkdir()
    (repo / "data").mkdir()
    (repo / "results").mkdir()
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").write_text("synthetic python")
    (repo / ".venv/pyvenv.cfg").write_text("synthetic runtime")
    for name in ("audit_data", "data_loaders", "group_protocol", "contracts", "suite"):
        (package / f"{name}.py").write_text(f"# {name}\n")
    for name in ("verify_v5_data", "verify_iot23_provenance"):
        (repo / "tools" / f"{name}.py").write_text(f"# {name}\n")
    (package / "audit/iot23_provenance.json").write_text("{}")
    audit_path = repo / "results/audit.json"
    audit_path.write_text("{}")
    records = {}
    for name in tool.evidence.DATASETS:
        (specs / f"{name}.json").write_text("{}")
        (repo / "data" / f"{name}.raw").write_text(f"raw {name}")
        raw_path = repo / "data" / f"{name}.raw"
        records[name] = {"record": {"source_spec": f"audit/source_specs/{name}.json",
                                    "files": [{"path": f"{name}.raw", "bytes": raw_path.stat().st_size,
                                               "sha256": tool.evidence.sha256(raw_path)}]},
                         "source_spec": {"origin_shards": []}}
    a = repo / "results/a"
    a.mkdir()
    (a / "marker").write_text("synthetic cache")
    work = repo / "results/continuation"
    args = argparse.Namespace(a_pid=4444, a_scope="original-a.scope", a_exit_record=work / "a_exit.json",
                              raw_audit=audit_path, cache_root_a=a, cache_root_b=repo / "results/b",
                              work_dir=work, python=str(repo / ".venv/bin/python"))
    process = {"pid": args.a_pid, "start_ticks": 12345, "boot_id": "boot-1", "cwd": str(repo),
               "exe": args.python, "cgroup": "/fake/a",
               "cmdline": [args.python, "spikeids_v5/suite.py", "prepare", "--data-dir", "data",
                           "--cache-root", str(a), "--raw-audit", str(audit_path),
                           "--source-spec-dir", str(specs)]}
    scope = {"name": args.a_scope, "LoadState": "loaded", "ActiveState": "active", "SubState": "running",
             "Result": "success", "InvocationID": "a" * 32, "ControlGroup": "/fake/a",
             "MemoryMax": str(tool.MEMORY_BYTES), "MemorySwapMax": "0"}
    state = {"process": process, "scope": scope, "resources": resources(), "boot": "boot-1"}
    monkeypatch.setattr(tool, "ROOT", repo)
    monkeypatch.setattr(tool.evidence, "__file__", str(repo / "tools/verify_v5_data.py"))
    monkeypatch.setattr(tool, "runtime", lambda _python: {"frozen_runtime": True})
    monkeypatch.setattr(tool, "boot_id", lambda: state["boot"])
    monkeypatch.setattr(tool, "process_identity", lambda _pid: copy.deepcopy(state["process"]))
    monkeypatch.setattr(tool, "scope_status", lambda name: copy.deepcopy(state["scope"])
                        if name == args.a_scope else missing_scope(name))
    monkeypatch.setattr(tool, "cgroup_sample", lambda _path: copy.deepcopy(state["resources"]))
    monkeypatch.setattr(tool.evidence, "_load_raw_audit", lambda *_args: ({}, records, 0))
    monkeypatch.setattr(tool.evidence, "_load_iot_provenance", lambda *_args: {})
    return SimpleNamespace(repo=repo, args=args, state=state, monkeypatch=monkeypatch)


def frozen(setup):
    path = tool.freeze(setup.args)
    plan, _ = tool.load_plan(path)
    return path, plan


def end_a(setup, path, code=0):
    setup.state["process"] = None
    setup.state["scope"] = missing_scope(setup.args.a_scope)
    return tool.record_a_exit(path, code)


def reseal(path, change):
    record = json.loads(path.read_text())
    record.pop("content_sha256")
    change(record)
    path.write_text(json.dumps(tool.evidence.seal(record)))


def test_freeze_pins_sources_raw_python_scope_and_original_process(setup):
    path, plan = frozen(setup)
    assert path == setup.args.work_dir / "plan.json"
    assert plan["a_process"]["start_ticks"] == 12345
    assert plan["a_scope"]["InvocationID"] == "a" * 32
    assert plan["automatic_retry"] is False and plan["training_authorized"] is False
    assert str(setup.repo / "data/unsw.raw") in plan["pins"]
    tool.assert_pins(plan)


def test_atomic_publication_never_overwrites(tmp_path):
    path = tmp_path / "record.json"
    tool.write_new(path, tool.evidence.seal({"first": True}))
    before = path.read_bytes()
    with pytest.raises(tool.evidence.VerificationError, match="Fresh output"):
        tool.write_new(path, {"replacement": True})
    assert path.read_bytes() == before


@pytest.mark.parametrize("kind", ["existing_b", "alias_a", "nested_a", "work_alias"])
def test_freeze_rejects_existing_or_aliasing_roots(setup, kind):
    if kind == "existing_b":
        setup.args.cache_root_b.mkdir()
    elif kind == "alias_a":
        setup.args.cache_root_b.symlink_to(setup.args.cache_root_a, target_is_directory=True)
    elif kind == "nested_a":
        setup.args.cache_root_b = setup.args.cache_root_a / "nested"
    else:
        setup.args.work_dir = setup.args.cache_root_a
    with pytest.raises(tool.evidence.VerificationError, match="Fresh|canonical|overlap"):
        tool.freeze(setup.args)


@pytest.mark.parametrize("change", ["source", "source_restore", "raw", "new_source", "runtime"])
def test_pins_reject_drift_including_changed_then_restored_bytes(setup, change):
    _path, plan = frozen(setup)
    if change == "runtime":
        setup.monkeypatch.setattr(tool, "runtime", lambda _python: {"frozen_runtime": False})
    elif change == "new_source":
        (setup.repo / "spikeids_v5/injected.py").write_text("# new module")
    else:
        target = setup.repo / ("data/unsw.raw" if change == "raw" else "spikeids_v5/data_loaders.py")
        before = target.read_bytes()
        target.write_bytes(before + b"changed")
        if change == "source_restore":
            target.write_bytes(before)
    with pytest.raises(tool.evidence.VerificationError, match="changed"):
        tool.assert_pins(plan)


@pytest.mark.parametrize("change", ["pid_reuse", "scope_reuse", "boot", "oom", "swap", "bound"])
def test_live_a_identity_and_resource_failures_stop(setup, change):
    _path, plan = frozen(setup)
    if change == "pid_reuse":
        setup.state["process"]["start_ticks"] += 1
    elif change == "scope_reuse":
        setup.state["scope"]["InvocationID"] = "b" * 32
    elif change == "boot":
        setup.state["boot"] = "boot-2"
    elif change == "oom":
        setup.state["resources"]["memory.events"]["oom_kill"] = 1
    elif change == "swap":
        setup.state["resources"]["memory.swap.current"] = 4096
    else:
        setup.state["resources"]["memory.max"] += 1
    with pytest.raises(tool.evidence.VerificationError):
        tool._a_ended(plan)


def test_pid_disappearance_and_complete_metadata_do_not_replace_owner_receipt(setup, capsys):
    _path, plan = frozen(setup)
    setup.state["process"] = None
    setup.state["scope"] = missing_scope(setup.args.a_scope)
    for name in tool.evidence.DATASETS:
        directory = setup.args.cache_root_a / name
        directory.mkdir()
        (directory / "metadata.json").write_text("{}")
    def one_wait(_seconds):
        raise TimeoutError("bounded synthetic wait")
    setup.monkeypatch.setattr(tool.time, "sleep", one_wait)
    with pytest.raises(TimeoutError):
        tool.wait_for_a(plan)
    assert "awaiting_owner_exit_receipt" in capsys.readouterr().out
    assert not setup.args.cache_root_b.exists()


def test_a_scope_children_must_finish_after_parent_pid_exits(setup):
    _path, plan = frozen(setup)
    setup.state["process"] = None
    ended, _scope, _resource = tool._a_ended(plan)
    assert ended is False


def test_owner_receipt_requires_actual_completion_and_is_fresh(setup):
    path, plan = frozen(setup)
    with pytest.raises(tool.evidence.VerificationError, match="still alive"):
        tool.record_a_exit(path, 0)
    receipt = end_a(setup, path)
    assert tool.load_a_receipt(plan)[0]["return_code"] == 0
    with pytest.raises(tool.evidence.VerificationError, match="Fresh output"):
        tool.record_a_exit(path, 0)
    assert receipt == setup.args.a_exit_record


@pytest.mark.parametrize("change", ["failed", "bool", "wrong_plan", "wrong_start", "wrong_scope"])
def test_owner_receipt_rejects_nonzero_boolean_and_identity_substitution(setup, change):
    path, plan = frozen(setup)
    receipt = end_a(setup, path, code=7 if change == "failed" else 0)
    if change != "failed":
        def alter(record):
            if change == "bool":
                record["return_code"] = False
            elif change == "wrong_plan":
                record["plan_sha256"] = "f" * 64
            elif change == "wrong_start":
                record["a_process"]["start_ticks"] += 1
            else:
                record["a_scope_invocation_id"] = "b" * 32
        reseal(receipt, alter)
    with pytest.raises(tool.evidence.VerificationError, match="receipt|A failure"):
        tool.load_a_receipt(plan)


def _summary(name):
    return {"data_fingerprint": name * 2, "raw_rows": 3, "counts": {"fit": 1, "validation": 1, "test": 1},
            "features": ["x"], "class_names": ["a", "b"], "realized_pattern_fractions": {},
            "raw_model_view_sha256": "f" * 64}


def _cache_result(plan, role):
    root = Path(plan[f"cache_root_{role}"])
    return {"role": role, "root": str(root), "root_identity": tool.directory_identity(root),
            "datasets": {name: _summary(name) for name in tool.evidence.DATASETS},
            "marker_sha256": tool.evidence.sha256(root / "marker"), "passed": True}


def _acceptance(plan):
    datasets = {name: {**_summary(name), "semantic_checks": {
        key: True for key in (*tool.evidence.SEMANTIC_CHECK_KEYS, "all_passed")},
        "rebuilds": [{"resolved_root": str(Path(plan[f"cache_root_{role}"]) / name)} for role in ("a", "b")]}
        for name in tool.evidence.DATASETS}
    return tool.evidence.seal({"kind": "spikeids_v5_data_acceptance", "acceptance_schema": 1,
        "data_acceptance_passed": True, "byte_identical_rebuilds": True, "two_distinct_fresh_roots": True,
        "datasets": datasets, "independent_verifier": {"path": str(tool.ROOT / "tools/verify_v5_data.py"),
            "sha256": plan["pins"][str(tool.ROOT / "tools/verify_v5_data.py")]["sha256"]},
        "raw_audit": {"path": plan["raw_audit"], "sha256": plan["pins"][plan["raw_audit"]]["sha256"]},
        "producer": {"path": str(tool.ROOT / "spikeids_v5/data_loaders.py"),
            "sha256": plan["pins"][str(tool.ROOT / "spikeids_v5/data_loaders.py")]["sha256"]},
        "upstream_provenance": {"path": plan["iot_provenance"],
            "sha256": plan["pins"][plan["iot_provenance"]]["sha256"]},
        "limitations": {key: False for key in ("capture_generalization_established", "device_generalization_established",
            "time_generalization_established", "upstream_preprocessing_verified", "external_authenticity_verified")}})


def orchestrator(setup, fail_phase=None, mutate=None):
    path, plan = frozen(setup)
    end_a(setup, path)
    calls = []
    def fake_phase(current, _path, phase):
        calls.append(phase)
        if phase == fail_phase:
            raise tool.evidence.VerificationError(f"{phase} scope failed: rc=1")
        receipt = Path(current["work_dir"]) / f"{phase}_exit.json"
        tool.write_new(receipt, tool.evidence.seal({"phase": phase, "passed": True}))
        consumed = {str(receipt): tool.evidence._file_snapshot(receipt)}
        if phase == "prepare_b":
            (Path(current["cache_root_b"]) / "marker").write_text("synthetic cache")
            if mutate:
                mutate(current)
            return {"consumed_evidence": consumed}
        if phase == "acceptance":
            tool.write_new(Path(current["acceptance"]), _acceptance(current))
            return {"consumed_evidence": consumed}
        return {"cache_check": _cache_result(current, phase[-1]), "consumed_evidence": consumed}
    def unchanged(result):
        assert tool.evidence.sha256(Path(result["root"]) / "marker") == result["marker_sha256"], "cache changed"
    setup.monkeypatch.setattr(tool, "run_phase", fake_phase)
    setup.monkeypatch.setattr(tool, "assert_cache_unchanged", unchanged)
    setup.monkeypatch.setattr(tool, "assert_cache_stat_unchanged", unchanged)
    return path, plan, calls


def test_success_is_one_shot_and_never_starts_training(setup):
    path, _plan, calls = orchestrator(setup)
    result = tool.run(path)
    assert calls == list(tool.PHASES)
    assert result["passed"] is True and result["training_started"] is False
    with pytest.raises(tool.evidence.VerificationError, match="Fresh output"):
        tool.run(path)
    assert calls == list(tool.PHASES)


@pytest.mark.parametrize("phase", list(tool.PHASES))
def test_child_failure_stops_without_retry_or_next_phase(setup, phase):
    path, _plan, calls = orchestrator(setup, fail_phase=phase)
    with pytest.raises(tool.evidence.VerificationError, match="scope failed"):
        tool.run(path)
    assert calls == list(tool.PHASES[:tool.PHASES.index(phase) + 1])
    assert not (setup.args.work_dir / "complete.json").exists()
    failure = tool.evidence.check_seal(tool.evidence.load_json(setup.args.work_dir / "failed.json"))
    assert failure["automatic_retry"] is False and failure["passed"] is False


@pytest.mark.parametrize("preexisting", ["b", "acceptance"])
def test_paths_created_after_freeze_are_not_overwritten(setup, preexisting):
    path, plan, calls = orchestrator(setup)
    if preexisting == "b":
        target = Path(plan["cache_root_b"])
        target.mkdir()
        (target / "important").write_text("keep")
    else:
        target = Path(plan["acceptance"])
        target.write_text("keep")
    with pytest.raises(tool.evidence.VerificationError, match="Fresh"):
        tool.run(path)
    assert not calls
    assert target.exists()


def test_a_cache_mutation_during_b_stops_before_independent_acceptance(setup):
    path, _plan, calls = orchestrator(setup, mutate=lambda plan:
        (Path(plan["cache_root_a"]) / "marker").write_text("changed"))
    with pytest.raises(AssertionError, match="cache changed"):
        tool.run(path)
    assert calls == ["check_a", "prepare_b"]


def test_run_claim_blocks_concurrent_instance_before_actions(setup):
    path, _plan = frozen(setup)
    tool.write_new(setup.args.work_dir / "run_started.json", {"already": "owned"})
    with pytest.raises(tool.evidence.VerificationError, match="Fresh output"):
        tool.run(path)
    assert not setup.args.cache_root_b.exists()


@pytest.mark.parametrize("field", ["cache_count", "verifier", "semantic", "limitation"])
def test_resealed_acceptance_must_match_inputs_and_exact_scientific_scope(setup, field):
    _path, plan, _calls = orchestrator(setup)
    Path(plan["cache_root_b"]).mkdir()
    (Path(plan["cache_root_b"]) / "marker").write_text("synthetic cache")
    report = _acceptance(plan)
    report.pop("content_sha256")
    if field == "cache_count":
        report["datasets"]["unsw"]["counts"]["fit"] += 1
    elif field == "verifier":
        report["independent_verifier"]["sha256"] = "e" * 64
    elif field == "semantic":
        report["datasets"]["unsw"]["semantic_checks"]["frozen_partition_and_closure_replayed"] = False
    else:
        report["limitations"]["external_authenticity_verified"] = True
    tool.write_new(Path(plan["acceptance"]), tool.evidence.seal(report))
    with pytest.raises(tool.evidence.VerificationError):
        tool.check_acceptance(plan, _cache_result(plan, "a"), _cache_result(plan, "b"))


@pytest.mark.parametrize("return_code,oom,expected", [(0, False, 0), (3, False, 1), (0, True, 1)])
def test_scope_worker_records_real_child_status_and_oom_without_retry(setup, return_code, oom, expected):
    path, plan = frozen(setup)
    end_a(setup, path)
    work = setup.args.work_dir
    phase = "prepare_b"
    name = tool.scope_name(plan, phase)
    tool.write_new(work / "run_started.json", tool.evidence.seal({"plan_sha256": plan["content_sha256"]}))
    tool.write_new(work / f"{phase}_started.json", tool.evidence.seal({
        "plan_sha256": plan["content_sha256"], "phase": phase, "scope": name}))
    worker = {**plan["a_process"], "pid": 5555, "start_ticks": 777, "cgroup": "/fake/worker",
              "cmdline": tool.worker_command(plan, path, phase)}
    scope = {**plan["a_scope"], "name": name, "InvocationID": "b" * 32,
             "ControlGroup": worker["cgroup"]}
    setup.monkeypatch.setattr(tool, "process_identity", lambda _pid: copy.deepcopy(worker))
    setup.monkeypatch.setattr(tool, "scope_status", lambda _name: copy.deepcopy(scope))
    samples = []
    def sample(_path):
        value = resources(worker["cgroup"])
        if samples and oom:
            value["memory.events"]["oom_kill"] = 1
        samples.append(value)
        return value
    setup.monkeypatch.setattr(tool, "cgroup_sample", sample)
    called = []
    def child(command, **kwargs):
        called.append(command)
        kwargs["stdout"].write(b"synthetic child output\n")
        return SimpleNamespace(returncode=return_code)
    setup.monkeypatch.setattr(tool.subprocess, "run", child)
    assert tool.phase_worker(path, phase) == expected
    assert called == [tool.phase_command(plan, phase)]
    receipt = tool.evidence.check_seal(tool.evidence.load_json(work / f"{phase}_exit.json"))
    assert receipt["passed"] is (expected == 0)
    assert receipt["return_code"] == return_code
    assert receipt["log_sha256"] == tool.evidence.sha256(work / f"{phase}.log")


def test_owner_can_record_a_real_failed_scope_without_fabricating_success(setup):
    path, plan = frozen(setup)
    setup.state["process"] = None
    setup.state["scope"]["ActiveState"] = "failed"
    setup.state["scope"]["Result"] = "oom-kill"
    tool.record_a_exit(path, 137)
    with pytest.raises(tool.evidence.VerificationError, match="A failure"):
        tool.load_a_receipt(plan)


def test_source_drift_at_final_boundary_blocks_completion(setup):
    path, _plan, calls = orchestrator(setup)
    previous = tool.check_acceptance
    def mutate_after_report(current, a_check, b_check):
        result = previous(current, a_check, b_check)
        (setup.repo / "spikeids_v5/data_loaders.py").write_text("changed after verification")
        return result
    setup.monkeypatch.setattr(tool, "check_acceptance", mutate_after_report)
    with pytest.raises(tool.evidence.VerificationError, match="Pinned input/source changed"):
        tool.run(path)
    assert calls == list(tool.PHASES)
    assert not (setup.args.work_dir / "complete.json").exists()


def test_acceptance_changed_after_consumption_is_rejected(setup):
    path, _plan, _calls = orchestrator(setup)
    previous = tool.check_acceptance
    def mutate_after_report(current, a_check, b_check):
        result = previous(current, a_check, b_check)
        reseal(Path(current["acceptance"]), lambda record: record.update(unchecked="tampered"))
        return result
    setup.monkeypatch.setattr(tool, "check_acceptance", mutate_after_report)
    with pytest.raises(tool.evidence.VerificationError, match="acceptance changed"):
        tool.run(path)


@pytest.mark.parametrize("missing", ["producer", "raw", "spec", "verifier", "directory"])
def test_resealed_plan_cannot_omit_mandatory_pins_or_directories(setup, missing):
    path, _plan = frozen(setup)
    targets = {"producer": setup.repo / "spikeids_v5/data_loaders.py",
               "raw": setup.repo / "data/unsw.raw",
               "spec": setup.repo / "spikeids_v5/audit/source_specs/unsw.json",
               "verifier": setup.repo / "tools/verify_v5_data.py"}
    def alter(record):
        if missing == "directory":
            record["directories"].pop("data")
        else:
            record["pins"].pop(str(targets[missing]))
    reseal(path, alter)
    if missing == "producer":
        targets[missing].write_text("changed after removing its pin")
    with pytest.raises(tool.evidence.VerificationError, match="Mandatory"):
        tool.load_plan(path)


@pytest.mark.parametrize("field,value", [("memory.max", float(tool.MEMORY_BYTES)),
    ("memory.swap.max", False), ("memory.swap.current", False),
    ("memory.current", True), ("memory.peak", True)])
def test_resource_scalars_are_exact_integers(field, value):
    sample = resources()
    sample[field] = value
    with pytest.raises(tool.evidence.VerificationError, match="exact integers"):
        tool.check_resources(sample)


@pytest.mark.parametrize("target", ["source", "a_cache", "phase_receipt"])
def test_final_slow_hash_window_has_cheap_end_checks(setup, target):
    path, plan, _calls = orchestrator(setup)
    previous = tool.assert_cache_unchanged
    def corrupt_after_last_hash(result):
        previous(result)
        if result["role"] == "b":
            if target == "source":
                (setup.repo / "spikeids_v5/data_loaders.py").write_text("mutated after final source hash")
            elif target == "a_cache":
                (Path(plan["cache_root_a"]) / "marker").write_text("mutated after final A hash")
            else:
                reseal(Path(plan["work_dir"]) / "check_a_exit.json", lambda row: row.update(passed=False))
    setup.monkeypatch.setattr(tool, "assert_cache_unchanged", corrupt_after_last_hash)
    with pytest.raises((tool.evidence.VerificationError, AssertionError), match="changed"):
        tool.run(path)
    assert not (setup.args.work_dir / "complete.json").exists()


def phase_subprocess_fixture(setup, mutate=None):
    path, plan = frozen(setup)
    phase = "prepare_b"
    work = Path(plan["work_dir"])
    scope = {**plan["a_scope"], "name": tool.scope_name(plan, phase),
             "InvocationID": "b" * 32, "ControlGroup": "/fake/worker"}
    worker = {**plan["a_process"], "pid": 5555, "start_ticks": 777,
              "cgroup": scope["ControlGroup"], "cmdline": tool.worker_command(plan, path, phase)}
    def subprocess(_command, **kwargs):
        kwargs["stdout"].write(b"scope output\n")
        (work / f"{phase}.log").write_text("child output\n")
        report = {"kind": "spikeids_v5_data_phase_exit", "schema": 1,
                  "plan_sha256": plan["content_sha256"], "phase": phase, "passed": True,
                  "return_code": 0, "scope": scope, "worker": worker,
                  "initial_cgroup": resources(worker["cgroup"]), "final_cgroup": resources(worker["cgroup"]),
                  "command": tool.phase_command(plan, phase),
                  "log_sha256": tool.evidence.sha256(work / f"{phase}.log")}
        if mutate:
            mutate(report)
        tool.write_new(work / f"{phase}_exit.json", tool.evidence.seal(report))
        return SimpleNamespace(returncode=0)
    setup.monkeypatch.setattr(tool.subprocess, "run", subprocess)
    return path, plan, phase


def test_phase_receipt_consumer_positive_binds_every_published_file(setup):
    path, plan, phase = phase_subprocess_fixture(setup)
    report = tool.run_phase(plan, path, phase)
    assert set(Path(value).name for value in report["consumed_evidence"]) == {
        "prepare_b_started.json", "prepare_b_exit.json", "prepare_b.log", "prepare_b_scope.log"}


@pytest.mark.parametrize("identity", ["missing", "bool", "command", "exe", "cwd", "a_pid"])
def test_phase_consumer_rejects_missing_or_false_worker_identity(setup, identity):
    def alter(report):
        worker = report["worker"]
        if identity == "missing":
            report["worker"] = {key: worker[key] for key in ("boot_id", "cgroup")}
        elif identity == "bool":
            worker["pid"], worker["start_ticks"] = True, False
        elif identity == "command":
            worker["cmdline"] = ["/bin/false"]
        elif identity == "exe":
            worker["exe"] = "/bin/false"
        elif identity == "cwd":
            worker["cwd"] = "/wrong"
        else:
            worker["pid"] = setup.args.a_pid
    path, plan, phase = phase_subprocess_fixture(setup, alter)
    with pytest.raises(tool.evidence.VerificationError, match="worker process identity"):
        tool.run_phase(plan, path, phase)


@pytest.mark.parametrize("filename", ["prepare_b_exit.json", "prepare_b_started.json", "prepare_b.log", "prepare_b_scope.log"])
def test_phase_evidence_changes_after_consumption_are_rejected(setup, filename):
    path, plan, phase = phase_subprocess_fixture(setup)
    previous = tool.assert_pins
    def mutate_after_pins(current, **kwargs):
        previous(current, **kwargs)
        target = Path(plan["work_dir"]) / filename
        if filename.endswith(".json"):
            reseal(target, lambda row: row.update(passed=False, return_code=137))
        else:
            target.write_text("changed log")
    setup.monkeypatch.setattr(tool, "assert_pins", mutate_after_pins)
    with pytest.raises(tool.evidence.VerificationError, match="Consumed phase evidence changed"):
        tool.run_phase(plan, path, phase)


def test_zero_owner_return_cannot_contradict_visible_failed_scope(setup):
    path, _plan = frozen(setup)
    setup.state["process"] = None
    setup.state["scope"]["ActiveState"] = "failed"
    setup.state["scope"]["Result"] = "oom-kill"
    with pytest.raises(tool.evidence.VerificationError, match="contradicts"):
        tool.record_a_exit(path, 0)
