"""Fail-closed file/protocol contracts. No ML imports or ambient working-directory state."""
from __future__ import annotations
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

SCHEMA = 5
PACKAGE = Path(__file__).resolve().parent
DATASETS = ("nslkdd", "unsw", "cicids2017", "iot23")
ARMS = {d: ("relu", "qcfs", "cnn") if d != "iot23" else ("relu", "qcfs") for d in DATASETS}
METRICS = ("overall_acc", "macro_f1")

class ContractError(ValueError):
    """Evidence is missing, inconsistent, stale, or outside a declared contract."""


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ContractError(message)


def json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(obj: Any) -> str:
    return hashlib.sha256(json_bytes(obj)).hexdigest()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, f"Duplicate JSON key: {key}")
        out[key] = value
    return out


def loads_json(payload: str | bytes, source: str = "<memory>") -> Any:
    def bad_constant(value):
        raise ContractError(f"Non-finite JSON constant {value} in {source}")
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="strict")
    return json.loads(payload, object_pairs_hook=_pairs,
                      parse_constant=bad_constant)


def load_json(path: Path) -> Any:
    return loads_json(Path(path).read_bytes(), str(path))


def atomic_write(path: Path, writer) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            writer(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: Path, obj: Any) -> None:
    data = json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False,
                      allow_nan=False).encode("utf-8") + b"\n"
    atomic_write(path, lambda f: f.write(data))


def write_text(path: Path, text: str) -> None:
    atomic_write(path, lambda f: f.write(text.encode("utf-8")))


@contextlib.contextmanager
def file_lock(path: Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        f.seek(0, 2)
        if f.tell() == 0:
            f.write(b"0"); f.flush()
        f.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ContractError(f"Another process holds lock {path}") from exc
        try:
            yield
        finally:
            f.seek(0)
            if os.name == "nt":
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def sources() -> dict[str, str]:
    # Includes transitive local Python helpers. No notebook/old src dependency is implicit.
    return {p.name: sha256(p) for p in sorted(PACKAGE.glob("*.py"))}


def finite(value: Any, name: str) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{name}: numeric value required")
    require(math.isfinite(value), f"{name}: non-finite value")
    return float(value)


def seed_rows(rows: list[dict], seeds: list[int]) -> dict[int, dict]:
    require(isinstance(rows, list) and len(rows) > 0, "Missing per_seed records")
    require(isinstance(seeds, list) and all(type(s) is int and 0 <= s < 2**32 for s in seeds)
            and len(seeds) == len(set(seeds)), "Invalid declared seeds")
    out = {}
    for row in rows:
        require(isinstance(row, dict), "per_seed must contain objects")
        s = row.get("seed")
        require(type(s) is int and 0 <= s < 2**32 and s not in out, f"Invalid/duplicate seed ID: {s}")
        out[s] = row
    require(set(out) == set(seeds), f"Observed seed IDs {sorted(out)} differ from declared {seeds}")
    return out


def seal(obj: dict, key: str = "content_sha256") -> dict:
    require(key not in obj, f"Digest field already present: {key}")
    return {**obj, key: digest(obj)}


def check_seal(obj: dict, key: str = "content_sha256") -> None:
    require(isinstance(obj, dict) and key in obj, f"Missing {key}")
    require(obj[key] == digest({k: v for k, v in obj.items() if k != key}), f"Integrity failure: {key}")


def same_pairing(a: dict, b: dict) -> None:
    """Same sample identities + preprocessing + execution budget, NOT same row counts."""
    for name in ("dataset", "data_fingerprint", "class_names", "pairing_contract"):
        require(name in a and name in b and a[name] == b[name], f"Paired arms differ or omit {name}")
    require(a["pairing_contract"] is not None, "Pairing contract missing")
    pa, pb = a["protocol"], b["protocol"]
    for name in ("seeds", "epochs", "batch_size", "eval_every", "eval_batch_size", "lr",
                 "weight_decay", "optimizer", "threads", "device", "hidden", "compile",
                 "data_placement", "vram_reserve_gib", "qcfs_formula", "levels",
                 "loss_weighting", "checkpoint_policy", "checkpoint_every"):
        require(name in pa and name in pb and pa[name] == pb[name], f"Paired budget differs or omits {name}")
    require(a["environment"] == b["environment"], "Paired arms used different software/hardware environments")
    ra = seed_rows(a["per_seed"], pa["seeds"])
    rb = seed_rows(b["per_seed"], pb["seeds"])
    for seed in ra:
        require(ra[seed]["batch_order_sha256"] == rb[seed]["batch_order_sha256"],
                f"seed={seed}: training permutations differ")
