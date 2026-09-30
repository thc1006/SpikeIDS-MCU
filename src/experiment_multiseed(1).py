"""Leakage-safe, audited multi-seed ReLU/QCFS experiment (FP32, one device).

Drop into the existing project's src/ directory. Requires the project's
config.py, models.py and metrics.py. See README_zh-TW.md for the protocol
changes and the limits of reproducibility. No network access is performed.
"""
from __future__ import annotations

# These settings MUST precede NumPy/PyTorch imports and CUDA initialization.
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


if __name__ == "__main__":
    _bootstrap()

import ast
import contextlib
import gc
import hashlib
import importlib
import inspect
import json
import math
import platform
import random
import subprocess
import tempfile
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np
import pandas as pd
import scipy
import sklearn
import torch
from scipy.stats import rankdata, t as student_t
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, OrdinalEncoder, StandardScaler

SCHEMA = 1
ROOT = Path(__file__).resolve().parent.parent
SCALAR_KEYS = (
    "overall_acc", "macro_acc", "balanced_acc", "macro_precision", "macro_recall",
    "macro_f1", "weighted_precision", "weighted_recall", "weighted_f1", "mcc",
    "roc_auc_macro", "roc_auc_weighted",
)
COMPARISON_KEYS = ("overall_acc", "macro_acc", "macro_f1")
CAT_COLS = ("protocol_type", "service", "flag")
REFERENCE_COMMIT = "09d80cab3ef6caa2dadcb46e7637b113cd44619e"
# This guard prevents silently replacing a locally modified QCFS algorithm.
REFERENCE_QCFS_FORWARD = '''
def forward(self, x):
    step = self.threshold / self.L
    x_scaled = x / (step + 1e-8)
    x_clipped = torch.clamp(x_scaled, 0.0, self.L.item())
    x_floored = FloorSTE.apply(x_clipped)
    return x_floored * step
'''


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


def load_checkpoint(path: Path, fingerprint: str) -> dict[str, Any]:
    # Only tensor/primitive payloads generated by this program are supported.
    state = torch.load(path, map_location="cpu", weights_only=True)
    expected = state.pop("payload_digest", None)
    if expected != tree_digest(state):
        raise RuntimeError(f"Checkpoint integrity failure: {path}")
    if state.get("fingerprint") != fingerprint or state.get("schema") != SCHEMA:
        raise RuntimeError(f"Checkpoint belongs to another protocol/environment: {path}")
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
            r = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                               text=True, capture_output=True, check=True, timeout=10)
            env["driver"] = r.stdout.strip().splitlines()
        except (OSError, subprocess.SubprocessError):
            env["driver"] = "unavailable; record NVIDIA driver manually"
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


def load_dependencies() -> tuple[Any, Any, Any]:
    try:
        return tuple(importlib.import_module(n) for n in ("config", "models", "metrics"))
    except ImportError as e:
        raise RuntimeError("Place this file in the original project's src/ directory, "
                           "beside config.py, models.py and metrics.py.") from e


def _ast(source: str) -> str:
    return ast.dump(ast.parse(textwrap.dedent(source)), include_attributes=False)


def replace_qcfs(model: torch.nn.Module, models: Any) -> None:
    if _ast(inspect.getsource(models.QCFS.forward)) != _ast(REFERENCE_QCFS_FORWARD):
        raise RuntimeError("Local QCFS.forward differs from the reviewed implementation. "
                           "Use --qcfs-kernel original until its semantics are reviewed.")

    class CachedQCFS(models.QCFS):
        def __init__(self, L: float, init_threshold: float = 1.0):
            super().__init__(L=L, init_threshold=init_threshold)
            self._level_value = float(self.L.item())

        def _load_from_state_dict(self, *args: Any, **kwargs: Any) -> None:
            super()._load_from_state_dict(*args, **kwargs)
            # One synchronization at checkpoint loading, never in forward.
            self._level_value = float(self.L.item())

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            step = self.threshold / self.L
            x_scaled = x / (step + 1e-8)
            x_clipped = torch.clamp(x_scaled, 0.0, self._level_value)
            x_floored = models.FloorSTE.apply(x_clipped)
            return x_floored * step

    def walk(parent: torch.nn.Module) -> None:
        for name, child in list(parent.named_children()):
            if type(child) is models.QCFS:
                new = CachedQCFS(float(child.L.item()), float(child.threshold.detach().item()))
                new.load_state_dict(child.state_dict(), strict=True)
                new.train(child.training)
                setattr(parent, name, new)
            else:
                walk(child)
    walk(model)


