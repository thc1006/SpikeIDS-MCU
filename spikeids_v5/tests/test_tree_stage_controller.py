"""Controller policy tests; all artifact writes stay in pytest's private fixture."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import run_v5_tree_stage as stage


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stage.seal(value), sort_keys=True) + "\n")


@pytest.mark.parametrize("bad", ["<failure/>", "<error/>", "<skipped/>"])
def test_junit_rejects_case_failure_even_with_clean_summary(tmp_path, bad):
    path = tmp_path / "junit.xml"
    path.write_text(f'<testsuites><testsuite tests="1"><testcase>{bad}</testcase></testsuite></testsuites>')
    with pytest.raises(Exception, match="failure, error, skip"):
        stage.junit_check(path)


@pytest.mark.parametrize("field", ["failures", "errors", "skipped"])
def test_junit_rejects_failed_summary_even_with_clean_cases(tmp_path, field):
    path = tmp_path / "junit.xml"
    path.write_text(f'<testsuites><testsuite {field}="1"><testcase/></testsuite></testsuites>')
    with pytest.raises(Exception, match="summary failed"):
        stage.junit_check(path)


def test_junit_rejects_empty_case_inventory(tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text('<testsuites><testsuite tests="859"/></testsuites>')
    with pytest.raises(Exception, match="no test cases"):
        stage.junit_check(path)


def test_exact_json_policy_rejects_bool_and_float_integer_coercion():
    assert stage.equal({"seeds": [0, 1], "fits": 84}, {"fits": 84, "seeds": [0, 1]})
    assert not stage.equal({"fits": 84}, {"fits": 84.0})
    assert not stage.equal({"seeds": [0, 1]}, {"seeds": [False, True]})


@pytest.fixture
def review_fixture(tmp_path):
    complete = tmp_path / "complete.json"
    write(complete, {"passed": True})
    cases = []
    for index, count in enumerate((859, 10)):
        path = tmp_path / f"tests{index}.xml"
        path.write_text('<testsuites><testsuite tests="' + str(count) + '">' +
                        '<testcase/>' * count + '</testsuite></testsuites>')
        cases.append({"path": str(path), "sha256": stage.snapshot(path)["sha256"],
                      "tests": count, "observed_exit_code": 0})
    docs = []
    for index, role in enumerate(sorted(stage.REVIEW_ROLES)):
        path = tmp_path / f"review{index}.md"
        path.write_text("test fixture independent review\n")
        docs.append({"role": role, "path": str(path), "sha256": stage.snapshot(path)["sha256"]})
    value = {"schema": 1, "kind": "spikeids_v5_postrun_tree_launch_review", "passed": True,
             "unresolved_tree_blockers": [], "completion": {"path": str(complete),
                 "sha256": stage.snapshot(complete)["sha256"]},
             "sources": {str(p): stage.snapshot(p)["sha256"] for p in stage.sources()},
             "tests": cases, "reviews": docs}
    path = tmp_path / "review.json"
    write(path, value)
    return path, complete, value


def test_exact_current_review_accepts(review_fixture):
    path, complete, _ = review_fixture
    value, pins = stage.review_gate(path, complete)
    assert value["passed"] is True
    assert len(pins) == 7 + len(stage.sources())


@pytest.mark.parametrize("mutation", ["pass", "schema", "blockers", "source", "completion", "exit_bool",
                                     "exit_fail", "test_count", "test_missing", "review_missing", "duplicate"])
def test_review_fail_closed(review_fixture, mutation):
    path, complete, value = review_fixture
    if mutation == "pass": value["passed"] = False
    elif mutation == "schema": value["schema"] = True
    elif mutation == "blockers": value["unresolved_tree_blockers"] = ["open defect"]
    elif mutation == "source": value["sources"].pop(next(iter(value["sources"])))
    elif mutation == "completion": value["completion"]["sha256"] = "0" * 64
    elif mutation == "exit_bool": value["tests"][0]["observed_exit_code"] = False
    elif mutation == "exit_fail": value["tests"][0]["observed_exit_code"] = 1
    elif mutation == "test_count": value["tests"][0]["tests"] = 1
    elif mutation == "test_missing": value["tests"].pop()
    elif mutation == "review_missing": value["reviews"].pop()
    elif mutation == "duplicate": value["reviews"][1] = value["reviews"][0]
    write(path, value)
    with pytest.raises(Exception): stage.review_gate(path, complete)


def test_review_replacement_during_validation_rejected(review_fixture, monkeypatch):
    path, complete, value = review_fixture
    original = stage.junit_check
    replaced = False
    def mutate(target):
        nonlocal replaced
        if not replaced:
            value["passed"] = False
            write(path, value)
            replaced = True
        return original(target)
    monkeypatch.setattr(stage, "junit_check", mutate)
    with pytest.raises(Exception, match="changed"):
        stage.review_gate(path, complete)


@pytest.mark.parametrize("attack", [None, "changed", "duplicate", "not_a_list"])
def test_review_supporting_evidence_is_committed(review_fixture, attack):
    path, complete, value = review_fixture
    supporting = path.parent / "numerical_replay.json"
    supporting.write_text('{"independent_fixture": true}\n')
    row = {"path": str(supporting), "sha256": stage.snapshot(supporting)["sha256"]}
    value["supporting_evidence"] = [row]
    if attack == "duplicate": value["supporting_evidence"].append(row)
    elif attack == "not_a_list": value["supporting_evidence"] = row
    write(path, value)
    if attack == "changed": supporting.write_text('{"independent_fixture": false}\n')
    if attack is None:
        _, pins = stage.review_gate(path, complete)
        assert pins[str(supporting)] == stage.snapshot(supporting)
    else:
        with pytest.raises(Exception): stage.review_gate(path, complete)


def test_review_sources_cover_local_helper_import_closure():
    import ast
    required = set()
    for path in stage.sources():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module == "tools":
                required.update(stage.ROOT / "tools" / (alias.name + ".py") for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("tools."):
                required.add(stage.ROOT / (node.module.replace(".", "/") + ".py"))
    assert required <= set(stage.sources())


@pytest.fixture
def plan_fixture(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    results = root / "results"
    results.mkdir(parents=True)
    work, tree, neural = (results / name for name in ("work", "tree", "neural"))
    work.mkdir(); neural.mkdir()
    completion, review_path = results / "prior/complete.json", results / "review/review.json"
    write(completion, {"passed": True}); write(review_path, {"passed": True})
    payload = neural / "model.bin"
    payload.write_bytes(b"pinned model fixture")
    docs = {str(completion): stage.snapshot(completion), str(payload): stage.snapshot(payload)}
    review_pins = {str(review_path): stage.snapshot(review_path)}
    monkeypatch.setattr(stage, "ROOT", root)
    tool = root / "tools/verify_v5_tree.py"
    tool.parent.mkdir()
    for path in stage.sources()[1:]:
        path.write_text("# fixture helper source\n")
    review = {"content_sha256": "a" * 64}
    formal = {"data_evidence": {"accepted_cache_root": str(results / "cache")}}
    monkeypatch.setattr(stage, "review_gate", lambda *_: (review, copy.deepcopy(review_pins)))
    monkeypatch.setattr(stage, "predecessor", lambda *_: (formal, copy.deepcopy(docs)))
    monkeypatch.setattr(stage.adapter, "build_tree_plan", lambda *_: {"fixed_fits": 84})
    boundary = stage.research.artifact_boundary(neural)
    expected = {**docs, **review_pins, **{str(p): stage.snapshot(p) for p in (*stage.sources(), tool)}}
    plan = {"work_dir": str(work), "tree_run": str(tree), "neural_run": str(neural),
            "completion": str(completion), "review_record": str(review_path),
            "plan_path": str(work / "plan.json"), "service_unit": "spikeids-v5-tree-fixture.service",
            "test_results_must_not_change_fixed_policy": True, "input_pins": expected,
            "neural_boundary": boundary, "cache_root": formal["data_evidence"]["accepted_cache_root"],
            "adapter_binding": stage.binding_for(review_path, completion, review), "tree_plan": {"fixed_fits": 84}}
    return plan


def test_plan_mandatory_commitments_positive(plan_fixture):
    stage.validate_plan_contract(plan_fixture)


@pytest.mark.parametrize("mutation", ["self", "adapter", "verifier", "complete", "review", "model", "boundary",
                                     "fit_count", "fit_float", "binding", "cache", "overlap", "service", "policy"])
def test_plan_rejects_omission_or_resealed_policy_change(plan_fixture, mutation):
    plan = plan_fixture
    if mutation in ("self", "adapter", "verifier", "complete", "review", "model"):
        target = {"self": str(stage.SELF), "adapter": str(stage.sources()[1]),
                  "verifier": str(stage.ROOT / "tools/verify_v5_tree.py"),
                  "complete": plan["completion"], "review": plan["review_record"],
                  "model": str(Path(plan["neural_run"]) / "model.bin")}[mutation]
        plan["input_pins"].pop(target)
    elif mutation == "boundary": plan["neural_boundary"]["pins"] = {}
    elif mutation == "fit_count": plan["tree_plan"]["fixed_fits"] = 8
    elif mutation == "fit_float": plan["tree_plan"]["fixed_fits"] = 84.0
    elif mutation == "binding": plan["adapter_binding"]["kind"] = "unreviewed"
    elif mutation == "cache": plan["cache_root"] += "-wrong"
    elif mutation == "overlap": plan["tree_run"] = plan["neural_run"]
    elif mutation == "service": plan["service_unit"] = "unrelated.service"
    elif mutation == "policy": plan["test_results_must_not_change_fixed_policy"] = 1
    with pytest.raises(Exception): stage.validate_plan_contract(plan)


def test_load_plan_detects_plan_replaced_during_contract_check(tmp_path, monkeypatch):
    path = tmp_path / "plan.json"
    value = {"kind": "spikeids_v5_tree_stage_plan", "schema": 1, "plan_path": str(path)}
    write(path, value)
    monkeypatch.setattr(stage, "check_inputs", lambda *_args, **_kwargs: None)
    def change(_): write(path, {**value, "unexpected_change": True})
    monkeypatch.setattr(stage, "validate_plan_contract", change)
    with pytest.raises(Exception, match="changed"):
        stage.load_plan(path)
