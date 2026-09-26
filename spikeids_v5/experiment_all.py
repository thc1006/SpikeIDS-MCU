"""Version-5 experiment runner: immutable prepared data, explicit ANN formula, strict FP32.

The ten uploaded files and legacy project dependencies are NOT imported.
Run the suite orchestrator for a global all-fit -> repeat -> test barrier.
Individual CLI runs are useful for smoke tests and declared ablations.
"""
from __future__ import annotations
import argparse
import os
import sys
def _bootstrap() -> None:
    p = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    p.add_argument("--threads", type=int, default=4)
    ns, _ = p.parse_known_args()
    if ns.threads < 1:
        raise SystemExit("--threads must be >= 1")
    desired = {
        "PYTHONHASHSEED": "0",
        "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
        "NVIDIA_TF32_OVERRIDE": "0",
        "TORCH_ALLOW_TF32_CUBLAS_OVERRIDE": "0",
        "OMP_NUM_THREADS": str(ns.threads),
        "MKL_NUM_THREADS": str(ns.threads),
        "OPENBLAS_NUM_THREADS": str(ns.threads),
        "NUMEXPR_NUM_THREADS": str(ns.threads),
        "TORCHINDUCTOR_COMPILE_THREADS": "1",
    }
    if any(os.environ.get(k) != v for k, v in desired.items()):
        env = os.environ.copy()
        env.update(desired)
        os.execve(sys.executable, [sys.executable, *sys.argv], env)

if __name__ == "__main__": _bootstrap()

import contextlib
import gc
import hashlib
import json
import math
import platform
import random
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Iterator
import numpy as np
import pandas as pd
import scipy
import sklearn
import torch
import models
import metrics as metrics_module
from contracts import SCHEMA, require, sources, load_json, seal, check_seal, seed_rows
from data_loaders import (open_cache, open_fit_cache, load_preprocessing,
                          _stable_regular_file, _same_file_snapshot)

def json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")

def digest_json(value: Any) -> str:
    return hashlib.sha256(json_bytes(value)).hexdigest()

def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def array_sha256(a: np.ndarray) -> str:
    a = np.ascontiguousarray(a)
    h = hashlib.sha256(json_bytes({"shape": list(a.shape), "dtype": a.dtype.str}))
    h.update(memoryview(a).cast("B"))
    return h.hexdigest()

def tree_digest(value: Any) -> str:
    """Semantic hash; independent of torch.save ZIP timestamps/storage IDs."""
    h = hashlib.sha256()

    def visit(v: Any) -> None:
        if isinstance(v, torch.Tensor):
            x = v.detach().cpu().contiguous()
            h.update(b"tensor" + json_bytes([str(x.dtype), list(x.shape)]))
            h.update(x.reshape(-1).view(torch.uint8).numpy().tobytes())
        elif isinstance(v, np.ndarray):
            h.update(b"array" + array_sha256(v).encode())
        elif isinstance(v, dict):
            h.update(b"dict[")
            for key in sorted(v, key=lambda x: (type(x).__name__, repr(x))):
                visit(key)
                visit(v[key])
            h.update(b"]")
        elif isinstance(v, (list, tuple)):
            h.update(type(v).__name__.encode() + b"[")
            for item in v:
                visit(item)
            h.update(b"]")
        else:
            h.update(type(v).__name__.encode() + b":" + json_bytes(v) + b";")
    visit(value)
    return h.hexdigest()

def cpu_tree(v: Any) -> Any:
    if isinstance(v, torch.Tensor):
        return v.detach().cpu().clone()
    if isinstance(v, dict):
        return {k: cpu_tree(x) for k, x in v.items()}
    if isinstance(v, list):
        return [cpu_tree(x) for x in v]
    if isinstance(v, tuple):
        return tuple(cpu_tree(x) for x in v)
    return v