def build_model(models: Any, kind: str, seed: int, input_dim: int, classes: int,
                hidden: int, kernel: str) -> torch.nn.Module:
    set_seed(seed)
    if kind == "relu":
        model = models.IDS_MLP(input_dim=input_dim, hidden=hidden, num_classes=classes)
    elif kind == "qcfs":
        model = models.IDS_MLP_QCFS(input_dim=input_dim, hidden=hidden, num_classes=classes, L=4)
        if kernel == "cached":
            replace_qcfs(model, models)
    else:
        raise ValueError(f"Unknown model: {kind}")
    return model


def read_raw(path: Path, config: Any) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    # NSL-KDD has 43 fields: 41 features + label + difficulty.
    df = pd.read_csv(path, header=None)
    if df.shape[1] != len(config.COL_NAMES):
        raise ValueError(f"{path.name}: expected {len(config.COL_NAMES)} columns; got {df.shape[1]}")
    df.columns = list(config.COL_NAMES)
    if df.empty or df.isna().any().any():
        raise ValueError(f"{path.name}: empty data or missing fields")
    mapped = df["label"].map(config.ATTACK_MAP)
    if mapped.isna().any():
        bad = sorted(df.loc[mapped.isna(), "label"].astype(str).unique().tolist())
        raise ValueError(f"{path.name}: unmapped attack labels {bad}; no rows were silently dropped")
    df["label"] = mapped
    return df.drop(columns="difficulty")


class TrainOnlyPreprocessor:
    """Same ordinal-feature/FP32/scaler family, fitted ONLY on the fit split."""
    def fit(self, frame: pd.DataFrame) -> "TrainOnlyPreprocessor":
        self.columns = [c for c in frame.columns if c != "label"]
        if len(self.columns) != len(set(self.columns)) or any(c not in self.columns for c in CAT_COLS):
            raise ValueError("Duplicate or missing feature columns")
        self.encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1,
                                      dtype=np.float32)
        self.encoder.fit(frame.loc[:, list(CAT_COLS)])
        self.scaler = StandardScaler()
        self.scaler.fit(self._unscaled(frame))
        return self

    def _unscaled(self, frame: pd.DataFrame) -> np.ndarray:
        if [c for c in frame.columns if c != "label"] != self.columns:
            raise ValueError("Feature column order/schema changed")
        if frame.loc[:, self.columns].isna().any().any():
            raise ValueError("NaN feature values are not accepted")
        cats = self.encoder.transform(frame.loc[:, list(CAT_COLS)])
        x = np.empty((len(frame), len(self.columns)), dtype=np.float32)
        cat_idx = {c: i for i, c in enumerate(CAT_COLS)}
        for i, col in enumerate(self.columns):
            x[:, i] = cats[:, cat_idx[col]] if col in cat_idx else frame[col].to_numpy(dtype=np.float32)
        if not np.isfinite(x).all():
            raise ValueError("Non-finite/overflowed input features")
        return x

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        x = np.ascontiguousarray(self.scaler.transform(self._unscaled(frame)), dtype=np.float32)
        if not np.isfinite(x).all():
            raise ValueError("Non-finite scaled features")
        return x

    def metadata(self) -> dict[str, Any]:
        return {"feature_columns": self.columns, "categorical_columns": list(CAT_COLS),
                "categories": [list(map(str, x)) for x in self.encoder.categories_],
                "unknown_category_code": -1, "mean": self.scaler.mean_.tolist(),
                "var": self.scaler.var_.tolist(), "scale": self.scaler.scale_.tolist(),
                "n_fit": int(self.scaler.n_samples_seen_), "output_dtype": "float32"}


