"""Regression cases for independent executions and the full fit barrier."""
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import contracts as c
import data_loaders as dl
import experiment_all as runner
import suite


def test_fit_reads_no_test_or_global_raw_labels(prepared, monkeypatch):
    observed = []
    load = dl._stable_npy
    def tracked(path, expected):
        observed.append(Path(path).name)
        assert "test" not in Path(path).name
        assert not Path(path).name.startswith("raw_unique")
        return load(path, expected)
    monkeypatch.setattr(dl, "_stable_npy", tracked)
    args = runner.parser().parse_args([
        "--dataset", "nslkdd", "--cache", str(prepared / "nslkdd"),
        "--output", "unused.json", "--model", "relu", "--device", "cpu",
    ])
    data = runner.prepare_data(args, include_test=False)
    assert data.x_test is data.y_test is None
    assert set(data.indices) == {"fit", "validation"}
    assert observed


def _invoke(command):
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _freeze(prepared, tmp_path):
    run = tmp_path / "formal"
    result = _invoke([
        sys.executable, str(c.PACKAGE / "suite.py"), "freeze",
        "--cache-root", str(prepared), "--run-dir", str(run),
        "--device", "cpu", "--threads", "1", "--seeds", "0",
        "--smoke-epochs", "1", "--nonformal-fixture-evidence-bypass",
    ])
    assert result.returncode == 0, result.stdout + result.stderr
    plan = c.load_json(run / "plan.json")
    job = next(j for j in plan["jobs"] if j["id"] == "nslkdd_relu")
    return run, plan, job


def test_copied_primary_checkpoint_cannot_resume_as_replica(prepared, tmp_path):
    run, plan, job = _freeze(prepared, tmp_path)
    for folder, role in (("results", "primary"), ("replicas", "replica")):
        output = run / folder / "nslkdd_relu.json"
        result = _invoke(suite.job_command(job, output, "fit", run, role))
        assert result.returncode == 0, result.stdout + result.stderr
    primary = run / "results/nslkdd_relu/runs/relu_seed_0.pt"
    replica = run / "replicas/nslkdd_relu/runs/relu_seed_0.pt"
    shutil.copyfile(primary, replica)
    result = _invoke(suite.job_command(
        job, run / "replicas/nslkdd_relu.json", "fit", run, "replica"))
    assert result.returncode != 0
    assert "different execution namespace" in result.stderr


def test_full_key_set_barrier_still_requires_every_execution(prepared, tmp_path):
    run, plan, job = _freeze(prepared, tmp_path)
    output = run / "results/nslkdd_relu.json"
    result = _invoke(suite.job_command(job, output, "fit", run, "primary"))
    assert result.returncode == 0, result.stderr
    digests = {j["id"]: "0" * 64 for j in plan["jobs"]}
    digests[job["id"]] = c.load_json(output)["training_digest"]
    c.write_json(run / "verification_fit.json", c.seal({
        "plan_sha256": plan["content_sha256"], "passed": True, "jobs": digests,
    }))
    result = _invoke(suite.job_command(job, output, "evaluate", run, "primary"))
    assert result.returncode != 0
    assert "barrier" in result.stderr.lower()
    manifest = c.load_json(output.with_suffix("") / "manifest.json")
    assert manifest["test_sessions_started"] == 0


def test_missing_execution_ledger_cannot_reset_existing_run(prepared, tmp_path):
    run, plan, job = _freeze(prepared, tmp_path)
    output = run / "results/nslkdd_relu.json"
    result = _invoke(suite.job_command(job, output, "fit", run, "primary"))
    assert result.returncode == 0, result.stderr
    manifest = output.with_suffix("") / "manifest.json"
    manifest.rename(manifest.with_name("saved_manifest.json"))
    result = _invoke(suite.job_command(job, output, "fit", run, "primary"))
    assert result.returncode != 0
    assert "ledger is missing" in result.stderr
