"""True subprocess/IO toy controls; no vendor/model/USB execution.

The fake vendor is a tiny standalone Python subprocess. Only fixed location/hash
constants are monkeypatched. The wrapper's capture, copy, command selection,
subprocess runner, publication and hashing all run normally.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("prepare_vendor_author_test", HERE / "prepare_vendor.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

MAPPING = """Total number of epochs                               7
>> pure software (SW) epochs                         3
>> hybrid epochs (using both software and hardware)  0
>> pure hardware (HW or EC) epochs                   4
"""


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    results = repo / "results"
    payload = results / "original" / "nslkdd" / "qcfs" / "qdq"
    payload.mkdir(parents=True)
    install = tmp_path / "installed"
    install.mkdir()
    source = repo / "source.py"
    source.write_bytes(b"toy source, not executable\n")
    inputs = {"model_qdq_int8.onnx": b"opaque toy model; not parsed", "export_report.json": b"{}"}
    for name, data in inputs.items():
        (payload / name).write_bytes(data)
    profile = install / "profile.json"
    profile.write_bytes(b"toy profile")
    mode = tmp_path / "mode.txt"
    mode.write_text("normal")
    tool = install / "fake_vendor"
    # Generates only within argv's fresh output. Never imports vendor code/model libraries.
    tool.write_text(f'''#!{sys.executable}
import pathlib,sys,time
mode=pathlib.Path({str(mode)!r}).read_text()
phase=sys.argv[1]
print('stdout '+phase,flush=True) if phase!='--version' else None
print('stderr '+phase,file=sys.stderr,flush=True)
if phase=='--version':
 print({p.VERSION!r} if mode!='version' else 'ST Edge AI Core v4.0')
 raise SystemExit(0)
assert phase in ('analyze','generate')
if mode=='nonzero' and phase=='analyze': raise SystemExit(23)
if mode=='timeout' and phase=='analyze': time.sleep(10)
if mode=='mutation' and phase=='analyze': pathlib.Path({str(payload / 'export_report.json')!r}).write_text('changed')
out=pathlib.Path(sys.argv[sys.argv.index('--output')+1])
name=sys.argv[sys.argv.index('--name')+1]
if phase=='analyze':
 if mode!='no_analyze': (out/(name+'_analyze_report.txt')).write_text('toy analyze report')
else:
 for suffix in ('.c','.h','_c_info.json'):
  (out/(name+suffix)).write_text('toy generated content')
 for suffix in ('.c','.h'): (out/('stai_'+name+suffix)).write_text('toy wrapper')
 if mode!='no_mapping':
  (out/(name+'_generate_report.txt')).write_text({MAPPING!r} if mode!='bad_mapping' else 'missing mapping')
 if mode!='no_binary':
  (out/(name+'_atonbuf.xSPI2.raw')).write_bytes(b'toy weights' if mode!='empty_binary' else b'')
 if mode=='symlink': (out/'foreign').symlink_to({str(source)!r})
''')
    tool.chmod(0o700)
    for key, value in {"REPO": repo, "PAYLOAD": payload, "INSTALL": install, "SELF": source,
                       "TOOL": tool, "PROFILE": profile,
                       "INPUT_HASHES": {k: hashlib.sha256(v).hexdigest() for k, v in inputs.items()},
                       "TOOL_HASHES": {"fake_vendor": hashlib.sha256(tool.read_bytes()).hexdigest(),
                                       "profile.json": hashlib.sha256(profile.read_bytes()).hexdigest()}}.items():
        monkeypatch.setattr(p, key, value)
    return {"repo": repo, "output": results / "fresh", "mode": mode, "tool": tool,
            "source": source, "payload": payload, "profile": profile}


def test_real_subprocess_positive(evidence):
    f = evidence
    report = p.run(f["output"], timeout_seconds=5)
    assert report["offline_compilation_completed"] is True
    assert all(report[k] is False for k in p.LIMITS)
    assert report["mapping"]["reported_epochs"] == dict(total=7, software=3, hybrid=0, hardware=4)
    assert len(report["binary_weight_files"]) == 1
    assert [c["phase"] for c in report["calls"]] == ["version", "analyze", "generate"]
    assert all(type(c["actual_return_code"]) is int and c["actual_return_code"] == 0 for c in report["calls"])
    assert (f["output"] / "model_qdq_int8.onnx").read_bytes() == (f["payload"] / "model_qdq_int8.onnx").read_bytes()
    assert (f["output"] / "generate.stderr").read_text() == "stderr generate\n"
    assert not (f["output"] / "FAILED.json").exists()
    assert json.loads((f["output"] / "RESULT.json").read_text()) == report
    assert report["artifacts_before_result"]["files"]
    for c in report["calls"]:
        assert c["environment"]["OMP_NUM_THREADS"] == "1"
        assert "HOME" not in c["environment"] and "GITHUB_TOKEN" not in c["environment"]
        assert not any(arg in c["argv"] for arg in ("validate", "--desc", "--quantize", "--relocatable"))


@pytest.mark.parametrize("mode", ["version", "nonzero", "no_analyze", "no_mapping", "bad_mapping",
                                  "no_binary", "empty_binary", "mutation", "symlink"])
def test_real_subprocess_failures_retained(evidence, mode):
    evidence["mode"].write_text(mode)
    with pytest.raises((p.PreparationError, OSError)):
        p.run(evidence["output"], timeout_seconds=5)
    assert (evidence["output"] / "FAILED.json").is_file()
    assert not (evidence["output"] / "RESULT.json").exists()
    if mode == "nonzero":
        record = json.loads((evidence["output"] / "analyze.json").read_text())
        assert record["actual_return_code"] == 23
        assert (evidence["output"] / "analyze.stdout").read_text() == "stdout analyze\n"
        assert not (evidence["output"] / "generate.json").exists()


def test_timeout_retains_actual_exit_partial_streams(evidence):
    evidence["mode"].write_text("timeout")
    with pytest.raises(p.PreparationError) as caught:
        p.run(evidence["output"], timeout_seconds=1)
    assert caught.value.code == 124
    record = json.loads((evidence["output"] / "analyze.json").read_text())
    assert record["timed_out"] is True and record["actual_return_code"] == -9
    assert (evidence["output"] / "analyze.stdout").read_text() == "stdout analyze\n"
    assert (evidence["output"] / "analyze.stderr").read_text() == "stderr analyze\n"


@pytest.mark.parametrize("target", ["source", "tool", "profile"])
def test_during_subprocess_source_tool_change(evidence, monkeypatch, target):
    original = p.invoke
    def mutate(owner, phase, timeout, pins):
        answer = original(owner, phase, timeout, pins)
        if phase == "version":
            evidence[target].write_bytes(evidence[target].read_bytes() + b"\n")
        return answer
    monkeypatch.setattr(p, "invoke", mutate)
    with pytest.raises(p.PreparationError, match="Held file changed"):
        p.run(evidence["output"], timeout_seconds=5)
    assert not (evidence["output"] / "analyze.json").exists()


@pytest.mark.parametrize("target", ["model_qdq_int8.onnx", "export_report.json"])
def test_fixed_input_wrong_sha_before_launch(evidence, target):
    (evidence["payload"] / target).write_bytes(b"wrong")
    with pytest.raises(p.PreparationError, match="Fixed SHA mismatch"):
        p.run(evidence["output"])
    assert not evidence["output"].exists()


def test_existing_output_untouched(evidence):
    evidence["output"].mkdir()
    marker = evidence["output"] / "keep"
    marker.write_bytes(b"original")
    with pytest.raises(p.PreparationError, match="already exists"):
        p.run(evidence["output"])
    assert list(evidence["output"].iterdir()) == [marker]


@pytest.mark.parametrize("timeout", [False, 0, 3601, 1.0, "1"])
def test_timeout_type_and_domain(evidence, timeout):
    with pytest.raises(p.PreparationError, match="Timeout"):
        p.run(evidence["output"], timeout_seconds=timeout)


@pytest.mark.parametrize("mutation", ["extra_file", "extra_directory", "result_replace", "input_restore"])
def test_publication_endpoint(evidence, monkeypatch, mutation):
    original = p.Output.write
    def write(owner, name, data):
        result = original(owner, name, data)
        if name == "RESULT.json":
            if mutation == "extra_file": (owner.path / "extra").write_bytes(b"extra")
            elif mutation == "extra_directory": (owner.path / "extra").mkdir()
            elif mutation == "result_replace": (owner.path / name).write_bytes(data.replace(b'"offline_compilation_completed": true', b'"offline_compilation_completed": false'))
            else:
                path = evidence["payload"] / "export_report.json"
                held = path.read_bytes()
                path.write_bytes(b"changed")
                path.write_bytes(held)
        return result
    monkeypatch.setattr(p.Output, "write", write)
    with pytest.raises(p.PreparationError):
        p.run(evidence["output"], timeout_seconds=5)
    assert (evidence["output"] / "FAILED.json").exists()


def test_own_fsync_replacement_rejected(evidence, monkeypatch):
    original = p.os.fsync
    def fsync(fd):
        original(fd)
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if path.name == "RESULT.json":
            path.write_bytes(b"replacement")
    monkeypatch.setattr(p.os, "fsync", fsync)
    with pytest.raises(p.PreparationError, match="fsync"):
        p.run(evidence["output"], timeout_seconds=5)


def test_output_rebind_does_not_write_foreign_marker(evidence, monkeypatch):
    original = p.invoke
    foreign = evidence["repo"] / "foreign"
    foreign.mkdir()
    def invoke(owner, phase, timeout, pins):
        result = original(owner, phase, timeout, pins)
        if phase == "version":
            owner.path.rename(owner.path.with_name("moved"))
            owner.path.symlink_to(foreign, target_is_directory=True)
        return result
    monkeypatch.setattr(p, "invoke", invoke)
    with pytest.raises((p.PreparationError, OSError)):
        p.run(evidence["output"], timeout_seconds=5)
    assert list(foreign.iterdir()) == []


def test_cli_nonzero_is_nonzero(evidence):
    evidence["mode"].write_text("nonzero")
    assert p.main(["--output-dir", str(evidence["output"]), "--timeout-seconds", "5"]) == 23


@pytest.mark.parametrize("args", [["--output", "/tmp/x"], ["--output-dir", "/tmp/x", "--model", "x"],
                                  ["--output-dir", "/tmp/x", "--command", "validate"]])
def test_no_abbreviated_or_external_commands(args):
    with pytest.raises(SystemExit) as caught:
        p.main(args)
    assert caught.value.code == 2


def test_mapping_ambiguous_or_mismatched(tmp_path):
    path = tmp_path / "report.txt"
    for text in (MAPPING + MAPPING, MAPPING.replace("7\n", "8\n")):
        path.write_text(text)
        with pytest.raises(p.PreparationError):
            p.mapping_report(path)