def split_indices(y: np.ndarray, fraction: float, seed: int, classes: int) -> tuple[np.ndarray, np.ndarray]:
    if not 0 < fraction < 1:
        raise ValueError("Validation fraction must be between zero and one")
    counts = np.bincount(y, minlength=classes)
    if len(counts) != classes or np.any(counts < 2):
        raise ValueError("Every class needs at least two training rows for a stratified split")
    fit, val = train_test_split(np.arange(len(y), dtype=np.int64), test_size=fraction,
                                random_state=seed, stratify=y)
    fit, val = np.sort(fit), np.sort(val)
    for name, indices in (("fit", fit), ("validation", val)):
        if np.any(np.bincount(y[indices], minlength=classes) == 0):
            raise ValueError(f"{name} is missing a class; revise the declared split protocol")
    return fit, val


@dataclass
class Data:
    x_fit: torch.Tensor
    y_fit: torch.Tensor
    x_val: torch.Tensor
    y_val: torch.Tensor
    x_test: torch.Tensor
    y_test: torch.Tensor
    names: list[str]
    weights: torch.Tensor
    metadata: dict[str, Any]
    indices: dict[str, np.ndarray]


def prepare_data(args: argparse.Namespace, config: Any) -> Data:
    train_path, test_path = args.data_dir / "KDDTrain+.txt", args.data_dir / "KDDTest+.txt"
    file_hashes = {p.name: file_sha256(p) for p in (train_path, test_path)}
    train, test = read_raw(train_path, config), read_raw(test_path, config)
    if len(set(config.NSL_CLASS_NAMES)) != len(config.NSL_CLASS_NAMES):
        raise ValueError("Duplicate class names in config")
    labels = LabelEncoder().fit(config.NSL_CLASS_NAMES)
    names = list(map(str, labels.classes_))
    y_train, y_test = labels.transform(train["label"]), labels.transform(test["label"])
    if np.any(np.bincount(y_test, minlength=len(names)) == 0):
        raise ValueError("Test set must contain all declared classes for this fixed-class protocol")
    fit, val = split_indices(y_train, args.val_fraction, args.split_seed, len(names))
    prep = TrainOnlyPreprocessor().fit(train.iloc[fit])
    xf, xv, xt = (prep.transform(frame) for frame in (train.iloc[fit], train.iloc[val], test))
    yf, yv, yt = (np.ascontiguousarray(y, dtype=np.int64) for y in (y_train[fit], y_train[val], y_test))
    counts = np.bincount(yf, minlength=len(names)).astype(np.float32)
    w = 1.0 / counts
    w = (w / w.sum() * len(names)).astype(np.float32)
    meta = {
        "files_sha256": file_hashes, "n_official_train": len(train), "n_fit": len(fit),
        "n_validation": len(val), "n_test": len(test), "class_names": names,
        "fit_support": counts.astype(int).tolist(),
        "validation_support": np.bincount(yv, minlength=len(names)).tolist(),
        "test_support": np.bincount(yt, minlength=len(names)).tolist(),
        "class_weights": w.tolist(), "preprocessor": prep.metadata(),
        "fit_indices_sha256": array_sha256(fit), "val_indices_sha256": array_sha256(val),
        "arrays_sha256": {k: array_sha256(x) for k, x in
                           zip(("x_fit", "y_fit", "x_val", "y_val", "x_test", "y_test"),
                               (xf, yf, xv, yv, xt, yt))},
    }
    del train, test
    gc.collect()
    return Data(*(torch.from_numpy(x) for x in (xf, yf, xv, yv, xt, yt)), names,
                torch.from_numpy(w), meta, {"fit": fit, "validation": val})


