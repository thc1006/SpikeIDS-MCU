#!/usr/bin/env python3
"""Fresh paper-stage rendering from immutable, post-run accepted evidence.

Never invokes finalize_all_det, a trainer, an exporter, or checkpoint/ONNX replay.
The complete existing statistical bodies are recomputed from verified saved
results and compared, never rewritten. This source contract does not accept a
PDF, arbitrary free prose, a release, or any hardware claim.
"""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "spikeids_v5")]
from tools import export_v5_runtime as runtime
from tools import run_v5_export_stage as stage
from tools import run_v5_exports as legacy
from tools import continue_v5_exports as continued
from types import ModuleType
import hashlib
import re
from tools import build_v5_paper as builder
from tools.verify_v5_neural import NEURAL_VERIFIER_PACKAGES, validate_tool_provenance
import check_paper_consistency as checker
import paper_contract
from run_globecom_stats import analyze as analyze_difference
from run_v4_equivalence import analyze as analyze_equivalence
from contracts import ARMS, DATASETS, METRICS, check_seal, digest, json_bytes, load_json, require, seal

SELF = Path(__file__).resolve()
data, research = stage.data, stage.research
LABELS = {"nslkdd": "NSL-KDD", "unsw": "UNSW-NB15", "cicids2017": "CICIDS2017", "iot23": "IoT-23"}
BLOCK_NAMES = ("protocol", "equivalence", "tree", "exports", "supports", "decisions")
ACCEPTANCE_KIND = "spikeids_v5_mixed_origin_export_postrun_acceptance"
ACCEPTANCE_SCOPE = "bounded_review_of_fixed_22_mixed_origin_neural_exports"
POST = ROOT / "results/v5_export_continuation_postreview_20260922_mw1Fyh"
PUBLISHER_SHA = "8d288a060547f3fb2617a8979815faaf829ecb963dbc72cd9521fa1157f4bfbd"
REVIEW_ROOT = ROOT / "results/v5_paper_continued_review_20260922_sQdjK1"
POST_FILES = ("accept_export_continuation.py", "audit_continuation_lifecycle.py", "audit_continuation_science.py", "observe_postreview.py")
INPUT_FILES = set(builder.PAPER_INPUT_ALLOWLIST)


def sources():
    return sorted(set([SELF, *continued.sources(), Path(builder.__file__).resolve(), *[POST / name for name in POST_FILES]]))


def _merge(pins, values):
    research.merge_pins(pins, values)


def _bound_record(path, pins):
    path = runtime.canonical(Path(path), file=True)
    require(str(path) in pins, f"Required paper input is not previously committed: {path}")
    value, observed = data.stable_record(path)
    require(runtime.equal(pins[str(path)], observed), f"Paper input differs from prior commitment: {path}")
    return value


def _publisher():
    path = POST / "accept_export_continuation.py"
    payload = stage.tree.resource_evidence._read_evidence_bytes(path)
    require(hashlib.sha256(payload).hexdigest() == PUBLISHER_SHA, "Unreviewed acceptance consumer")
    module = ModuleType("continued_paper_acceptance_consumer")
    module.__file__ = str(path)
    exec(compile(payload, str(path), "exec"), module.__dict__)
    return module


def _acceptance(neural_run, tree_run, acceptance_path, exit_path, acceptance_sha, exit_sha):
    publisher = _publisher()
    accepted, pin = data.stable_record(acceptance_path)
    require(pin["sha256"] == acceptance_sha, "Acceptance differs from caller commitment")
    pins = {str(acceptance_path): pin}
    observed = publisher.raw(exit_path, pins)
    require(pins[str(exit_path)]["sha256"] == exit_sha, "Acceptance exit observation differs")
    p = accepted["paths"]
    state = publisher.prepare(Path(p["plan"]), Path(p["formal_owner"]), Path(p["lifecycle_audit"]),
        Path(p["lifecycle_owner"]), Path(p["science_audit"]), Path(p["science_owner"]),
        Path(p["review_manifest"]), expected_review_sha256=observed["review_manifest_file_sha256"])
    expected = publisher.body(state)
    expected["created_at"] = accepted["created_at"]
    require(runtime.equal(accepted, seal(expected)), "Accepted mixed-origin body differs from complete read-only replay")
    require(accepted["kind"] == ACCEPTANCE_KIND and accepted["scope"] == ACCEPTANCE_SCOPE,
            "Old single-root acceptance is not a mixed-origin receipt")
    context = state["context"]
    controller, completed, export = context["plan"], context["done"], context["export"]
    _check_acceptance_exit(accepted, pin, acceptance_path, controller, state["review"], observed)
    require([b["root"] for b in accepted["unchanged_predecessor_boundaries"]] == [str(neural_run), str(tree_run)],
            "Accepted neural/tree roots differ")
    _merge(pins, state["pins"])
    stage.assert_output_inventory(acceptance_path.parent, {str(acceptance_path): pin})
    retained = _derive_retained(accepted, acceptance_path, pin, pins)
    publisher.check(state, full=False)
    publisher.retained_inventories(state)
    data.assert_snapshots(pins, full=False)
    return accepted, controller, completed, export, context["matrix"], state["report"], pins, retained


def _check_acceptance_exit(accepted, pin, acceptance_path, controller, review, observed):
    wanted = {"schema": 1, "kind": "root_observed_mixed_origin_export_acceptance_exit",
        "actual_return_code": 0, "publisher_source_sha256": PUBLISHER_SHA,
        "controller_plan_sha256": controller["content_sha256"],
        "review_manifest_content_sha256": review["content_sha256"],
        "review_manifest_file_sha256": accepted["review_evidence"][accepted["paths"]["review_manifest"]]["sha256"],
        "acceptance_path": str(acceptance_path), "acceptance_file_sha256": pin["sha256"],
        "acceptance_content_sha256": accepted["content_sha256"], "review_evidence_files": len(accepted["review_evidence"]),
        "matrix_entries": 22, "positive_parity_outcomes": accepted["counts"]["passed"],
        "negative_parity_outcomes": accepted["counts"]["negative"],
        "all_parity_gates_passed": accepted["all_parity_gates_passed"], "not_accepted": accepted["not_accepted"]}
    require(all(runtime.equal(observed.get(k), v) for k, v in wanted.items()) and
        type(observed.get("actual_exec_session")) is int and observed["actual_exec_session"] > 0 and
        type(observed.get("invocation_id")) is str and re.fullmatch("[0-9a-f]{32}", observed["invocation_id"]) and
        type(observed.get("service_scope")) is str and observed["service_scope"].endswith(".scope"),
        "Actual acceptance exit/source/report/counts binding differs")


