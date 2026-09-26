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
from tools import export_v5_science as science
from tools import build_v5_paper as builder
from tools.verify_v5_neural import NEURAL_VERIFIER_PACKAGES, validate_tool_provenance
import check_paper_consistency as checker
import paper_contract
from run_globecom_stats import analyze as analyze_difference
from run_v4_equivalence import analyze as analyze_equivalence
from contracts import ARMS, DATASETS, METRICS, check_seal, digest, json_bytes, load_json, require, seal, sha256

SELF = Path(__file__).resolve()
data, research = stage.data, stage.research
LABELS = {"nslkdd": "NSL-KDD", "unsw": "UNSW-NB15", "cicids2017": "CICIDS2017", "iot23": "IoT-23"}
BLOCK_NAMES = ("protocol", "equivalence", "tree", "exports")
ACCEPTANCE_KIND = "spikeids_v5_export_postrun_acceptance"
ACCEPTANCE_SCOPE = "bounded_review_of_fixed_22_neural_exports"
INPUT_FILES = set(builder.PAPER_INPUT_ALLOWLIST)


def sources():
    return sorted(set([SELF, *stage.sources(), Path(builder.__file__).resolve()]))


def _merge(pins, values):
    research.merge_pins(pins, values)


def _bound_record(path, pins):
    path = runtime.canonical(Path(path), file=True)
    require(str(path) in pins, f"Required paper input is not previously committed: {path}")
    value, observed = data.stable_record(path)
    require(runtime.equal(pins[str(path)], observed), f"Paper input differs from prior commitment: {path}")
    return value


