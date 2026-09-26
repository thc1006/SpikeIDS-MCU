"""Consume the exact isolated paper build; never trust a touched live PDF.

This module imports the installed builder, never code from a bundle. The
package gate separately recomputes scientific macros and validates prose.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import tempfile

from tools import build_v5_paper as builder

ROOT = Path(__file__).resolve().parent.parent
LOG_FILES = ('main.log', 'main.blg', 'main.fls', 'main.aux', 'main.bbl', 'latexmk.transcript')
ROOT_FILES = ('main.pdf', 'main.txt', 'pdfinfo.txt', 'main.aux', 'main.bbl')
PLAN_KEYS = ('neural', 'tree', 'export')
REQUIRED_FILES = frozenset({
    'paper_build.json', *ROOT_FILES,
    *(f'build-{i}/{name}' for i in (1, 2) for name in LOG_FILES),
    *(f'inputs/paper/{name}' for name in builder.PAPER_INPUT_ALLOWLIST),
    *(f'inputs/plans/{name}_plan.json' for name in PLAN_KEYS),
})
REQUIRED_DIRECTORIES = frozenset(
    parent.as_posix() for name in REQUIRED_FILES for parent in Path(name).parents
    if parent != Path('.'))


def _require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def _identity(row: os.stat_result) -> tuple:
    return (row.st_dev, row.st_ino, row.st_mode, row.st_nlink,
            row.st_size, row.st_mtime_ns, row.st_ctime_ns)


def _private(path: Path) -> bytes:
    path = Path(path).absolute()
    _require(path == path.resolve(), f'Paper evidence traverses a symlink: {path}')
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
             f'Paper evidence is not an independent regular file: {path}')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        _require(_identity(before) == _identity(os.fstat(stream.fileno())),
                 f'Paper evidence changed while opening: {path}')
        data = stream.read()
        after = os.fstat(stream.fileno())
    _require(_identity(before) == _identity(after) == _identity(path.lstat()),
             f'Paper evidence changed while reading: {path}')
    return data


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record(data: bytes) -> dict:
    return {'sha256': _digest(data), 'size_bytes': len(data)}


def _json(data: bytes, name: str) -> dict:
    value = builder._parse_json_bytes(data, name)
    builder._check_seal(value, name)
    return value


def validate_paper_build(build_dir: Path, paper_dir: Path,
                         plan_paths: dict[str, Path], *, replay: bool = False,
                         repo_root: Path | None = None) -> dict:
    """Validate a live or relocated build directory and optionally rebuild it.

    ``paper_dir`` and ``plan_paths`` always identify the accepted live inputs;
    ``build_dir`` may be the bundle's copied evidence directory. A replay uses
    two new isolated builds and compares the paper payload, never source mtime.
    """
    repo = (repo_root or ROOT).resolve()
    build_dir = Path(build_dir).absolute()
    paper_dir = Path(paper_dir).absolute()
    _require(build_dir == build_dir.resolve() and build_dir.is_dir(),
             'Paper build directory is not canonical')
    _require(set(plan_paths) == set(PLAN_KEYS), 'Paper build requires three accepted plans')
    paths = list(build_dir.rglob('*'))
    _require(not any(path.is_symlink() for path in paths), 'Paper build contains a symlink')
    inventory = {path.relative_to(build_dir).as_posix() for path in paths if path.is_file()}
    _require(inventory == REQUIRED_FILES, 'Paper build fixed inventory is incomplete or has extras')
    _require({path.relative_to(build_dir).as_posix() for path in paths} ==
             REQUIRED_FILES | REQUIRED_DIRECTORIES,
             'Paper build fixed directory inventory differs')
    watched = [*(build_dir/name for name in REQUIRED_FILES),
               *(paper_dir/name for name in builder.PAPER_INPUT_ALLOWLIST),
               *(Path(path).absolute() for path in plan_paths.values())]
    identities = {path: _identity(path.lstat()) for path in watched}
    payload = {name: _private(build_dir/name) for name in REQUIRED_FILES}
    report = _json(payload['paper_build.json'], 'paper build')
    _require(report.get('schema_version') == 2 and
             report.get('kind') == 'spikeids_v5_deterministic_fresh_paper_build' and
             report.get('status') == 'passed', 'Paper build did not pass')
    publication = report.get('publication_manifest', {})
    _require(publication.get('self_sealed_file') == 'paper_build.json' and
             publication.get('exact_inventory') == sorted(REQUIRED_FILES) and
             publication.get('hashed_files') == {
                 name: _record(data) for name, data in payload.items() if name != 'paper_build.json'
             } and publication.get('exact_directories') == sorted(
                 path.relative_to(build_dir).as_posix() for path in paths if path.is_dir()),
             'Paper publication manifest differs from actual payload')
    source_bytes = {name: _private(paper_dir/name) for name in builder.PAPER_INPUT_ALLOWLIST}
    _require(report.get('paper_input_allowlist') == list(builder.PAPER_INPUT_ALLOWLIST),
             'Paper source allowlist changed')
    for name, data in source_bytes.items():
        _require(data == payload[f'inputs/paper/{name}'] and
                 report.get('paper_inputs', {}).get(name) == {
                     'path': (paper_dir/name).relative_to(repo).as_posix(), **_record(data)},
                 f'Live paper input differs from the built input: {name}')
    plans, plan_inventory = {}, {}
    for name in PLAN_KEYS:
        path = Path(plan_paths[name]).absolute()
        data = _private(path)
        plans[name] = _json(data, name)
        plan_inventory[name] = {'source_path': str(path), **_record(data),
                                'content_sha256': plans[name]['content_sha256']}
        _require(data == payload[f'inputs/plans/{name}_plan.json'],
                 f'Built paper used another {name} plan')
    _require(report.get('plans') == plan_inventory and report.get('plan_bindings') == {
        f'{name}_plan_sha256': plans[name]['content_sha256'] for name in PLAN_KEYS
    }, 'Paper plan bindings differ')
    _require(report.get('macro_provenance') == builder._validate_provenance(
        source_bytes, plans, plan_inventory), 'Paper macro provenance differs')
    builder_file = Path(builder.__file__).resolve()
    recorded_builder = report.get('builder', {})
    expected_builder_path = (builder_file.relative_to(repo).as_posix()
                             if builder_file.is_relative_to(repo) else str(builder_file))
    _require(recorded_builder == {'path': expected_builder_path,
                                  'sha256': _digest(_private(builder_file))},
             'Paper builder differs from the accepted build')
    builds = report.get('builds', [])
    _require(len(builds) == 2 and [row.get('build_index') for row in builds] == [1, 2],
             'Paper build must contain two distinct build executions')
    for index, row in enumerate(builds, 1):
        expected_env = builder._minimal_env('', report['source_date_epoch'])
        expected_env.pop('PATH')
        _require(row.get('command') == [
            'latexmk', '-norc', '-pdf', '-g', '-recorder',
            '-interaction=nonstopmode', '-halt-on-error', '-file-line-error',
            '-pdflatex=pdflatex %O -no-shell-escape %S', 'main.tex'] and
            row.get('environment') == expected_env, 'Paper command or sandbox policy changed')
        for name in LOG_FILES:
            _require(row.get('artifacts', {}).get(name) ==
                     _record(payload[f'build-{index}/{name}']), 'Paper build log binding differs')
        for name in ROOT_FILES:
            _require(row.get('artifacts', {}).get(name) == _record(payload[name]),
                     'Paper reproducible artifact binding differs')
        _require(row.get('pdfinfo_fields') == builder._parse_pdfinfo(payload['pdfinfo.txt']),
                 'Paper PDF metadata differs from its recorded fields')
        _require(row.get('fls_input_inventory_sha256') ==
                 _digest(builder._json_bytes(row.get('fls_inputs'))) and
                 row.get('bibliography_input_inventory_sha256') ==
                 _digest(builder._json_bytes(row.get('bibliography_inputs'))),
                 'Paper normalized input inventories differ')
        builder._lint_logs({name: payload[f'build-{index}/{name}']
                            for name in ('main.log', 'main.blg')} | {
                                'latexmk transcript': payload[f'build-{index}/latexmk.transcript']})
        builder._assert_bibliography_style_unchanged(row)
    _require(builds[0]['fls_inputs'] == builds[1]['fls_inputs'] and
             builds[0]['bibliography_inputs'] == builds[1]['bibliography_inputs'],
             'The two paper builds used different normalized inputs')
    expected_repro = {
        'isolated_fresh_builds': 2,
        'pdf_bytes_identical': True, 'pdf_sha256': _digest(payload['main.pdf']),
        'text_bytes_identical': True, 'text_sha256': _digest(payload['main.txt']),
        'aux_bytes_identical': True, 'aux_sha256': _digest(payload['main.aux']),
        'bbl_bytes_identical': True, 'bbl_sha256': _digest(payload['main.bbl']),
        'normalized_fls_inputs_identical': True,
        'normalized_fls_inputs_sha256': builds[0]['fls_input_inventory_sha256'],
    }
    _require(report.get('reproducibility') == expected_repro,
             'Paper reproducibility summary differs')
    builder._validate_pdf_bytes(payload['main.pdf'])
    builder._lint_pdf_text(payload['main.txt'], payload['pdfinfo.txt'])
    _require(set(report.get('tools', {})) == set(builder.TOOL_VERSION_ARGS),
             'Paper toolchain inventory is incomplete')
    builder._assert_tools_unchanged(report['tools'])
    current_tools, _ = builder._discover_tools(30)
    _require(current_tools == report['tools'],
             'Paper toolchain versions differ from the current executable evidence')
    if replay:
        with tempfile.TemporaryDirectory(prefix='spikeids-paper-acceptance-') as temporary:
            destination = Path(temporary)/'fresh'
            fresh = builder.build_paper(repo_root=repo, paper_dir=paper_dir,
                                        output_dir=destination, plan_paths=plan_paths,
                                        source_date_epoch=report['source_date_epoch'])
            for name in ROOT_FILES:
                _require(_private(destination/name) == payload[name],
                         f'Independent paper build replay differs: {name}')
            _require(fresh['tools'] == report['tools'] and
                     fresh['reproducibility'] == report['reproducibility'] and
                     fresh['builds'][0]['bibliography_inputs'] == builds[0]['bibliography_inputs'],
                     'Independent paper replay input inventory differs')
    # Preserve snapshots across an expensive replay, including a mutate/restore
    # attempt, instead of accepting a final hash alone.
    _require({path.relative_to(build_dir).as_posix() for path in build_dir.rglob('*')
              if path.is_file() or path.is_symlink()} == REQUIRED_FILES,
             'Paper build inventory changed during validation')
    _require({path.relative_to(build_dir).as_posix() for path in build_dir.rglob('*')} ==
             REQUIRED_FILES | REQUIRED_DIRECTORIES,
             'Paper build directory inventory changed during validation')
    for name, data in payload.items():
        _require(_private(build_dir/name) == data, 'Paper build changed during validation')
    for name, data in source_bytes.items():
        _require(_private(paper_dir/name) == data, 'Paper source changed during validation')
    for path, identity in identities.items():
        _require(_identity(path.lstat()) == identity,
                 f'Paper input identity changed during validation: {path}')
    return report