def _raw_bound(path, pins):
    payload = stage.tree.resource_evidence._read_evidence_bytes(Path(path))
    require(hashlib.sha256(payload).hexdigest() == pins[str(path)]["sha256"], "Unbound ordinary JSON input")
    value = runtime.loads_json(payload, str(path))
    data.assert_snapshots({str(path): pins[str(path)]}, full=False)
    return value


def _held_boundary(root, files, pins):
    root = Path(root)
    paths = sorted(str(root / name) for name in files)
    directories = {"."}
    for name in files: directories.update(str(p) for p in Path(name).parents)
    return {"root": str(root), "files": sorted(files), "directories": sorted(directories),
        "pins": {p: pins[p] for p in paths}}


def _derive_retained(accepted, acceptance_path, pin, pins):
    """Pure reconstruction from already held receipts, never fresh inventories."""
    p = accepted["paths"]
    life = _bound_record(Path(p["lifecycle_audit"]) / "LIFECYCLE_AUDIT.json", pins)
    owner = {"launch_intent.json", "observed_exit.json", "completion_link.json", "execution.log"}
    extra = [_held_boundary(p["formal_owner"], {"launch_intent.json", "observed_exit.json", "completion_link.json",
        "systemd_run.log", "service_journal.log"}, pins),
        _held_boundary(p["lifecycle_audit"], {"LIFECYCLE_AUDIT.json"}, pins),
        _held_boundary(p["lifecycle_owner"], owner, pins)]
    return {"strict_boundaries": life["boundary_checks"],
        "exact_boundaries": [*extra, *accepted["postreview_boundaries"]],
        "work_pins": {p: pins[p] for p in life["work_inventory"]},
        "output_pins": {p: pins[p] for p in life["output_inventory"]},
        "installed": accepted["installed_build_files"], "acceptance_pin": pin}


def _check_gate(check, *, qdq=False):
    require(isinstance(check, dict) and type(check.get("vectors_checked")) is int and
            check["vectors_checked"] == 1024 and type(check.get("allclose")) is bool and
            type(check.get("max_abs_error")) in (int, float) and
            math.isfinite(check["max_abs_error"]) and check["max_abs_error"] >= 0 and
            type(check.get("prediction_disagreement_fraction")) in (int, float) and
            math.isfinite(check["prediction_disagreement_fraction"]) and
            0 <= check["prediction_disagreement_fraction"] <= (0.01 if qdq else 0.0) and
            (qdq or check["allclose"] is True), "Export diagnostic fails its fixed sampled gate")


def _export_values(summary, records):
    """Describe the held numerical adjudications, not an invented single root."""
    expected = [(d, arm, mode) for d, arm in legacy.JOBS for mode in ("fp32", "qdq")]
    rows = summary["attempts"]
    require([(r["dataset"], r["model"], r["mode"]) for r in rows] == expected, "Export matrix incomplete/reordered")
    require(sum(r["passed"] for r in rows if r["mode"] == "fp32") == summary["fp32_passed"] and
        sum(r["passed"] for r in rows if r["mode"] == "qdq") == summary["qdq_passed"], "Export counts differ")
    fp_errors, qdq_disagreements = [], []
    values = {"vExportFpPassed": str(summary["fp32_passed"]), "vExportFpTotal": "11",
        "vExportQdqPassed": str(summary["qdq_passed"]), "vExportQdqTotal": "11",
        "vExportValidationVectors": "1024", "vExportCalibrationRows": "1000", "vExportQdqLimitPct": "1.00"}
    for row in rows:
        d, arm, mode = row["dataset"], row["model"], row["mode"]
        record = records[f"{d}:{arm}:{mode}"]
        require(type(row["passed"]) is bool and type(row["return_code"]) is int and
            row["return_code"] == (0 if row["passed"] else 1) and
            record["expected_original_passed"] is row["passed"] and
            record["retained_failure_stage"] == row["negative_stage"], "Changed parity outcome or failed stage")
        if row["passed"]:
            require(row["negative_stage"] is None, "Passing result carries a failed gate")
            check = record["comparisons"]["onnx_check"]["diagnostic"]
            _check_gate(check)
            fp_errors.append(check["max_abs_error"])
            if mode == "qdq":
                check = record["comparisons"]["quantization_check"]["diagnostic"]
                _check_gate(check, qdq=True)
                qdq_disagreements.append(check["prediction_disagreement_fraction"])
        else:
            require(row["negative_stage"] in {"freeze", "fp32_parity", "qdq_parity"} and
                (row["negative_stage"] != "qdq_parity" or mode == "qdq"), "Unknown failure stage")
        prefix = _export_prefix(d, arm, mode)
        values[prefix + "Status"] = r"\text{pass}" if row["passed"] else r"\text{negative}"
        stage_label = {None: "n/a", "freeze": "BN freeze", "fp32_parity": "FP32 parity", "qdq_parity": "QDQ parity"}[row["negative_stage"]]
        values[prefix + "FailureStage"] = r"\text{" + stage_label + "}"
    values["vExportFpWorstAbsError"] = legacy._scientific_tex(max(fp_errors)) if fp_errors else r"\text{n/a}"
    values["vExportQdqWorstPassedDisagreementPct"] = f"{100 * max(qdq_disagreements):.3f}" if qdq_disagreements else r"\text{n/a}"
    return values


def _export_prefix(dataset, arm, mode):
    return "vExport" + paper_contract.PREFIX[dataset] + arm.capitalize() + ("Fp" if mode == "fp32" else "Qdq")