def _acceptance(neural_run, tree_run, export_root, acceptance_path):
    accepted, acceptance_pin = data.stable_record(acceptance_path)
    require(type(accepted.get("schema")) is int and accepted["schema"] == 1 and
            accepted.get("kind") == ACCEPTANCE_KIND and accepted.get("scope") == ACCEPTANCE_SCOPE and
            accepted.get("passed") is True and accepted.get("matrix_execution_complete") is True and
            type(accepted.get("owner_observed_service_return_code")) is int and
            accepted["owner_observed_service_return_code"] == 0 and
            type(accepted.get("all_parity_gates_passed")) is bool and
            accepted.get("unresolved_export_blockers") == [] and
            accepted.get("next_phase_requires_new_review") is True and
            {"paper", "release", "boards", "NPU", "energy"} <= set(accepted.get("not_accepted", [])),
            "Paper requires bounded export post-run acceptance and an actually observed successful owner exit")
    reviews = accepted.get("review_evidence")
    require(isinstance(reviews, dict) and reviews and
            sum(Path(p).suffix == ".md" for p in reviews) >= 2,
            "Accepted export lacks retained independent review documents")
    pins = dict(reviews)
    _merge(pins, {str(acceptance_path): acceptance_pin})
    data.assert_snapshots(pins)
    boundaries = accepted["unchanged_predecessor_boundaries"] + [accepted["export_artifact_boundary"]]
    require([b["root"] for b in boundaries] == list(map(str, (neural_run, tree_run, export_root))),
            "Accepted paper predecessor roots differ")
    for boundary in boundaries:
        research.assert_boundary(boundary)
        _merge(pins, boundary["pins"])
    export_plan = _bound_record(export_root / "export_plan.json", pins)
    controller_path = Path(export_plan["execution_adapter"]["controller_plan"]["path"])
    controller = _bound_record(controller_path, pins)
    work = controller_path.parent
    completed = _bound_record(work / "complete.json", pins)
    started = _bound_record(work / "run_started.json", pins)
    require(not (work / "failed.json").exists() and not (work / "failed.json").is_symlink() and
            controller.get("kind") == "spikeids_v5_export_stage_plan" and
            controller.get("plan_path") == str(controller_path) and controller.get("work_dir") == str(work) and
            controller.get("neural_run") == str(neural_run) and controller.get("export_root") == str(export_root) and
            completed.get("kind") == "spikeids_v5_export_stage_complete" and
            completed.get("passed") is True and completed.get("scope") == stage.SCOPE and
            completed.get("matrix_execution_complete") is True and
            type(completed.get("all_parity_gates_passed")) is bool and
            controller["content_sha256"] == completed.get("plan_sha256") ==
                accepted.get("controller_plan_sha256") == started.get("plan_sha256") and
            export_plan["content_sha256"] == completed.get("export_plan_sha256") == accepted.get("export_plan_sha256") and
            completed["content_sha256"] == accepted.get("controller_completion_sha256") and
            accepted["source_plan_sha256"] == export_plan["source_plan_sha256"] == controller["formal_plan_sha256"] and
            runtime.equal(completed["artifact_boundary"], boundaries[-1]) and
            runtime.equal(controller["predecessor_boundaries"], boundaries[:2]) and
            runtime.equal(started["controller"], completed["controller"]) and
            completed["all_parity_gates_passed"] is accepted["all_parity_gates_passed"],
            "Accepted export/controller/completion/predecessor cross-binding differs")
    _merge(pins, completed["consumed_evidence"])
    _merge(pins, controller["input_pins"])
    owners, links = [], []
    for path in reviews:
        if Path(path).suffix != ".json":
            continue
        value = load_json(Path(path))
        if isinstance(value, dict) and value.get("kind") == "export_service_owner_observed_exit":
            owners.append((path, _bound_record(Path(path), pins)))
        if isinstance(value, dict) and value.get("kind") == "export_owner_exit_completion_link":
            links.append(_bound_record(Path(path), pins))
    require(len(owners) == len(links) == 1, "Exactly one bound owner exit and completion link are required")
    owner_path, owner = owners[0]
    link = links[0]
    expected_command = ["/usr/bin/systemd-run", "--user", "--wait", "--pipe", "--unit=" + controller["service_unit"],
        "--property=Type=exec", "--property=Restart=no", "--property=RemainAfterExit=no",
        "--property=KillMode=control-group", "--property=MemoryMax=16G", "--property=MemorySwapMax=0",
        "--working-directory=" + str(ROOT), "--setenv=TMPDIR=" + controller["temporary_runtime"]["path"],
        *["--setenv=" + key + "=" + value for key, value in sorted(stage.ENVIRONMENT.items())],
        controller["python"], str(stage.SELF), "run", "--plan", str(controller_path)]
    require(type(owner.get("schema")) is int and owner["schema"] == 1 and
            type(owner.get("actual_return_code")) is int and owner["actual_return_code"] == 0 and
            owner.get("actual_command") == expected_command and
            owner.get("not_postrun_acceptance") is True and
            type(owner.get("elapsed_seconds")) in (int, float) and math.isfinite(owner["elapsed_seconds"]) and
            owner["elapsed_seconds"] > 0 and
            owner.get("plan_sha256") == controller["content_sha256"] and
            owner.get("service_unit") == controller["service_unit"] and
            type(link.get("schema")) is int and link["schema"] == 1 and
            link.get("not_postrun_acceptance") is True and
            link.get("plan_sha256") == controller["content_sha256"] and
            type(link.get("journal_return_code")) is int and link["journal_return_code"] == 0 and
            link.get("invocation_id") == completed["controller"]["service"]["InvocationID"] and
            runtime.equal(link.get("controller"), completed["controller"]["process"]) and
            link.get("all_parity_gates_passed") is completed["all_parity_gates_passed"] and
            runtime.equal(link.get("observed_exit"), {"path": owner_path, **pins[owner_path]}) and
            runtime.equal(link.get("complete"), {"path": str(work / "complete.json"), **pins[str(work / "complete.json")]}),
            "Owner observation does not belong to this completed export execution")
    for record in (owner["log"], owner["launch_intent"], link["journal"]):
        require(runtime.equal(record, {"path": record["path"], **pins[record["path"]]}),
                "Owner launch/log/journal was not retained at acceptance")
    intent = _bound_record(Path(owner["launch_intent"]["path"]), pins)
    require(intent.get("kind") == "export_service_owner_launch_intent" and
            intent.get("automatic_retry") is False and intent.get("not_postrun_acceptance") is True and
            intent.get("plan_sha256") == controller["content_sha256"] and intent.get("command") == expected_command and
            runtime.equal(intent.get("plan"), {"path": str(controller_path), **pins[str(controller_path)]}),
            "Original owner launch intent differs from the actual observed invocation")
    for source in stage.sources():
        require(str(source) in pins, f"Accepted export source closure omitted {source}")
    data.assert_snapshots(pins)
    return accepted, controller, completed, export_plan, pins, boundaries