def place_data(data: Data, device: torch.device, placement: str, reserve_gib: float) -> None:
    keys = ("x_fit", "y_fit", "x_val", "y_val", "x_test", "y_test")
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
def predict_logits(model: torch.nn.Module, x: torch.Tensor, batch: int,
                   device: torch.device) -> torch.Tensor:
    model.eval()
    chunks = [model(x[a:b].to(device, non_blocking=True))
              for a, b in batch_slices(len(x), batch)]
    logits = torch.cat(chunks)
    if logits.ndim != 2:
        raise ValueError("Expected an (N, C) logit matrix")
    # Caller makes one CPU copy, rather than one synchronization per class/batch.
    return logits


def validation_score(model: torch.nn.Module, data: Data, batch: int,
                     device: torch.device) -> float:
    logits = predict_logits(model, data.x_val, batch, device).cpu().numpy()
    if logits.shape[1] != len(data.names) or not np.isfinite(logits).all():
        raise RuntimeError("Invalid validation logits")
    y = data.y_val.cpu().numpy()
    pred = logits.argmax(axis=1)
    cm = np.bincount(len(data.names) * y + pred, minlength=len(data.names)**2).reshape(len(data.names), -1)
    return float(np.mean(np.diag(cm) / cm.sum(axis=1)) * 100.0)


def validate_model_state(model: torch.nn.Module, models: Any) -> dict[str, torch.Tensor]:
    state = cpu_tree(model.state_dict())
    if any(v.is_floating_point() and not bool(torch.isfinite(v).all()) for v in state.values()):
        raise RuntimeError("Non-finite parameter or buffer; experiment aborted")
    for name, m in model.named_modules():
        if isinstance(m, models.QCFS):
            threshold = float(state[name + ".threshold"])
            levels = float(state[name + ".L"])
            if threshold <= 0 or levels != 4:
                raise RuntimeError("QCFS threshold must stay positive and L must stay 4; "
                                   "no silent clamping/reparameterization is applied")
            if hasattr(m, "_level_value") and m._level_value != levels:
                raise RuntimeError("Cached QCFS level differs from its registered buffer")
    return state


def make_optimizer(model: torch.nn.Module, args: argparse.Namespace) -> torch.optim.Optimizer:
    return torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay,
                            foreach=args.optimizer == "foreach", fused=args.optimizer == "fused")


def train_one(kind: str, seed: int, data: Data, models: Any, args: argparse.Namespace,
              device: torch.device, fingerprint: str, checkpoint: Path,
              *, stop_after: int | None = None) -> dict[str, Any]:
    """stop_after is a test-only fault-injection hook; CLI never changes epoch budget."""
    model = build_model(models, kind, seed, data.x_fit.shape[1], len(data.names),
                        args.hidden, args.qcfs_kernel).to(device)
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
        old = load_checkpoint(checkpoint, fingerprint)
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
        model_state = validate_model_state(model, models)
        entry = {"epoch": epoch + 1, "lr_used": lr_used, "mean_batch_loss": diagnostics[0],
                 "order_sha256": order_hash, "validation_macro_recall_pct": None}
        check = (epoch + 1) % args.eval_every == 0 or epoch + 1 == args.epochs
        if check:
            score = validation_score(model, data, args.eval_batch_size, device)
            entry["validation_macro_recall_pct"] = score
            if score > best_score:  # first/earliest checkpoint wins an exact tie
                best_score, best_epoch, best_state = score, epoch + 1, model_state
            print(f"  {kind} seed={seed} epoch={epoch+1}/{args.epochs} "
                  f"val_macro_recall={score:.6f}% best_epoch={best_epoch}", flush=True)
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
    state = load_checkpoint(checkpoint, fingerprint)
    if state["epoch"] != args.epochs or not state.get("fit_result"):
        raise RuntimeError("Test evaluation requires a completed fixed-budget fit")
    model = build_model(models, kind, seed, data.x_fit.shape[1], len(data.names),
                        args.hidden, args.qcfs_kernel).to(device)
    model.load_state_dict(state["best_model"], strict=True)
    validate_model_state(model, models)
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
              "reproducibility": reproducibility, "test_evaluated": True}
    atomic_write(artifacts, lambda f: np.savez(f, logits=logits, probabilities=probabilities,
                                              y_true=y_true, y_pred=y_pred))
    return result