def _read_neural_results(run, pins):
    """Consume accepted result JSON/independent commitments, not 440 model loads."""
    plan = _bound_record(run / "plan.json", pins)
    jobs = plan["jobs"]
    expected = {(d, arm) for d in DATASETS for arm in ARMS[d]}
    require(plan.get("protocol_role") == "planned_benchmark" and runtime.equal(plan.get("seeds"), list(range(20))) and
            len(jobs) == len(expected) == 11 and len({j["id"] for j in jobs}) == 11 and
            {(j["dataset"], j["model"]) for j in jobs} == expected, "Fixed full neural matrix is incomplete")
    fit, evaluation = (_bound_record(run / name, pins) for name in ("verification_fit.json", "verification_evaluate.json"))
    indie = _bound_record(run / "independent_verification.json", pins)
    for gate in (fit, evaluation):
        require(gate.get("passed") is True and gate.get("plan_sha256") == plan["content_sha256"] and
                set(gate.get("jobs", {})) == {j["id"] for j in jobs}, "Accepted neural global barrier is incomplete")
    require(indie.get("verification_fit_sha256") == pins[str(run / "verification_fit.json")]["sha256"] and
            indie.get("verification_evaluate_sha256") == pins[str(run / "verification_evaluate.json")]["sha256"] and
            set(indie.get("execution_scientific_digests", {})) == {j["id"] for j in jobs},
            "Independent neural execution/barrier commitments differ")
    results = {}
    for job in jobs:
        records = []
        for execution in ("results", "replicas"):
            row = _bound_record(run / execution / (job["id"] + ".json"), pins)
            require(row.get("status") == "complete" and row.get("dataset") == job["dataset"] and
                    row.get("kind") == job["model"] and row.get("data_fingerprint") == job["data_fingerprint"] and
                    runtime.equal(row["protocol"].get("seeds"), plan["seeds"]) and
                    all(runtime.equal(row["protocol"].get(k), v) for k, v in job["hyperparameters"].items()) and
                    runtime.equal([r.get("seed") for r in row["per_seed"]], plan["seeds"]) and
                    row["training_digest"] == fit["jobs"][job["id"]] and
                    row["scientific_digest"] == evaluation["jobs"][job["id"]] ==
                        indie["execution_scientific_digests"][job["id"]][execution],
                    "Accepted per-seed neural result identity/budget/digest differs")
            records.append(row)
        require(records[0]["fingerprint"] == records[1]["fingerprint"] and
                runtime.equal(records[0]["per_seed"], records[1]["per_seed"]),
                "Accepted primary/replica per-seed results differ")
        results[job["dataset"], job["model"]] = records[0]
    return plan, results


def load_evidence(neural_run, tree_run, acceptance_path, acceptance_exit_path, *,
                  expected_acceptance_sha256, expected_exit_sha256):
    """Metadata-only replay; no checkpoint/array/ONNX deserialization or stats write."""
    neural_run, tree_run = [runtime.canonical(Path(p), directory=True) for p in (neural_run, tree_run)]
    accepted_path, exit_path = [runtime.canonical(Path(p), file=True) for p in (acceptance_path, acceptance_exit_path)]
    source_pins = {str(p): stage.snapshot(p) for p in sources()}
    accepted, controller, complete, export, summary, replay, pins, retained = _acceptance(
        neural_run, tree_run, accepted_path, exit_path, expected_acceptance_sha256, expected_exit_sha256)
    _merge(pins, source_pins)
    neural, results = _read_neural_results(neural_run, pins)
    require(runtime.equal(neural.get("seeds"), list(range(20))) and len(neural["jobs"]) == 11 and
            neural.get("protocol_role") == "planned_benchmark" and
            neural["content_sha256"] == accepted["source_plan_sha256"], "Only the accepted full 440-fit neural plan may feed paper")
    tree, tree_report = (_bound_record(tree_run / name, pins) for name in ("plan.json", "results.json"))
    stage.tree.adapter._validate_plan(tree)
    require(tree_report.get("plan_sha256") == tree["content_sha256"] and
            tree_report.get("test_evaluated_after_global_fit_barrier") is True and
            tree_report.get("verification_fit_sha256") == pins[str(tree_run / "verification_fit.json")]["sha256"] and
            tree["neural_plan"] == {"path": str(neural_run / "plan.json"),
                "sha256": pins[str(neural_run / "plan.json")]["sha256"], "content_sha256": neural["content_sha256"]},
            "Accepted tree result/global barrier/neural binding differs")
    difference, equivalence = analyze_difference(neural_run, (neural, results)), analyze_equivalence(neural_run, (neural, results))
    for name, expected in (("stats_report_globecom.json", difference), ("equivalence_v5.json", equivalence)):
        require(runtime.equal(_bound_record(neural_run / name, pins), seal(expected)),
                f"Preexisting statistical report differs; renderer will not rewrite it: {name}")
    indie = _bound_record(neural_run / "independent_verification.json", pins)
    require(indie.get("kind") == "independent_formal_neural_and_statistics_verification" and indie.get("passed") is True and
            indie.get("plan_sha256") == neural["content_sha256"] and
            type(indie.get("prediction_artifacts_checked")) is int and indie["prediction_artifacts_checked"] == 440 and
            type(indie.get("checkpoints_checked")) is int and indie["checkpoints_checked"] == 440 and
            indie["statistics"]["difference_report_sha256"] == pins[str(neural_run / "stats_report_globecom.json")]["sha256"] and
            indie["statistics"]["equivalence_report_sha256"] == pins[str(neural_run / "equivalence_v5.json")]["sha256"],
            "Independent neural/statistical evidence is missing or stale")
    validate_tool_provenance(indie["tool_provenance"], ROOT / "tools/verify_v5_neural.py", NEURAL_VERIFIER_PACKAGES,
        {"run_dir": str(neural_run), "output": str(neural_run / "independent_verification.json")})
    tree_indie = _bound_record(tree_run / "independent_verification.json", pins)
    require(tree_indie.get("kind") == "independent_formal_tree_verification" and tree_indie.get("passed") is True and
            tree_indie.get("tree_plan_sha256") == tree["content_sha256"] and
            tree_indie.get("tree_results_sha256") == pins[str(tree_run / "results.json")]["sha256"] and
            runtime.equal(tree_indie.get("neural_plan"), tree["neural_plan"]), "Independent tree evidence is missing or stale")
    count = 0
    for dataset in ("nslkdd", "unsw"):
        for kind, seeds in (("random_forest", list(range(20))), ("xgboost", [0])):
            models = tree_indie["models"][dataset][kind]
            require(set(models) == set(map(str, seeds)), "Independent tree seed coverage differs")
            for seed in seeds:
                require(set(models[str(seed)]) == {"primary", "replica"}, "Independent tree replica coverage differs")
                for row in models[str(seed)].values():
                    require(pins[str(tree_run / row["artifact"])]["sha256"] == row["artifact_sha256"],
                            "Independent tree model artifact commitment differs")
                    count += 1
    require(count == 84, "Independent tree does not cover all 84 models")
    export_records, export_paths = {}, {}
    for index, row in enumerate(summary["attempts"]):
        key = f"{row['dataset']}:{row['model']}:{row['mode']}"
        path = Path(accepted["paths"]["science_audit"]) / f"attempt_{index + 1:02d}" / "recomputed.json"
        export_records[key], export_paths[key] = _bound_record(path, pins), str(path)
    metadata = {job["dataset"]: _bound_record(Path(job["cache"]) / "metadata.json", pins) for job in neural["jobs"]}
    context = seal({"schema": 1, "kind": "spikeids_v5_continued_readonly_paper_context",
        "paths": {"neural_run": str(neural_run), "tree_run": str(tree_run),
            "export_root": controller["export_root"], "export_acceptance": str(accepted_path),
            "acceptance_exit": str(exit_path), "export_plan": controller["original_export_plan"],
            "export_summary": str(Path(controller["work_dir"]) / "summary.json"),
            "controller_plan": controller["plan_path"]},
        "acceptance_sha256": accepted["content_sha256"], "neural_plan": neural,
        "results": {f"{d}:{a}": result for (d, a), result in results.items()},
        "tree_plan": tree, "tree_report": tree_report, "difference": difference, "equivalence": equivalence,
        "export_plan": export, "export_summary": summary, "export_records": export_records,
        "export_record_paths": export_paths, "export_values": _export_values(summary, export_records),
        "controller_plan": controller, "metadata": metadata, "input_pins": pins,
        "retained": retained, "source_pins": source_pins,
        "publication_accepted": False, "free_prose_scientific_claims_proven": False})
    _context(context)
    return context