def _check_gate(check, *, qdq=False):
    require(isinstance(check, dict) and type(check.get("vectors_checked")) is int and
            check["vectors_checked"] == 1024 and type(check.get("allclose")) is bool and
            type(check.get("max_abs_error")) in (int, float) and
            math.isfinite(check["max_abs_error"]) and check["max_abs_error"] >= 0 and
            type(check.get("prediction_disagreement_fraction")) in (int, float) and
            math.isfinite(check["prediction_disagreement_fraction"]) and
            0 <= check["prediction_disagreement_fraction"] <= (0.01 if qdq else 0.0) and
            (qdq or check["allclose"] is True), "Export diagnostic fails its fixed sampled gate")


def _exports(export_root, controller, plan, summary, pins):
    require(runtime.equal(summary, stage.summary_for(plan, summary.get("attempts", []))),
            "External summary schema/policy/counts differ from complete fixed matrix")
    records = {}
    work = Path(controller["work_dir"])
    for row in summary["attempts"]:
        d, arm, mode = row["dataset"], row["model"], row["mode"]
        relative, key = f"{d}/{arm}/{mode}", f"{d}_{arm}_{mode}"
        require(set(row) == {"dataset", "model", "mode", "passed", "return_code", "elapsed_seconds",
                            "export_plan_sha256", "output_dir", "evidence", "evidence_sha256", "log", "log_sha256"} and
                row["output_dir"] == relative and row["evidence"] == relative + "/runner_validation.json" and
                row["log"] == str(work / "attempts" / (key + ".log")) and
                row["export_plan_sha256"] == plan["content_sha256"] and
                type(row["elapsed_seconds"]) in (int, float) and math.isfinite(row["elapsed_seconds"]) and
                row["elapsed_seconds"] > 0, "External export row identity/log/runtime differs")
        evidence_path = export_root / row["evidence"]
        evidence = _bound_record(evidence_path, pins)
        require(pins[str(evidence_path)]["sha256"] == row["evidence_sha256"] and
                pins[row["log"]]["sha256"] == row["log_sha256"], "Export summary evidence/log digest differs")
        rc = row["return_code"]
        observed = _bound_record(work / "attempts" / (key + "_exit.json"), pins)
        require(observed.get("kind") == "observed_export_worker_exit" and
                type(observed.get("actual_return_code")) is int and observed["actual_return_code"] == rc and
                observed.get("actual_os_command") == runtime.worker_invocation(export_root, d, arm, mode) and
                observed.get("export_plan_sha256") == plan["content_sha256"] and
                observed.get("controller_plan_sha256") == controller["content_sha256"] and
                observed.get("replay") is False, "Export row lacks matching actual child exit")
        checked = runtime.validate_worker_receipt(export_root, d, arm, mode, rc)
        for name, value in checked.items():
            require(runtime.equal(pins.get(name), value), "Worker evidence was not retained at acceptance")
        require(evidence.get("source_plan_sha256") == plan["source_plan_sha256"] and
                evidence.get("export_plan_sha256") == plan["content_sha256"] and
                (evidence.get("dataset"), evidence.get("model"), evidence.get("mode")) == (d, arm, mode) and
                runtime.equal(evidence.get("tool_provenance"), plan["tool_provenance"]) and
                evidence.get("exporter_invocation") == observed["actual_os_command"],
                "Export independent evidence belongs to another execution")
        output = export_root / relative
        inventory = legacy.output_files_sha256(output)
        require(evidence.get("output_files_sha256") == inventory,
                "Export independent evidence payload inventory differs")
        if row["passed"]:
            require(evidence.get("publication_gate") is True and evidence.get("status") == "independently_validated",
                    "Passing export lacks independent sampled validation")
            _check_gate(evidence["fp32_check"])
            _check_gate(evidence["independent_freeze_check"])
            audit_dir = export_root / "independent_audits" / relative
            adapter = evidence["scientific_adapter"]
            audit = _bound_record(audit_dir / "scientific_validation.json", pins)
            require(adapter.get("audit_dir") == str(audit_dir) and
                    adapter.get("report") == str(audit_dir / "scientific_validation.json") and
                    adapter.get("report_sha256") == pins[adapter["report"]]["sha256"] and
                    adapter.get("source_sha256") == sha256(Path(science.__file__).resolve()) and
                    audit.get("kind") == "independent_export_scientific_replay" and audit.get("passed") is True and
                    audit.get("source_plan_sha256") == plan["source_plan_sha256"] and
                    audit.get("export_plan_sha256") == plan["content_sha256"] and
                    (audit.get("dataset"), audit.get("model"), audit.get("mode")) == (d, arm, mode) and
                    runtime.equal(audit.get("policy"), science.policy()) and
                    runtime.equal(audit.get("freeze_check"), evidence["independent_freeze_check"]),
                    "Export independent freeze/recipe audit is missing or changed")
            if mode == "qdq":
                _check_gate(evidence["qdq_check"], qdq=True)
                replay = evidence["independent_qdq_recipe_replay"]
                require(runtime.equal(replay, audit["qdq_recipe_replay"]) and replay.get("passed") is True and
                        replay.get("kind") == "independent_exact_qdq_recipe_replay" and
                        replay.get("graph") == str(audit_dir / "model_qdq_rebuilt.onnx") and
                        replay["graph_sha256"] == inventory["model_qdq_int8.onnx"] == pins[replay["graph"]]["sha256"],
                        "QDQ recipe reproduction is missing or changed")
            else:
                require(evidence.get("independent_qdq_recipe_replay") is None and audit.get("qdq_recipe_replay") is None,
                        "FP32 evidence incorrectly claims a QDQ replay")
        else:
            require(evidence.get("publication_gate") is False and evidence.get("status") == "export_subprocess_failed" and
                    evidence.get("failure_classification") == "reproduced_scientific_gate" and
                    type(evidence.get("return_code")) is int and evidence["return_code"] == 1,
                    "An infrastructure/unclassified export failure cannot be published as a scientific negative")
            failed = legacy.scientific_failure(output, plan, d, arm, mode, rc)
            replay_dir = export_root / "replays" / relative
            require(runtime.equal(failed, legacy.scientific_failure(replay_dir, plan, d, arm, mode, 1)) and
                    legacy.output_files_sha256(replay_dir) == inventory,
                    "Retained negative replay is not an exact scientific reproduction")
            for name, value in runtime.validate_worker_receipt(export_root, d, arm, mode, 1, replay=True).items():
                require(runtime.equal(pins.get(name), value), "Negative replay receipt was not retained at acceptance")
            replay_exit = _bound_record(work / "attempts" / (key + "_replay_exit.json"), pins)
            require(type(replay_exit.get("actual_return_code")) is int and replay_exit["actual_return_code"] == 1 and
                    replay_exit.get("replay") is True and replay_exit.get("export_plan_sha256") == plan["content_sha256"] and
                    replay_exit.get("actual_os_command") == runtime.worker_invocation(export_root, d, arm, mode, True),
                    "Negative replay lacks a matching actual child exit")
        records[f"{d}:{arm}:{mode}"] = evidence
    return records, _export_values(export_root, summary, records)


