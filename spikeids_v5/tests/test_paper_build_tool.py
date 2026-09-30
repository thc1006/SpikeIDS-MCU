"""Focused adversarial tests for the isolated deterministic paper builder."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import build_v5_paper  # noqa: E402


FAKE_TOOL = r'''#!/usr/bin/python3
import json
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
root = Path(sys.argv[0]).resolve().parent
config = json.loads((root / "config.json").read_text(encoding="utf-8"))

if "--version" in sys.argv or "-v" in sys.argv:
    print(f"fake {name} 1.0")
    raise SystemExit(0)

if name == "latexmk":
    counter_path = root / "counter.txt"
    count = int(counter_path.read_text() if counter_path.exists() else "0") + 1
    counter_path.write_text(str(count), encoding="ascii")
    pdf = b"%PDF-1.7\nfresh deterministic v5 pdf\n%%EOF\n"
    if config.get("non_reproducible"):
        pdf = b"%PDF-1.7\n" + str(count).encode("ascii") + b"\n%%EOF\n"
    if config.get("non_pdf"):
        pdf = b"not a pdf"
    if config.get("missing_pdf_eof"):
        pdf = b"%PDF-1.7\nmissing terminal marker\n"
    Path("main.pdf").write_bytes(pdf)
    Path("main.log").write_text(config.get("log", "Output written on main.pdf (1 page).\n"), encoding="utf-8")
    Path("main.blg").write_text(
        config.get(
            "blg",
            "This is BibTeX\nThe style file: IEEEtran.bst\n"
            "Database file #1: references.bib\nDone.\n",
        ),
        encoding="utf-8",
    )
    Path("main.bbl").write_text("safe bibliography\n", encoding="utf-8")
    Path("main.aux").write_text("safe aux\n", encoding="utf-8")
    inputs = [
        "main.tex", "result_macros_v5.tex", "export_macros_v5.tex",
        "main.aux", "main.bbl",
    ]
    if config.get("extra_input"):
        inputs.append(config["extra_input"])
    rows = [f"PWD {Path.cwd().resolve()}"] + [f"INPUT {item}" for item in inputs]
    Path("main.fls").write_text("\n".join(rows) + "\n", encoding="utf-8")
    mutate = config.get("mutate_path")
    if mutate and count == 1:
        Path(mutate).write_text("changed during build\n", encoding="utf-8")
    if config.get("mutate_staged"):
        Path("references.bib").write_text("changed staged bibliography\n", encoding="utf-8")
    print(config.get("transcript", "fake forced latexmk build completed"))
    raise SystemExit(0)

if name == "kpsewhich":
    print(root / "IEEEtran.bst")
    raise SystemExit(0)

if name == "pdfinfo":
    print("Title: Safe version-5 paper")
    print("Pages: 1")
    print("Encrypted: no")
    print("JavaScript: no")
    print("PDF version: 1.7")
    raise SystemExit(0)

if name == "pdftotext":
    print(config.get("text", "Leakage-Safe and Reproducible Intrusion Detection"))
    raise SystemExit(0)

raise SystemExit(f"unexpected fake tool invocation: {name}")
'''


def _digest(value: dict) -> str:
    data = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _sealed(body: dict) -> dict:
    return {**body, "content_sha256": _digest(body)}


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _make_repository(root: Path) -> Path:
    paper = root / "paper" / "globecom"
    paper.mkdir(parents=True)
    (paper / "main.tex").write_text(
        "\\documentclass{IEEEtran}\n"
        "\\input{result_macros_v5.tex}\n"
        "\\input{export_macros_v5.tex}\n"
        "\\begin{document}safe \\cite{x}\\bibliographystyle{IEEEtran}"
        "\\bibliography{references}\\end{document}\n",
        encoding="utf-8",
    )
    (paper / "references.bib").write_text(
        "@article{x,title={Safe},author={A},journal={J},year={2026}}\n",
        encoding="utf-8",
    )
    (paper / "result_macros_v5.tex").write_text("\\newcommand{\\Result}{safe}\n", encoding="utf-8")
    (paper / "export_macros_v5.tex").write_text("\\newcommand{\\Export}{safe}\n", encoding="utf-8")
    plans = root / "plans"
    plans.mkdir()
    neural = _sealed({"schema": 5, "protocol_role": "planned_benchmark"})
    tree = _sealed({"schema": 5, "kind": "tree_baseline_plan"})
    export = _sealed({
        "schema": 1,
        "kind": "spikeids_v5_export_plan",
        "source_plan_sha256": neural["content_sha256"],
    })
    _write_json(plans / "neural.json", neural)
    _write_json(plans / "tree.json", tree)
    _write_json(plans / "export.json", export)
    result_provenance = _sealed({
        "plan_sha256": neural["content_sha256"],
        "tree_plan_sha256": tree["content_sha256"],
        "macro_sha256": hashlib.sha256((paper / "result_macros_v5.tex").read_bytes()).hexdigest(),
    })
    export_provenance = _sealed({
        "kind": "spikeids_v5_export_paper_macros",
        "plan_sha256": neural["content_sha256"],
        "export_plan_sha256": export["content_sha256"],
        "macro_sha256": hashlib.sha256((paper / "export_macros_v5.tex").read_bytes()).hexdigest(),
    })
    _write_json(paper / "result_macros_v5.provenance.json", result_provenance)
    _write_json(paper / "export_macros_v5.provenance.json", export_provenance)
    return paper


def _make_toolchain(root: Path, config: dict) -> Path:
    tools = root / "fake-tools"
    tools.mkdir()
    (tools / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (tools / "IEEEtran.bst").write_text("fake IEEEtran bibliography style\n", encoding="utf-8")
    for name in ("latexmk", "pdflatex", "bibtex", "kpsewhich", "pdfinfo", "pdftotext"):
        path = tools / name
        path.write_text(FAKE_TOOL, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return tools


def _build(repo: Path, paper: Path, output: Path) -> dict:
    return build_v5_paper.build_paper(
        repo_root=repo,
        paper_dir=paper,
        output_dir=output,
        plan_paths={
            "neural": repo / "plans" / "neural.json",
            "tree": repo / "plans" / "tree.json",
            "export": repo / "plans" / "export.json",
        },
        timeout_seconds=20,
    )


def test_fresh_build_ignores_touched_unrelated_pdf_and_seals_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    stale_pdf = paper / "main.pdf"
    stale_pdf.write_bytes(b"unrelated legacy PDF")
    os.utime(stale_pdf, (4102444800, 4102444800))
    tools = _make_toolchain(tmp_path, {})
    monkeypatch.setenv("PATH", str(tools))

    output = tmp_path / "published"
    evidence = _build(repo, paper, output)

    assert stale_pdf.read_bytes() == b"unrelated legacy PDF"
    assert (output / "main.pdf").read_bytes().startswith(b"%PDF-")
    assert set(evidence["paper_inputs"]) == set(build_v5_paper.PAPER_INPUT_ALLOWLIST)
    assert "main.pdf" not in evidence["paper_inputs"]
    assert evidence["reproducibility"]["pdf_bytes_identical"] is True
    assert evidence["reproducibility"]["isolated_fresh_builds"] == 2
    stored = json.loads((output / "paper_build.json").read_text(encoding="utf-8"))
    seal = stored.pop("content_sha256")
    assert seal == _digest(stored)
    assert seal == evidence["content_sha256"]
    for relative, record in evidence["publication_manifest"]["hashed_files"].items():
        data = (output / relative).read_bytes()
        assert hashlib.sha256(data).hexdigest() == record["sha256"]
        assert len(data) == record["size_bytes"]
    actual_inventory = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    assert actual_inventory == set(evidence["publication_manifest"]["exact_inventory"])
    actual_directories = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_dir() and not path.is_symlink()
    }
    assert actual_directories == set(evidence["publication_manifest"]["exact_directories"])
    assert not any(path.is_symlink() for path in output.rglob("*"))
    for name in build_v5_paper.PAPER_INPUT_ALLOWLIST:
        assert (output / "inputs" / "paper" / name).read_bytes() == (paper / name).read_bytes()
    for name in ("neural", "tree", "export"):
        assert (output / "inputs" / "plans" / f"{name}_plan.json").read_bytes() == (
            repo / "plans" / f"{name}.json"
        ).read_bytes()
    assert (output / "main.aux").is_file()
    assert (output / "main.bbl").is_file()
    assert "independent recomputation of generated macro numeric values" in evidence["evidence_boundary"]["does_not_establish"]


@pytest.mark.skipif(
    any(shutil.which(name) is None for name in ("latexmk", "pdflatex", "bibtex", "kpsewhich", "pdfinfo", "pdftotext")),
    reason="installed TeX/Poppler toolchain is unavailable",
)
def test_installed_toolchain_produces_two_identical_fresh_pdfs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    main = paper / "main.tex"
    main.write_text(main.read_text().replace(
        r"safe \cite{x}", r"Result: \Result. Export: \Export. Reference: \cite{x}"
    ))
    output = tmp_path / "published-real"

    evidence = _build(repo, paper, output)

    assert evidence["reproducibility"]["pdf_bytes_identical"] is True
    assert evidence["builds"][0]["fls_input_inventory_sha256"] == evidence["builds"][1]["fls_input_inventory_sha256"]
    assert (output / "main.pdf").stat().st_size > 1000
    rendered = " ".join((output / "main.txt").read_text().split())
    assert "Result: safe. Export: safe. Reference: [1]" in rendered
    for index, record in enumerate(evidence["builds"], start=1):
        built = output / f"build-{index}"
        transcript = (built / "latexmk.transcript").read_text()
        # A fresh real bibliography necessarily starts unresolved, but a later
        # pdflatex pass resolves it. The retained transcript proves both phases.
        assert "Run number 1 of rule 'pdflatex'" in transcript
        assert "Run number 2 of rule 'pdflatex'" in transcript
        assert "Citation `x'" in transcript and "undefined" in transcript
        assert "This is BibTeX" in transcript
        assert "undefined" not in (built / "main.log").read_text().lower()
        assert "Database file #1: references.bib" in (built / "main.blg").read_text()
        assert record["bibliography_inputs"]["references.bib"]["sha256"] == hashlib.sha256(
            (paper / "references.bib").read_bytes()
        ).hexdigest()
        assert record["artifacts"]["main.pdf"]["sha256"] == hashlib.sha256(
            (output / "main.pdf").read_bytes()
        ).hexdigest()


@pytest.mark.skipif(
    any(shutil.which(name) is None for name in ("latexmk", "pdflatex", "bibtex", "kpsewhich", "pdfinfo", "pdftotext")),
    reason="installed TeX/Poppler toolchain is unavailable",
)
def test_real_unresolved_bibliography_citation_cannot_publish(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    main = paper / "main.tex"
    # The long missing key forces TeX's warning to wrap in a real log.
    missing = "missing-v5-bibliography-entry-" * 4
    main.write_text(main.read_text().replace(r"\cite{x}", "\\cite{x," + missing + "}"))
    output = tmp_path / "published-invalid"
    with pytest.raises(build_v5_paper.PaperBuildError, match="undefined citation|missing bibliography entry"):
        _build(repo, paper, output)
    assert not output.exists()


@pytest.mark.skipif(
    any(shutil.which(name) is None for name in ("latexmk", "pdflatex", "bibtex", "kpsewhich", "pdfinfo", "pdftotext")),
    reason="installed TeX/Poppler toolchain is unavailable",
)
def test_real_build_with_transcript_only_final_warning_cannot_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    real_run = build_v5_paper._run

    def inject_final_warning(command: list[str], **kwargs) -> subprocess.CompletedProcess[bytes]:
        completed = real_run(command, **kwargs)
        if "-pdf" in command and "main.tex" in command:
            # Real processes/artifacts, with a wrapped diagnostic visible only
            # in the orchestration transcript after the final successful pass.
            return subprocess.CompletedProcess(
                completed.args, completed.returncode,
                completed.stdout + b"\nLaTeX Warning: Citation\n`missing' on page 1\nundefined.\n",
                completed.stderr,
            )
        return completed

    monkeypatch.setattr(build_v5_paper, "_run", inject_final_warning)
    output = tmp_path / "published-transcript-warning"
    with pytest.raises(build_v5_paper.PaperBuildError, match="undefined citation"):
        _build(repo, paper, output)
    assert not output.exists()


def test_final_log_is_not_masked_by_converged_latexmk_transcript() -> None:
    transcript = (
        b"Run number 1 of rule 'pdflatex'\nCitation `x' undefined.\n"
        b"Run number 2 of rule 'pdflatex'\nOutput written on main.pdf.\n"
    )
    with pytest.raises(build_v5_paper.PaperBuildError, match="undefined citation"):
        build_v5_paper._lint_logs({
            "main.log": b"LaTeX Warning: Citation\n`unresolved' on page 1\nundefined.\n",
            "main.blg": b"The style file: IEEEtran.bst\n",
            "latexmk transcript": transcript,
        })


def test_final_bibtex_log_is_not_masked_by_converged_latexmk_transcript() -> None:
    with pytest.raises(build_v5_paper.PaperBuildError, match="missing bibliography entry"):
        build_v5_paper._lint_logs({
            "main.log": b"Output written on main.pdf.\n",
            "main.blg": b"Warning--I didn't find a database entry for missing\n",
            "latexmk transcript": b"Run number 2 of rule 'pdflatex'\nOutput written on main.pdf.\n",
        })


def test_non_reproducible_fresh_build_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    tools = _make_toolchain(tmp_path, {"non_reproducible": True})
    monkeypatch.setenv("PATH", str(tools))
    output = tmp_path / "published"

    with pytest.raises(build_v5_paper.PaperBuildError, match="different PDF SHA-256"):
        _build(repo, paper, output)
    assert not output.exists()


@pytest.mark.parametrize("plan_name", ["neural", "tree", "export"])
def test_fake_or_post_seal_mutated_plan_is_rejected(
    plan_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    plan_path = repo / "plans" / f"{plan_name}.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["mutated_after_seal"] = True
    _write_json(plan_path, plan)
    tools = _make_toolchain(tmp_path, {})
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match="content hash is invalid"):
        _build(repo, paper, tmp_path / "published")


def test_random_unsealed_plan_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    (repo / "plans" / "neural.json").write_text('{"random":"not a sealed plan"}\n', encoding="utf-8")
    tools = _make_toolchain(tmp_path, {})
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match="missing content_sha256"):
        _build(repo, paper, tmp_path / "published")


def test_plan_mutated_while_building_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    plan = repo / "plans" / "tree.json"
    tools = _make_toolchain(tmp_path, {"mutate_path": str(plan)})
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match="tree plan changed during build"):
        _build(repo, paper, tmp_path / "published")


def test_macro_swap_is_rejected_by_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    result = (paper / "result_macros_v5.tex").read_bytes()
    exported = (paper / "export_macros_v5.tex").read_bytes()
    (paper / "result_macros_v5.tex").write_bytes(exported)
    (paper / "export_macros_v5.tex").write_bytes(result)
    tools = _make_toolchain(tmp_path, {})
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match="provenance does not bind"):
        _build(repo, paper, tmp_path / "published")


@pytest.mark.parametrize(
    ("provenance_name", "field"),
    [
        ("result_macros_v5.provenance.json", "tree_plan_sha256"),
        ("export_macros_v5.provenance.json", "export_plan_sha256"),
    ],
)
def test_resealed_wrong_macro_provenance_cross_binding_is_rejected(
    provenance_name: str,
    field: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    path = paper / provenance_name
    provenance = json.loads(path.read_text(encoding="utf-8"))
    provenance.pop("content_sha256")
    provenance[field] = "f" * 64
    _write_json(path, _sealed(provenance))
    tools = _make_toolchain(tmp_path, {})
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match="provenance does not bind"):
        _build(repo, paper, tmp_path / "published")


def test_resealed_export_plan_and_provenance_cannot_break_neural_cross_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    export_plan_path = repo / "plans" / "export.json"
    export_plan = json.loads(export_plan_path.read_text(encoding="utf-8"))
    export_plan.pop("content_sha256")
    export_plan["source_plan_sha256"] = "f" * 64
    export_plan = _sealed(export_plan)
    _write_json(export_plan_path, export_plan)
    provenance_path = paper / "export_macros_v5.provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance.pop("content_sha256")
    provenance["export_plan_sha256"] = export_plan["content_sha256"]
    _write_json(provenance_path, _sealed(provenance))
    tools = _make_toolchain(tmp_path, {})
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match="Export plan is not cross-bound"):
        _build(repo, paper, tmp_path / "published")


def test_post_build_source_mutation_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    tools = _make_toolchain(tmp_path, {"mutate_path": str(paper / "main.tex")})
    monkeypatch.setenv("PATH", str(tools))
    output = tmp_path / "published"

    with pytest.raises(build_v5_paper.PaperBuildError, match="input changed during build"):
        _build(repo, paper, output)
    assert not output.exists()


def test_tex_cannot_mutate_a_staged_allowlisted_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    tools = _make_toolchain(tmp_path, {"mutate_staged": True})
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match="modified its sealed staged input"):
        _build(repo, paper, tmp_path / "published")


def test_undefined_citation_is_rejected_from_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    tools = _make_toolchain(
        tmp_path,
        {"log": "LaTeX Warning: Citation `missing' on page 1 undefined.\n"},
    )
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match="undefined citation"):
        _build(repo, paper, tmp_path / "published")


def test_wrapped_warning_in_final_transcript_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    tools = _make_toolchain(
        tmp_path,
        {"transcript": "LaTeX Warning: Citation\n`missing' on page 1\nundefined."},
    )
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match="undefined citation"):
        _build(repo, paper, tmp_path / "published")


@pytest.mark.parametrize(
    ("bad_log", "reason"),
    [
        ("LaTeX Warning: There were multiply-defined labels.\n", "multiply-defined label"),
        ("LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.\n", "rerun required"),
        ("! Undefined control sequence.\n", "undefined control sequence"),
    ],
)
def test_other_non_converged_or_fatal_logs_are_rejected(
    bad_log: str,
    reason: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    tools = _make_toolchain(tmp_path, {"log": bad_log})
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match=reason):
        _build(repo, paper, tmp_path / "published")


def test_unexpected_live_repository_input_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    unexpected = repo / "secret.tex"
    unexpected.write_text("must not be an implicit paper input\n", encoding="utf-8")
    tools = _make_toolchain(tmp_path, {"extra_input": str(unexpected)})
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match="live repository input"):
        _build(repo, paper, tmp_path / "published")


@pytest.mark.parametrize(
    "bad_blg",
    [
        "The style file: IEEEtran.bst\nDatabase file #1: references.bib\nDatabase file #2: extra.bib\n",
        "The style file: plain.bst\nDatabase file #1: references.bib\n",
    ],
)
def test_extra_bibliography_database_or_wrong_style_is_rejected(
    bad_blg: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    tools = _make_toolchain(tmp_path, {"blg": bad_blg})
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match="BibTeX must use exactly"):
        _build(repo, paper, tmp_path / "published")


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"non_pdf": True}, "PDF magic header"),
        ({"missing_pdf_eof": True}, "PDF EOF marker"),
    ],
)
def test_malformed_pdf_bytes_are_rejected_before_pdfinfo(
    config: dict,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    tools = _make_toolchain(tmp_path, config)
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match=message):
        _build(repo, paper, tmp_path / "published")


def test_caller_supplied_paper_directory_symlink_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    paper_link = repo / "paper-link"
    paper_link.symlink_to(paper, target_is_directory=True)
    tools = _make_toolchain(tmp_path, {})
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match="Paper directory cannot be a symlink"):
        _build(repo, paper_link, tmp_path / "published")


def test_atomic_publish_rejects_racing_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    tools = _make_toolchain(tmp_path, {})
    monkeypatch.setenv("PATH", str(tools))
    output = tmp_path / "published"
    real_publish = build_v5_paper._publish_noreplace

    def race(staging: Path, target: Path) -> None:
        target.mkdir()
        (target / "racer.txt").write_text("owned by racing publisher\n", encoding="utf-8")
        real_publish(staging, target)

    monkeypatch.setattr(build_v5_paper, "_publish_noreplace", race)
    with pytest.raises(build_v5_paper.PaperBuildError, match="appeared during atomic publication"):
        _build(repo, paper, output)
    assert (output / "racer.txt").read_text(encoding="utf-8") == "owned by racing publisher\n"


def test_output_directory_symlink_is_rejected_before_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    output = tmp_path / "published"
    output.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    tools = _make_toolchain(tmp_path, {})
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match="Output directory cannot be a symlink"):
        _build(repo, paper, output)


def test_extra_staged_file_is_rejected_by_exact_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    tools = _make_toolchain(tmp_path, {})
    monkeypatch.setenv("PATH", str(tools))
    real_verify = build_v5_paper._verify_staged_manifest

    def inject(staging: Path, evidence: dict) -> None:
        (staging / "unmanifested.txt").write_text("injected\n", encoding="utf-8")
        real_verify(staging, evidence)

    monkeypatch.setattr(build_v5_paper, "_verify_staged_manifest", inject)
    with pytest.raises(build_v5_paper.PaperBuildError, match="inventory differs"):
        _build(repo, paper, tmp_path / "published")


@pytest.mark.parametrize(
    "legacy_text",
    [
        "Sub-Millijoule Intrusion Detection on a Commodity MCU",
        "QCFS and ReLU are statistically indistinguishable on all four datasets",
        "On-board inference is 0.28–0.58 ms and 44–69 µJ",
    ],
)
def test_forbidden_legacy_pdf_claim_is_rejected(
    legacy_text: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    paper = _make_repository(repo)
    tools = _make_toolchain(tmp_path, {"text": legacy_text})
    monkeypatch.setenv("PATH", str(tools))

    with pytest.raises(build_v5_paper.PaperBuildError, match="PDF contains"):
        _build(repo, paper, tmp_path / "published")