def _retained_inventory(context):
    r, plan = context["retained"], context["controller_plan"]
    for b in r["strict_boundaries"]: continued.assert_boundary(b, plan)
    for b in r["exact_boundaries"]:
        research.assert_boundary(b, full=False)
        stage.assert_output_inventory(Path(b["root"]), b["pins"])
    stage.assert_output_inventory(Path(plan["work_dir"]), r["work_pins"])
    stage.assert_output_inventory(Path(plan["export_root"]), r["output_pins"])
    accepted = Path(context["paths"]["export_acceptance"])
    stage.assert_output_inventory(accepted.parent, {str(accepted): r["acceptance_pin"]})


def _retained(context):
    _retained_inventory(context)
    r, pins = context["retained"], context["input_pins"]
    continued.builds._end_stats(r["installed"])
    data.assert_snapshots(pins, full=False)


def _context(context, *, full=False):
    check_seal(context)
    require(type(context.get("schema")) is int and context["schema"] == 1 and
        context.get("kind") == "spikeids_v5_continued_readonly_paper_context" and
        context.get("publication_accepted") is False and context.get("free_prose_scientific_claims_proven") is False,
        "Invalid continued read-only context")
    require(set(context["source_pins"]) == {str(p) for p in sources()}, "Renderer source inventory differs")
    data.assert_snapshots(context["source_pins"])
    pins, p = context["input_pins"], context["paths"]
    require(set(context["results"]) == {f"{d}:{a}" for d in DATASETS for a in ARMS[d]} and
        set(context["metadata"]) == set(DATASETS), "Missing/extra neural arms or metadata datasets")
    data.assert_snapshots(pins, full=full)
    bindings = {"neural_plan": Path(p["neural_run"])/"plan.json",
        "tree_plan": Path(p["tree_run"])/"plan.json", "tree_report": Path(p["tree_run"])/"results.json",
        "export_plan": Path(p["export_plan"]), "export_summary": Path(p["export_summary"]),
        "controller_plan": Path(p["controller_plan"])}
    for key, path in bindings.items():
        require(runtime.equal(context[key], _bound_record(path, pins)), "Changed held context: " + key)
    for key, name in (("difference", "stats_report_globecom.json"), ("equivalence", "equivalence_v5.json")):
        require(runtime.equal(seal(context[key]), _bound_record(Path(p["neural_run"])/name, pins)), "Changed statistics")
    for job in context["neural_plan"]["jobs"]:
        key = job["dataset"] + ":" + job["model"]
        require(runtime.equal(context["results"][key], _bound_record(Path(p["neural_run"])/"results"/(job["id"]+".json"), pins)),
            "Changed seed result body")
        require(runtime.equal(context["metadata"][job["dataset"]], _bound_record(Path(job["cache"])/"metadata.json", pins)),
            "Changed metadata body")
    keys = {f"{r['dataset']}:{r['model']}:{r['mode']}" for r in context["export_summary"]["attempts"]}
    require(set(context["export_records"]) == set(context["export_record_paths"]) == keys, "Missing/extra export records")
    accepted = _bound_record(Path(p["export_acceptance"]), pins)
    required_flags = {"schema": 1, "kind": ACCEPTANCE_KIND, "scope": ACCEPTANCE_SCOPE, "passed": True,
        "matrix_execution_complete": True, "owner_observed_service_return_code": 0,
        "same_validator_implementation": True, "independent_third_numerical_algorithm": False,
        "validation_reexposure": True, "software_scope": "fixed sampled CPU parity only",
        "unresolved_export_blockers": [], "next_phase_requires_new_review": True,
        "not_accepted": ["paper", "release", "boards", "NPU", "latency", "energy"]}
    require(all(runtime.equal(accepted.get(k), v) for k, v in required_flags.items()),
        "Mixed-origin acceptance flags or scope changed")
    rows = context["export_summary"]["attempts"]
    wanted_counts = {"total": 22, "retained_original": 3, "new_exports": 19,
        "passed": sum(r["passed"] for r in rows), "negative": sum(not r["passed"] for r in rows),
        "fp32_passed": context["export_summary"]["fp32_passed"], "qdq_passed": context["export_summary"]["qdq_passed"]}
    require(runtime.equal(accepted["counts"], wanted_counts) and
        runtime.equal(accepted["all_parity_gates_passed"], all(r["passed"] for r in rows)), "Acceptance outcome totals differ")
    mandatory = dict(accepted["review_evidence"])
    _merge(mandatory, {name: pins[name] for name in (p["export_acceptance"], p["acceptance_exit"])})
    _merge(mandatory, context["source_pins"])
    require(runtime.equal(pins, mandatory), "Paper omitted/rebound mandatory accepted evidence")
    _check_acceptance_exit(accepted, pins[p["export_acceptance"]], Path(p["export_acceptance"]),
        context["controller_plan"], _bound_record(Path(accepted["paths"]["review_manifest"]), pins),
        _raw_bound(Path(p["acceptance_exit"]), pins))
    require(runtime.equal(context["retained"], _derive_retained(accepted, Path(p["export_acceptance"]),
        pins[p["export_acceptance"]], pins)), "Paper omitted/rebound mandatory retained namespaces")
    for index, row in enumerate(context["export_summary"]["attempts"]):
        key = f"{row['dataset']}:{row['model']}:{row['mode']}"
        path = Path(accepted["paths"]["science_audit"]) / f"attempt_{index+1:02d}" / "recomputed.json"
        require(context["export_record_paths"][key] == str(path) and
            runtime.equal(context["export_records"][key], _bound_record(path, pins)), "Changed mixed-origin numerical record")
    require(runtime.equal(context["export_values"], _export_values(context["export_summary"], context["export_records"])),
        "Changed export macro values")
    require(accepted["content_sha256"] == context["acceptance_sha256"] and accepted["kind"] == ACCEPTANCE_KIND and
        accepted["source_plan_sha256"] == context["neural_plan"]["content_sha256"] and
        accepted["controller_plan_sha256"] == context["controller_plan"]["content_sha256"] and
        runtime.equal(accepted["matrix"], context["export_summary"]["attempts"]), "Changed acceptance linkage")
    indie = _bound_record(Path(p["neural_run"])/"independent_verification.json", pins)
    validate_tool_provenance(indie["tool_provenance"], ROOT/"tools/verify_v5_neural.py", NEURAL_VERIFIER_PACKAGES,
        {"run_dir": p["neural_run"], "output": str(Path(p["neural_run"])/"independent_verification.json")})
    _retained(context)


