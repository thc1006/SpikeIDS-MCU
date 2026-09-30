"""Finite installed-tool domain checks: real tiny files, no compiler invocation."""
import ast
import hashlib
import importlib.util
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
raw = (HERE / 'build_v2.py').read_bytes()
assert hashlib.sha256(raw).hexdigest() == 'c7281032fd00c9b0fcbbd260c5a3a792c3bac1a243a7e74a598644ad8b77e01c'
spec = importlib.util.spec_from_file_location('indie_stage_build_v2', HERE / 'build_v2.py')
b = importlib.util.module_from_spec(spec)
exec(compile(raw, str(spec.origin), 'exec'), b.__dict__)
provider = b.VENDOR.read_bytes()
assert hashlib.sha256(provider).hexdigest() == b.VENDOR_SHA
spec = importlib.util.spec_from_file_location('indie_stage_writer', b.VENDOR)
v = importlib.util.module_from_spec(spec)
exec(compile(provider, str(spec.origin), 'exec'), v.__dict__)


def mixed_recheck(tool_paths):
    # Exercise the exact nested function body, without build()/Popen/ARM tools.
    tree = ast.parse(raw)
    build = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'build')
    check = next(n for n in build.body if isinstance(n, ast.FunctionDef) and n.name == 'recheck')
    namespace = dict(v=v, tool_paths=tool_paths, tool_snapshot=b.tool_snapshot, Path=Path)
    exec(compile(ast.Module(body=[check], type_ignores=[]), '<actual nested recheck>', 'exec'), namespace)
    return namespace['recheck']


def test_hardlinked_tool_keeps_original_identity_without_weakening_sources(tmp_path):
    p = tmp_path / 'tool'; p.write_bytes(b'\0installed toy bytes\xff')
    os.link(p, tmp_path / 'tool-alias')
    source = tmp_path / 'source'; source.write_bytes(b'ordinary source')
    pin = b.tool_snapshot(v, p)
    assert pin['links'] == 2 and pin['sha256'] == hashlib.sha256(p.read_bytes()).hexdigest()
    mixed_recheck({str(p)})({str(p):pin, str(source):v.snapshot(source)})
    with pytest.raises(v.PreparationError):v.snapshot(p)


def test_link_count_change_during_same_fd_read_is_rejected(tmp_path, monkeypatch):
    p = tmp_path / 'tool'; p.write_bytes(b'unchanged tool bytes')
    original = b.os.read
    called = False
    def read(fd, count):
        nonlocal called
        data = original(fd, count)
        if not called:
            called = True; os.link(p, tmp_path / 'new-link')
        return data
    monkeypatch.setattr(b.os, 'read', read)
    with pytest.raises(v.PreparationError, match='Tool changed during read'):
        b.tool_snapshot(v, p)


def test_original_mixed_recheck_rejects_new_link_even_with_unchanged_bytes(tmp_path):
    p = tmp_path / 'tool'; p.write_bytes(b'fixed bytes')
    os.link(p, tmp_path / 'original-alias')
    pin = b.tool_snapshot(v, p)
    check = mixed_recheck({str(p)})
    check({str(p):pin})
    os.link(p, tmp_path / 'late-alias')
    assert hashlib.sha256(p.read_bytes()).hexdigest() == pin['sha256']
    with pytest.raises(v.PreparationError, match='Installed tool changed'):
        check({str(p):pin})