def _export_values(export_root, summary, records):
    fp_errors, qdq_disagreements = [], []
    for row in summary["attempts"]:
        evidence = records[f"{row['dataset']}:{row['model']}:{row['mode']}"]
        if row["passed"]:
            _check_gate(evidence["fp32_check"])
            fp_errors.append(evidence["fp32_check"]["max_abs_error"])
            if row["mode"] == "qdq":
                _check_gate(evidence["qdq_check"], qdq=True)
                qdq_disagreements.append(evidence["qdq_check"]["prediction_disagreement_fraction"])
    values = {"vExportFpPassed": str(summary["fp32_passed"]), "vExportFpTotal": "11",
        "vExportQdqPassed": str(summary["qdq_passed"]), "vExportQdqTotal": "11",
        "vExportValidationVectors": "1024", "vExportCalibrationRows": "1000", "vExportQdqLimitPct": "1.00",
        "vExportFpWorstAbsError": legacy._scientific_tex(max(fp_errors)) if fp_errors else r"\text{n/a}",
        "vExportQdqWorstPassedDisagreementPct": f"{100 * max(qdq_disagreements):.3f}" if qdq_disagreements else r"\text{n/a}"}
    for row in summary["attempts"]:
        prefix = _export_prefix(row["dataset"], row["model"], row["mode"])
        values[prefix + "Status"] = r"\text{pass}" if row["passed"] else r"\text{negative}"
        failure = None if row["passed"] else load_json(export_root / row["output_dir"] / "FAILED.json")["stage"]
        text = {None: "n/a", "freeze": "BN freeze", "fp32_parity": "FP32 parity", "qdq_parity": "QDQ parity"}[failure]
        values[prefix + "FailureStage"] = r"\text{" + text + "}"
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