def _markers(name):
    require(name in BLOCK_NAMES, "Unknown managed paper block")
    if name == "protocol": return checker.PROTOCOL_START, checker.PROTOCOL_END
    return f"% BEGIN V5 MANAGED {name.upper()}\n", f"% END V5 MANAGED {name.upper()}\n"


def _wrap(name, lines):
    begin, end = _markers(name)
    return begin + "\n".join(lines) + "\n" + end


def result_values(context):
    plan, tree_report = context["neural_plan"], context["tree_report"]
    results = {tuple(key.split(":")): value for key, value in context["results"].items()}
    extra = {}
    for dataset in ("nslkdd", "unsw"):
        for kind, label in (("random_forest", "RandomForest"), ("xgboost", "Xgboost")):
            rows = tree_report["results"][dataset][kind]["per_seed"]
            wanted = list(range(20)) if kind == "random_forest" else [0]
            require(runtime.equal([row["seed"] for row in rows], wanted), "Paper tree seed set/order differs")
            for metric in METRICS:
                summary = paper_contract.summary([row[metric] for row in rows])
                prefix = "vFive" + paper_contract.PREFIX[dataset] + label + paper_contract.METRIC_NAME[metric]
                extra[prefix + "Mean"] = f"{summary['mean']:.2f}"
                extra[prefix + "Sd"] = r"\text{n/a}" if summary["std"] is None else f"{summary['std']:.2f}"
    return {**paper_contract.expected_macros(plan, results, context["difference"], context["equivalence"], tree_report), **extra}


def tex_literal(value):
    text = str(value)
    require(not any(ord(c) < 32 for c in text), "Control character in class label")
    escaped = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
        "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(escaped.get(c, c) for c in text)


def support_block(context):
    lines = [r"\paragraph{Class supports and inferential limits.}",
        "Counts are unique labelled final-FP32 patterns, not traffic frequencies or independent seed observations.",
        "Fit preprocessing uses canonical-raw unique labelled patterns before final-FP32 deduplication.",
        "Twenty seeds describe optimization variation on fixed splits, not population confidence intervals.",
        "Rare-class supports do not justify reliable rare-attack detection claims. CICIDS2017 and IoT-23",
        "are not unseen-device, capture, or future-time holdouts; IoT-23 upstream preprocessing remains a limitation.",
        r"\begin{center}\scriptsize\resizebox{\columnwidth}{!}{\begin{tabular}{llrrr}",
        r"Dataset & Class & Fit & Validation & Test \\"]
    for d in DATASETS:
        meta = context["metadata"][d]
        labels, support = meta["class_names"], meta["partition"]["support"]
        require(type(labels) is list and len(set(map(str, labels))) == len(labels), "Invalid class order")
        for part in ("fit", "validation", "test"):
            require(type(support[part]) is list and len(support[part]) == len(labels) and
                all(type(n) is int and n > 0 for n in support[part]) and
                type(meta["counts"][part]) is int and sum(support[part]) == meta["counts"][part],
                "Class support and accepted counts differ")
        for i, name in enumerate(labels):
            lines.append(f"{LABELS[d]} & {tex_literal(name)} & {support['fit'][i]} & "
                f"{support['validation'][i]} & {support['test'][i]} " + r"\\")
    return _wrap("supports", [*lines, r"\end{tabular}}\end{center}"])


def decision_block(context):
    expected = [f"{d}:relu_vs_{a}:{m}" for d in DATASETS for a in ARMS[d] if a != "relu" for m in METRICS]
    difference, pairs = context["difference"], context["equivalence"]["pairs"]
    require(context["neural_plan"]["difference_family"] == expected and
        set(difference["comparisons"]) == set(expected), "All fourteen difference tests are required")
    for r in difference["comparisons"].values(): require(type(r["reject"]) is bool, "Invalid difference decision")
    for r in pairs.values():
        require(all(type(r[k]) is bool for k in ("equivalent_familywise", "equivalent_familywise_signed_rank_robustness",
            "primary_robustness_discordant")) and r["primary_robustness_discordant"] ==
            (r["equivalent_familywise"] != r["equivalent_familywise_signed_rank_robustness"]), "Inconsistent discordance")
    primary = sum(r["equivalent_familywise"] for r in pairs.values())
    robust = sum(r["equivalent_familywise_signed_rank_robustness"] for r in pairs.values())
    both = sum(all(pairs[f"{d}:{m}"]["equivalent_familywise"] for m in METRICS) for d in DATASETS)
    lines = [r"\paragraph{Complete decision summary.}",
        f"Difference rejection occurs in {sum(r['reject'] for r in difference['comparisons'].values())}/14 hypotheses.",
        f"Primary mean-equivalence support occurs in {primary}/8 hypotheses, versus {robust}/8 in signed-rank robustness.",
        f"Both metrics support primary equivalence in {both}/4 datasets; no decision establishes non-equivalence.",
        "Difference rejection and numerical-equivalence support can coexist. Each family has separate Holm control.",
        "Mean differences are descriptive; Hodges--Lehmann (HL) pseudomedians summarize the symmetric location tested by signed ranks.",
        r"\begin{center}\scriptsize\resizebox{\columnwidth}{!}{\begin{tabular}{lllrrrc}",
        r"Dataset & Comparator & Metric & Mean difference & HL location & Holm $p$ & Reject \\"]
    for key in expected:
        d, comparison, m = key.split(":"); arm = comparison.removeprefix("relu_vs_")
        prefix = "vFive" + paper_contract.PREFIX[d] + "ReluVs" + arm.capitalize() + paper_contract.METRIC_NAME[m]
        lines.append(f"{LABELS[d]} & {arm.upper()} & {'OA' if m == 'overall_acc' else 'Macro-F1'} & "
            f"\\{prefix}MeanDifference & \\{prefix}PseudomedianDifference & \\{prefix}HolmP & \\{prefix}DifferenceSupported " + r"\\")
    return _wrap("decisions", [*lines, r"\end{tabular}}\end{center}"])