def summary_stats(values: list[float | None]) -> dict[str, Any]:
    valid = [float(x) for x in values if x is not None]
    if any(not math.isfinite(x) for x in valid):
        raise ValueError("Non-finite aggregate input")
    n = len(valid)
    return {"n_valid": n, "n_total": len(values), "values": values,
            "mean": float(np.mean(valid)) if n else None,
            "std": float(np.std(valid, ddof=1)) if n > 1 else None,
            "min": min(valid) if n else None, "max": max(valid) if n else None}


def aggregate_results(results: list[dict[str, Any]], names: list[str]) -> dict[str, Any]:
    if not results:
        raise ValueError("No seed results to aggregate")
    seeds = [r["seed"] for r in results]
    if len(seeds) != len(set(seeds)):
        raise ValueError("Duplicate seed results")
    agg = {k: summary_stats([r[k] for r in results]) for k in SCALAR_KEYS}
    agg["per_class"] = {
        name: {k: summary_stats([r["per_class"][name][k] for r in results])
               for k in ("accuracy", "precision", "recall", "f1", "fpr", "fnr")}
        for name in names}
    cm = np.asarray([r["confusion_matrix"] for r in results], dtype=np.float64)
    agg["confusion_matrix_mean"] = cm.mean(axis=0).tolist()
    agg["confusion_matrix_std"] = cm.std(axis=0, ddof=1).tolist() if len(results) > 1 else None
    agg["seeds"] = seeds
    return agg


def exact_signed_rank(differences: np.ndarray, decimals: int = 12) -> dict[str, Any]:
    """Exact conditional sign-flip distribution, including ties; zeros discarded.

    Integer dynamic programming enumerates the distribution, NOT a Monte Carlo
    approximation. Assumes independent symmetric paired differences under H0.
    Average ranks are doubled so all DP arithmetic is exact integer arithmetic.
    Rounding resolution is declared in the output, never tuned using a p-value.
    """
    d = np.asarray(differences, dtype=np.float64)
    if d.ndim != 1 or len(d) == 0 or not np.isfinite(d).all():
        raise ValueError("Expected a nonempty finite vector of paired differences")
    d = np.round(d, decimals=decimals)
    nz = d[d != 0]
    m = len(nz)
    if m > 100:
        raise ValueError("Exact signed-rank is limited to 100 nonzero pairs to bound runtime")
    if m == 0:
        return {"statistic": 0.0, "pvalue": 1.0, "n_nonzero": 0,
                "rank_biserial": 0.0, "min_attainable_two_sided_p": 1.0,
                "round_decimals": decimals, "method": "exact_conditional_sign_flip",
                "note": "All paired differences are zero; no evidence against H0."}
    ranks2 = np.rint(2 * rankdata(np.abs(nz), method="average")).astype(int)
    total = int(ranks2.sum())
    counts = [0] * (total + 1)
    counts[0] = 1
    reached = 0
    for rank in ranks2:
        r = int(rank)
        for s in range(reached, -1, -1):
            counts[s + r] += counts[s]
        reached += r
    positive = int(ranks2[nz > 0].sum())
    lower = min(positive, total - positive)
    p = min(1.0, 2 * sum(counts[:lower + 1]) / (1 << m))
    return {"statistic": lower / 2.0, "pvalue": float(p), "n_nonzero": m,
            "rank_biserial": (2 * positive - total) / total,
            "min_attainable_two_sided_p": min(1.0, 2.0 / (1 << m)),
            "round_decimals": decimals, "method": "exact_conditional_sign_flip"}


def holm_adjust(pvalues: list[float]) -> list[float]:
    if any(not 0 <= p <= 1 for p in pvalues):
        raise ValueError("Invalid p-value")
    out = [0.0] * len(pvalues)
    running = 0.0
    for rank, i in enumerate(sorted(range(len(pvalues)), key=lambda i: pvalues[i])):
        running = max(running, (len(pvalues) - rank) * pvalues[i])
        out[i] = min(1.0, running)
    return out