def load_evidence(neural_run, tree_run, export_root, export_acceptance_path):
    """Load accepted immutable inputs; never execute inference or rewrite stats."""
    neural_run, tree_run, export_root = [runtime.canonical(Path(p), directory=True)
                                      for p in (neural_run, tree_run, export_root)]
    accepted_path = runtime.canonical(Path(export_acceptance_path), file=True)
    require(not any(accepted_path.is_relative_to(p) for p in (neural_run, tree_run, export_root)),
            "Post-run acceptance must be external to immutable scientific roots")
    source_pins = {str(p): stage.snapshot(p) for p in sources()}
    accepted, controller, complete, preliminary, pins, boundaries = _acceptance(
        neural_run, tree_run, export_root, accepted_path)
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
    export = runtime.load_plan(export_root, neural)
    require(runtime.equal(export, preliminary), "Export plan changed across accepted input validation")
    summary = _bound_record(export_root / "summary.json", pins)
    require(summary.get("all_gates_passed") is accepted["all_parity_gates_passed"] and
            complete["all_parity_gates_passed"] is summary["all_gates_passed"], "Acceptance changes negative export outcomes")
    export_records, export_values = _exports(export_root, controller, export, summary, pins)
    metadata = {}
    for job in neural["jobs"]:
        path = Path(job["cache"]) / "metadata.json"
        if str(path) not in pins:
            # Metadata was already committed by the export plan; never bless a new observation.
            binding = next(row for row in export["inputs"] if row["path"] == str(path))
            observed = stage.snapshot(path)
            require(binding["sha256"] == observed["sha256"] and
                    binding["stat"] == {"device": observed["device"], "inode": observed["inode"], "size": observed["bytes"],
                                        "mtime_ns": observed["mtime_ns"], "ctime_ns": observed["ctime_ns"]}, "Metadata prior binding differs")
            _merge(pins, {str(path): observed})
        metadata[job["dataset"]] = _bound_record(path, pins)
    for boundary in boundaries:
        research.assert_boundary(boundary, full=False)
    data.assert_snapshots(pins, full=False)
    return seal({"schema": 1, "kind": "spikeids_v5_readonly_paper_context",
        "paths": {"neural_run": str(neural_run), "tree_run": str(tree_run), "export_root": str(export_root),
                  "export_acceptance": str(accepted_path)},
        "acceptance_sha256": accepted["content_sha256"], "neural_plan": neural,
        "results": {f"{d}:{a}": result for (d, a), result in results.items()},
        "tree_plan": tree, "tree_report": tree_report, "difference": difference, "equivalence": equivalence,
        "export_plan": export, "export_summary": summary, "export_records": export_records,
        "export_values": export_values, "metadata": metadata, "input_pins": pins,
        "boundaries": boundaries, "source_pins": source_pins,
        "publication_accepted": False, "free_prose_scientific_claims_proven": False})