def managed_blocks(context):
    """Pure canonical rendering; not an evidence-acceptance API by itself."""
    neural, tree, export, meta = (context[k] for k in ("neural_plan", "tree_plan", "export_plan", "metadata"))
    expected_pairs = [f"{d}:{metric}" for d in DATASETS for metric in METRICS]
    require(neural["equivalence_family"] == expected_pairs and context["equivalence"]["family"] == expected_pairs and
            set(context["equivalence"]["pairs"]) == set(expected_pairs), "All eight primary/robustness hypotheses are required")
    block = checker.expected_protocol_block(neural, tree, export, meta)
    rounds = tree["hyperparameters"]["xgboost"]["n_estimators"]
    old = f"XGBoost uses {rounds} histogram trees,"
    require(block.count(old) == 1, "Old protocol renderer changed; explicit rounds correction needs review")
    block = block.replace(old, f"XGBoost uses {rounds} histogram boosting rounds,", 1)
    counts = [rounds * (len(meta[d]["class_names"]) if len(meta[d]["class_names"]) > 2 else 1)
              for d in ("nslkdd", "unsw")]
    block = block.replace(checker.PROTOCOL_END,
        f"The multiclass models contain {counts[0]} NSL-KDD and {counts[1]} UNSW-NB15 trees.\n"
        "XGBoost has one seed; its seed standard deviation is unavailable, not zero.\n" + checker.PROTOCOL_END)
    lines = [r"\paragraph{Complete equivalence and robustness families.}",
        "Primary paired t-TOST concerns the mean seed difference; signed-rank TOST concerns a symmetric location/pseudomedian.",
        "The same eight hypotheses are Holm-adjusted separately in the two families; all decisions and discordances follow.",
        "The frozen margin is numerical sensitivity, not established practical importance. A no decision does not prove nonequivalence.",
        r"\begin{center}\small\resizebox{\columnwidth}{!}{\begin{tabular}{llccccc}",
        r"Dataset & Metric & Primary Holm $p$ & Support & Robust Holm $p$ & Support & Discordant \\"]
    for d in DATASETS:
        for metric in METRICS:
            prefix = "vFive" + paper_contract.PREFIX[d] + "Equivalence" + paper_contract.METRIC_NAME[metric]
            label = "OA" if metric == "overall_acc" else "Macro-F1"
            lines.append(f"{LABELS[d]} & {label} & \\{prefix}HolmP & \\{prefix}Supported & "
                         f"\\{prefix}SignedRankHolmP & \\{prefix}SignedRankSupported & \\{prefix}Discordant " + r"\\")
    lines += [r"\end{tabular}}\end{center}"]
    equivalence = _wrap("equivalence", lines)
    lines = [r"\paragraph{Tree baselines on the same accepted datasets.}",
        "Means and sample standard deviations describe optimization seeds on one fixed split, not independent dataset sampling.",
        "The single-seed XGBoost standard deviation is n/a, never a fabricated zero.",
        r"\begin{center}\small\resizebox{\columnwidth}{!}{\begin{tabular}{llrrrrr}",
        r"Dataset & Model & Seeds & OA mean (\%) & OA SD & Macro-F1 mean (\%) & Macro-F1 SD \\"]
    for d in ("nslkdd", "unsw"):
        for model, label in (("RandomForest", "RF"), ("Xgboost", "XGBoost")):
            prefix = "vFive" + paper_contract.PREFIX[d] + model
            lines.append(f"{LABELS[d]} & {label} & \\{prefix}Seeds & \\{prefix}OaMean & \\{prefix}OaSd & "
                         f"\\{prefix}MacroFoneMean & \\{prefix}MacroFoneSd " + r"\\")
    lines += [r"\end{tabular}}\end{center}"]
    tree_block = _wrap("tree", lines)
    rows = context["export_summary"]["attempts"]
    require([(r["dataset"], r["model"], r["mode"]) for r in rows] ==
            [(d, arm, mode) for d, arm in legacy.JOBS for mode in ("fp32", "qdq")], "All 22 export outcomes are required")
    lines = [r"\paragraph{Complete sampled software export outcomes.}",
        r"FP32 passes: \vExportFpPassed/\vExportFpTotal; QDQ passes: \vExportQdqPassed/\vExportQdqTotal.",
        r"The fixed gate uses \vExportValidationVectors\ validation vectors; QDQ, when reached, uses \vExportCalibrationRows\ fit calibration rows.",
        "The first three original exports were retained unchanged after an infrastructure stop; only the nineteen unstarted entries were continued.",
        "The explicit engineering amendment distinguishes distribution versions from full loaded runtime build versions; no seed or tolerance changed.",
        "The original failed workflow remains preserved; completing this mixed-origin matrix does not erase that failure or rerun its first three exports.",
        "The numerical post-review reuses the same validator implementation, not a third independent numerical algorithm.",
        r"Across passing export entries only, the worst FP32-check absolute error is \vExportFpWorstAbsError;",
        r"among passing QDQ entries, the largest class disagreement is \vExportQdqWorstPassedDisagreementPct\%.",
        "A negative is a retained and exactly reproduced scientific gate failure, not a passed model or an omitted attempt.",
        "Controller execution completion is not parity success. These CPU software results establish no all-input guarantee,",
        "all-INT8/NPU mapping, board deployment, latency, or energy result.",
        r"\begin{center}\small\resizebox{\columnwidth}{!}{\begin{tabular}{llllll}",
        r"Dataset & Arm & Mode & Origin & Outcome & Failed gate \\"]
    for index, row in enumerate(rows):
        d, arm, mode = row["dataset"], row["model"], row["mode"]
        origin = "retained_original" if index < 3 else "new_suffix"
        require(row["execution_origin"] == origin, "Export history origin changed")
        prefix = _export_prefix(d, arm, mode)
        lines.append(f"{LABELS[d]} & {arm.upper()} & {mode.upper()} & {'original' if index < 3 else 'continued'} & "
            f"\\{prefix}Status & \\{prefix}FailureStage " + r"\\")
    lines += [r"\end{tabular}}\end{center}"]
    return {"protocol": block, "equivalence": equivalence, "tree": tree_block, "exports": _wrap("exports", lines),
        "supports": support_block(context), "decisions": decision_block(context)}


