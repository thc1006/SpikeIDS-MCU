#!/usr/bin/env python3
"""Build the v5 paper twice from sealed inputs and reject stale/non-reproducible PDFs."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any


TEX_SOURCE_ALLOWLIST = (
    "main.tex",
    "references.bib",
    "result_macros_v5.tex",
    "export_macros_v5.tex",
)
PROVENANCE_ALLOWLIST = (
    "result_macros_v5.provenance.json",
    "export_macros_v5.provenance.json",
)
PAPER_INPUT_ALLOWLIST = TEX_SOURCE_ALLOWLIST + PROVENANCE_ALLOWLIST
REQUIRED_FLS_SOURCES = {
    "main.tex",
    "result_macros_v5.tex",
    "export_macros_v5.tex",
}
GENERATED_INPUTS = {
    "main.aux",
    "main.bbl",
    "main.bcf",
    "main.lof",
    "main.lot",
    "main.out",
    "main.run.xml",
    "main.toc",
}
TOOL_VERSION_ARGS = {
    "latexmk": ("--version",),
    "pdflatex": ("--version",),
    "bibtex": ("--version",),
    "kpsewhich": ("--version",),
    "pdfinfo": ("-v",),
    "pdftotext": ("-v",),
}
SYSTEM_TEX_ROOTS = tuple(
    Path(path).resolve()
    for path in (
        "/etc/texmf",
        "/usr/share/texlive",
        "/usr/share/texmf",
        "/var/lib/texmf",
    )
    if Path(path).exists()
)
LOG_FAILURE_PATTERNS = (
    ("undefined citation", re.compile(r"citation[\s\S]{0,500}?undefined", re.IGNORECASE)),
    ("undefined reference", re.compile(r"reference[\s\S]{0,500}?undefined", re.IGNORECASE)),
    ("undefined references", re.compile(r"there\s+were\s+undefined\s+(?:references|citations)", re.IGNORECASE)),
    ("multiply-defined label", re.compile(r"(?:multiply[-\s]+defined[\s\S]{0,200}?labels?|labels?[\s\S]{0,200}?multiply\s+defined)", re.IGNORECASE)),
    ("rerun required", re.compile(r"rerun\s+to\s+get\s+cross-references\s+right|label\(s\)\s+may\s+have\s+changed|please\s+(?:re)?run\s+(?:latex|bibtex)|rerunfilecheck\s+warning:[\s\S]{0,500}?has\s+changed", re.IGNORECASE)),
    ("undefined control sequence", re.compile(r"undefined\s+control\s+sequence", re.IGNORECASE)),
    ("TeX error", re.compile(r"(?:^|\n)!\s+.+|latex\s+error:|package\s+.+?\s+error:|emergency\s+stop|fatal\s+error\s+occurred|no\s+pages\s+of\s+output", re.IGNORECASE)),
    ("missing bibliography entry", re.compile(r"warning--i\s+didn't\s+find\s+a\s+database\s+entry|i\s+found\s+no\s+\\citation\s+commands", re.IGNORECASE)),
)
FORBIDDEN_LEGACY_PATTERNS = (
    ("legacy title", re.compile(r"sub\s*[-\u2013\u2014]?\s*millijoule\s+intrusion\s+detection", re.IGNORECASE)),
    ("unverified STM32N6570 deployment", re.compile(r"stm32n6570(?:-dk)?", re.IGNORECASE)),
    ("legacy all-four indistinguishability", re.compile(r"statistically\s+indistinguishable\s+on\s+all\s+four\s+datasets", re.IGNORECASE)),
    ("legacy latency range", re.compile(r"0[.]28\s*(?:[-\u2013\u2014]|to)\s*0[.]58\s*ms", re.IGNORECASE)),
    ("legacy energy range", re.compile(r"44\s*(?:[-\u2013\u2014]|to)\s*69\s*(?:u|\u00b5|\u03bc)j", re.IGNORECASE)),
    ("legacy T=1 equivalence", re.compile(r"practical\s+t\s*=\s*1\s+(?:near[- ]?)?equivalence", re.IGNORECASE)),
)


class PaperBuildError(RuntimeError):
    """The paper build or one of its evidence gates failed closed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PaperBuildError(message)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    _require("content_sha256" not in payload, "Evidence payload is already sealed")
    return {**payload, "content_sha256": _sha256_bytes(_json_bytes(payload))}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise PaperBuildError(f"Non-finite JSON constant in {label}: {value}")

    try:
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PaperBuildError(f"Invalid JSON in {label}: {exc}") from exc
    _require(isinstance(value, dict), f"JSON root must be an object: {label}")
    return value