def atomic_write(path: Path, writer: Callable[[Any], None]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            writer(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                         allow_nan=False).encode("utf-8") + b"\n"
    atomic_write(path, lambda f: f.write(payload))

def save_checkpoint(path: Path, state: dict[str, Any]) -> None:
    state = cpu_tree(state)
    state["payload_digest"] = tree_digest(state)
    atomic_write(path, lambda f: torch.save(state, f))

def load_checkpoint(path: Path, fingerprint: str, *, execution_identity=None) -> dict[str, Any]:
    # Only tensor/primitive payloads generated by this program are supported.
    descriptor, before = _stable_regular_file(path)
    with os.fdopen(descriptor, "rb") as stream:
        state = torch.load(stream, map_location="cpu", weights_only=True)
        after = os.fstat(stream.fileno())
    require(_same_file_snapshot(before, after), "Checkpoint changed while loading")
    expected = state.pop("payload_digest", None)
    if expected != tree_digest(state):
        raise RuntimeError(f"Checkpoint integrity failure: {path}")
    if state.get("fingerprint") != fingerprint or state.get("schema") != SCHEMA:
        raise RuntimeError(f"Checkpoint belongs to another protocol/environment: {path}")
    if execution_identity is not None:
        require(state.get("execution_identity") == execution_identity,
                "Checkpoint belongs to a different execution namespace")
    return state

@contextlib.contextmanager
def output_lock(path: Path) -> Iterator[None]:
    """Process-scoped advisory lock; released by the OS after a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        f.seek(0, 2)
        if f.tell() == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise RuntimeError(f"Another process holds output lock: {path}") from e
        try:
            yield
        finally:
            f.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def configure_runtime(device: str, threads: int) -> tuple[torch.device, dict[str, Any]]:
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable. Install a CUDA-enabled PyTorch "
                           "build and working NVIDIA driver, or explicitly use --device cpu.")
    dev = torch.device(device)
    if dev.type == "cuda":
        torch.cuda.set_device(0)
    torch.set_num_threads(threads)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True, warn_only=False)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    # Do not mix the new precision API with legacy allow_tf32 setters.
    if hasattr(torch.backends, "fp32_precision"):
        torch.backends.fp32_precision = "ieee"
        torch.backends.cuda.matmul.fp32_precision = "ieee"
        torch.backends.cudnn.fp32_precision = "ieee"
        precision_api = "fp32_precision=ieee"
    else:
        torch.set_float32_matmul_precision("highest")
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        precision_api = "legacy_tf32_disabled"
    if hasattr(torch.utils, "deterministic"):
        torch.utils.deterministic.fill_uninitialized_memory = True
    env = {
        "python": sys.version, "platform": platform.platform(),
        "machine": platform.machine(), "processor": platform.processor(),
        "torch": str(torch.__version__), "cuda_build": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(), "numpy": np.__version__,
        "pandas": pd.__version__, "scipy": scipy.__version__,
        "sklearn": sklearn.__version__, "device": str(dev),
        "threads": threads, "interop_threads": 1, "precision_api": precision_api,
        "deterministic_algorithms": True, "warn_only": False,
        "torch_build_config": torch.__config__.show(),
        "environment": {k: v for k, v in sorted(os.environ.items())
                        if k.startswith(("CUBLAS_", "CUDA_", "CUDNN_", "TORCH_", "TORCHINDUCTOR_"))
                        or k in {"NVIDIA_TF32_OVERRIDE", "PYTHONHASHSEED", "OMP_NUM_THREADS",
                                 "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"}},
    }
    if dev.type == "cuda":
        prop = torch.cuda.get_device_properties(dev)
        env["gpu"] = {"name": prop.name, "capability": [prop.major, prop.minor],
                      "sm_count": prop.multi_processor_count, "total_memory": prop.total_memory}
        try:
            fields = ("driver_version", "uuid", "pci.bus_id", "vbios_version",
                      "power.limit", "power.default_limit", "power.max_limit",
                      "clocks.max.sm", "clocks.max.memory", "persistence_mode")
            r = subprocess.run([
                "nvidia-smi", "--query-gpu=" + ",".join(fields),
                "--format=csv,noheader,nounits",
            ], text=True, capture_output=True, check=True, timeout=10)
            rows = r.stdout.strip().splitlines()
            require(len(rows) == 1, "Formal runtime requires exactly one visible GPU")
            values = [value.strip() for value in rows[0].split(",")]
            require(len(values) == len(fields), "Unexpected static GPU evidence schema")
            env["gpu_runtime"] = dict(zip(fields, values))
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("Static NVIDIA runtime evidence unavailable") from exc
    return dev, env

def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

def capture_rng(order_rng: torch.Generator, device: torch.device) -> dict[str, Any]:
    ns = np.random.get_state()
    return {"python": random.getstate(), "numpy": [ns[0], ns[1].tolist(), ns[2], ns[3], ns[4]],
            "torch": torch.get_rng_state(), "order": order_rng.get_state(),
            "cuda": torch.cuda.get_rng_state(device) if device.type == "cuda" else None}

def restore_rng(state: dict[str, Any], order_rng: torch.Generator, device: torch.device) -> None:
    random.setstate(state["python"])
    ns = state["numpy"]
    np.random.set_state((ns[0], np.asarray(ns[1], dtype=np.uint32), ns[2], ns[3], ns[4]))
    torch.set_rng_state(state["torch"])
    order_rng.set_state(state["order"])
    if device.type == "cuda":
        torch.cuda.set_rng_state(state["cuda"], device)

def batch_slices(n: int, batch_size: int, training: bool = False) -> list[tuple[int, int]]:
    if n < 1 or batch_size < 1 or (training and (n < 2 or batch_size < 2)):
        raise ValueError("Invalid sample/batch count (BatchNorm training needs >=2)")
    out, start = [], 0
    while start < n:
        end = min(n, start + batch_size)
        if training and n - end == 1:
            end = n  # merge singleton tail, never drop a row or duplicate a label
        out.append((start, end))
        start = end
    return out

@dataclass
class Data:
    x_fit: torch.Tensor
    y_fit: torch.Tensor
    x_val: torch.Tensor
    y_val: torch.Tensor
    x_test: torch.Tensor | None
    y_test: torch.Tensor | None
    names: list[str]
    weights: torch.Tensor
    weighting: dict[str, Any]
    metadata: dict[str, Any]
    indices: dict[str, np.ndarray]

def build_model(kind, seed, data, args):
    set_seed(seed)
    return models.build(kind, data.x_fit.shape[1], len(data.names), args.hidden, args.levels, args.qcfs_formula)


def class_weight_policy(y_fit: np.ndarray, class_names: list[str], scheme: str) -> tuple[np.ndarray, dict[str, Any]]:
    counts = np.bincount(y_fit, minlength=len(class_names)).astype(np.int64)
    require(counts.shape == (len(class_names),) and (counts > 0).all(),
            "Fit split is missing a declared class")
    if scheme == "sqrt_inverse_fit_only_v1":
        raw = np.reciprocal(np.sqrt(counts.astype(np.float64)))
    elif scheme == "unweighted_fit_only_v1":
        raw = np.ones(len(counts), dtype=np.float64)
    elif scheme == "inverse_fit_only_legacy_v1":
        raw = np.reciprocal(counts.astype(np.float64))
    else:
        raise ValueError(f"Unknown class-weight policy: {scheme}")
    weights = np.asarray(raw / raw.sum() * len(counts), dtype=np.float32)
    require(np.isfinite(weights).all() and (weights > 0).all(), "Invalid class weights")
    policy = {"scheme": scheme, "source": "fit labels only",
              "normalization": "sum_to_number_of_classes",
              "class_names": class_names, "fit_class_counts": counts.tolist(),
              "weights_float32": weights.tolist(), "weights_sha256": array_sha256(weights)}
    return weights, policy


def prepare_data(args, *, include_test: bool = True):
    meta, arrays = (open_cache if include_test else open_fit_cache)(args.cache)
    require(meta["dataset"] == args.dataset, "Prepared cache belongs to another dataset")
    prep = load_preprocessing(args.cache, meta)
    y_fit = arrays["y_fit"]
    weights, weighting = class_weight_policy(y_fit, meta["class_names"], args.loss_weighting)
    tensors = [torch.from_numpy(arrays[name]) for name in
               ("x_fit", "y_fit", "x_validation", "y_validation")]
    test_tensors = ([torch.from_numpy(arrays[name]) for name in ("x_test", "y_test")]
                    if include_test else [None, None])
    return Data(*tensors, *test_tensors, meta["class_names"], torch.from_numpy(weights), weighting,
                {**meta, "preprocessor": prep},
                {s: arrays["ids_"+s] for s in
                 (("fit", "validation", "test") if include_test else ("fit", "validation"))})


def place_data(data: Data, device: torch.device, placement: str, reserve_gib: float) -> None:
    keys = ["x_fit", "y_fit", "x_val", "y_val"]
    if data.x_test is not None or data.y_test is not None:
        require(data.x_test is not None and data.y_test is not None,
                "Test tensors must be jointly present or absent")
        keys.extend(("x_test", "y_test"))
    if device.type == "cuda" and placement == "gpu":
        tensors = [getattr(data, k) for k in keys]
        need = sum(t.numel() * t.element_size() for t in tensors)
        # Includes a full training permutation copy; model/activation headroom is reserved separately.
        need += data.x_fit.numel() * 4 + data.y_fit.numel() * 16
        free, _ = torch.cuda.mem_get_info(device)
        if need + reserve_gib * 1024**3 > free:
            raise RuntimeError("Insufficient free VRAM for declared residency + reserve. "
                               "Close GPU applications or explicitly use --data-placement cpu; "
                               "batch size is never silently changed.")
        for k in keys:
            setattr(data, k, getattr(data, k).to(device))
    elif device.type == "cuda":
        for k in keys:
            setattr(data, k, getattr(data, k).pin_memory())
    data.weights = data.weights.to(device)

def shuffled_epoch(data: Data, order_rng: torch.Generator) -> tuple[torch.Tensor, torch.Tensor, str]:
    order = torch.randperm(len(data.y_fit), generator=order_rng, device="cpu")
    order_hash = array_sha256(order.numpy())
    if data.x_fit.device.type == "cuda":
        order = order.to(data.x_fit.device)
        return data.x_fit.index_select(0, order), data.y_fit.index_select(0, order), order_hash
    if data.x_fit.is_pinned():
        x = torch.empty(data.x_fit.shape, dtype=data.x_fit.dtype, pin_memory=True)
        y = torch.empty(data.y_fit.shape, dtype=data.y_fit.dtype, pin_memory=True)
        torch.index_select(data.x_fit, 0, order, out=x)
        torch.index_select(data.y_fit, 0, order, out=y)
        return x, y, order_hash
    return data.x_fit.index_select(0, order), data.y_fit.index_select(0, order), order_hash

@torch.inference_mode()
def predict_logits(model, x, batch, device):
    model.eval()
    output = None
    for a, b in batch_slices(len(x), batch):
        chunk = model(x[a:b].to(device, non_blocking=True))
        require(chunk.ndim == 2, "Expected (N,C) logits")
        if output is None:
            output = torch.empty((len(x), chunk.shape[1]), device=device, dtype=chunk.dtype)
        output[a:b].copy_(chunk)
    return output


def validation_score(model: torch.nn.Module, data: Data, batch: int,
                     device: torch.device) -> float:
    logits = predict_logits(model, data.x_val, batch, device).cpu().numpy()
    if logits.shape[1] != len(data.names) or not np.isfinite(logits).all():
        raise RuntimeError("Invalid validation logits")
    y = data.y_val.cpu().numpy()
    pred = logits.argmax(axis=1)
    cm = np.bincount(len(data.names) * y + pred, minlength=len(data.names)**2).reshape(len(data.names), -1)
    return float(np.mean(np.diag(cm) / cm.sum(axis=1)) * 100.0)

def validate_model_state(model: torch.nn.Module, models: Any, expected_levels: int) -> dict[str, torch.Tensor]:
    state = cpu_tree(model.state_dict())
    if any(v.is_floating_point() and not bool(torch.isfinite(v).all()) for v in state.values()):
        raise RuntimeError("Non-finite parameter or buffer; experiment aborted")
    for name, m in model.named_modules():
        if isinstance(m, models.QCFS):
            threshold = float(state[name + ".threshold"])
            levels = float(state[name + ".L"])
            if threshold <= 0 or levels != expected_levels:
                raise RuntimeError("QCFS threshold must stay positive and L must match the declared protocol; "
                                   "no silent clamping/reparameterization is applied")
            if hasattr(m, "_levels") and m._levels != levels:
                raise RuntimeError("Cached QCFS level differs from its registered buffer")
    return state

def make_optimizer(model: torch.nn.Module, args: argparse.Namespace) -> torch.optim.Optimizer:
    return torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay,
                            foreach=args.optimizer == "foreach", fused=args.optimizer == "fused")

def train_one(kind: str, seed: int, data: Data, models: Any, args: argparse.Namespace,
              device: torch.device, fingerprint: str, checkpoint: Path,
              *, stop_after: int | None = None) -> dict[str, Any]:
    """stop_after is a test-only fault-injection hook; CLI never changes epoch budget."""
    model = build_model(kind, seed, data, args).to(device)
    optimizer = make_optimizer(model, args)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    criterion = torch.nn.CrossEntropyLoss(weight=data.weights)
    order_rng = torch.Generator(device="cpu").manual_seed(seed)
    history: list[dict[str, Any]] = []
    best_score, best_epoch, best_state = -math.inf, 0, None
    begin = 0
    elapsed_previous = 0.0
    if checkpoint.exists():
        if not args.resume:
            raise RuntimeError(f"Checkpoint exists; use --resume: {checkpoint}")
        old = load_checkpoint(checkpoint, fingerprint,
                              execution_identity=getattr(args, "execution_identity", None))
        if old["kind"] != kind or old["seed"] != seed:
            raise RuntimeError("Checkpoint run identity mismatch")
        model.load_state_dict(old["model"], strict=True)
        optimizer.load_state_dict(old["optimizer"])
        scheduler.load_state_dict(old["scheduler"])
        history = old["history"]
        best_score = old["best_score"] if old["best_score"] is not None else -math.inf
        best_epoch, best_state = old["best_epoch"], old["best_model"]
        begin, elapsed_previous = old["epoch"], old["elapsed_seconds"]
        if not 0 <= begin <= args.epochs or len(history) != begin:
            raise RuntimeError("Invalid checkpoint epoch/history")
        restore_rng(old["rng"], order_rng, device)
        if begin == args.epochs:
            return old["fit_result"]
    runtime_model = torch.compile(model, fullgraph=True, dynamic=False) if args.compile else model
    thresholds = [m.threshold for m in model.modules() if isinstance(m, models.QCFS)]
    slices = batch_slices(len(data.y_fit), args.batch_size, training=True)
    started = time.perf_counter()
    for epoch in range(begin, args.epochs):
        runtime_model.train()
        x, y, order_hash = shuffled_epoch(data, order_rng)
        losses, threshold_trace = [], []
        lr_used = float(optimizer.param_groups[0]["lr"])
        for a, b in slices:
            if thresholds:
                threshold_trace.append(torch.stack(thresholds).detach())
            optimizer.zero_grad(set_to_none=True)
            logits = runtime_model(x[a:b].to(device, non_blocking=True))
            loss = criterion(logits, y[a:b].to(device, non_blocking=True))
            loss.backward()
            optimizer.step()
            losses.append(loss.detach())
        if thresholds:
            threshold_trace.append(torch.stack(thresholds).detach())
        loss_values = torch.stack(losses)
        finite = torch.isfinite(loss_values).all()
        if thresholds:
            trace = torch.stack(threshold_trace)
            finite = finite & torch.isfinite(trace).all() & (trace > 0).all()
        diagnostics = torch.stack((loss_values.mean(), finite.to(loss_values.dtype))).cpu().tolist()
        if diagnostics[1] != 1 or not math.isfinite(diagnostics[0]):
            raise RuntimeError(f"{kind} seed={seed} epoch={epoch+1}: non-finite loss or invalid QCFS threshold")
        scheduler.step()
        # Validate once per epoch, not once per parameter per CUDA batch.
        model_state = validate_model_state(model, models, args.levels)
        entry = {"epoch": epoch + 1, "lr_used": lr_used, "mean_batch_loss": diagnostics[0],
                 "order_sha256": order_hash, "validation_macro_recall_pct": None}
        check = (epoch + 1) % args.eval_every == 0 or epoch + 1 == args.epochs
        if check:
            score = validation_score(model, data, args.eval_batch_size, device)
            entry["validation_macro_recall_pct"] = score
            if args.checkpoint_policy == "best_validation_macro_recall_legacy_v1" and score > best_score:
                best_score, best_epoch, best_state = score, epoch + 1, model_state
            elif args.checkpoint_policy == "fixed_final_epoch_v1" and epoch + 1 == args.epochs:
                best_score, best_epoch, best_state = score, epoch + 1, model_state
            print(f"  {kind} seed={seed} epoch={epoch+1}/{args.epochs} "
                  f"val_macro_recall={score:.6f}% selected_epoch={best_epoch}", flush=True)
        history.append(entry)
        elapsed = elapsed_previous + time.perf_counter() - started
        fit_result = None
        if epoch + 1 == args.epochs:
            if best_state is None:
                raise RuntimeError("No finite validation checkpoint was selected")
            stable = {"seed": seed, "kind": kind, "best_epoch": best_epoch,
                      "best_validation_macro_recall_pct": best_score,
                      "best_state_sha256": tree_digest(best_state),
                      "final_state_sha256": tree_digest(model_state),
                      "optimizer_state_sha256": tree_digest(optimizer.state_dict()),
                      "scheduler_state_sha256": tree_digest(scheduler.state_dict()),
                      "rng_state_sha256": tree_digest(capture_rng(order_rng, device)),
                      "history": history}
            fit_result = {**stable, "training_reproducibility_sha256": digest_json(stable),
                          "elapsed_seconds": elapsed, "fit_complete": True}
        if check or (epoch + 1) % args.checkpoint_every == 0 or stop_after == epoch + 1:
            save_checkpoint(checkpoint, {
                "schema": SCHEMA, "fingerprint": fingerprint, "kind": kind, "seed": seed,
                "execution_identity": getattr(args, "execution_identity", None),
                "epoch": epoch + 1, "model": model_state, "optimizer": optimizer.state_dict(),
                "scheduler": scheduler.state_dict(), "rng": capture_rng(order_rng, device),
                "history": history, "best_model": best_state,
                # -Infinity cannot be serialized/hashes as valid JSON. No-selection is explicit.
                "best_score": best_score if best_state is not None else None,
                "best_epoch": best_epoch, "elapsed_seconds": elapsed, "fit_result": fit_result,
            })
        del x, y, losses, threshold_trace, loss_values, model_state
        if stop_after == epoch + 1 and epoch + 1 < args.epochs:
            raise InterruptedError("Injected interruption after a completed epoch")
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    return fit_result

def evaluate_one(kind: str, seed: int, data: Data, models: Any, metrics_module: Any,
                 args: argparse.Namespace, device: torch.device, fingerprint: str,
                 checkpoint: Path, artifacts: Path) -> dict[str, Any]:
    require(data.x_test is not None and data.y_test is not None,
            "Test tensors are unavailable before the explicit evaluation stage")
    state = load_checkpoint(checkpoint, fingerprint,
                            execution_identity=getattr(args, "execution_identity", None))
    if state["epoch"] != args.epochs or not state.get("fit_result"):
        raise RuntimeError("Test evaluation requires a completed fixed-budget fit")
    model = build_model(kind, seed, data, args).to(device)
    model.load_state_dict(state["best_model"], strict=True)
    validate_model_state(model, models, args.levels)
    with torch.inference_mode():
        logits_device = predict_logits(model, data.x_test, args.eval_batch_size, device)
        probabilities = torch.softmax(logits_device, dim=1).cpu().numpy()
        logits = logits_device.cpu().numpy()
    y_true = data.y_test.cpu().numpy()
    if logits.shape != (len(y_true), len(data.names)) or not np.isfinite(logits).all():
        raise RuntimeError("Invalid test logits")
    if (not np.isfinite(probabilities).all() or np.any(probabilities < 0)
            or not np.allclose(probabilities.sum(axis=1), 1.0, rtol=1e-5, atol=1e-6)):
        raise RuntimeError("Invalid probabilities; ROC-AUC must not hide this error")
    y_pred = logits.argmax(axis=1).astype(np.int64)
    metrics = metrics_module.full_evaluate(y_true, y_pred, probabilities, len(data.names), data.names)
    json_bytes(metrics)  # fail closed on NaN/Infinity anywhere in the metric output
    if set(metrics["per_class"]) != set(data.names):
        raise RuntimeError("Metric class-name mismatch")
    cm = np.asarray(metrics["confusion_matrix"], dtype=np.int64)
    expected_cm = np.bincount(len(data.names) * y_true + y_pred,
                              minlength=len(data.names)**2).reshape(len(data.names), -1)
    if not np.array_equal(cm, expected_cm):
        raise RuntimeError("Shared metrics returned an inconsistent confusion matrix")
    if not np.isclose(metrics["macro_acc"], metrics["balanced_acc"], rtol=0, atol=1e-10):
        raise RuntimeError("Macro recall/balanced accuracy disagreement")
    reproducibility = {"training_sha256": state["fit_result"]["training_reproducibility_sha256"],
                       "logits_sha256": array_sha256(logits),
                       "probabilities_sha256": array_sha256(probabilities),
                       "predictions_sha256": array_sha256(y_pred),
                       "labels_sha256": array_sha256(y_true), "metrics_sha256": digest_json(metrics)}
    result = {**metrics, "seed": seed, "kind": kind, "best_epoch": state["best_epoch"],
              "best_validation_macro_recall_pct": state["best_score"],
              "reproducibility": reproducibility, "test_evaluated": True,
              "batch_order_sha256": digest_json([h["order_sha256"] for h in state["history"]]),
              "best_state_sha256": state["fit_result"]["best_state_sha256"]}
    atomic_write(artifacts, lambda f: np.savez(f, logits=logits, probabilities=probabilities,
                                              y_true=y_true, y_pred=y_pred))
    result["artifact"] = {"filename": artifacts.name, "sha256": file_sha256(artifacts)}
    return result

def parser():
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--dataset", required=True, choices=("nslkdd","unsw","cicids2017","iot23"))
    p.add_argument("--cache", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--seeds", type=int, nargs="+", default=list(range(20)))
    p.add_argument("--model", choices=("relu","qcfs","cnn"), required=True)
    p.add_argument("--epochs", type=int)
    p.add_argument("--batch-size", type=int)
    p.add_argument("--eval-batch-size", type=int, default=4096)
    p.add_argument("--eval-every", type=int, default=10)
    p.add_argument("--checkpoint-every", type=int, default=10)
    p.add_argument("--hidden", type=int, default=256)
    p.add_argument("--levels", type=int, default=4)
    p.add_argument("--qcfs-formula", choices=("shifted_v1","legacy_floor_v1"), default="shifted_v1")
    p.add_argument("--lr", type=float, default=.001)
    p.add_argument("--weight-decay", type=float, default=.00001)
    p.add_argument("--device", choices=("cpu","cuda"), default="cuda")
    p.add_argument("--optimizer", choices=("single","foreach","fused"), default="single")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--data-placement", choices=("cpu","gpu"), default="gpu")
    p.add_argument("--vram-reserve-gib", type=float, default=2.)
    p.add_argument("--compile", action="store_true")
    p.add_argument("--loss-weighting",
                   choices=("sqrt_inverse_fit_only_v1", "unweighted_fit_only_v1",
                            "inverse_fit_only_legacy_v1"),
                   default="sqrt_inverse_fit_only_v1")
    p.add_argument("--checkpoint-policy",
                   choices=("fixed_final_epoch_v1", "best_validation_macro_recall_legacy_v1"),
                   default="fixed_final_epoch_v1")
    p.add_argument("--stage", choices=("fit","evaluate","all"), default="fit")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--formal-plan", type=Path)
    p.add_argument("--formal-execution", choices=("primary", "replica"))
    p.add_argument("--fit-verification", type=Path)
    return p


def validate_args(args):
    require(args.seeds and len(args.seeds) <= 100 and len(set(args.seeds)) == len(args.seeds)
            and all(0 <= s < 2**32 for s in args.seeds), "Unique seeds in [0,2**32), at most100, required")
    args.seeds = sorted(args.seeds)
    if args.epochs is None: args.epochs = 40 if args.dataset == "iot23" else 80
    if args.batch_size is None: args.batch_size = 1024 if args.dataset == "iot23" else 512
    for key in ("epochs","eval_batch_size","eval_every","checkpoint_every","levels","threads"):
        require(getattr(args,key) >= 1, f"Invalid {key}")
    require(args.batch_size >= 2 and args.hidden >= 2, "Batch and hidden width must be >=2")
    require(all(math.isfinite(v) for v in (args.lr,args.weight_decay,args.vram_reserve_gib))
            and args.lr > 0 and args.weight_decay >= 0 and args.vram_reserve_gib >= 0, "Invalid numeric hyperparameter")
    require(not (args.dataset == "iot23" and args.model == "cnn"), "IoT CNN is outside this declared suite")
    require(args.output.suffix == ".json", "Output filename must end in .json")
    require(not args.compile, "Compiled training is not part of this validated baseline. Benchmark single/foreach/fused first.")
    if args.device == "cpu": args.data_placement = "cpu"
    args.output = args.output.resolve(); args.cache = args.cache.resolve()
    require((args.formal_plan is None) == (args.formal_execution is None),
            "Formal plan and execution role must be supplied together")
    require(args.fit_verification is None or args.formal_plan is not None,
            "A fit-verification artifact is valid only for a formal job")
    if args.formal_plan is not None:
        args.formal_plan = args.formal_plan.resolve()
        require(args.stage != "all", "Formal jobs forbid the single-job fit-and-test stage")
        require((args.stage == "evaluate") == (args.fit_verification is not None),
                "Formal evaluation requires exactly one explicit fit-verification artifact")
        if args.fit_verification is not None:
            args.fit_verification = args.fit_verification.resolve()


def formal_contract(args, protocol, data_fingerprint, environment):
    if args.formal_plan is None:
        return None, None
    from evidence import read_plan
    from suite import validate_plan_data_evidence
    plan = read_plan(args.formal_plan.parent)
    validate_plan_data_evidence(plan)
    require(plan.get("schema") == SCHEMA and plan.get("sources") == sources(),
            "Formal plan schema/source binding differs from the executing code")
    require(plan.get("environment") == environment,
            "Formal runtime environment differs from the frozen plan")
    run_dir = args.formal_plan.parent
    require(args.formal_plan == run_dir / "plan.json", "Formal plan must be the run directory plan.json")
    job_id = f"{args.dataset}_{args.model}"
    jobs = [row for row in plan.get("jobs", []) if row.get("id") == job_id]
    require(len(jobs) == 1, "Formal plan does not contain exactly one matching job")
    job = jobs[0]
    folder = "results" if args.formal_execution == "primary" else "replicas"
    require(args.output == (run_dir / folder / f"{job_id}.json").resolve(),
            "Formal output path/role differs from the sealed plan")
    require(Path(job["cache"]).resolve() == args.cache and
            job.get("data_fingerprint") == data_fingerprint,
            "Formal cache identity differs from the sealed job")
    for key, value in job.get("hyperparameters", {}).items():
        require(protocol.get(key) == value, f"Formal job parameter changed: {key}")
    formal = {"plan_sha256": plan["content_sha256"], "job_id": job_id,
              "execution": args.formal_execution}
    verification = None
    if args.stage == "evaluate":
        expected = (run_dir / "verification_fit.json").resolve()
        require(args.fit_verification == expected, "Formal evaluation used the wrong fit-verification path")
        verification = load_json(expected); check_seal(verification)
        expected_jobs = {row["id"] for row in plan["jobs"]}
        require(verification.get("passed") is True and
                verification.get("plan_sha256") == plan["content_sha256"] and
                set(verification.get("jobs", {})) == expected_jobs,
                "Formal global fit barrier is missing, stale, or incomplete")
        from evidence import validate_global_fit_barrier
        validate_global_fit_barrier(run_dir, plan, verification)
    return formal, verification


def main():
    if "--probe" in sys.argv:
        p = argparse.ArgumentParser(allow_abbrev=False)
        p.add_argument("--probe", action="store_true")
        p.add_argument("--device", choices=("cuda","cpu"), required=True)
        p.add_argument("--threads", type=int, required=True)
        p.add_argument("--output", type=Path, required=True)
        a = p.parse_args()
        _, env = configure_runtime(a.device, a.threads)
        write_json(a.output, env)
        return
    args = parser().parse_args(); validate_args(args)
    dev, environment = configure_runtime(args.device,args.threads)
    out, work = args.output, args.output.with_suffix("")
    with output_lock(out.with_suffix(".lock")):
        manifest_path = work / "manifest.json"
        require(args.resume or not (out.exists() or manifest_path.exists()), "Existing run: use --resume or a fresh output")
        require(args.stage != "evaluate" or (args.resume and manifest_path.exists()), "Evaluation requires an existing completed fit and --resume")
        # Fit processes do not retain test tensors in host or GPU memory.  The
        # evaluate process materializes them only after the sealed global fit
        # barrier has passed.
        data = prepare_data(args, include_test=False)
        protocol = {k: getattr(args,k) for k in ("dataset","model","seeds","epochs","batch_size","eval_batch_size",
                     "eval_every","checkpoint_every","hidden","levels","qcfs_formula","lr","weight_decay",
                     "device","optimizer","threads","data_placement","vram_reserve_gib",
                     "compile","loss_weighting",
                     "checkpoint_policy")}
        protocol.update(precision="IEEE FP32; AMP/TF32 off",
                        selection=("fixed final epoch; validation is diagnostic only"
                                   if args.checkpoint_policy == "fixed_final_epoch_v1"
                                   else "best validation macro recall; earliest exact tie"),
                        singleton_tail="merge into previous batch; no dropped samples")
        formal, fit_verification = formal_contract(
            args, protocol, data.metadata["data_fingerprint"], environment,
        )
        scientific_formal = ({k: formal[k] for k in ("plan_sha256", "job_id")}
                             if formal is not None else None)
        binding = {"schema": SCHEMA, "protocol": protocol, "environment": environment,
                   "sources": sources(), "data_fingerprint": data.metadata["data_fingerprint"],
                   "formal": scientific_formal, "weighting": data.weighting}
        fingerprint = digest_json(binding)
        if manifest_path.exists():
            previous = load_json(manifest_path); check_seal(previous)
            require(previous["binding"] == binding and previous["fingerprint"] == fingerprint,
                    "Resume rejected: source, software, hardware, protocol, or data changed")
        else:
            require(not out.exists() and not work.exists(),
                    "Execution ledger is missing for an existing output namespace; refusing reset")
            previous = {"fingerprint": fingerprint, "binding": binding, "formal": formal,
                        "test_sessions_started": 0, "test_sessions_completed": 0,
                        "execution_identity": {
                            "execution_id": secrets.token_hex(16),
                            "output_path": str(out), "formal": formal,
                        }}
            write_json(manifest_path,seal(previous))
        previous.pop("content_sha256",None)
        identity = previous.get("execution_identity")
        require(isinstance(identity, dict) and set(identity) ==
                {"execution_id", "output_path", "formal"} and
                isinstance(identity.get("execution_id"), str) and
                len(identity["execution_id"]) == 32 and
                identity["output_path"] == str(out) and identity["formal"] == formal,
                "Execution ledger identity is missing or bound to another output")
        args.execution_identity = identity
        require(previous.get("formal") == formal, "Formal execution role/path binding changed")
        require(type(previous.get("test_sessions_started")) is int and
                type(previous.get("test_sessions_completed")) is int and
                0 <= previous["test_sessions_completed"] <= previous["test_sessions_started"],
                "Invalid test-session counters")
        if formal is not None:
            require(previous["test_sessions_started"] == 0 and
                    previous["test_sessions_completed"] == 0,
                    "Formal output has already opened test; use a fresh run namespace")
        if args.stage != "evaluate":
            place_data(data,dev,args.data_placement,args.vram_reserve_gib)
        run_dir=work/"runs"; run_dir.mkdir(parents=True,exist_ok=True)
        pairing = {"ids_sha256": {s:data.metadata["files_sha256"][f"ids_{s}.npy"] for s in ("fit","validation","test")},
                   "preprocessor_sha256":data.metadata["preprocessor_sha256"], "raw_binding_sha256":digest_json(data.metadata["raw_binding"])}
        output = {"schema":SCHEMA,"dataset":args.dataset,"kind":args.model,"protocol":protocol,
                  "environment":environment,"fingerprint":fingerprint,"data_fingerprint":data.metadata["data_fingerprint"],
                  "pairing_contract":pairing,"class_names":data.names,"counts":data.metadata["counts"],
                  "official_train_raw_rows":data.metadata["official_train_raw_rows"],
                  "n_train_validation_patterns":data.metadata["n_train_validation_patterns"],
                  "scope":data.metadata["scope"],
                  "cache_path":str(args.cache),"fit_runs":[],"per_seed":[],"status":"fitting",
                  "test_previously_exposed":previous["test_sessions_started"]>0,
                  "formal":formal, "weighting":data.weighting,
                  "execution_identity":identity,
                  "model_semantics":"quantized ANN" if args.model=="qcfs" else "ANN",
                  "snn_conversion_validated":False}
        for seed in args.seeds:
            cp=run_dir/f"{args.model}_seed_{seed}.pt"
            if args.stage=="evaluate":
                state=load_checkpoint(cp,fingerprint,execution_identity=identity)
                require(state["epoch"]==args.epochs and state.get("fit_result"),"All fits must complete before test")
                result=state["fit_result"]
            else:
                result=train_one(args.model,seed,data,models,args,dev,fingerprint,cp)
            output["fit_runs"].append(result)
            write_json(out,seal(output))
        output["training_digest"] = digest_json([r["training_reproducibility_sha256"] for r in output["fit_runs"]])
        output["status"]="fit_complete"
        write_json(out,seal(output))
        if args.stage != "evaluate":
            for snapshot_path, snapshot in (
                    (work/"fit_evidence.json", seal(output)),
                    (work/"fit_manifest.json", seal(previous))):
                if snapshot_path.exists():
                    require(load_json(snapshot_path) == snapshot,
                            "Immutable fit snapshot changed during resume")
                else:
                    write_json(snapshot_path, snapshot)
        if args.stage=="fit":
            print("FIT COMPLETE",out,"test previously exposed:",output["test_previously_exposed"],flush=True)
            return
        if formal is not None:
            require(fit_verification["jobs"].get(formal["job_id"]) == output["training_digest"],
                    "Formal job training digest differs from the global fit barrier")
        previous["test_sessions_started"] += 1
        write_json(manifest_path,seal(previous))
        # Only this point can materialize test arrays. Formal evaluation has
        # already checked all independent fit snapshots and current checkpoints.
        del data
        gc.collect()
        if dev.type == "cuda":
            torch.cuda.empty_cache()
        data = prepare_data(args, include_test=True)
        place_data(data,dev,args.data_placement,args.vram_reserve_gib)
        output["status"]="evaluating"
        for seed in args.seeds:
            cp=run_dir/f"{args.model}_seed_{seed}.pt"
            artifact=run_dir/f"{args.model}_seed_{seed}_predictions.npz"
            result=evaluate_one(args.model,seed,data,models,metrics_module,args,dev,fingerprint,cp,artifact)
            output["per_seed"].append(result)
            write_json(out,seal(output))
        output["aggregate"]=metrics_module.aggregate(output["per_seed"],data.names)
        output["scientific_digest"]=digest_json({"training":output["training_digest"],
                    "predictions":[r["reproducibility"] for r in output["per_seed"]]})
        output["status"]="complete"
        write_json(out,seal(output))
        previous["test_sessions_completed"] += 1
        write_json(manifest_path,seal(previous))
        print("COMPLETE",out,output["scientific_digest"],flush=True)

if __name__ == "__main__":
    try: main()
    except (ValueError,RuntimeError,FileNotFoundError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr,flush=True)
        raise SystemExit(2) from exc