def _block_span(text, name):
    begin, end = _markers(name)
    require(text.count(begin) == text.count(end) == 1, f"Exactly one explicit managed {name} block is required")
    start, finish = text.index(begin), text.index(end) + len(end)
    require(start < finish - len(end), f"Reversed managed {name} block")
    require(checker._context_at(paper_contract.strip_comments(text[:start]),
        len(paper_contract.strip_comments(text[:start]))) == (0, ["document"]),
        f"Managed {name} block must be literal visible document-level content")
    return start, finish


def canonical_text(template_text, blocks):
    require(set(blocks) == set(BLOCK_NAMES), "Managed block inventory differs")
    spans = [(name, *_block_span(template_text, name)) for name in BLOCK_NAMES]
    ordered = sorted(spans, key=lambda item: item[1])
    require(all(left[2] <= right[1] for left, right in zip(ordered, ordered[1:])), "Nested managed blocks are prohibited")
    result = template_text
    for name, start, finish in reversed(ordered):
        result = result[:start] + blocks[name] + result[finish:]
    return result


def _provenance(context, result_text, export_text):
    import hashlib
    h = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
    upstream = {"acceptance": context["paths"]["export_acceptance"], "acceptance_sha256": context["acceptance_sha256"],
                "renderer": {"path": str(SELF), "sha256": context["source_pins"][str(SELF)]["sha256"]},
                "context_sha256": context["content_sha256"], "publication_accepted": False}
    result = seal({"plan_sha256": context["neural_plan"]["content_sha256"],
        "tree_plan_sha256": context["tree_plan"]["content_sha256"],
        "tree_result_sha256": context["input_pins"][str(Path(context["paths"]["tree_run"]) / "results.json")]["sha256"],
        "macro_sha256": h(result_text), "difference_sha256": digest(context["difference"]),
        "equivalence_sha256": digest(context["equivalence"]), "readonly_stage": upstream})
    export = seal({"schema": 1, "kind": "spikeids_v5_export_paper_macros",
        "plan_sha256": context["neural_plan"]["content_sha256"], "export_plan_sha256": context["export_plan"]["content_sha256"],
        "export_summary_sha256": context["input_pins"][context["paths"]["export_summary"]]["sha256"],
        "macro_sha256": h(export_text), "readonly_stage": upstream})
    return result, export


def check_candidate(context, paper_dir, *, template_review_path, expected_template_review_sha256):
    """Read-only source/number check; intentionally not PDF/publication approval."""
    _context(context)
    template, template_review, template_pins = _template(context, template_review_path, expected_template_review_sha256)
    paper = runtime.canonical(Path(paper_dir), directory=True)
    require({p.name for p in paper.iterdir()} == INPUT_FILES, "Paper candidate needs exactly the six builder inputs")
    before = {str(p): stage.snapshot(p) for p in sorted(paper.iterdir())}
    blocks = managed_blocks(context)
    text = (paper / "main.tex").read_text(encoding="utf-8")
    require(canonical_text((template / "main.tex").read_text(encoding="utf-8"), blocks) == text,
        "Candidate differs from the reviewed template and exact managed blocks")
    require((paper / "references.bib").read_bytes() == (template / "references.bib").read_bytes(), "Changed bibliography")
    files = checker.validate_manuscript(paper / "main.tex", blocks["protocol"])
    expected_result, expected_export = paper_contract.macro_text(result_values(context)), legacy.export_macro_text(context["export_values"])
    require((paper / "result_macros_v5.tex").read_text(encoding="utf-8") == expected_result and
            (paper / "export_macros_v5.tex").read_text(encoding="utf-8") == expected_export,
            "Read-only paper macros differ from accepted evidence")
    provenances = _provenance(context, expected_result, expected_export)
    for name, expected in zip(("result_macros_v5.provenance.json", "export_macros_v5.provenance.json"), provenances):
        require(runtime.equal(load_json(paper / name), expected), "Paper macro source/provenance differs")
    free_files = dict(files)
    for block in blocks.values():
        free_files["main.tex"] = free_files["main.tex"].replace(paper_contract.strip_comments(block).strip(), "", 1)
    findings = checker.protocol_findings(free_files, blocks["protocol"])
    require(not findings, "Stale literal/free-prose protocol claim: " + "; ".join(findings))
    # Table-format redefinitions could make a literal complete table disappear.
    for match in checker.CONTROL.finditer(paper_contract.strip_comments(text)):
        if match.group(1) in checker.DEFINITION_COMMANDS:
            target = checker._definition_target(paper_contract.strip_comments(text), match.end())
            require(target not in {"tabular", "resizebox", "paragraph", "ensuremath", "text", "center", "small"},
                    "Redefinition of a managed-block rendering command is forbidden")
    data.assert_snapshots(before)
    _template_end(template, template_review, template_pins)
    _context(context)
    _retained_inventory(context)
    _template_end(template, template_review, template_pins)
    stage.assert_output_inventory(paper, before)
    data.assert_snapshots({**context["input_pins"], **template_pins, **before}, full=False)
    return {"schema": 1, "kind": "spikeids_v5_readonly_managed_paper_check",
        "numeric_consistency_passed": True, "external_export_consistency_passed": True,
        "all_eight_primary_robustness_discordance_rows_present": True, "all_twenty_two_export_outcomes_present": True,
        "tree_single_seed_sd_is_unavailable": True, "xgboost_budget_unit": "boosting rounds",
        "context_sha256": context["content_sha256"], "plan_sha256": context["neural_plan"]["content_sha256"],
        "tree_plan_sha256": context["tree_plan"]["content_sha256"], "export_plan_sha256": context["export_plan"]["content_sha256"],
        "paper_evidence": before, "managed_block_sha256": {name: digest(block) for name, block in blocks.items()},
        "publication_accepted": False, "pdf_build_performed": False, "free_prose_scientific_claims_proven": False,
        "all_input_parity_or_hardware_claims_verified": False,
        "visibility_scope": "literal top-level canonical TeX blocks; actual PDF rendering still requires isolated double build and review"}