def _context(context, *, full=False):
    check_seal(context)
    require(type(context.get("schema")) is int and context["schema"] == 1 and
            context.get("kind") == "spikeids_v5_readonly_paper_context" and
            context.get("publication_accepted") is False and context.get("free_prose_scientific_claims_proven") is False,
            "Invalid read-only paper context")
    require(set(context["source_pins"]) == {str(p) for p in sources()}, "Paper renderer source inventory changed")
    data.assert_snapshots(context["source_pins"])
    data.assert_snapshots(context["input_pins"], full=full)
    for boundary in context["boundaries"]:
        research.assert_boundary(boundary, full=False)
    paths, pins = context["paths"], context["input_pins"]
    neural, tree, exports = (Path(paths[key]) for key in ("neural_run", "tree_run", "export_root"))
    for key, path in (("neural_plan", neural / "plan.json"), ("tree_plan", tree / "plan.json"),
                      ("tree_report", tree / "results.json"), ("export_plan", exports / "export_plan.json"),
                      ("export_summary", exports / "summary.json")):
        require(runtime.equal(context[key], _bound_record(path, pins)), f"Paper context body differs from committed {key}")
    for key, name in (("difference", "stats_report_globecom.json"), ("equivalence", "equivalence_v5.json")):
        require(runtime.equal(seal(context[key]), _bound_record(neural / name, pins)),
                f"Paper context statistics were changed: {key}")
    for job in context["neural_plan"]["jobs"]:
        require(runtime.equal(context["results"][job['dataset'] + ':' + job['model']],
                              _bound_record(neural / "results" / (job["id"] + ".json"), pins)),
                "Paper context per-seed result body changed")
        require(runtime.equal(context["metadata"][job["dataset"]],
                              _bound_record(Path(job["cache"]) / "metadata.json", pins)),
                "Paper context metadata changed")
    for row in context["export_summary"]["attempts"]:
        key = f"{row['dataset']}:{row['model']}:{row['mode']}"
        require(runtime.equal(context["export_records"][key], _bound_record(exports / row["evidence"], pins)),
                "Paper context export record body changed")
    require(runtime.equal(context["export_values"], _export_values(exports, context["export_summary"], context["export_records"])),
            "Paper context export macro values changed")
    accepted = _bound_record(Path(paths["export_acceptance"]), pins)
    require(accepted["content_sha256"] == context["acceptance_sha256"] and accepted.get("passed") is True and
            accepted.get("kind") == ACCEPTANCE_KIND and accepted["source_plan_sha256"] == context["neural_plan"]["content_sha256"] and
            accepted["export_plan_sha256"] == context["export_plan"]["content_sha256"], "Paper context acceptance changed")


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
        r"Each uses \vExportValidationVectors\ validation vectors and \vExportCalibrationRows\ fit calibration rows.",
        "A negative is a retained and exactly reproduced scientific gate failure, not a passed model or an omitted attempt.",
        "Controller execution completion is not parity success. These CPU software results establish no all-input guarantee,",
        "all-INT8/NPU mapping, board deployment, latency, or energy result.",
        r"\begin{center}\small\resizebox{\columnwidth}{!}{\begin{tabular}{lllll}",
        r"Dataset & Arm & Mode & Outcome & Failed gate \\"]
    for row in rows:
        d, arm, mode = row["dataset"], row["model"], row["mode"]
        prefix = _export_prefix(d, arm, mode)
        lines.append(f"{LABELS[d]} & {arm.upper()} & {mode.upper()} & \\{prefix}Status & \\{prefix}FailureStage " + r"\\")
    lines += [r"\end{tabular}}\end{center}"]
    return {"protocol": block, "equivalence": equivalence, "tree": tree_block, "exports": _wrap("exports", lines)}


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
        "export_summary_sha256": context["input_pins"][str(Path(context["paths"]["export_root"]) / "summary.json")]["sha256"],
        "macro_sha256": h(export_text), "readonly_stage": upstream})
    return result, export


