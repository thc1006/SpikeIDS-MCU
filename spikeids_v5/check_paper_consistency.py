"""Bind literal manuscript inputs and visible protocol to verified v5 evidence.

This is a restricted TeX source contract, not arbitrary TeX execution or proof
of every natural-language claim. Publication still requires the independent
isolated double-builder.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re
import sys

from contracts import (ARMS, DATASETS, check_seal, digest, load_json, require,
                       seal, sha256, write_json)
from evidence import verified_suite
from run_globecom_stats import analyze as analyze_difference
from run_v4_equivalence import analyze as analyze_equivalence
from paper_contract import expected_macros, macro_text, strip_comments, tex_sources
from tree_baseline import load_verified_tree_suite

MACRO_FILES = ("result_macros_v5.tex", "export_macros_v5.tex")
PROTOCOL_START = "% BEGIN V5 FROZEN PROTOCOL\n"
PROTOCOL_END = "% END V5 FROZEN PROTOCOL\n"
# The manuscript contract fixes standard LaTeX catcodes: only ASCII letters
# form control words. In particular, @ is a delimiter, since makeatletter and
# arbitrary catcode changes are rejected below. Treating it as a letter would
# misread '\\def\\vFiveSeeds@foo{1}' as a harmless different macro definition.
PROTECTED = re.compile(r"^(?:vFive|vExport)")
CONTROL_WORD = r"[A-Za-z]+"
CONTROL = re.compile(r"\\(" + CONTROL_WORD + r"|.)", re.DOTALL)
DEFINITION_COMMANDS = {
    "def", "gdef", "edef", "xdef", "let", "futurelet", "chardef", "mathchardef",
    "countdef", "dimendef", "skipdef", "muskipdef", "toksdef", "newif",
    "newcommand", "renewcommand", "providecommand", "DeclareRobustCommand",
    "NewDocumentCommand", "RenewDocumentCommand", "ProvideDocumentCommand",
    "DeclareDocumentCommand", "NewExpandableDocumentCommand",
    "RenewExpandableDocumentCommand", "ProvideExpandableDocumentCommand",
    "DeclareExpandableDocumentCommand", "newenvironment", "renewenvironment",
    "NewDocumentEnvironment", "RenewDocumentEnvironment", "ProvideDocumentEnvironment",
    "DeclareDocumentEnvironment",
}
PARSER_COMMANDS = {
    "catcode", "scantokens", "endlinechar", "escapechar", "makeatletter",
    "ExplSyntaxOn", "directlua", "everyjob", "everyeof", "everypar", "everymath",
    "everydisplay", "everyhbox", "everyvbox", "everycr", "toks", "afterassignment",
    "lccode", "uccode", "endinput", "stop", "newif",
}
INPUT_COMMANDS = {"input", "include", "includeonly", "InputIfFileExists", "IfFileExists"}
# TeX/e-TeX/pdfTeX conditional primitives, not arbitrary 'if...' control words:
# '\\iff' is ordinary LaTeX mathematics. pdfTeX additions are documented at
# https://tug.org/applications/pdftex/ (pdfTeX user manual).
CONDITIONAL_COMMANDS = {
    "if", "ifcat", "ifnum", "ifdim", "ifodd", "ifvmode", "ifhmode", "ifmmode",
    "ifinner", "ifvoid", "ifhbox", "ifvbox", "ifx", "ifeof", "iftrue", "iffalse",
    "ifcase", "ifdefined", "ifcsname", "iffontchar", "ifincsname",
    "ifpdfprimitive", "ifpdfabsnum", "ifpdfabsdim", "else", "or", "fi", "unless",
}
SCANNER_SENSITIVE = DEFINITION_COMMANDS | INPUT_COMMANDS | PARSER_COMMANDS | CONDITIONAL_COMMANDS


def _regular(path: Path) -> None:
    require(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1
            and not any(parent.is_symlink() for parent in path.absolute().parents),
            f"Paper evidence must be a regular, unlinked file: {path}")


def _definition_target(text: str, end: int) -> str:
    tail = text[end:].lstrip()
    if tail.startswith("*"):
        tail = tail[1:].lstrip()
    pattern = (r"\{\s*(?:\\)?(" + CONTROL_WORD + r")\s*\}" if tail.startswith("{")
               else r"\\(" + CONTROL_WORD + ")")
    match = re.match(pattern, tail)
    require(match is not None, "Dynamic/nonliteral definition target is outside the paper contract")
    target = match.group(1)
    require(target not in {"csname", "expandafter", "noexpand"},
            "Dynamic definition target is outside the paper contract")
    return target


def _source_syntax(text: str) -> None:
    require("^^" not in text, "TeX character-code escapes are outside the paper contract")
    for match in CONTROL.finditer(text):
        command = match.group(1)
        require(command not in PARSER_COMMANDS,
                f"TeX parser/implicit execution primitive is outside the paper contract: {command}")
        require(command not in CONDITIONAL_COMMANDS,
                "Conditional manuscript content is outside the paper contract")
        if command in DEFINITION_COMMANDS:
            target = _definition_target(text, match.end())
            require(not PROTECTED.match(target), f"Redefinition of protected generated macro: {target}")
            require(target not in SCANNER_SENSITIVE
                    and target not in {"csname", "endcsname", "begin", "end"},
                    f"Redefinition of scanner-sensitive primitive: {target}")
            if command in {"def", "gdef", "edef", "xdef"}:
                tail = text[match.end():].lstrip()
                target_match = CONTROL.match(tail)
                require(target_match is not None, "Nonliteral primitive definition target")
                body_start = tail.find("{", target_match.end())
                require(body_start >= 0 and "\\" not in tail[target_match.end():body_start],
                        "Control tokens in primitive definition parameters are outside the paper contract")
            if command in {"let", "futurelet"}:
                tail = text[match.end():]
                target_match = CONTROL.search(tail)
                source_match = CONTROL.search(tail, target_match.end()) if target_match else None
                if source_match:
                    source = source_match.group(1)
                    require(source not in SCANNER_SENSITIVE and not PROTECTED.match(source),
                            "Aliases of generated macros or definition/input primitives are prohibited")
        if command == "csname":
            end = text.find(r"\endcsname", match.end())
            require(end >= 0, "Unclosed csname in manuscript")
            name = text[match.end():end].strip()
            require(re.fullmatch(r"[A-Za-z@]+", name) is not None,
                    "Computed csname is outside the paper contract")
            require(not PROTECTED.match(name) and name not in SCANNER_SENSITIVE,
                    "Dynamic protected macro or definition/input primitive is prohibited")


def _context_at(text: str, offset: int) -> tuple[int, list[str]]:
    """Track literal grouping/environments; escaped braces are single tokens."""
    depth, environments = 0, []
    for match in re.finditer(r"\\(?:begin|end)\s*\{([^{}]+)\}|\\(?:" + CONTROL_WORD + r"|.)|[{}]",
                             text[:offset], re.DOTALL):
        token = match.group(0)
        if match.group(1) is not None:
            name = match.group(1)
            if token.startswith(r"\begin"):
                environments.append(name)
            else:
                require(environments and environments[-1] == name, "Unbalanced manuscript environment")
                environments.pop()
        elif token == "{":
            depth += 1
        elif token == "}":
            depth -= 1
            require(depth >= 0, "Unbalanced manuscript braces")
    return depth, environments


def validate_manuscript(main: Path, protocol_block: str | None = None) -> dict[str, str]:
    """Require direct, top-level, exactly-once literal macro inputs in all modes."""
    main = Path(main)
    files = tex_sources(main)
    for name in files:
        _regular(main.parent / name)
    counts: Counter[str] = Counter()
    for name, text in files.items():
        if name in MACRO_FILES:
            continue  # The evidence checker separately requires exact regenerated bytes.
        _source_syntax(text)
        require("result_macros.tex" not in text and "IfFileExists" not in text,
                "Legacy/fallback macro inputs are prohibited")
        for match in re.finditer(r"\\(input|include)\s*\{([^{}]+)\}", text):
            path = match.group(2)
            normalized = path if Path(path).suffix else path + ".tex"
            if Path(normalized).name in MACRO_FILES:
                require(name == "main.tex" and match.group(1) == "input" and path in MACRO_FILES,
                        "Generated macros need literal direct main.tex inputs including .tex")
                require(_context_at(text, match.start()) == (0, []),
                        "Generated macros must be unconditional top-level preamble inputs")
                document_start = text.find(r"\begin{document}")
                require(document_start >= 0 and match.start() < document_start,
                        "Generated macro inputs must precede the document")
                counts[path] += 1
    require(counts == Counter({name: 1 for name in MACRO_FILES}),
            "main.tex must input each result/export macro exactly once")
    main_text = files["main.tex"]
    require(_context_at(main_text, len(main_text)) == (0, []), "Manuscript groups/environments are unbalanced")
    require(len(re.findall(r"\\begin\{document\}", main_text)) == 1 and
            len(re.findall(r"\\end\{document\}", main_text)) == 1,
            "Manuscript needs exactly one literal document environment")
    if protocol_block is not None:
        raw = main.read_text(encoding="utf-8")
        require(raw.count(PROTOCOL_START) == raw.count(PROTOCOL_END) == 1,
                "Exactly one frozen protocol block is required")
        start, finish = raw.index(PROTOCOL_START), raw.index(PROTOCOL_END) + len(PROTOCOL_END)
        require(raw[start:finish] == protocol_block,
                "Manuscript protocol block differs from verified data/neural/tree/export plans")
        prefix = strip_comments(raw[:start])
        require(_context_at(prefix, len(prefix)) == (0, ["document"]),
                "Frozen protocol block must be visible at document top level")
    return files


def _number(value: int | float) -> str:
    require(type(value) in (int, float), "Protocol number must be numeric")
    return format(value, ".12g")


def expected_protocol_block(plan: dict, tree_plan: dict, export_plan: dict,
                            metadata: dict[str, dict]) -> str:
    """Visible deterministic prose/tables with values from verified source plans."""
    from group_protocol import FOLD_INDEX, FOLDS, PROTOCOL_VERSION, TEST_SEED, VALIDATION_SEED

    require(plan.get("training_policy") == {
        "loss_weighting": "sqrt_inverse_fit_only_v1",
        "checkpoint_policy": "fixed_final_epoch_v1", "validation_role": "diagnostic_only",
    }, "Paper protocol renderer does not support this neural training policy")
    jobs = {(job["dataset"], job["model"]): job for job in plan["jobs"]}
    require(set(jobs) == {(d, a) for d in DATASETS for a in ARMS[d]},
            "Paper protocol needs the exact four-dataset, eleven-arm matrix")
    lines = [PROTOCOL_START.rstrip(), r"\paragraph{Frozen data and training protocol.}",
             "The evaluation unit is a unique labelled final-FP32 input pattern.",
             "Preprocessing is fitted on canonical-raw unique labelled fit patterns;",
             "it is not refitted after final-FP32 deduplication. Distinct raw patterns",
             "that later collapse can therefore influence the scaler more than once.",
             "Exact input assignment components never cross fit, validation, and test.",
             "Conflicting labels remain distinct labelled patterns within one component.",
             "Official NSL-KDD and UNSW-NB15 roles are retained, excluding official-test",
             "components that touch official training data. CICIDS2017 and IoT-23 use",
             "approximate target 64/16/20 grouped pattern splits, not capture, device,",
             "or time holdouts. Realized pattern counts are reported below.",
             f"StratifiedGroupKFold uses {_number(FOLDS)} folds, fixed fold {_number(FOLD_INDEX)},",
             f"validation seed {_number(VALIDATION_SEED)}, and combined-data test seed {_number(TEST_SEED)}.",
             r"\begin{center}\small", r"\resizebox{\columnwidth}{!}{", r"\begin{tabular}{lrrrrrr}",
             r"Dataset & Inputs & Classes & Fit & Validation & Test & Epochs/batch \\"]
    labels = {"nslkdd": "NSL-KDD", "unsw": "UNSW-NB15", "cicids2017": "CICIDS2017", "iot23": "IoT-23"}
    for dataset in DATASETS:
        meta = metadata[dataset]
        require(meta["partition"]["protocol_version"] == PROTOCOL_VERSION,
                "Paper protocol renderer does not support this data partition version")
        h = jobs[dataset, "relu"]["hyperparameters"]
        for arm in ARMS[dataset]:
            job = jobs[dataset, arm]
            require(job["data_fingerprint"] == meta["data_fingerprint"],
                    "Paper dataset metadata differs from the neural plan")
            require(all(job["hyperparameters"].get(key) == value for key, value in h.items()
                        if key != "model"), "Paper arm budgets differ")
        counts = meta["counts"]
        lines.append(f"{labels[dataset]} & {len(meta['features'])} & {len(meta['class_names'])} & "
                     f"{counts['fit']} & {counts['validation']} & {counts['test']} & "
                     f"{h['epochs']}/{h['batch_size']} " + r"\\")
    lines.extend([r"\end{tabular}}", r"\end{center}"])
    common = jobs["nslkdd", "relu"]["hyperparameters"]
    common_keys = ("hidden", "levels", "qcfs_formula", "optimizer", "lr", "weight_decay",
                   "eval_every", "loss_weighting", "checkpoint_policy")
    require(all(all(job["hyperparameters"][key] == common[key] for key in common_keys)
                for job in jobs.values()), "Paper protocol requires common declared model/optimizer settings")
    require(common["qcfs_formula"] == "shifted_v1", "Unsupported QCFS paper formula")
    require(common["loss_weighting"] == "sqrt_inverse_fit_only_v1" and
            common["checkpoint_policy"] == "fixed_final_epoch_v1",
            "Job training policy differs from declared paper policy")
    width, levels = common["hidden"], common["levels"]
    lines.extend([
        f"The MLP hidden widths are {width}, {width}, and {width // 2}, with BatchNorm.",
        f"QCFS uses the shifted formula with $L={levels}$; it is a quantized ANN activation.",
        r"\[q(x)=\left(\frac{\lfloor L\,\mathrm{clip}(x/\theta,0,1)+1/2\rfloor}{L}\right)\theta.\]",
        "TinyCNN uses two feature-axis Conv2D layers of kernel $1\\times3$ with 8 and 16 channels.",
        "IoT-23 includes ReLU and QCFS only; the other datasets also include TinyCNN.",
        f"Adam uses learning rate {_number(common['lr'])} and weight decay {_number(common['weight_decay'])},",
        "cosine decay, deterministic FP32 operations, and square-root inverse-frequency",
        "weights computed from final-deduplicated fit labels and normalized to sum to the class count.",
        f"Validation is diagnostic every {common['eval_every']} epochs and at the final epoch.",
        "The checkpoint is always the fixed final epoch; validation does not select it.",
        f"There are {len(plan['seeds'])} paired seeds and {len(plan['jobs']) * len(plan['seeds'])} primary fits,",
        "each independently repeated before the global test barrier opens.",
        "Seed variation quantifies optimization variability on one fixed split, not sampling uncertainty.",
    ])
    require(set(tree_plan["datasets"]) == {"nslkdd", "unsw"}, "Tree paper dataset matrix differs")
    for dataset, row in tree_plan["datasets"].items():
        require(row["data_fingerprint"] == metadata[dataset]["data_fingerprint"], "Tree and neural manuscript data differ")
    rf, xgb = (tree_plan["hyperparameters"][kind] for kind in ("random_forest", "xgboost"))
    require(rf["class_weight"] == "balanced" and xgb["tree_method"] == "hist" and
            xgb["sample_weight"] == "inverse fit-class frequency" and
            xgb["subsample"] == xgb["colsample_bytree"] == 1.0 and
            len(tree_plan["xgboost_seeds"]) == 1, "Unsupported tree protocol in manuscript")
    export = export_plan["protocol"]
    require(export_plan["source_plan_sha256"] == plan["content_sha256"], "Export paper protocol refers to another neural plan")
    recipe = export["qdq_recipe"]
    require(recipe["quant_format"] == "QDQ" and recipe["activation_type"] == recipe["weight_type"] == "QInt8"
            and recipe["per_channel"] is True and recipe["calibrate_method"] == "MinMax", "Unsupported QDQ paper recipe")
    lines.extend([
        f"Random Forest uses {rf['n_estimators']} trees, depth {rf['max_depth']}, balanced weights,",
        f"and {len(tree_plan['random_forest_seeds'])} seeds on NSL-KDD and UNSW-NB15.",
        f"XGBoost uses {xgb['n_estimators']} histogram trees, depth {xgb['max_depth']}, learning rate {_number(xgb['learning_rate'])},",
        "inverse fit-class-frequency sample weights, and one deterministic seed without subsampling.",
        "Tree hyperparameters are fixed before evaluation; independent semantic model replication precedes test prediction.",
        f"The difference family has {len(plan['difference_family'])} paired signed-rank tests;",
        f"the equivalence family has {len(plan['equivalence_family'])} paired t-TOST tests at alpha {_number(plan['alpha'])}.",
        "Holm adjustment is applied separately within each declared family.",
        f"The numerical sensitivity margin is $\\pm{_number(plan['equivalence_margin_pp'])}$ percentage points;",
        "it is not an established practical-importance threshold or historical preregistration.",
        "Signed-rank tests target a symmetric difference location; means are descriptive.",
        "A separate Holm-adjusted signed-rank TOST family is a robustness analysis, with discordance disclosed.",
        f"Exports use deployment seed {export['deployment_seed']}, opset {export['opset']}, and batch {export['export_batch']}.",
        f"Validation uses {export['validation_samples']} fixed validation vectors and calibration uses {export['calibration_samples']} fit rows.",
        f"FP32 gates use atol {_number(export['fp32_atol'])}, rtol {_number(export['fp32_rtol'])}, and zero prediction disagreement.",
        f"QDQ accepts prediction disagreement at most {_number(100 * export['int8_max_prediction_disagreement'])} percent.",
        "The QDQ recipe uses signed INT8 activations and weights, per-channel weights, and MinMax calibration.",
        "ONNX Runtime software parity establishes neither full-INT8/NPU mapping nor board latency or energy.",
        PROTOCOL_END.rstrip(),
    ])
    return "\n".join(lines) + "\n"


def protocol_findings(files: dict[str, str], protocol_block: str) -> list[str]:
    """Conservative stale-claim detection, not semantic proof of free prose."""
    block = strip_comments(protocol_block).strip()
    issues = []
    patterns = (
        r"validation[- ]selected|model\s+selection\s+uses\s+validation|best\s+checkpoint\s+is\s+selected",
        r"(?:uses?|receives?)\b.{0,100}\b(?:row[- ]split|train/test\s+row\s+split)",
        r"row[- ]split\s+benchmark\s+performance",
        r"inverse[- ]frequency\s+(?:fit[- ]only\s+)?class\s+weight",
        r"(?:batch\s+size|hidden\s+(?:widths?|sizes?)|learning\s+rate|max(?:imum)?\s+depth)\s+\d",
        r"\b\d+\s+(?:epochs|trees)\b|\bL\s*=\s*\d+",
        r"(?:NSL-KDD|UNSW-NB15|CICIDS2017|IoT-23)\s*&\s*\d",
        r"\bp\s*(?:_\{?adj\}?\s*)?\{?[=<>]\}?\s*~?\s*0\.\d+",
        r"\d+\.\d+\s*(?:\\pm|\$\\pm\$|±)\s*\d+\.\d+",
        r"statistically\s+indistinguishable\s+on\s+all\s+four",
        r"FP32\s+ReLU\s*=\s*T|practical\s+equivalence",
    )
    for name, text in files.items():
        if name in MACRO_FILES:
            continue
        if name == "main.tex":
            text = text.replace(block, "", 1)
        normalized = re.sub(r"\s+", " ", text)
        for pattern in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                issues.append(f"{name}: stale/literal protocol or claim outside frozen block: {match.group(0)}")
    return issues


def _export_evidence(export_root: Path, paper_dir: Path, plan: dict) -> dict:
    # load_export_plan checks the source digest of this outside-package runner.
    repo = Path(__file__).resolve().parent.parent
    require((repo / "tools" / "run_v5_exports.py").is_file(), "Export runner missing from checkout")
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    from tools.run_v5_exports import load_export_plan, expected_export_macros, export_macro_text

    export_plan = load_export_plan(export_root, plan)
    summary_path = export_root / "summary.json"
    _regular(summary_path)
    summary = load_json(summary_path)
    check_seal(summary)
    require(summary.get("source_plan_sha256") == plan["content_sha256"] and
            summary.get("export_plan_sha256") == export_plan["content_sha256"], "Export summary plan binding differs")
    macro = paper_dir / "export_macros_v5.tex"
    provenance_path = paper_dir / "export_macros_v5.provenance.json"
    _regular(macro)
    _regular(provenance_path)
    require(macro.read_text(encoding="utf-8") == export_macro_text(expected_export_macros(export_root, summary)),
            "Export macros are missing, stale, duplicated, or hand-edited")
    provenance = load_json(provenance_path)
    check_seal(provenance)
    require(provenance.get("schema") == 1 and provenance.get("kind") == "spikeids_v5_export_paper_macros"
            and provenance.get("plan_sha256") == plan["content_sha256"]
            and provenance.get("export_plan_sha256") == export_plan["content_sha256"]
            and provenance.get("export_summary_sha256") == sha256(summary_path)
            and provenance.get("macro_sha256") == sha256(macro), "Export macro provenance invalid")
    return export_plan


def check(run_dir, tree_run_dir, paper_dir, strict=False, *, export_root=None):
    run_dir, tree_run_dir, paper_dir = map(Path, (run_dir, tree_run_dir, paper_dir))
    require(export_root is not None, "Paper consistency requires an explicit verified export root")
    initial_files = validate_manuscript(paper_dir / "main.tex")
    paper_paths = {*initial_files, "result_macros_v5.provenance.json", "export_macros_v5.provenance.json"}
    for name in paper_paths:
        _regular(paper_dir / name)
    initial_hashes = {name: sha256(paper_dir / name) for name in paper_paths}
    context = verified_suite(run_dir)
    plan, results = context
    tree_plan, tree_report = load_verified_tree_suite(tree_run_dir)
    require(plan["protocol_role"] == "planned_benchmark" and len(plan["seeds"]) == 20,
            "Smoke/subset runs cannot validate the 20-seed paper")
    difference, equivalence = analyze_difference(run_dir, context), analyze_equivalence(run_dir, context)
    for name, want in (("stats_report_globecom.json", difference), ("equivalence_v5.json", equivalence)):
        actual = load_json(run_dir / name)
        check_seal(actual)
        require(actual == seal(want), f"Stale/inconsistent statistical report: {name}")
    path = paper_dir / "result_macros_v5.tex"
    _regular(path)
    require(path.read_text(encoding="utf-8") == macro_text(expected_macros(plan, results, difference, equivalence, tree_report)),
            "Missing, duplicated, hand-edited, or stale generated macro")
    manifest_path = paper_dir / "result_macros_v5.provenance.json"
    _regular(manifest_path)
    manifest = load_json(manifest_path)
    check_seal(manifest)
    require(manifest["plan_sha256"] == plan["content_sha256"] and manifest["macro_sha256"] == sha256(path), "Macro provenance invalid")
    require(manifest["tree_plan_sha256"] == tree_plan["content_sha256"] and
            manifest["tree_result_sha256"] == sha256(tree_run_dir / "results.json"), "Tree macro provenance invalid")
    require(manifest["difference_sha256"] == digest(difference) and
            manifest["equivalence_sha256"] == digest(equivalence), "Macro sources changed")
    export_plan = _export_evidence(Path(export_root), paper_dir, plan)
    metadata = {}
    for job in plan["jobs"]:
        if job["dataset"] in metadata:
            continue
        meta = load_json(Path(job["cache"]) / "metadata.json")
        check_seal(meta)
        require(meta["data_fingerprint"] == job["data_fingerprint"], "Paper metadata binding differs")
        metadata[job["dataset"]] = meta
    block = expected_protocol_block(plan, tree_plan, export_plan, metadata)
    files = validate_manuscript(paper_dir / "main.tex", block)
    findings = protocol_findings(files, block) if strict else []
    require(not findings, "Strict manuscript check failed:\n" + "\n".join(findings))
    require(set(files) == set(initial_files) and
            initial_hashes == {name: sha256(paper_dir / name) for name in paper_paths},
            "Paper inputs changed during numerical/protocol verification")
    return {"numeric_consistency_passed": True, "export_consistency_passed": True,
            "literal_macro_inputs_passed": True, "frozen_protocol_block_passed": True,
            "strict_heuristic_scan_passed": strict,
            "plan_sha256": plan["content_sha256"], "tree_plan_sha256": tree_plan["content_sha256"],
            "export_plan_sha256": export_plan["content_sha256"],
            "manuscript_sources_sha256": {name: initial_hashes[name] for name in files},
            "paper_evidence_sha256": initial_hashes,
            "protocol_block_sha256": digest(block),
            "natural_language_scientific_claims_proven": False, "deployment_claims_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--tree-run-dir", required=True, type=Path)
    parser.add_argument("--export-root", required=True, type=Path)
    parser.add_argument("--paper-dir", required=True, type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = check(args.run_dir, args.tree_run_dir, args.paper_dir, args.strict, export_root=args.export_root)
    write_json(args.run_dir / "paper_numeric_check.json", seal(report))
    print(report)


if __name__ == "__main__":
    main()