def _check_seal(value: dict[str, Any], label: str) -> str:
    content_sha256 = value.get("content_sha256")
    if not isinstance(content_sha256, str):
        raise PaperBuildError(f"Sealed JSON is missing content_sha256: {label}")
    body = {key: item for key, item in value.items() if key != "content_sha256"}
    _require(
        content_sha256 == _sha256_bytes(_json_bytes(body)),
        f"Sealed JSON content hash is invalid: {label}",
    )
    return content_sha256


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _snapshot_sources(
    repo_root: Path,
    paper_dir: Path,
) -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    _require(paper_dir.is_dir() and not paper_dir.is_symlink(), f"Paper directory is invalid: {paper_dir}")
    _require(_under(paper_dir, repo_root), "Paper directory must be inside the declared repository")
    content: dict[str, bytes] = {}
    inventory: dict[str, dict[str, Any]] = {}
    for name in PAPER_INPUT_ALLOWLIST:
        path = paper_dir / name
        _require(path.is_file() and not path.is_symlink(), f"Missing or symlinked paper input: {path}")
        data = path.read_bytes()
        _require(bool(data), f"Paper input is empty: {path}")
        content[name] = data
        inventory[name] = {
            "path": path.relative_to(repo_root).as_posix(),
            "sha256": _sha256_bytes(data),
            "size_bytes": len(data),
        }
    return content, inventory


def _snapshot_plan(path: Path, label: str) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    requested = path.absolute()
    _require(not requested.is_symlink(), f"{label} plan path cannot be a symlink: {requested}")
    resolved = requested.resolve(strict=False)
    _require(resolved.is_file() and not resolved.is_symlink(), f"{label} plan is not a regular file: {resolved}")
    data = resolved.read_bytes()
    value = _parse_json_bytes(data, f"{label} plan")
    content_sha256 = _check_seal(value, f"{label} plan")
    record = {
        "source_path": str(resolved),
        "sha256": _sha256_bytes(data),
        "size_bytes": len(data),
        "content_sha256": content_sha256,
    }
    return data, value, record


