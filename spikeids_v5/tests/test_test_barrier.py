"""Adversarial tests for the formal global-fit-to-test capability barrier."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

import pytest

import contracts as c
import experiment_all as runner
import suite


def test_data_evidence_bypass_is_smoke_only(prepared: Path, tmp_path: Path) -> None:
    missing = suite.make_parser().parse_args([
        "freeze", "--cache-root", str(prepared), "--run-dir", str(tmp_path / "missing"),
        "--device", "cpu", "--seeds", "0", "--smoke-epochs", "1",
    ])
    with pytest.raises(c.ContractError, match="requires raw audit"):
        suite.freeze(missing)
    forbidden = suite.make_parser().parse_args([
        "freeze", "--cache-root", str(prepared), "--run-dir", str(tmp_path / "forbidden"),
        "--device", "cpu", "--seeds", "0", "--nonformal-fixture-evidence-bypass",
    ])
    with pytest.raises(c.ContractError, match="restricted"):
        suite.freeze(forbidden)


def _telemetry_plan(device: str = "cpu") -> dict:
    return {
        "content_sha256": "a" * 64,
        "jobs": [{"hyperparameters": {"device": device}}],
        "resource_limits": {
            "maximum_process_tree_rss_bytes": 2**63 - 1,
            "maximum_gpu_memory_used_mib": 20_000,
            "maximum_gpu_temperature_c": 100,
            "require_zero_swap_io": True,
            "require_zero_oom_kills": True,
        },
    }


def _stable_host_sample() -> dict:
    return {
        "mem_available_bytes": 10**9, "swap_free_bytes": 10**9,
        "vmstat": {"pswpin": 7, "pswpout": 8, "oom_kill": 9},
        "pressure": {"cpu": "some total=0", "memory": "some total=0",
                     "io": "some total=0"},
        "loadavg": "0 0 0 1/1 1",
    }


def test_resource_telemetry_persists_raw_samples_and_sealed_summary(
        tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(suite, "_host_sample", _stable_host_sample)
    with suite.resource_monitor(tmp_path, "fit", _telemetry_plan(), .01):
        time.sleep(.03)
    report = c.load_json(tmp_path / "resource_fit_001.json")
    c.check_seal(report)
    assert report["telemetry_passed"] is True and report["samples"] >= 1
    raw = tmp_path / report["raw_samples"]["path"]
    assert c.sha256(raw) == report["raw_samples"]["sha256"]
    assert len(raw.read_text().splitlines()) == report["samples"]


def test_resource_telemetry_sampling_error_fails_closed(tmp_path: Path, monkeypatch) -> None:
    def fail_sample():
        raise RuntimeError("injected sampler failure")
    monkeypatch.setattr(suite, "_host_sample", fail_sample)
    with pytest.raises(c.ContractError, match="telemetry failed closed"):
        with suite.resource_monitor(tmp_path, "fit", _telemetry_plan(), .01):
            time.sleep(.02)
    report = c.load_json(tmp_path / "resource_fit_001.json")
    assert report["telemetry_passed"] is False and report["sampling_errors"]


def test_resource_telemetry_rejects_persistent_foreign_gpu_identity(
        tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(suite, "_process_tree", lambda _pid: [{
        "pid": 111, "ppid": 0, "rss_bytes": 1, "start_ticks": 10, "cmdline": "suite",
    }])
    monkeypatch.setattr(suite, "_pid_start_ticks", lambda pid: 20 if pid == 222 else 10)
    monkeypatch.setattr(suite, "_host_sample", _stable_host_sample)
    monkeypatch.setattr(suite, "_gpu_sample", lambda: {
        "uuid": "GPU-test", "utilization_pct": 10.0, "memory_used_mib": 100.0,
        "memory_total_mib": 16384.0, "power_w": 20.0, "temperature_c": 30.0,
        "sm_clock_mhz": 1000.0, "pstate": "P2", "clock_event_reasons_active": "None",
        "compute_processes": [{"pid": 222, "memory_used_mib": 100.0}],
    })
    with pytest.raises(c.ContractError, match="telemetry failed closed"):
        with suite.resource_monitor(tmp_path, "fit", _telemetry_plan("cuda"), .01):
            time.sleep(.04)
    report = c.load_json(next(tmp_path.glob("resource_fit_*.json")))
    assert report["foreign_gpu_pids"] == [222]
    assert report["foreign_gpu_process_identities"] == ["222:20"]


@pytest.mark.parametrize(("counter", "violation"), [
    ("pswpin", "host_swap_io"), ("pswpout", "host_swap_io"),
    ("oom_kill", "host_oom_kill"),
])
def test_resource_telemetry_rejects_host_counter_increase(
        tmp_path: Path, monkeypatch, counter: str, violation: str) -> None:
    calls = 0

    def changing_host() -> dict:
        nonlocal calls
        result = _stable_host_sample()
        result["vmstat"][counter] += calls
        calls += 1
        return result

    monkeypatch.setattr(suite, "_host_sample", changing_host)
    with pytest.raises(c.ContractError, match="telemetry failed closed"):
        with suite.resource_monitor(tmp_path, "fit", _telemetry_plan(), .01):
            deadline = time.monotonic() + 1.0
            while calls < 3 and time.monotonic() < deadline:
                time.sleep(.01)
            assert calls >= 2
    report = c.load_json(next(tmp_path.glob("resource_fit_*.json")))
    assert violation in report["resource_limit_violations"]


def test_short_action_tail_counter_change_is_detected(tmp_path, monkeypatch):
    tail = False
    def host():
        result = _stable_host_sample()
        result["vmstat"]["pswpout"] += 123 if tail else 0
        return result
    monkeypatch.setattr(suite, "_host_sample", host)
    with pytest.raises(c.ContractError, match="telemetry failed closed"):
        with suite.resource_monitor(tmp_path, "fit", _telemetry_plan(), 60):
            tail = True
    report = c.load_json(tmp_path / "resource_fit_001.json")
    assert report["vmstat_delta"]["pswpout"] == 123
    assert report["samples"] == 2


def _runner_args(cache: Path, output: Path, *extra: str) -> list[str]:
    return [
        "--dataset", "nslkdd", "--cache", str(cache), "--output", str(output),
        "--model", "relu", "--epochs", "1", "--batch-size", "16",
        "--eval-every", "1", "--checkpoint-every", "1", "--hidden", "16",
        "--seeds", "0", "--device", "cpu", "--threads", "1", *extra,
    ]


def test_formal_job_forbids_combined_stage(prepared: Path, tmp_path: Path) -> None:
    args = runner.parser().parse_args(_runner_args(
        prepared / "nslkdd", tmp_path / "run" / "results" / "nslkdd_relu.json",
        "--stage", "all", "--formal-plan", str(tmp_path / "run" / "plan.json"),
        "--formal-execution", "primary",
    ))
    with pytest.raises(c.ContractError, match="forbid"):
        runner.validate_args(args)


def test_preexposed_job_cannot_be_adopted_by_formal_plan(
        prepared: Path, tmp_path: Path) -> None:
    run_dir = tmp_path / "formal"
    subprocess.run([
        sys.executable, str(c.PACKAGE / "suite.py"), "freeze",
        "--cache-root", str(prepared), "--run-dir", str(run_dir),
        "--device", "cpu", "--optimizer", "single", "--threads", "1",
        "--workers", "1", "--seeds", "0", "--smoke-epochs", "1",
        "--nonformal-fixture-evidence-bypass",
    ], check=True, capture_output=True, text=True)
    plan = c.load_json(run_dir / "plan.json")
    job = next(row for row in plan["jobs"] if row["id"] == "nslkdd_relu")
    output = run_dir / "results" / "nslkdd_relu.json"

    # Attack: evaluate this exact output path without the formal binding or
    # global barrier, then try to let the formal orchestrator adopt it.
    direct = [sys.executable, str(c.PACKAGE / "experiment_all.py"),
              *_runner_args(prepared / "nslkdd", output, "--stage", "all")]
    subprocess.run(direct, check=True, capture_output=True, text=True)
    formal = suite.job_command(job, output, "fit", run_dir, "primary")
    failed = subprocess.run(formal, check=False, capture_output=True, text=True)
    assert failed.returncode != 0
    message = (failed.stdout + failed.stderr).lower()
    assert "resume rejected" in message and "changed" in message


def test_incomplete_fit_verification_cannot_unlock_test(
        prepared: Path, tmp_path: Path) -> None:
    run_dir = tmp_path / "formal"
    subprocess.run([
        sys.executable, str(c.PACKAGE / "suite.py"), "freeze",
        "--cache-root", str(prepared), "--run-dir", str(run_dir),
        "--device", "cpu", "--optimizer", "single", "--threads", "1",
        "--workers", "1", "--seeds", "0", "--smoke-epochs", "1",
        "--nonformal-fixture-evidence-bypass",
    ], check=True, capture_output=True, text=True)
    plan = c.load_json(run_dir / "plan.json")
    job = next(row for row in plan["jobs"] if row["id"] == "nslkdd_relu")
    output = run_dir / "results" / "nslkdd_relu.json"
    subprocess.run(suite.job_command(job, output, "fit", run_dir, "primary"),
                   check=True, capture_output=True, text=True)
    c.write_json(run_dir / "verification_fit.json", c.seal({
        "plan_sha256": plan["content_sha256"], "passed": True,
        "jobs": {"nslkdd_relu": c.load_json(output)["training_digest"]},
    }))
    failed = subprocess.run(
        suite.job_command(job, output, "evaluate", run_dir, "primary"),
        check=False, capture_output=True, text=True)
    assert failed.returncode != 0
    assert "barrier" in (failed.stdout + failed.stderr).lower()