def statistical_comparison(relu: list[dict[str, Any]], qcfs: list[dict[str, Any]]) -> dict[str, Any]:
    def index(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        out = {r["seed"]: r for r in rows}
        if len(out) != len(rows):
            raise ValueError("Duplicate seeds in paired comparison")
        return out
    left, right = index(relu), index(qcfs)
    if not left or set(left) != set(right):
        raise ValueError("Paired comparison requires identical nonempty seed sets")
    seeds = sorted(left)
    output, raw = {}, []
    for key in COMPARISON_KEYS:
        a = np.asarray([left[s][key] for s in seeds], dtype=np.float64)
        b = np.asarray([right[s][key] for s in seeds], dtype=np.float64)
        d = b - a
        test = exact_signed_rank(d)
        n = len(d)
        ci = None
        if n > 1:
            half = float(student_t.ppf(0.975, n - 1) * np.std(d, ddof=1) / np.sqrt(n))
            ci = [float(d.mean() - half), float(d.mean() + half)]
        output[key] = {
            "paired_seeds": seeds, "n_pairs": n,
            "relu_mean": float(a.mean()), "qcfs_mean": float(b.mean()),
            "relu_std": float(a.std(ddof=1)) if n > 1 else None,
            "qcfs_std": float(b.std(ddof=1)) if n > 1 else None,
            "mean_diff": float(d.mean()), "median_diff": float(np.median(d)),
            "differences": d.tolist(), "units": "percentage_points",
            "paired_mean_95ci_t": ci,
            "ci_scope": "training-seed variability, fixed split/test; normal-difference assumption",
            "wilcoxon_stat": test["statistic"], "wilcoxon_p": test["pvalue"],
            "signed_rank_details": test,
        }
        raw.append(test["pvalue"])
    for key, p in zip(COMPARISON_KEYS, holm_adjust(raw)):
        output[key]["holm_adjusted_p"] = p
        output[key]["significant_005"] = p < 0.05
    return output


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    p.add_argument("--seeds", type=int, nargs="+", default=list(range(10)))
    p.add_argument("--model", choices=("relu", "qcfs", "both"), default="both")
    p.add_argument("--epochs", type=int, default=80)
    p.add_argument("--batch-size", type=int, default=512)
    p.add_argument("--eval-batch-size", type=int, default=4096)
    p.add_argument("--eval-every", type=int, default=10)
    p.add_argument("--checkpoint-every", type=int, default=10)
    p.add_argument("--hidden", type=int, default=256)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--weight-decay", type=float, default=1e-5)
    p.add_argument("--val-fraction", type=float, default=0.2)
    p.add_argument("--split-seed", type=int, default=20260920)
    p.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--optimizer", choices=("auto", "single", "foreach", "fused"), default="auto",
                   help="auto = fused on CUDA, single on CPU; recorded explicitly in the fingerprint")
    p.add_argument("--qcfs-kernel", choices=("cached", "original"), default="cached")
    p.add_argument("--data-placement", choices=("gpu", "cpu"), default="gpu")
    p.add_argument("--vram-reserve-gib", type=float, default=2.0)
    p.add_argument("--compile", action="store_true", help="Opt-in experimental fullgraph compiler; not the FP32 eager baseline")
    p.add_argument("--stage", choices=("fit", "evaluate", "all"), default="all",
                   help="fit never evaluates test; evaluate requires all completed checkpoints")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--data-dir", type=Path, default=ROOT / "data")
    p.add_argument("--results-dir", type=Path, default=ROOT / "results")
    p.add_argument("--output", type=Path, default=Path("multiseed_experiment.json"))
    return p