def _validate_provenance(
    paper_bytes: dict[str, bytes],
    plans: dict[str, dict[str, Any]],
    plan_inventory: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result = _parse_json_bytes(
        paper_bytes["result_macros_v5.provenance.json"],
        "result macro provenance",
    )
    export = _parse_json_bytes(
        paper_bytes["export_macros_v5.provenance.json"],
        "export macro provenance",
    )
    result_seal = _check_seal(result, "result macro provenance")
    export_seal = _check_seal(export, "export macro provenance")
    neural_sha = plan_inventory["neural"]["content_sha256"]
    tree_sha = plan_inventory["tree"]["content_sha256"]
    export_sha = plan_inventory["export"]["content_sha256"]
    _require(
        plans["neural"].get("protocol_role") == "planned_benchmark",
        "Neural plan is not a formal planned_benchmark",
    )
    _require(
        plans["tree"].get("kind") == "tree_baseline_plan",
        "Tree plan has the wrong protocol kind",
    )
    _require(
        plans["export"].get("kind") == "spikeids_v5_export_plan",
        "Export plan has the wrong protocol kind",
    )
    _require(
        result.get("plan_sha256") == neural_sha
        and result.get("tree_plan_sha256") == tree_sha
        and result.get("macro_sha256")
        == _sha256_bytes(paper_bytes["result_macros_v5.tex"]),
        "Result macro provenance does not bind the staged macro and neural/tree plans",
    )
    _require(
        export.get("kind") == "spikeids_v5_export_paper_macros"
        and export.get("plan_sha256") == neural_sha
        and export.get("export_plan_sha256") == export_sha
        and export.get("macro_sha256")
        == _sha256_bytes(paper_bytes["export_macros_v5.tex"]),
        "Export macro provenance does not bind the staged macro and neural/export plans",
    )
    _require(
        plans["export"].get("source_plan_sha256") == neural_sha,
        "Export plan is not cross-bound to the neural plan",
    )
    return {
        "result": {"content_sha256": result_seal},
        "export": {"content_sha256": export_seal},
    }


def _minimal_env(path_value: str, source_date_epoch: int, build_dir: Path | None = None) -> dict[str, str]:
    environment = {
        "PATH": path_value,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "SOURCE_DATE_EPOCH": str(source_date_epoch),
        "FORCE_SOURCE_DATE": "1",
        "openin_any": "p",
        "openout_any": "p",
        "shell_escape": "0",
    }
    if build_dir is not None:
        home = build_dir / ".home"
        temporary = build_dir / ".tmp"
        texmf_home = build_dir / ".texmf-home"
        texmf_config = build_dir / ".texmf-config"
        texmf_var = build_dir / ".texmf-var"
        for directory in (home, temporary, texmf_home, texmf_config, texmf_var):
            directory.mkdir()
        environment.update({
            "HOME": str(home),
            "TMPDIR": str(temporary),
            "TEXMFHOME": str(texmf_home),
            "TEXMFCONFIG": str(texmf_config),
            "TEXMFVAR": str(texmf_var),
        })
    return environment


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PaperBuildError(f"Command could not complete: {command[0]}: {exc}") from exc


def _discover_tools(timeout_seconds: int) -> tuple[dict[str, dict[str, Any]], str]:
    resolved: dict[str, Path] = {}
    for name in TOOL_VERSION_ARGS:
        candidate = shutil.which(name)
        if candidate is None:
            raise PaperBuildError(f"Required paper tool is unavailable: {name}")
        path = Path(candidate).resolve()
        _require(path.is_file(), f"Resolved paper tool is not a file: {path}")
        resolved[name] = path
    path_parts = list(dict.fromkeys(str(path.parent) for path in resolved.values()))
    for fallback in ("/usr/bin", "/bin"):
        if Path(fallback).is_dir() and fallback not in path_parts:
            path_parts.append(fallback)
    path_value = os.pathsep.join(path_parts)
    environment = _minimal_env(path_value, 0)
    inventory: dict[str, dict[str, Any]] = {}
    for name, arguments in TOOL_VERSION_ARGS.items():
        result = _run(
            [str(resolved[name]), *arguments],
            cwd=resolved[name].parent,
            env=environment,
            timeout_seconds=min(timeout_seconds, 30),
        )
        combined = result.stdout + result.stderr
        _require(result.returncode == 0 and bool(combined.strip()), f"Could not identify paper tool: {name}")
        inventory[name] = {
            "path": str(resolved[name]),
            "sha256": _sha256_file(resolved[name]),
            "version": combined.decode("utf-8", errors="strict").strip(),
            "version_sha256": _sha256_bytes(combined),
        }
    return inventory, path_value


def _lint_logs(named_logs: dict[str, bytes]) -> None:
    decoded: list[str] = []
    for name, data in named_logs.items():
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise PaperBuildError(f"Non-UTF-8 build log: {name}") from exc
        if name == "latexmk transcript":
            markers = list(
                re.finditer(
                    r"(?m)^Run\s+number\s+\d+\s+of\s+rule\s+'pdflatex'",
                    text,
                )
            )
            if markers:
                text = text[markers[-1].start():]
        decoded.append(f"[{name}]\n{text}")
    combined = "\n".join(decoded)
    for description, pattern in LOG_FAILURE_PATTERNS:
        match = pattern.search(combined)
        _require(match is None, f"Paper log gate found {description}: {match.group(0) if match else ''}")


def _normal_input_id(path: Path, build_dir: Path) -> str:
    if _under(path, build_dir):
        relative = path.relative_to(build_dir).as_posix()
        if relative in TEX_SOURCE_ALLOWLIST:
            return f"source/{relative}"
        _require(relative in GENERATED_INPUTS, f"Unexpected build-local TeX input: {relative}")
        return f"generated/{relative}"
    for root in SYSTEM_TEX_ROOTS:
        if _under(path, root):
            return f"system/{path.as_posix()}"
    raise PaperBuildError(f"Unexpected external TeX input outside trusted TeX roots: {path}")


def _fls_inventory(fls: bytes, build_dir: Path, repo_root: Path) -> list[dict[str, Any]]:
    text = fls.decode("utf-8", errors="strict")
    pwd_rows = [Path(line[4:].strip()).resolve() for line in text.splitlines() if line.startswith("PWD ")]
    _require(bool(pwd_rows) and all(path == build_dir for path in pwd_rows), "Recorder PWD does not match isolated build directory")
    inventory: dict[str, dict[str, Any]] = {}
    staged_sources: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("INPUT "):
            continue
        raw = line[6:].strip().strip('"')
        _require(bool(raw), "Recorder contains an empty INPUT row")
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = build_dir / candidate
        path = candidate.resolve()
        _require(not _under(path, repo_root), f"Recorder read a live repository input instead of its sealed snapshot: {path}")
        _require(path.is_file(), f"Recorder input is missing after build: {path}")
        identifier = _normal_input_id(path, build_dir)
        digest = _sha256_file(path)
        previous = inventory.get(identifier)
        _require(previous is None or previous["sha256"] == digest, f"Recorder identity collision: {identifier}")
        inventory[identifier] = {
            "id": identifier,
            "sha256": digest,
            "size_bytes": path.stat().st_size,
        }
        if identifier.startswith("source/"):
            staged_sources.add(identifier.removeprefix("source/"))
    missing = REQUIRED_FLS_SOURCES - staged_sources
    _require(not missing, f"Recorder omitted required staged inputs: {sorted(missing)}")
    _require(bool(inventory), "Recorder contains no TeX inputs")
    return [inventory[key] for key in sorted(inventory)]


def _parse_pdfinfo(raw: bytes) -> dict[str, str]:
    text = raw.decode("utf-8", errors="strict")
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        _require(key not in fields, f"pdfinfo emitted duplicate field: {key}")
        fields[key] = value.strip()
    _require(fields.get("Pages", "").isdigit() and int(fields["Pages"]) > 0, "PDF has no positive page count")
    _require(fields.get("Encrypted", "").casefold() == "no", "PDF must not be encrypted")
    _require(bool(fields.get("PDF version")), "PDF version is absent")
    if "JavaScript" in fields:
        _require(fields["JavaScript"].casefold() == "no", "PDF contains JavaScript")
    return fields


def _lint_pdf_text(text_bytes: bytes, pdfinfo_bytes: bytes) -> None:
    text = text_bytes.decode("utf-8", errors="strict")
    _require(bool(text.strip()), "pdftotext produced empty manuscript text")
    normalized = unicodedata.normalize("NFKC", text + "\n" + pdfinfo_bytes.decode("utf-8", errors="strict"))
    for description, pattern in FORBIDDEN_LEGACY_PATTERNS:
        match = pattern.search(normalized)
        _require(match is None, f"PDF contains {description}: {match.group(0) if match else ''}")


def _validate_pdf_bytes(data: bytes) -> None:
    _require(data.startswith(b"%PDF-"), "latexmk output lacks the PDF magic header")
    _require(
        re.search(br"%%EOF[\x00\x09\x0a\x0c\x0d\x20]*\Z", data) is not None,
        "latexmk output lacks a terminal PDF EOF marker",
    )


def _bibliography_inventory(
    *,
    blg: bytes,
    build_dir: Path,
    repo_root: Path,
    tools: dict[str, dict[str, Any]],
    environment: dict[str, str],
    timeout_seconds: int,
) -> dict[str, dict[str, Any]]:
    try:
        text = blg.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PaperBuildError("BibTeX log is not strict UTF-8") from exc
    databases = re.findall(r"(?m)^Database\s+file\s+#\d+:\s*(\S+)\s*$", text)
    styles = re.findall(r"(?m)^The\s+style\s+file:\s*(\S+)\s*$", text)
    _require(
        databases == ["references.bib"],
        f"BibTeX must use exactly references.bib, observed: {databases}",
    )
    _require(
        styles == ["IEEEtran.bst"],
        f"BibTeX must use exactly IEEEtran.bst, observed: {styles}",
    )
    lookup = _run(
        [tools["kpsewhich"]["path"], "IEEEtran.bst"],
        cwd=build_dir,
        env=environment,
        timeout_seconds=min(timeout_seconds, 60),
    )
    _require(lookup.returncode == 0 and not lookup.stderr, "kpsewhich failed to resolve IEEEtran.bst cleanly")
    try:
        rows = [line for line in lookup.stdout.decode("utf-8", errors="strict").splitlines() if line]
    except UnicodeDecodeError as exc:
        raise PaperBuildError("kpsewhich emitted non-UTF-8 output") from exc
    _require(len(rows) == 1, f"kpsewhich returned an ambiguous IEEEtran.bst inventory: {rows}")
    style = Path(rows[0])
    if not style.is_absolute():
        style = build_dir / style
    style = style.resolve()
    _require(style.is_file(), f"Resolved IEEEtran.bst is missing: {style}")
    _require(not _under(style, repo_root) and not _under(style, build_dir), "IEEEtran.bst must not come from the repository/build directory")
    trusted_roots = SYSTEM_TEX_ROOTS + (Path(tools["kpsewhich"]["path"]).parent.resolve(),)
    _require(
        any(_under(style, root) for root in trusted_roots),
        f"IEEEtran.bst is outside the trusted TeX/tool roots: {style}",
    )
    references = build_dir / "references.bib"
    auxiliary = build_dir / "main.aux"
    return {
        "main.aux": {
            "id": "generated/main.aux",
            "sha256": _sha256_file(auxiliary),
            "size_bytes": auxiliary.stat().st_size,
        },
        "references.bib": {
            "id": "source/references.bib",
            "sha256": _sha256_file(references),
            "size_bytes": references.stat().st_size,
        },
        "IEEEtran.bst": {
            "id": f"system/{style.as_posix()}",
            "path": str(style),
            "sha256": _sha256_file(style),
            "size_bytes": style.stat().st_size,
        },
    }


def _build_once(
    *,
    index: int,
    build_dir: Path,
    repo_root: Path,
    source_bytes: dict[str, bytes],
    tools: dict[str, dict[str, Any]],
    path_value: str,
    source_date_epoch: int,
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    build_dir.mkdir()
    for name, data in source_bytes.items():
        (build_dir / name).write_bytes(data)
    environment = _minimal_env(path_value, source_date_epoch, build_dir)
    tool_bin = build_dir / ".tool-bin"
    tool_bin.mkdir()
    for name, record in tools.items():
        (tool_bin / name).symlink_to(record["path"])
    environment["PATH"] = os.pathsep.join((str(tool_bin), path_value))
    command = [
        tools["latexmk"]["path"],
        "-norc",
        "-pdf",
        "-g",
        "-recorder",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "-pdflatex=pdflatex %O -no-shell-escape %S",
        "main.tex",
    ]
    latexmk = _run(command, cwd=build_dir, env=environment, timeout_seconds=timeout_seconds)
    transcript = latexmk.stdout + b"\n[stderr]\n" + latexmk.stderr
    _require(latexmk.returncode == 0, f"latexmk fresh build {index} failed with exit {latexmk.returncode}")

    required = ("main.pdf", "main.log", "main.fls", "main.blg", "main.aux", "main.bbl")
    for name in required:
        path = build_dir / name
        _require(path.is_file() and not path.is_symlink() and path.stat().st_size > 0, f"Fresh build {index} omitted {name}")
    raw = {name: (build_dir / name).read_bytes() for name in required}
    raw["latexmk.transcript"] = transcript
    _validate_pdf_bytes(raw["main.pdf"])
    for name, expected in source_bytes.items():
        _require(
            (build_dir / name).read_bytes() == expected,
            f"Fresh build {index} modified its sealed staged input: {name}",
        )
    _lint_logs({
        "main.log": raw["main.log"],
        "main.blg": raw["main.blg"],
        "latexmk transcript": transcript,
    })
    bibliography_inputs = _bibliography_inventory(
        blg=raw["main.blg"],
        build_dir=build_dir,
        repo_root=repo_root,
        tools=tools,
        environment=environment,
        timeout_seconds=timeout_seconds,
    )
    fls_inputs = _fls_inventory(raw["main.fls"], build_dir, repo_root)

    pdfinfo_result = _run(
        [tools["pdfinfo"]["path"], "-isodates", "main.pdf"],
        cwd=build_dir,
        env=environment,
        timeout_seconds=min(timeout_seconds, 60),
    )
    _require(
        pdfinfo_result.returncode == 0 and not pdfinfo_result.stderr,
        f"pdfinfo failed or emitted diagnostics for fresh build {index}",
    )
    pdfinfo_raw = pdfinfo_result.stdout
    pdfinfo_fields = _parse_pdfinfo(pdfinfo_raw)
    text_result = _run(
        [tools["pdftotext"]["path"], "-enc", "UTF-8", "-layout", "main.pdf", "-"],
        cwd=build_dir,
        env=environment,
        timeout_seconds=min(timeout_seconds, 60),
    )
    _require(
        text_result.returncode == 0 and not text_result.stderr,
        f"pdftotext failed or emitted diagnostics for fresh build {index}",
    )
    text_raw = text_result.stdout
    _lint_pdf_text(text_raw, pdfinfo_raw)
    raw["main.txt"] = text_raw
    raw["pdfinfo.txt"] = pdfinfo_raw

    record = {
        "build_index": index,
        "command": [
            "latexmk", "-norc", "-pdf", "-g", "-recorder",
            "-interaction=nonstopmode", "-halt-on-error", "-file-line-error",
            "-pdflatex=pdflatex %O -no-shell-escape %S", "main.tex",
        ],
        "environment": {
            key: environment[key]
            for key in ("SOURCE_DATE_EPOCH", "FORCE_SOURCE_DATE", "TZ", "LANG", "LC_ALL", "openin_any", "openout_any", "shell_escape")
        },
        "artifacts": {
            name: {"sha256": _sha256_bytes(data), "size_bytes": len(data)}
            for name, data in sorted(raw.items())
        },
        "fls_inputs": fls_inputs,
        "fls_input_inventory_sha256": _sha256_bytes(_json_bytes(fls_inputs)),
        "bibliography_inputs": bibliography_inputs,
        "bibliography_input_inventory_sha256": _sha256_bytes(
            _json_bytes(bibliography_inputs)
        ),
        "pdfinfo_fields": pdfinfo_fields,
    }
    return record, raw


def _assert_sources_unchanged(
    repo_root: Path,
    paper_dir: Path,
    expected: dict[str, dict[str, Any]],
) -> None:
    for name, record in expected.items():
        path = paper_dir / name
        _require(path.is_file() and not path.is_symlink(), f"Paper input disappeared during build: {name}")
        _require(
            _sha256_file(path) == record["sha256"] and path.stat().st_size == record["size_bytes"],
            f"Paper input changed during build: {path.relative_to(repo_root)}",
        )


def _assert_tools_unchanged(tools: dict[str, dict[str, Any]]) -> None:
    for name, record in tools.items():
        path = Path(record["path"])
        _require(path.is_file(), f"Paper tool disappeared during build: {name}")
        _require(_sha256_file(path) == record["sha256"], f"Paper tool changed during build: {name}")


def _assert_plans_unchanged(plan_inventory: dict[str, dict[str, Any]]) -> None:
    for name, record in plan_inventory.items():
        path = Path(record["source_path"])
        _require(
            path.is_file() and not path.is_symlink(),
            f"{name} plan disappeared or became a symlink during build",
        )
        _require(
            _sha256_file(path) == record["sha256"]
            and path.stat().st_size == record["size_bytes"],
            f"{name} plan changed during build",
        )


def _assert_bibliography_style_unchanged(build_record: dict[str, Any]) -> None:
    record = build_record["bibliography_inputs"]["IEEEtran.bst"]
    path = Path(record["path"])
    _require(
        path.is_file()
        and _sha256_file(path) == record["sha256"]
        and path.stat().st_size == record["size_bytes"],
        "IEEEtran.bst changed after the recorded build",
    )


def _publish_noreplace(staging: Path, output_dir: Path) -> None:
    """Atomically publish a directory without replacing a racing target."""
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as exc:
        raise PaperBuildError("Atomic no-replace directory publication is unavailable") from exc
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(staging),
        -100,
        os.fsencode(output_dir),
        1,
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in (errno.EEXIST, errno.ENOTEMPTY):
        raise PaperBuildError(f"Output directory appeared during atomic publication: {output_dir}")
    raise PaperBuildError(f"Atomic paper publication failed: {os.strerror(error)}")


def _verify_staged_manifest(
    staging: Path,
    evidence: dict[str, Any],
) -> None:
    expected = set(evidence["publication_manifest"]["exact_inventory"])
    actual = {
        path.relative_to(staging).as_posix()
        for path in staging.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    _require(actual == expected, f"Published evidence inventory differs: expected={sorted(expected)}, actual={sorted(actual)}")
    _require(not any(path.is_symlink() for path in staging.rglob("*")), "Published evidence contains a symlink")
    expected_directories = set(evidence["publication_manifest"]["exact_directories"])
    actual_directories = {
        path.relative_to(staging).as_posix()
        for path in staging.rglob("*")
        if path.is_dir() and not path.is_symlink()
    }
    _require(
        actual_directories == expected_directories,
        f"Published evidence directory inventory differs: expected={sorted(expected_directories)}, actual={sorted(actual_directories)}",
    )
    for relative, record in evidence["publication_manifest"]["hashed_files"].items():
        path = staging / relative
        _require(
            path.is_file()
            and _sha256_file(path) == record["sha256"]
            and path.stat().st_size == record["size_bytes"],
            f"Published evidence file differs from its manifest: {relative}",
        )
    stored = _parse_json_bytes((staging / "paper_build.json").read_bytes(), "paper build evidence")
    _check_seal(stored, "paper build evidence")
    _require(stored == evidence, "Written paper build evidence differs from the in-memory seal")


def build_paper(
    *,
    repo_root: Path,
    paper_dir: Path,
    output_dir: Path,
    plan_paths: dict[str, Path],
    source_date_epoch: int = 946684800,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Run two isolated builds and atomically publish only reproducible evidence."""
    repo_root = repo_root.resolve()
    requested_paper_dir = paper_dir.absolute()
    _require(
        not requested_paper_dir.is_symlink(),
        f"Paper directory cannot be a symlink: {requested_paper_dir}",
    )
    paper_dir = requested_paper_dir.resolve()
    requested_output_dir = output_dir.absolute()
    _require(not requested_output_dir.is_symlink(), f"Output directory cannot be a symlink: {requested_output_dir}")
    output_dir = requested_output_dir.resolve(strict=False)
    _require(repo_root.is_dir(), f"Repository root is invalid: {repo_root}")
    _require(output_dir != paper_dir, "Output directory cannot replace the paper source directory")
    _require(not output_dir.exists() and not output_dir.is_symlink(), f"Output directory already exists: {output_dir}")
    _require(
        type(source_date_epoch) is int and 0 <= source_date_epoch <= 253402300799,
        "SOURCE_DATE_EPOCH must be a non-negative integral Unix timestamp",
    )
    _require(type(timeout_seconds) is int and timeout_seconds > 0, "Timeout must be a positive integer")
    expected_plan_keys = {"neural", "tree", "export"}
    _require(set(plan_paths) == expected_plan_keys, f"Plan paths must be exactly {sorted(expected_plan_keys)}")

    paper_bytes, source_inventory = _snapshot_sources(repo_root, paper_dir)
    plan_bytes: dict[str, bytes] = {}
    plans: dict[str, dict[str, Any]] = {}
    plan_inventory: dict[str, dict[str, Any]] = {}
    for name in sorted(expected_plan_keys):
        data, plan, record = _snapshot_plan(plan_paths[name], name)
        plan_bytes[name] = data
        plans[name] = plan
        plan_inventory[name] = record
    _require(
        len({record["content_sha256"] for record in plan_inventory.values()}) == 3,
        "Neural, tree, and export plans must have distinct content identities",
    )
    provenance = _validate_provenance(paper_bytes, plans, plan_inventory)
    tex_source_bytes = {name: paper_bytes[name] for name in TEX_SOURCE_ALLOWLIST}
    tools, path_value = _discover_tools(timeout_seconds)
    builder_path = Path(__file__).resolve()
    builder = {
        "path": builder_path.relative_to(repo_root).as_posix() if _under(builder_path, repo_root) else str(builder_path),
        "sha256": _sha256_file(builder_path),
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent))
    try:
        with tempfile.TemporaryDirectory(prefix="spikeids-v5-paper-") as temporary:
            temporary_root = Path(temporary).resolve()
            _require(not _under(temporary_root, repo_root), "Isolated TeX builds must be outside the repository")
            first, first_raw = _build_once(
                index=1,
                build_dir=temporary_root / "build-1",
                repo_root=repo_root,
                source_bytes=tex_source_bytes,
                tools=tools,
                path_value=path_value,
                source_date_epoch=source_date_epoch,
                timeout_seconds=timeout_seconds,
            )
            second, second_raw = _build_once(
                index=2,
                build_dir=temporary_root / "build-2",
                repo_root=repo_root,
                source_bytes=tex_source_bytes,
                tools=tools,
                path_value=path_value,
                source_date_epoch=source_date_epoch,
                timeout_seconds=timeout_seconds,
            )
            _assert_sources_unchanged(repo_root, paper_dir, source_inventory)
            _assert_plans_unchanged(plan_inventory)
            _assert_tools_unchanged(tools)
            _assert_bibliography_style_unchanged(first)
            _assert_bibliography_style_unchanged(second)
            _require(_sha256_file(builder_path) == builder["sha256"], "Paper builder changed during execution")
            _require(
                first["artifacts"]["main.pdf"]["sha256"] == second["artifacts"]["main.pdf"]["sha256"],
                "Two isolated fresh builds produced different PDF SHA-256 digests",
            )
            _require(first_raw["main.pdf"] == second_raw["main.pdf"], "Two isolated fresh builds produced different PDF bytes")
            _require(first_raw["main.txt"] == second_raw["main.txt"], "Two isolated fresh builds produced different extracted text")
            _require(first_raw["main.aux"] == second_raw["main.aux"], "Two isolated fresh builds produced different final AUX bytes")
            _require(first_raw["main.bbl"] == second_raw["main.bbl"], "Two isolated fresh builds produced different final BBL bytes")
            _require(
                first["fls_input_inventory_sha256"] == second["fls_input_inventory_sha256"],
                "Two isolated builds used different normalized TeX input inventories",
            )
            _require(
                first["bibliography_input_inventory_sha256"]
                == second["bibliography_input_inventory_sha256"],
                "Two isolated builds used different bibliography inputs",
            )

            (staging / "main.pdf").write_bytes(first_raw["main.pdf"])
            (staging / "main.txt").write_bytes(first_raw["main.txt"])
            (staging / "pdfinfo.txt").write_bytes(first_raw["pdfinfo.txt"])
            (staging / "main.aux").write_bytes(first_raw["main.aux"])
            (staging / "main.bbl").write_bytes(first_raw["main.bbl"])
            for index, raw in ((1, first_raw), (2, second_raw)):
                build_evidence = staging / f"build-{index}"
                build_evidence.mkdir()
                for name in (
                    "main.log",
                    "main.blg",
                    "main.fls",
                    "main.aux",
                    "main.bbl",
                    "latexmk.transcript",
                ):
                    (build_evidence / name).write_bytes(raw[name])
            paper_inputs = staging / "inputs" / "paper"
            paper_inputs.mkdir(parents=True)
            for name, data in paper_bytes.items():
                (paper_inputs / name).write_bytes(data)
            plan_inputs = staging / "inputs" / "plans"
            plan_inputs.mkdir()
            for name, data in plan_bytes.items():
                (plan_inputs / f"{name}_plan.json").write_bytes(data)

        _assert_sources_unchanged(repo_root, paper_dir, source_inventory)
        _assert_plans_unchanged(plan_inventory)
        _assert_tools_unchanged(tools)
        _assert_bibliography_style_unchanged(first)
        _assert_bibliography_style_unchanged(second)
        _require(_sha256_file(builder_path) == builder["sha256"], "Paper builder changed during execution")
        hashed_files = {
            path.relative_to(staging).as_posix(): {
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(staging.rglob("*"))
            if path.is_file()
        }
        payload = {
            "schema_version": 2,
            "kind": "spikeids_v5_deterministic_fresh_paper_build",
            "status": "passed",
            "plan_bindings": {
                f"{name}_plan_sha256": plan_inventory[name]["content_sha256"]
                for name in sorted(plan_inventory)
            },
            "source_date_epoch": source_date_epoch,
            "paper_input_allowlist": list(PAPER_INPUT_ALLOWLIST),
            "paper_inputs": source_inventory,
            "plans": plan_inventory,
            "macro_provenance": provenance,
            "builder": builder,
            "tools": tools,
            "builds": [first, second],
            "reproducibility": {
                "isolated_fresh_builds": 2,
                "pdf_bytes_identical": True,
                "pdf_sha256": first["artifacts"]["main.pdf"]["sha256"],
                "text_bytes_identical": True,
                "text_sha256": first["artifacts"]["main.txt"]["sha256"],
                "aux_bytes_identical": True,
                "aux_sha256": first["artifacts"]["main.aux"]["sha256"],
                "bbl_bytes_identical": True,
                "bbl_sha256": first["artifacts"]["main.bbl"]["sha256"],
                "normalized_fls_inputs_identical": True,
                "normalized_fls_inputs_sha256": first["fls_input_inventory_sha256"],
            },
            "evidence_boundary": {
                "establishes": [
                    "byte identity and provenance cross-binding of staged paper inputs",
                    "two-build PDF reproducibility on the recorded local toolchain",
                    "absence of the enumerated build-log and legacy-text failures",
                ],
                "does_not_establish": [
                    "independent recomputation of generated macro numeric values",
                    "truth or completeness of natural-language or scientific claims",
                    "physical deployment, NPU mapping, latency, or energy validation",
                ],
            },
            "publication_manifest": {
                "semantics": "hashed_files plus self-sealed paper_build.json and exact_directories are the complete inventory; no extras or symlinks are permitted",
                "hashed_files": hashed_files,
                "self_sealed_file": "paper_build.json",
                "exact_inventory": sorted([*hashed_files, "paper_build.json"]),
                "exact_directories": sorted(
                    path.relative_to(staging).as_posix()
                    for path in staging.rglob("*")
                    if path.is_dir() and not path.is_symlink()
                ),
            },
        }
        evidence = _seal(payload)
        evidence_path = staging / "paper_build.json"
        evidence_path.write_bytes(json.dumps(evidence, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n")
        _verify_staged_manifest(staging, evidence)
        _require(not output_dir.exists() and not output_dir.is_symlink(), f"Output directory appeared before publication: {output_dir}")
        _publish_noreplace(staging, output_dir)
        return evidence
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--paper-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--neural-plan", type=Path, required=True)
    parser.add_argument("--tree-plan", type=Path, required=True)
    parser.add_argument("--export-plan", type=Path, required=True)
    parser.add_argument("--source-date-epoch", type=int, default=946684800)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        evidence = build_paper(
            repo_root=args.repo_root,
            paper_dir=args.paper_dir,
            output_dir=args.output_dir,
            plan_paths={
                "neural": args.neural_plan,
                "tree": args.tree_plan,
                "export": args.export_plan,
            },
            source_date_epoch=args.source_date_epoch,
            timeout_seconds=args.timeout_seconds,
        )
    except PaperBuildError as exc:
        print(f"paper build rejected: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": evidence["status"],
        "content_sha256": evidence["content_sha256"],
        "pdf_sha256": evidence["reproducibility"]["pdf_sha256"],
        "output_dir": str(args.output_dir.absolute()),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
