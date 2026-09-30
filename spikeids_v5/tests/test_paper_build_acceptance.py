"""Consumer acceptance executes the real builder, never mocks its gate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import verify_v5_paper_build as gate  # noqa: E402
from tools import build_v5_paper as builder  # noqa: E402
from test_paper_build_tool import _make_repository, _make_toolchain, _build  # noqa: E402


def setup(tmp_path, monkeypatch, *, fake=True):
    repo = tmp_path/'repo'
    paper = _make_repository(repo)
    if fake:
        tools = _make_toolchain(tmp_path, {})
        monkeypatch.setenv('PATH', str(tools))
    output = tmp_path/'published'
    _build(repo, paper, output)
    plans = {name: repo/'plans'/f'{name}.json' for name in ('neural','tree','export')}
    return repo, paper, output, plans


def test_real_double_build_is_accepted_and_replayed(tmp_path, monkeypatch):
    repo,paper,output,plans = setup(tmp_path,monkeypatch,fake=False)
    report = gate.validate_paper_build(output,paper,plans,repo_root=repo,replay=True)
    assert report['status'] == 'passed'


def test_live_unrelated_pdf_is_not_the_selected_pdf(tmp_path, monkeypatch):
    repo,paper,output,plans = setup(tmp_path,monkeypatch)
    (paper/'main.pdf').write_bytes(b'unrelated PDF with a newer mtime')
    gate.validate_paper_build(output,paper,plans,repo_root=repo)
    assert (output/'main.pdf').read_bytes().startswith(b'%PDF-')


@pytest.mark.parametrize('attack',['pdf','input','plan','missing_log','extra','hardlink','symlink'])
def test_paper_build_consumer_rejects_stale_or_aliased_payload(tmp_path, monkeypatch, attack):
    repo,paper,output,plans = setup(tmp_path,monkeypatch)
    if attack == 'pdf': (output/'main.pdf').write_bytes(b'%PDF-1.7\nreplacement\n%%EOF\n')
    elif attack == 'input': (paper/'main.tex').write_text('changed source')
    elif attack == 'plan': plans['neural'].write_text('{}')
    elif attack == 'missing_log': (output/'build-2/main.log').unlink()
    elif attack == 'extra': (output/'unplanned.txt').write_text('extra')
    else:
        source = output/'main.pdf'
        saved = tmp_path/'elsewhere.pdf'
        source.rename(saved)
        if attack == 'hardlink': source.hardlink_to(saved)
        else: source.symlink_to(saved)
    with pytest.raises((RuntimeError,ValueError)):
        gate.validate_paper_build(output,paper,plans,repo_root=repo)


def test_coordinately_resealed_replacement_pdf_fails_real_builder_replay(tmp_path,monkeypatch):
    repo,paper,output,plans = setup(tmp_path,monkeypatch)
    replacement = b'%PDF-1.7\nresealed wrong PDF\n%%EOF\n'
    (output/'main.pdf').write_bytes(replacement)
    path = output/'paper_build.json'
    report = json.loads(path.read_text())
    report.pop('content_sha256')
    record = {'sha256': hashlib.sha256(replacement).hexdigest(), 'size_bytes': len(replacement)}
    report['publication_manifest']['hashed_files']['main.pdf'] = record
    for row in report['builds']: row['artifacts']['main.pdf'] = record
    report['reproducibility']['pdf_sha256'] = record['sha256']
    path.write_text(json.dumps(builder._seal(report)))
    with pytest.raises(RuntimeError,match='replay differs'):
        gate.validate_paper_build(output,paper,plans,repo_root=repo,replay=True)


@pytest.mark.parametrize('replay', [False, True])
def test_resealed_pdfinfo_payload_must_match_both_build_records(tmp_path, monkeypatch, replay):
    repo, paper, output, plans = setup(tmp_path, monkeypatch)
    info = (b'Title: Fabricated metadata\nPages: 9999\nEncrypted: yes\n'
            b'JavaScript: yes\nPDF version: 1.7\n')
    (output / 'pdfinfo.txt').write_bytes(info)
    path = output / 'paper_build.json'
    report = json.loads(path.read_text())
    report.pop('content_sha256')
    report['publication_manifest']['hashed_files']['pdfinfo.txt'] = {
        'sha256': hashlib.sha256(info).hexdigest(), 'size_bytes': len(info),
    }
    path.write_text(json.dumps(builder._seal(report)))
    with pytest.raises((RuntimeError, ValueError)):
        gate.validate_paper_build(output, paper, plans, repo_root=repo, replay=replay)


@pytest.mark.parametrize('replay', [False, True])
def test_resealed_tool_versions_are_compared_with_installed_tools(tmp_path, monkeypatch, replay):
    repo, paper, output, plans = setup(tmp_path, monkeypatch)
    path = output / 'paper_build.json'
    report = json.loads(path.read_text())
    report.pop('content_sha256')
    for tool in report['tools'].values():
        tool['version'] = 'fabricated version 123'
        tool['version_sha256'] = hashlib.sha256(b'fabricated version 123\n').hexdigest()
    path.write_text(json.dumps(builder._seal(report)))
    with pytest.raises((RuntimeError, ValueError)):
        gate.validate_paper_build(output, paper, plans, repo_root=repo, replay=replay)


@pytest.mark.parametrize('replay', [False, True])
def test_resealed_extra_empty_directory_cannot_extend_fixed_build_inventory(tmp_path, monkeypatch, replay):
    repo, paper, output, plans = setup(tmp_path, monkeypatch)
    (output / 'empty-unplanned').mkdir()
    path = output / 'paper_build.json'
    report = json.loads(path.read_text())
    report.pop('content_sha256')
    report['publication_manifest']['exact_directories'].append('empty-unplanned')
    report['publication_manifest']['exact_directories'].sort()
    path.write_text(json.dumps(builder._seal(report)))
    with pytest.raises((RuntimeError, ValueError)):
        gate.validate_paper_build(output, paper, plans, repo_root=repo, replay=replay)
