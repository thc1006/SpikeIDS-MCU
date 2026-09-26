#!/usr/bin/env python3
"""Fixed-model offline ST Edge AI 3.0 preparation; never validates/flashes a board.

This is a finite filesystem/bookend check, not an OS sandbox or portable toolchain
closure. The caller must separately authorize real compilation and isolate it in
a resource-limited scope. The CLI has no model/tool/options override.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time

SELF = Path(__file__).resolve()
REPO = SELF.parents[2]
PAYLOAD = REPO / "results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq"
INSTALL = Path("/home/thc1006/opt/stedgeai/3.0")
TOOL = INSTALL / "Utilities/linux/stedgeai"
PROFILE = INSTALL / "Utilities/linux/targets/stm32/resources/NPU/STM32N6xx/neural_art.json"
NAME = "nsl_qcfs_seed0"
VERSION = "ST Edge AI Core v3.0.0-20426 123672867"
INPUT_HASHES = {
    "model_qdq_int8.onnx": "22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d",
    "model_fp32.onnx": "3b14adf8179a5df0fd4215a7b6000e7edf22c8a0d462a11e10c21731b3d12038",
    "validation_vectors.npz": "cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb",
    "preprocessing.json": "c296ddcd0cc89eac605a3277f9077a9f3b76d34a737496328a915763e3f02aec",
    "calibration_rows.json": "af48ddf5d8d218b4975385b7819ef8e30d1db495650488062a22cd0860f74cbe",
    "export_policy.json": "2ca6fda8b6bbca50784a48318544f55634b48e6dddd8af04d0d8dc5109639d0f",
    "export_report.json": "46a0f963aa7401320a017a2506cfca0f704b81d50270f4dda76d4fca34e4e881",
}
TOOL_HASHES = {
    "Utilities/linux/stedgeai": "0aa7d9222af9620fce802037f09432f0320b77e90d3415f1d2c1d366b7872714",
    "Utilities/linux/atonn": "fb9c35c207dda7fecd9933fdabdde5c92b91e0c3c45ad1a60dbb9275f29b2a19",
    "Utilities/linux/ecasm": "e8bc1781131a405772ebf46c38046953b00cec164d32edc1e57e33a779070e26",
    "Utilities/linux/python": "a52afb14c4356d39135cc0fbe78e35c8245003b4dc5b5a47c2b85dd7906df529",
    "Utilities/linux/targets/stm32/resources/NPU/STM32N6xx/neural_art.json": "5a416483007fc8ae1896d1a14a8eb2bc488ae9e8ec4077e418d4b76512b86e55",
    "Utilities/linux/targets/stm32/resources/NPU/STM32N6xx/stm32n6.mpool": "85cbb7205023b482f1ae640fd0c02d6ccf9574ca4bf05abbe6640bf6a69acb49",
    "Utilities/configs/stm32n6.mdesc": "f29a0cf46aeb7c5eae90568b43f0f6f694b0a5ec97bba4223f5acc46005a1aac",
    "Utilities/configs/cortex-m55.cdesc": "98faf4e88d63cfbfd8cae704e78cf6adffffad751bb378d23fcc8df988675d03",
    "Utilities/linux/scripts/st_ai_cli/st_ai.cpython-39-x86_64-linux-gnu.so": "9721892ba0b43f51adcec41c26e834e4e2b858e34cec7752d6f89cada97f41a4",
    "Utilities/linux/scripts/st_ai_cli/st_ai_args.cpython-39-x86_64-linux-gnu.so": "5b03227fdc323180f196daacc805f04bd3217e9bc229fdb13f9309b7769cd1b9",
    "Utilities/linux/scripts/st_ai_cli/st_ai_cli_defaults.cpython-39-x86_64-linux-gnu.so": "5a5a782df2fbdb484f580f1c4d0484d662916bedc9536e460e035040aee3bd99",
    "Utilities/linux/scripts/st_ai_cli/st_ai_cli_utility.cpython-39-x86_64-linux-gnu.so": "bb42d35e00d2e1bfad96745709fd059fdf0e7ad1527c09c746a5ed24c465814b",
    "Utilities/linux/scripts/st_ai_cli/st_ai_cli_version.cpython-39-x86_64-linux-gnu.so": "8796895e58ef543d9821929f87395a143906529ccfd410a0e74d25ed3c98debd",
    "Utilities/linux/scripts/st_ai_cli/st_ai_config.cpython-39-x86_64-linux-gnu.so": "67f137fd8a999c8fdc15edd508e1df99030e72be06cb7b3f5b7628ec2c97064f",
}
LIMITS = {
    "board_validated": False, "energy_measured": False,
    "npu_placement_verified": False, "publication_accepted": False,
    "deployment_accepted": False, "full_toolchain_closure": False,
}


class PreparationError(RuntimeError):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code if type(code) is int and 1 <= code <= 125 else 1


def require(ok, message):
    if not ok:
        raise PreparationError(message)


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def stat_record(s):
    return dict(device=s.st_dev, inode=s.st_ino, size=s.st_size,
                mtime_ns=s.st_mtime_ns, ctime_ns=s.st_ctime_ns,
                mode=s.st_mode, links=s.st_nlink)


def canonical(path):
    require(path.is_absolute() and path == path.resolve(), f"Noncanonical/symlink path: {path}")


def snapshot(path):
    canonical(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = stat_record(os.fstat(fd))
        require(stat.S_ISREG(before["mode"]) and before["links"] == 1,
                f"Not an ordinary single-link file: {path}")
        digest = hashlib.sha256()
        while block := os.read(fd, 1024 * 1024):
            digest.update(block)
        require(before == stat_record(os.fstat(fd)) == stat_record(path.lstat()),
                f"File changed while hashing: {path}")
        return {**before, "sha256": digest.hexdigest()}
    finally:
        os.close(fd)


def recheck(pins):
    for name, pin in pins.items():
        require(snapshot(Path(name)) == pin, f"Held file changed: {name}")
    # Finite final metadata pass after all potentially long hash reads.
    for name, pin in pins.items():
        require(stat_record(Path(name).lstat()) == {k: v for k, v in pin.items() if k != "sha256"},
                f"Late held-file change: {name}")


def capture_inputs():
    # Capture this source before any input/tool use; never bless a late edit.
    pins = {str(SELF): snapshot(SELF)}
    interpreter = Path(sys.executable).resolve()
    pins[str(interpreter)] = snapshot(interpreter)
    for base, expected in ((PAYLOAD, INPUT_HASHES), (INSTALL, TOOL_HASHES)):
        for rel, digest in expected.items():
            path = base / rel
            pin = snapshot(path)
            require(pin["sha256"] == digest, f"Fixed SHA mismatch: {path}")
            pins[str(path)] = pin
    recheck(pins)
    return pins


def identity(s):
    return s.st_dev, s.st_ino, s.st_mode


class Output:
    """Fresh directory owned by pinned parent/child FDs; never adopts foreign roots."""
    def __init__(self, path):
        canonical(path)
        require(path.is_relative_to(REPO / "results"), "Output must be inside repository results")
        require(not path.is_relative_to(PAYLOAD.parents[2]), "Output overlaps original exports")
        require(not os.path.lexists(path), "Output already exists; no resume/overwrite")
        self.path = path
        self.pins = {}
        self.parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.parent_id = identity(os.fstat(self.parent))
        self.fd = None
        try:
            self.guard_parent()
            os.mkdir(path.name, 0o700, dir_fd=self.parent)
            self.fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.parent)
            self.dir_id = identity(os.fstat(self.fd))
            self.guard()
            os.fsync(self.fd)
            os.fsync(self.parent)
        except BaseException:
            self.close()
            raise

    def guard_parent(self):
        canonical(self.path.parent)
        require(identity(self.path.parent.lstat()) == self.parent_id == identity(os.fstat(self.parent)),
                "Output parent identity changed")

    def guard(self):
        self.guard_parent()
        canonical(self.path)
        require(identity(self.path.lstat()) == self.dir_id == identity(os.fstat(self.fd)),
                "Output directory identity changed")

    def open_new(self, name):
        require(Path(name).name == name, "Only top-level owned writes")
        self.guard()
        return os.fdopen(os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=self.fd), "w+b")

    def finish(self, stream, name, expected=None):
        stream.flush()
        pin = stat_record(os.fstat(stream.fileno()))
        stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if expected is not None:
            require(digest == hashlib.sha256(expected).hexdigest(), "Owned bytes differ from intended bytes")
        require(pin == stat_record(os.fstat(stream.fileno())), "Owned file changed during readback")
        os.fsync(stream.fileno())
        self.guard()
        require(pin == stat_record(os.fstat(stream.fileno())), "Owned file changed during fsync")
        full = {**pin, "sha256": digest}
        require(snapshot(self.path / name) == full, "Owned pathname no longer matches original FD")
        self.pins[str(self.path / name)] = full
        os.fsync(self.fd)
        return full

    def write(self, name, data):
        with self.open_new(name) as stream:
            stream.write(data)
            return self.finish(stream, name, data)

    def directory(self, name):
        self.guard()
        os.mkdir(name, 0o700, dir_fd=self.fd)
        return self.path / name

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        os.close(self.parent)


def inventory(path):
    canonical(path)
    files, dirs = {}, []
    for base, child_dirs, names in os.walk(path, followlinks=False):
        for name in sorted(child_dirs):
            item = Path(base) / name
            canonical(item)
            require(stat.S_ISDIR(item.lstat().st_mode), "Nonordinary directory")
            dirs.append(str(item.relative_to(path)))
        for name in sorted(names):
            item = Path(base) / name
            files[str(item.relative_to(path))] = snapshot(item)
    return {"files": files, "directories": sorted(dirs)}


def environment(output):
    # Do not inherit credentials, Python injection, GPU configuration or compiler flags.
    return {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1", "CUDA_VISIBLE_DEVICES": "",
            "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1",
            "TMPDIR": str(output / "tmp"), "XDG_CACHE_HOME": str(output / "cache")}


def command(output, phase):
    require(phase in ("version", "analyze", "generate"), "Unsupported command")
    if phase == "version":
        return [str(TOOL), "--version"]
    args = [str(TOOL), phase, "--model", str(output / "model_qdq_int8.onnx"),
            "--type", "onnx", "--target", "stm32n6", "--name", NAME,
            "--st-neural-art", f"default@{PROFILE}", "--c-api", "st-ai",
            "--input-data-type", "float32", "--output-data-type", "float32",
            "--compression", "lossless", "--optimization", "balanced",
            "--workspace", str(output / f"{phase}_workspace"),
            "--output", str(output / phase), "--verbosity", "2"]
    if phase == "generate":
        args.append("--binary")
    return args


def invoke(owner, phase, timeout, pins):
    owner.guard()
    recheck({**pins, **owner.pins})
    argv = command(owner.path, phase)
    record = {"phase": phase, "argv": argv, "cwd": str(owner.path),
              "environment": environment(owner.path), "actual_return_code": None,
              "timed_out": False, "exception": None}
    started = time.monotonic()
    proc = None
    with owner.open_new(f"{phase}.stdout") as stdout, owner.open_new(f"{phase}.stderr") as stderr:
        try:
            proc = subprocess.Popen(argv, cwd=owner.path, env=record["environment"],
                                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                    start_new_session=True, close_fds=True)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record["timed_out"] = True
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
        except BaseException as exc:
            record["exception"] = f"{type(exc).__name__}: {exc}"
            if proc is not None and proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
        finally:
            record["actual_return_code"] = proc.returncode if proc is not None else None
            record["elapsed_seconds"] = time.monotonic() - started
            record["stdout"] = owner.finish(stdout, f"{phase}.stdout")
            record["stderr"] = owner.finish(stderr, f"{phase}.stderr")
    owner.write(f"{phase}.json", encoded(record))
    require(not record["exception"], f"Subprocess exception in {phase}: {record['exception']}")
    if record["timed_out"]:
        raise PreparationError(f"Timed out: {phase}; partial streams retained", 124)
    if record["actual_return_code"] != 0:
        raise PreparationError(f"Vendor {phase} failed: {record['actual_return_code']}", record["actual_return_code"])
    recheck({**pins, **owner.pins})
    owner.guard()
    return record


def mapping_report(path):
    text = path.read_text(encoding="utf-8")
    patterns = {
        "total": r"^Total number of epochs\s+(\d+)",
        "software": r"^>> pure software \(SW\) epochs\s+(\d+)",
        "hybrid": r"^>> hybrid epochs \(using both software and hardware\)\s+(\d+)",
        "hardware": r"^>> pure hardware \(HW or EC\) epochs\s+(\d+)",
    }
    counts = {}
    for key, pattern in patterns.items():
        found = re.findall(pattern, text, re.MULTILINE)
        require(len(found) == 1, f"Missing/ambiguous observed mapping count: {key}")
        counts[key] = int(found[0])
    require(counts["total"] > 0 and counts["total"] == sum(counts[k] for k in ("software", "hybrid", "hardware")),
            "Inconsistent mapping counts")
    return {"reported_epochs": counts, "interpretation": "vendor report observation only; not kernel, parity or board proof"}


def run(output_dir, *, timeout_seconds=900):
    require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 3600, "Timeout must be an integer in [1,3600]")
    pins = capture_inputs()
    owner = Output(Path(output_dir))
    try:
        for directory in ("tmp", "cache", "analyze", "analyze_workspace", "generate", "generate_workspace"):
            owner.directory(directory)
        owner.write("INTENT.json", encoded({"schema": 1, "kind": "n6_offline_vendor_preparation_intent",
                    "model": str(PAYLOAD / "model_qdq_int8.onnx"), "expected_version": VERSION,
                    "held_inputs_source_tools": pins, "timeout_seconds": timeout_seconds, **LIMITS}))
        owner.write("model_qdq_int8.onnx", (PAYLOAD / "model_qdq_int8.onnx").read_bytes())
        require(owner.pins[str(owner.path / "model_qdq_int8.onnx")]["sha256"] == INPUT_HASHES["model_qdq_int8.onnx"], "Copied model mismatch")
        calls = [invoke(owner, "version", min(timeout_seconds, 30), pins)]
        require((owner.path / "version.stdout").read_text().splitlines()[0] == VERSION, "Unexpected installed tool version")
        calls.append(invoke(owner, "analyze", timeout_seconds, pins))
        # Freeze analyze outputs as soon as that process exits, before generate.
        analyze = inventory(owner.path / "analyze")
        require(analyze["files"], "Analyze succeeded without retained artifacts")
        analyze_pins = {str(owner.path / "analyze" / k): v for k, v in analyze["files"].items()}
        pins.update(analyze_pins)
        calls.append(invoke(owner, "generate", timeout_seconds, pins))
        require(inventory(owner.path / "analyze") == analyze, "Analyze namespace changed during generate")
        report_path = owner.path / "generate" / f"{NAME}_generate_report.txt"
        report_pin = snapshot(report_path)
        mapping = mapping_report(report_path)
        require(snapshot(report_path) == report_pin, "Mapping report changed during interpretation")
        for name in (f"{NAME}.c", f"{NAME}.h", f"stai_{NAME}.c", f"stai_{NAME}.h", f"{NAME}_c_info.json"):
            require(snapshot(owner.path / "generate" / name)["size"] > 0, f"Missing generated code/metadata: {name}")
        binaries = sorted(p.name for p in (owner.path / "generate").iterdir()
                          if (p.name.startswith(f"{NAME}_atonbuf.") and p.name.endswith(".raw"))
                          or p.name == f"{NAME}_weights.bin")
        require(binaries and all(snapshot(owner.path / "generate" / name)["size"] > 0 for name in binaries),
                "No nonempty generated binary weights")
        artifacts = inventory(owner.path)
        require("FAILED.json" not in artifacts["files"], "Contradictory failure marker")
        recheck({**pins, **owner.pins})
        result = {"schema": 1, "kind": "n6_offline_vendor_preparation", "offline_compilation_completed": True,
                  "model_sha256": INPUT_HASHES["model_qdq_int8.onnx"], "version": VERSION,
                  "calls": calls, "mapping": mapping, "binary_weight_files": binaries, "artifacts_before_result": artifacts,
                  "held_inputs_source_tools": pins, "limits": [
                      "No model inference, validation command, board, serial, flash or power measurement requested.",
                      "Selected tool binaries/front-end/profile/config files are pinned; transitive libraries are not fully captured.",
                      "Finite filesystem bookends, not an atomic snapshot, OS sandbox, or independent compiler correctness proof.",
                      "Default vendor memory profile is diagnostic, not an approved firmware/linker/flash layout.",
                      "Preserves all 17 historical export negatives; no threshold/checkpoint/quantization changes."], **LIMITS}
        result["content_sha256"] = hashlib.sha256(encoded(result)).hexdigest()
        own = owner.write("RESULT.json", encoded(result))
        expected = {"files": {**artifacts["files"], "RESULT.json": own}, "directories": artifacts["directories"]}
        require(inventory(owner.path) == expected, "Late output mutation/publication namespace change")
        recheck({**pins, **owner.pins, **{str(owner.path / k): v for k, v in expected["files"].items()}})
        owner.guard()
        return result
    except BaseException as exc:
        try:
            owner.guard()
            owner.write("FAILED.json", encoded({"schema": 1, "kind": "n6_offline_vendor_preparation_failure",
                         "exception": f"{type(exc).__name__}: {exc}", **LIMITS}))
        except BaseException:
            pass  # Unsafe/rebound directory: never follow it to write a failure marker.
        raise
    finally:
        owner.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    try:
        result = run(args.output_dir, timeout_seconds=args.timeout_seconds)
    except Exception as exc:
        print(f"PREPARATION FAILED: {exc}", file=sys.stderr)
        return exc.code if isinstance(exc, PreparationError) else 1
    print(json.dumps({"offline_compilation_completed": True, "content_sha256": result["content_sha256"], **LIMITS}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