def _template_end(template, review, pins):
    stage.assert_output_inventory(template, review["inputs"])
    data.assert_snapshots(pins, full=False)


def _template(context, review_path, expected_sha256):
    review_path = runtime.canonical(Path(review_path), file=True)
    review, pin = data.stable_record(review_path)
    require(pin["sha256"] == expected_sha256 and set(review) == {
        "schema", "kind", "renderer_sha256", "template_dir", "inputs", "passed",
        "free_prose_reviewed", "unresolved_blockers", "content_sha256"},
        "Template review differs from explicit caller commitment/schema")
    require(runtime.equal(review["schema"], 1) and review["kind"] == "continued_paper_template_review" and
        review["passed"] is True and review["free_prose_reviewed"] is True and
        review["unresolved_blockers"] == [] and
        review["renderer_sha256"] == context["source_pins"][str(SELF)]["sha256"],
        "Template requires source-bound scientific prose review")
    template = runtime.canonical(Path(review["template_dir"]), directory=True)
    require(set(review["inputs"]) == {str(template/n) for n in ("main.tex", "references.bib")},
        "Only the reviewed two-file template is allowed")
    pins = {str(review_path): pin}
    _merge(pins, review["inputs"])
    data.assert_snapshots(pins)
    _template_end(template, review, pins)
    return template, review, pins


def _write_bytes(path, payload):
    with path.open("xb") as stream:
        stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    pin = stage.snapshot(path)
    require(pin["sha256"] == hashlib.sha256(payload).hexdigest(), "Written paper payload changed")
    return pin


def render_candidate(context, template_dir, new_stage_dir, *, template_review_path, expected_template_review_sha256):
    """Fresh reviewed stage only; not PDF, manuscript, or publication acceptance."""
    _context(context, full=True)
    template, review, template_pins = _template(context, template_review_path, expected_template_review_sha256)
    require(runtime.canonical(Path(template_dir), directory=True) == template, "Template redirected")
    stage_dir = runtime.canonical(Path(new_stage_dir))
    require(stage_dir.parent == REVIEW_ROOT, "Paper candidate must use the approved new review namespace")
    data.new_path(stage_dir)
    forbidden = [template, POST, *[Path(b["root"]) for b in
        [*context["retained"]["strict_boundaries"], *context["retained"]["exact_boundaries"]]],
        *[Path(context["paths"][k]) for k in ("neural_run", "tree_run", "export_root")]]
    require(all(not stage_dir.is_relative_to(p) and not p.is_relative_to(stage_dir) for p in forbidden) and
        all(not Path(p).is_relative_to(stage_dir) for p in [*context["input_pins"], *template_pins]),
        "Fresh paper stage overlaps a held namespace/input")
    main = canonical_text((template/"main.tex").read_text(encoding="utf-8"), managed_blocks(context))
    result, export = paper_contract.macro_text(result_values(context)), legacy.export_macro_text(context["export_values"])
    result_provenance, export_provenance = _provenance(context, result, export)
    payloads = {"main.tex": main.encode(), "references.bib": (template/"references.bib").read_bytes(),
        "result_macros_v5.tex": result.encode(), "export_macros_v5.tex": export.encode(),
        "result_macros_v5.provenance.json": json_bytes(result_provenance)+b"\n",
        "export_macros_v5.provenance.json": json_bytes(export_provenance)+b"\n"}
    _template_end(template, review, template_pins); _context(context)
    stage_dir.mkdir(mode=0o700); runtime._fsync_dir(stage_dir.parent)
    own = {}
    try:
        paper = stage_dir/"paper"; paper.mkdir(); runtime._fsync_dir(stage_dir)
        for name, payload in payloads.items(): own[str(paper/name)] = _write_bytes(paper/name, payload)
        runtime._fsync_dir(paper)
        checked = check_candidate(context, paper, template_review_path=template_review_path,
            expected_template_review_sha256=expected_template_review_sha256)
        require(runtime.equal(checked["paper_evidence"], own), "Checker reblessed a changed paper output")
        records = {"paper_numeric_check.json": seal(checked),
            "render_manifest.json": seal({"schema": 1, "kind": "spikeids_v5_continued_readonly_paper_stage",
                "context_sha256": context["content_sha256"], "accepted_export": context["paths"]["export_acceptance"],
                "template_review": {"path": str(template_review_path), "sha256": expected_template_review_sha256},
                "template_inputs": template_pins, "input_pins": context["input_pins"], "source_pins": context["source_pins"],
                "paper_evidence": dict(own), "paper_check_sha256": hashlib.sha256(json_bytes(seal(checked))+b"\n").hexdigest(),
                "publication_accepted": False, "automatic_next_phase": False})}
        for name, value in records.items(): own[str(stage_dir/name)] = _write_bytes(stage_dir/name, json_bytes(value)+b"\n")
        runtime._fsync_dir(stage_dir)
        _context(context); _template_end(template, review, template_pins)
        stage.assert_output_inventory(stage_dir, own)
        _retained(context)
        continued.builds._end_stats(context["retained"]["installed"])
        _retained_inventory(context)
        _template_end(template, review, template_pins)
        stage.assert_output_inventory(stage_dir, own)
        data.assert_snapshots({**context["input_pins"], **template_pins, **own}, full=False)
        return checked
    except BaseException as exc:
        failed = stage_dir/"FAILED.json"
        if not failed.exists() and not failed.is_symlink():
            data.write_new(failed, seal({"schema": 1, "kind": "continued_paper_stage_failure", "passed": False,
                "error": repr(exc), "publication_accepted": False, "automatic_retry": False}))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("neural-run", "tree-run", "export-acceptance", "acceptance-exit", "template-dir", "new-stage-dir", "template-review"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("acceptance-sha256", "exit-sha256", "template-review-sha256"):
        parser.add_argument("--" + name, required=True)
    a = parser.parse_args()
    context = load_evidence(a.neural_run, a.tree_run, a.export_acceptance, a.acceptance_exit,
        expected_acceptance_sha256=a.acceptance_sha256, expected_exit_sha256=a.exit_sha256)
    result = render_candidate(context, a.template_dir, a.new_stage_dir,
        template_review_path=a.template_review, expected_template_review_sha256=a.template_review_sha256)
    print(json_bytes(result).decode())


if __name__ == "__main__": main()