def validate_args(args: argparse.Namespace) -> None:
    if (not args.seeds or len(set(args.seeds)) != len(args.seeds)
            or any(not 0 <= s < 2**32 for s in args.seeds)):
        raise ValueError("Seeds must be unique integers in [0, 2**32)")
    if len(args.seeds) > 100:
        raise ValueError("At most 100 planned seeds are supported by the exact statistics")
    args.seeds = sorted(args.seeds)
    for name in ("epochs", "eval_batch_size", "eval_every", "checkpoint_every", "threads"):
        if getattr(args, name) < 1:
            raise ValueError(f"--{name.replace('_', '-')} must be >=1")
    if args.batch_size < 2 or args.hidden < 2:
        raise ValueError("Batch size and hidden width must be >=2")
    if (not math.isfinite(args.lr) or args.lr <= 0 or not math.isfinite(args.weight_decay)
            or args.weight_decay < 0 or not math.isfinite(args.vram_reserve_gib)
            or args.vram_reserve_gib < 0):
        raise ValueError("Invalid learning rate, weight decay, or VRAM reserve")
    if not 0 < args.val_fraction < 1 or not 0 <= args.split_seed < 2**32:
        raise ValueError("Invalid validation fraction or split seed")
    if args.optimizer == "auto":
        args.optimizer = "fused" if args.device == "cuda" else "single"
    if args.device == "cpu":
        args.data_placement = "cpu"
    if args.compile and args.device != "cuda":
        raise ValueError("This runner exposes --compile only for separately verified CUDA experiments")
    if args.output.suffix.lower() != ".json":
        raise ValueError("--output must end in .json")


