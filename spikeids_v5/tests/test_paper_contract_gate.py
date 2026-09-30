"""Adversarial manuscript contract cases; every number here is synthetic."""
from copy import deepcopy
from pathlib import Path
import os
import shutil
import subprocess
import sys
import types

import pytest

import contracts as c
import check_paper_consistency as checker
from group_protocol import PROTOCOL_VERSION


INPUTS = "\\input{result_macros_v5.tex}\n\\input{export_macros_v5.tex}\n"
BLOCK = checker.PROTOCOL_START + "A visible fixed protocol.\n" + checker.PROTOCOL_END


def paper(tmp_path, *, preamble=INPUTS, body=BLOCK):
    (tmp_path / "result_macros_v5.tex").write_text(r"\newcommand{\vFiveSeeds}{20}")
    (tmp_path / "export_macros_v5.tex").write_text(r"\newcommand{\vExportFpPassed}{11}")
    main = tmp_path / "main.tex"
    main.write_text(preamble + "\\begin{document}\n" + body + "\\end{document}\n")
    return main


def test_valid_literal_inputs_and_visible_protocol(tmp_path):
    files = checker.validate_manuscript(paper(tmp_path), BLOCK)
    assert set(files) == {"main.tex", *checker.MACRO_FILES}


@pytest.mark.parametrize("preamble", [
    r"\input{result_macros_v5.tex}",
    INPUTS + r"\input{result_macros_v5.tex}",
    INPUTS + r"\input{export_macros_v5.tex}",
    INPUTS.replace("export_macros_v5.tex", "export_macros_v5"),
    INPUTS.replace(r"\input{export", r"\include{export"),
    INPUTS.replace(r"\input{export_macros_v5.tex}", r"\newcommand{\unused}{\input{export_macros_v5.tex}}"),
    INPUTS.replace(r"\input{export_macros_v5.tex}", r"\iffalse\input{export_macros_v5.tex}\fi"),
    INPUTS.replace(r"\input{export_macros_v5.tex}", r"% \input{export_macros_v5.tex}"),
    INPUTS + r"\IfFileExists{old.tex}{}{}",
    INPUTS + r"\input result_macros_v5.tex",
])
def test_missing_duplicate_fallback_and_nonvisible_inputs_rejected(tmp_path, preamble):
    with pytest.raises(c.ContractError):
        checker.validate_manuscript(paper(tmp_path, preamble=preamble), BLOCK)


def test_generated_macro_cannot_be_input_indirectly(tmp_path):
    (tmp_path / "section.tex").write_text(r"\input{export_macros_v5.tex}")
    main = paper(tmp_path, preamble=r"\input{result_macros_v5.tex}\input{section.tex}")
    with pytest.raises(c.ContractError, match="literal direct"):
        checker.validate_manuscript(main, BLOCK)


@pytest.mark.parametrize("attack", [
    "\\renewcommand\n{\\vFiveSeeds}{1}",
    "\\providecommand*\n{\\vExportFpPassed}{9}",
    r"\gdef\vFiveSeeds{1}", r"\global\long\edef\vFiveSeeds{1}",
    r"\xdef\vExportFpPassed{9}", r"\let\vFiveSeeds=\relax",
    r"\futurelet\vFiveSeeds\relax", r"\chardef\vFiveSeeds=65",
    r"\mathchardef\vExportFpPassed=65", r"\countdef\vFiveSeeds=0",
    r"\dimendef\vFiveSeeds=0", r"\skipdef\vFiveSeeds=0",
    r"\muskipdef\vFiveSeeds=0", r"\toksdef\vFiveSeeds=0",
    r"\DeclareRobustCommand{\vFiveSeeds}{1}",
    r"\RenewDocumentCommand{\vExportFpPassed}{}{9}",
    r"\newenvironment{vFiveSeeds}{}{}",
    r"\expandafter\gdef\csname vFiveSeeds\endcsname{1}",
    r"\csname renewcommand\endcsname{\vFiveSeeds}{1}",
    r"\def\prefix{vFive}\expandafter\def\csname\prefix Seeds\endcsname{1}",
    r"\let\alias\def\alias\vFiveSeeds{1}",
    r"\let\alias\vFiveSeeds", r"\def\input#1{}",
    r"\def\unused{\def\vFiveSeeds{1}}",
    r"\catcode`\@=11", r"\scantokens{\def\vFiveSeeds{1}}",
    r"\de^^66\vFiveSeeds{1}",
    r"\endinput",
    "\\def\\unused\n\\input{export_macros_v5.tex}",
    r"\def\vFiveSeeds@foo{1}",
    r"\gdef\vExportFpPassed@foo{9}",
    r"\edef\vFiveSeeds@foo{1}",
    r"\xdef\vFiveSeeds@foo{1}",
    r"\let\vFiveSeeds@foo=\relax",
    r"\def\vFiveSeeds:foo{1}",
    r"\let\alias\iftrue",
    r"\csname iftrue\endcsname",
    r"\newif\ifpaperswitch",
])
def test_protected_macro_redefinitions_and_dynamic_bypasses_fail(tmp_path, attack):
    with pytest.raises(c.ContractError):
        checker.validate_manuscript(paper(tmp_path, preamble=INPUTS + attack + "\n"), BLOCK)