def check_candidate(context, paper_dir):
    """Read-only source/number check; intentionally not PDF/publication approval."""
    _context(context)
    paper = runtime.canonical(Path(paper_dir), directory=True)
    require({p.name for p in paper.iterdir()} == INPUT_FILES, "Paper candidate needs exactly the six builder inputs")
    before = {str(p): stage.snapshot(p) for p in sorted(paper.iterdir())}
    blocks = managed_blocks(context)
    text = (paper / "main.tex").read_text(encoding="utf-8")
    require(canonical_text(text, blocks) == text, "Managed numerical blocks are missing or hand-edited")
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
    _context(context)
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


def render_candidate(context, template_dir, new_stage_dir):
    """Only a fresh stage is written; source template and all predecessors stay unchanged."""
    _context(context, full=True)
    template = runtime.canonical(Path(template_dir), directory=True)
    stage_dir = runtime.canonical(Path(new_stage_dir))
    require(not stage_dir.exists() and stage_dir.parent.is_dir(), "Paper stage must be a fresh canonical namespace")
    forbidden = [template, *(Path(context["paths"][key]) for key in ("neural_run", "tree_run", "export_root"))]
    require(all(not stage_dir.is_relative_to(p) and not p.is_relative_to(stage_dir) for p in forbidden),
            "Fresh paper stage overlaps a template or immutable predecessor")
    require({p.name for p in template.iterdir()} == {"main.tex", "references.bib"},
            "Candidate template must contain only explicit main.tex and references.bib")
    template_pins = {str(p): stage.snapshot(p) for p in sorted(template.iterdir())}
    main = canonical_text((template / "main.tex").read_text(encoding="utf-8"), managed_blocks(context))
    result, export = paper_contract.macro_text(result_values(context)), legacy.export_macro_text(context["export_values"])
    result_provenance, export_provenance = _provenance(context, result, export)
    payloads = {"main.tex": main.encode(), "references.bib": (template / "references.bib").read_bytes(),
                "result_macros_v5.tex": result.encode(), "export_macros_v5.tex": export.encode(),
                "result_macros_v5.provenance.json": json_bytes(result_provenance) + b"\n",
                "export_macros_v5.provenance.json": json_bytes(export_provenance) + b"\n"}
    data.assert_snapshots(template_pins)
    _context(context)
    stage_dir.mkdir(mode=0o700)
    runtime._fsync_dir(stage_dir.parent)
    paper = stage_dir / "paper"; paper.mkdir()
    runtime._fsync_dir(stage_dir)
    for name, payload in payloads.items():
        with (paper / name).open("xb") as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    runtime._fsync_dir(paper)
    checked = check_candidate(context, paper)
    data.assert_snapshots(template_pins)
    _context(context)
    data.write_new(stage_dir / "paper_numeric_check.json", seal(checked))
    data.write_new(stage_dir / "render_manifest.json", seal({"schema": 1, "kind": "spikeids_v5_readonly_paper_stage",
        "context_sha256": context["content_sha256"], "accepted_export": context["paths"]["export_acceptance"],
        "template_inputs": template_pins, "input_pins": context["input_pins"], "source_pins": context["source_pins"],
        "paper_check_sha256": sha256(stage_dir / "paper_numeric_check.json"),
        "publication_accepted": False, "automatic_next_phase": False}))
    data.assert_snapshots(checked["paper_evidence"])
    data.assert_snapshots(template_pins)
    _context(context)
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    for name in ("neural-run", "tree-run", "export-root", "export-acceptance", "template-dir", "new-stage-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    context = load_evidence(args.neural_run, args.tree_run, args.export_root, args.export_acceptance)
    result = render_candidate(context, args.template_dir, args.new_stage_dir)
    print(json_bytes(result).decode())


if __name__ == "__main__":
    main()