def main() -> None:
    args = make_parser().parse_args()
    validate_args(args)
    device, environment = configure_runtime(args.device, args.threads)
    config, models, metrics_module = load_dependencies()
    out = args.output if args.output.is_absolute() else args.results_dir / args.output
    out = out.resolve()
    work = out.with_suffix("")
    with output_lock(out.with_suffix(".lock")):
        manifest_path = work / "manifest.json"
        if (out.exists() or manifest_path.exists()) and not args.resume:
            raise RuntimeError("Output already exists. Use a new --output or an explicit --resume; nothing overwritten.")
        if args.stage == "evaluate" and not manifest_path.exists():
            raise RuntimeError("--stage evaluate needs an existing completed fit and --resume")
        print(f"Device={device}; optimizer={args.optimizer}; FP32 strict; threads={args.threads}", flush=True)
        print("Loading data and fitting preprocessing on the training-only subset...", flush=True)
        data = prepare_data(args, config)
        kinds = ["relu", "qcfs"] if args.model == "both" else [args.model]
        protocol = {k: getattr(args, k) for k in
                    ("seeds", "model", "epochs", "batch_size", "eval_batch_size", "eval_every",
                     "checkpoint_every", "hidden", "lr", "weight_decay", "val_fraction", "split_seed",
                     "device", "threads", "optimizer", "qcfs_kernel", "data_placement", "compile")}
        protocol.update({"schema": SCHEMA, "precision": "FP32; TF32/AMP disabled",
                         "selection": "validation macro recall, earliest checkpoint wins ties",
                         "batch_order": "independent CPU torch.Generator, full permutation per epoch",
                         "singleton_tail": "merge into previous training batch",
                         "statistics": "exact conditional signed-rank, differences rounded at 12 decimals; Holm over 3 metrics"})
        sources = {"runner": file_sha256(Path(__file__))}
        for name, module in (("config", config), ("models", models), ("metrics", metrics_module)):
            sources[name] = file_sha256(Path(module.__file__))
        binding = {"protocol": protocol, "environment": environment,
                   "source_sha256": sources, "data": data.metadata}
        fingerprint = digest_json(binding)
        if manifest_path.exists():
            prior = json.loads(manifest_path.read_text(encoding="utf-8"))
            if prior.get("fingerprint") != fingerprint or prior.get("binding") != binding:
                raise RuntimeError("Resume rejected: data, source, environment, planned seeds or protocol changed")
        else:
            prior = {"fingerprint": fingerprint, "binding": binding,
                     "reviewed_dependency_snapshot": REFERENCE_COMMIT,
                     "test_evaluation_sessions_started": 0}
            write_json(manifest_path, prior)
            atomic_write(work / "split_indices.npz", lambda f: np.savez(f, **data.indices))
            write_json(work / "preprocessing.json", data.metadata["preprocessor"])
        place_data(data, device, args.data_placement, args.vram_reserve_gib)
        runs = work / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        output = {"schema": SCHEMA, "fingerprint": fingerprint, "protocol": protocol,
                  "dataset": "NSL-KDD", "class_names": data.names,
                  "n_train": data.metadata["n_fit"], "n_official_train": data.metadata["n_official_train"],
                  "n_validation": data.metadata["n_validation"], "n_test": data.metadata["n_test"],
                  "metric_units": {"accuracy_precision_recall_f1": "percent",
                                   "fpr_fnr_auc": "fraction", "mcc": "[-1,1]"},
                  "inference_scope": "fixed NSL-KDD split; seed variation is NOT new independent datasets",
                  "status": "fitting", "fit_runs": [],
                  "test_previously_exposed": prior.get("test_evaluation_sessions_started", 0) > 0}
        # Complete ALL predeclared model/seed fits before exposing test results.
        for seed in args.seeds:
            for kind in kinds:
                checkpoint = runs / f"{kind}_seed_{seed}.pt"
                if args.stage == "evaluate":
                    state = load_checkpoint(checkpoint, fingerprint)
                    if state["epoch"] != args.epochs or not state.get("fit_result"):
                        raise RuntimeError("All planned fits must finish before test evaluation")
                    result = state["fit_result"]
                else:
                    result = train_one(kind, seed, data, models, args, device, fingerprint, checkpoint)
                output["fit_runs"].append(result)
                write_json(out, output)
        output["status"] = ("fit_complete_test_previously_exposed" if output["test_previously_exposed"]
                            else "fit_complete_test_not_evaluated")
        write_json(out, output)
        if args.stage == "fit":
            print(f"Fit complete. No test evaluation in this invocation. "
                  f"Previously exposed={output['test_previously_exposed']}. Output: {out}", flush=True)
            return
        # Conservative audit marker: persist BEFORE any test prediction. A later
        # --stage fit must never claim this already-exposed test set is untouched.
        # This tracks this output directory only; it cannot detect human reuse elsewhere.
        prior["test_evaluation_sessions_started"] = prior.get("test_evaluation_sessions_started", 0) + 1
        write_json(manifest_path, prior)
        output["test_evaluation_sessions_started"] = prior["test_evaluation_sessions_started"]
        collected: dict[str, list[dict[str, Any]]] = {k: [] for k in kinds}
        output["status"] = "evaluating"
        for seed in args.seeds:
            for kind in kinds:
                checkpoint = runs / f"{kind}_seed_{seed}.pt"
                result = evaluate_one(kind, seed, data, models, metrics_module, args, device,
                                      fingerprint, checkpoint, runs / f"{kind}_seed_{seed}_predictions.npz")
                collected[kind].append(result)
                key = "qcfs_L4" if kind == "qcfs" else kind
                output[key] = {"per_seed": collected[kind]}
                write_json(out, output)
                print(f"TEST {kind} seed={seed}: OA={result['overall_acc']:.6f}% "
                      f"macro_F1={result['macro_f1']:.6f}%", flush=True)
        for kind, results in collected.items():
            output["qcfs_L4" if kind == "qcfs" else kind]["aggregate"] = aggregate_results(results, data.names)
        if len(kinds) == 2:
            output["statistical_tests"] = statistical_comparison(collected["relu"], collected["qcfs"])
        output["status"] = "complete"
        output["experiment_reproducibility_sha256"] = digest_json({
            "fingerprint": fingerprint,
            "results": {k: [r["reproducibility"] for r in v] for k, v in collected.items()},
            "statistics": output.get("statistical_tests"),
        })
        write_json(out, output)
        print(f"Results: {out}\nReproducibility hash: {output['experiment_reproducibility_sha256']}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2) from exc