@pytest.mark.parametrize("safe", [
    r"\newcommand{\DatasetName}{NSL-KDD}",
    r"\newcommand{\SeedReference}{\vFiveSeeds}",
    r"\def\MeaningfulName#1{Value #1}",
    r"\def\MeaningfulName@foo{Value}",
    r"\newenvironment{CustomNote}{}{}",
    r"% \def\vFiveSeeds{1}",
])
def test_unrelated_literal_definitions_and_readonly_references_allowed(tmp_path, safe):
    checker.validate_manuscript(paper(tmp_path, preamble=INPUTS + safe + "\n"), BLOCK)


def _compile_pdf_text(main):
    for tool in ("pdflatex", "pdftotext"):
        if shutil.which(tool) is None:
            pytest.skip(f"Real TeX regression requires {tool}")
    compiled = subprocess.run(
        ["pdflatex", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", main.name],
        cwd=main.parent, capture_output=True, text=True, timeout=60,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    extracted = subprocess.run(
        ["pdftotext", "main.pdf", "-"], cwd=main.parent,
        capture_output=True, text=True, check=True, timeout=15,
    )
    return " ".join(extracted.stdout.split())


def test_real_tex_at_delimiter_overrides_generated_macro_and_gate_rejects(tmp_path):
    # At standard catcodes, @ is a parameter delimiter, not part of the
    # control-word name. Prove the changed rendered value with a real engine.
    main = paper(
        tmp_path,
        preamble="\\documentclass{article}\n" + INPUTS + "\\def\\vFiveSeeds@foo{1}\n",
        body=BLOCK + "The generated seed count is \\vFiveSeeds@foo.\n",
    )
    assert "The generated seed count is 1." in _compile_pdf_text(main)
    assert (tmp_path / "result_macros_v5.tex").read_text() == r"\newcommand{\vFiveSeeds}{20}"
    with pytest.raises(c.ContractError, match="protected generated macro"):
        checker.validate_manuscript(main, BLOCK)


def test_real_tex_mathematical_iff_is_not_a_conditional_primitive(tmp_path):
    main = paper(
        tmp_path, preamble="\\documentclass{article}\n" + INPUTS,
        body=BLOCK + "A standard equivalence statement is $A \\iff B$.\n",
    )
    assert "A standard equivalence statement" in _compile_pdf_text(main)
    checker.validate_manuscript(main, BLOCK)


@pytest.mark.parametrize("command", [
    "if", "ifx", "ifnum", "iffalse", "ifdefined", "ifcsname", "iffontchar",
    "ifincsname", "ifpdfprimitive", "ifpdfabsnum", "ifpdfabsdim", "unless", "fi",
])
def test_explicit_tex_conditionals_and_their_csname_forms_still_fail(tmp_path, command):
    for text in ("\\" + command, "\\csname " + command + "\\endcsname"):
        with pytest.raises(c.ContractError):
            checker.validate_manuscript(paper(tmp_path, preamble=INPUTS + text + "\n"), BLOCK)


@pytest.mark.parametrize("body", [
    "No protocol block.\n", BLOCK + BLOCK,
    BLOCK.replace("visible", "stale"),
    "\\newcommand{\\unused}{\n" + BLOCK + "}\n",
    "\\begin{verbatim}\n" + BLOCK + "\\end{verbatim}\n",
    "\\iffalse\n" + BLOCK + "\\fi\n",
])
def test_absent_stale_duplicate_or_hidden_protocol_block_fails(tmp_path, body):
    with pytest.raises(c.ContractError):
        checker.validate_manuscript(paper(tmp_path, body=body), BLOCK)


def test_linked_manuscript_source_rejected(tmp_path):
    main = paper(tmp_path)
    os.link(main, tmp_path / "outside_alias.tex")
    with pytest.raises(c.ContractError, match="unlinked"):
        checker.validate_manuscript(main, BLOCK)


@pytest.mark.parametrize("stale", [
    "Our validation-selected protocol is fixed.",
    "Model selection uses\nvalidation macro recall.",
    "The best checkpoint is selected by macro recall.",
    "CICIDS2017 uses a row split.",
    "IoT-23 first receives a stratified train/test row split.",
    "We claim row-split benchmark performance.",
    "Neural loss uses inverse-frequency fit-only class weighting.",
    "We train for 80 epochs with batch size 512.",
    "Random Forest has 100 trees.",
    "CICIDS2017 & 77 & 15 & 99",
    "The p = 0.001 result is significant.",
    r"Accuracy was 99.00\pm0.01.",
    "They are statistically indistinguishable on all four datasets.",
])
def test_stale_protocol_claims_outside_block_reported(stale):
    assert checker.protocol_findings({"main.tex": stale}, BLOCK)


def plans():
    metadata = {d: {"data_fingerprint": d, "partition": {"protocol_version": PROTOCOL_VERSION},
                    "features": list(range(76 if d == "cicids2017" else 13)),
                    "class_names": list(range(5)), "counts": {"fit": 64, "validation": 16, "test": 20}}
                for d in c.DATASETS}
    policy = {"loss_weighting": "sqrt_inverse_fit_only_v1", "checkpoint_policy": "fixed_final_epoch_v1",
              "validation_role": "diagnostic_only"}
    neural = {"content_sha256": "neural", "training_policy": policy, "seeds": list(range(20)),
              "difference_family": list(range(14)), "equivalence_family": list(range(8)),
              "alpha": .05, "equivalence_margin_pp": .5, "jobs": []}
    for dataset in c.DATASETS:
        for model in c.ARMS[dataset]:
            neural["jobs"].append({"dataset": dataset, "model": model, "data_fingerprint": dataset,
                "hyperparameters": {"model": model, "epochs": 40 if dataset == "iot23" else 80,
                    "batch_size": 1024 if dataset == "iot23" else 512, "hidden": 256, "levels": 4,
                    "qcfs_formula": "shifted_v1", "optimizer": "foreach", "lr": .001,
                    "weight_decay": .00001, "eval_every": 10,
                    "loss_weighting": policy["loss_weighting"], "checkpoint_policy": policy["checkpoint_policy"]}})
    tree = {"datasets": {d: {"data_fingerprint": d} for d in ("nslkdd", "unsw")},
            "hyperparameters": {"random_forest": {"n_estimators": 100, "max_depth": 20, "class_weight": "balanced"},
                "xgboost": {"n_estimators": 100, "max_depth": 6, "learning_rate": .1, "tree_method": "hist",
                    "subsample": 1., "colsample_bytree": 1., "sample_weight": "inverse fit-class frequency"}},
            "random_forest_seeds": list(range(20)), "xgboost_seeds": [0]}
    export = {"source_plan_sha256": "neural", "protocol": {"deployment_seed": 0, "opset": 17, "export_batch": 1,
               "validation_samples": 1024, "calibration_samples": 1000, "fp32_atol": 1e-6, "fp32_rtol": 1e-5,
               "int8_max_prediction_disagreement": .01, "qdq_recipe": {"quant_format": "QDQ", "activation_type": "QInt8",
                   "weight_type": "QInt8", "per_channel": True, "calibrate_method": "MinMax"}}}
    return neural, tree, export, metadata


def test_protocol_values_are_plan_derived_and_own_block_is_not_flagged(tmp_path):
    args = plans()
    block = checker.expected_protocol_block(*args)
    assert "CICIDS2017 & 76" in block and "220 primary fits" in block
    assert "fixed final epoch" in block and "not sampling uncertainty" in block
    files = checker.validate_manuscript(paper(tmp_path, body=block), block)
    assert checker.protocol_findings(files, block) == []
    changed = deepcopy(args)
    changed[1]["hyperparameters"]["random_forest"]["n_estimators"] = 75
    assert checker.expected_protocol_block(*changed) != block
    changed = deepcopy(args)
    changed[3]["cicids2017"]["counts"]["test"] += 1
    assert checker.expected_protocol_block(*changed) != block


@pytest.mark.parametrize("mutator", [
    lambda args: args[0]["training_policy"].update(checkpoint_policy="best_validation"),
    lambda args: args[0]["jobs"][0]["hyperparameters"].update(loss_weighting="inverse"),
    lambda args: args[0]["jobs"][1]["hyperparameters"].update(batch_size=99),
    lambda args: args[1]["datasets"]["nslkdd"].update(data_fingerprint="wrong"),
    lambda args: args[2].update(source_plan_sha256="wrong"),
    lambda args: args[2]["protocol"]["qdq_recipe"].update(activation_type="QUInt8"),
    lambda args: args[3]["cicids2017"]["partition"].update(protocol_version="row_split_v0"),
])
def test_unsupported_or_inconsistent_protocol_fails_closed(mutator):
    args = plans()
    mutator(args)
    with pytest.raises(c.ContractError):
        checker.expected_protocol_block(*args)


def test_checker_cannot_silently_omit_export_gate(tmp_path):
    with pytest.raises(c.ContractError, match="explicit verified export root"):
        checker.check(tmp_path, tmp_path, tmp_path)


def test_finalize_build_uses_independent_builder_and_explicit_export():
    source = (Path(checker.__file__).parent / "finalize_all_det.py").read_text()
    assert '"--export-plan"' in source and '"--neural-plan"' in source
    assert '"build_v5_paper.py"' in source
    assert 'subprocess.run(["latexmk"' not in source


@pytest.fixture
def export_fixture(tmp_path, monkeypatch):
    # Isolate runner verification at its public API; the runner has its own
    # signed-policy/artifact tests. These attacks exercise the checker's links.
    runner = types.ModuleType("tools.run_v5_exports")
    export_plan = {"content_sha256": "export-plan"}
    runner.load_export_plan = lambda root, plan: export_plan
    runner.expected_export_macros = lambda root, summary: {"vExportFpPassed": "11"}
    runner.export_macro_text = lambda values: "exact export bytes\n"
    monkeypatch.setitem(sys.modules, "tools.run_v5_exports", runner)
    actual_repo = Path.cwd()
    monkeypatch.setattr(checker, "__file__", str(actual_repo / "spikeids_v5/check_paper_consistency.py"))
    export_root, paper_dir = tmp_path / "exports", tmp_path / "paper"
    export_root.mkdir(); paper_dir.mkdir()
    summary_path = export_root / "summary.json"
    c.write_json(summary_path, c.seal({"source_plan_sha256": "neural", "export_plan_sha256": "export-plan"}))
    macro = paper_dir / "export_macros_v5.tex"
    macro.write_text("exact export bytes\n")
    provenance_path = paper_dir / "export_macros_v5.provenance.json"
    c.write_json(provenance_path, c.seal({"schema": 1, "kind": "spikeids_v5_export_paper_macros",
        "plan_sha256": "neural", "export_plan_sha256": "export-plan",
        "export_summary_sha256": c.sha256(summary_path), "macro_sha256": c.sha256(macro)}))
    return export_root, paper_dir, {"content_sha256": "neural"}


def test_export_provenance_and_bytes_are_consumed(export_fixture):
    assert checker._export_evidence(*export_fixture)["content_sha256"] == "export-plan"


@pytest.mark.parametrize("field", ["plan_sha256", "export_plan_sha256", "export_summary_sha256", "macro_sha256", "kind"])
def test_resealed_export_provenance_with_wrong_link_rejected(export_fixture, field):
    path = export_fixture[1] / "export_macros_v5.provenance.json"
    provenance = c.load_json(path)
    provenance.pop("content_sha256")
    provenance[field] = "wrong"
    c.write_json(path, c.seal(provenance))
    with pytest.raises(c.ContractError, match="provenance"):
        checker._export_evidence(*export_fixture)


def test_coordinated_reseal_of_hand_edited_export_macro_rejected(export_fixture):
    paper_dir = export_fixture[1]
    macro = paper_dir / "export_macros_v5.tex"
    macro.write_text("fabricated result\n")
    path = paper_dir / "export_macros_v5.provenance.json"
    provenance = c.load_json(path)
    provenance.pop("content_sha256")
    provenance["macro_sha256"] = c.sha256(macro)
    c.write_json(path, c.seal(provenance))
    with pytest.raises(c.ContractError, match="hand-edited"):
        checker._export_evidence(*export_fixture)
