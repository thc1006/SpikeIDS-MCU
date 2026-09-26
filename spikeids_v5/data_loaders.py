"""Exact-input-grouped, fit-only preparation for four declared benchmarks.

No legacy preprocessed loader is imported. Raw files are read in stable order;
exact model-input groups determine frozen splits, then categorical vocabularies
and StandardScaler are fitted exclusively on retained fit rows. Final FP32
collisions trigger monotonic regrouping and refitting. The processed cache is
immutable and hashed. IoT/CIC are NOT held-out-device/capture evaluations.
"""
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from sklearn.preprocessing import StandardScaler

from contracts import (
    SCHEMA,
    ContractError,
    check_seal,
    digest,
    file_lock,
    load_json,
    loads_json,
    require,
    seal,
    sha256,
    write_json,
)
from group_protocol import (
    EXCLUSION_REASONS,
    PROTOCOL_VERSION,
    TEST_SEED,
    VALIDATION_SEED,
    build_partition,
    canonical_model_view,
    categorical_identity_tokens,
    collision_iteration_bound,
    exact_group_ids,
    exact_overlap_counts,
    final_xy_duplicate_count,
    finalize_partition,
    group_fingerprint,
    merge_final_collisions,
    validate_collision_trace,
)

NSL_FEATURES = [
    "duration", "protocol_type", "service", "flag", "src_bytes", "dst_bytes", "land", "wrong_fragment",
    "urgent", "hot", "num_failed_logins", "logged_in", "num_compromised", "root_shell", "su_attempted",
    "num_root", "num_file_creations", "num_shells", "num_access_files", "num_outbound_cmds", "is_host_login",
    "is_guest_login", "count", "srv_count", "serror_rate", "srv_serror_rate", "rerror_rate", "srv_rerror_rate",
    "same_srv_rate", "diff_srv_rate", "srv_diff_host_rate", "dst_host_count", "dst_host_srv_count",
    "dst_host_same_srv_rate", "dst_host_diff_srv_rate", "dst_host_same_src_port_rate", "dst_host_srv_diff_host_rate",
    "dst_host_serror_rate", "dst_host_srv_serror_rate", "dst_host_rerror_rate", "dst_host_srv_rerror_rate"]
NSL_MAP = {"normal": "normal"}
for _group, _attacks in {
    "DoS": "back land neptune pod smurf teardrop mailbomb apache2 processtable udpstorm",
    "Probe": "ipsweep nmap portsweep satan mscan saint",
    "R2L": "ftp_write guess_passwd imap multihop phf spy warezclient warezmaster sendmail named snmpgetattack snmpguess xlock xsnoop worm",
    "U2R": "buffer_overflow loadmodule perl rootkit httptunnel ps sqlattack xterm",
}.items():
    NSL_MAP.update({x: _group for x in _attacks.split()})
IOT_NUM = ["id.orig_p", "id.resp_p", "duration", "orig_bytes", "resp_bytes", "missed_bytes",
           "orig_pkts", "orig_ip_bytes", "resp_pkts", "resp_ip_bytes"]
CATS = {"nslkdd": ["protocol_type", "service", "flag"], "unsw": ["proto", "service", "state"],
        "cicids2017": [], "iot23": ["proto", "service", "conn_state"]}
CLASSES = {
    "nslkdd": ["DoS", "Probe", "R2L", "U2R", "normal"],
    "unsw": ["Analysis", "Backdoor", "DoS", "Exploits", "Fuzzers", "Generic", "Normal", "Reconnaissance", "Shellcode", "Worms"],
    "cicids2017": sorted(["BENIGN", "Bot", "DDoS", "DoS GoldenEye", "DoS Hulk", "DoS Slowhttptest", "DoS slowloris",
                          "FTP-Patator", "Heartbleed", "Infiltration", "PortScan", "SSH-Patator",
                          "Web Attack - Brute Force", "Web Attack - Sql Injection", "Web Attack - XSS"]),
    "iot23": ["Benign", "C&C", "DDoS", "Okiru", "PortScan"],
}
IOT_MAP = {"Benign": "Benign", "DDoS": "DDoS", "Okiru": "Okiru", "Okiru-Attack": "Okiru",
           "PartOfAHorizontalPortScan": "PortScan", **{x: "C&C" for x in
             ("C&C", "C&C-HeartBeat", "Attack", "C&C-FileDownload", "C&C-Torii", "FileDownload",
              "C&C-HeartBeat-FileDownload", "C&C-Mirai")}}
CIC_FILES = ["Monday-WorkingHours.pcap_ISCX.csv", "Tuesday-WorkingHours.pcap_ISCX.csv",
             "Wednesday-workingHours.pcap_ISCX.csv", "Thursday-WorkingHours-Morning-WebAttacks.pcap_ISCX.csv",
             "Thursday-WorkingHours-Afternoon-Infilteration.pcap_ISCX.csv", "Friday-WorkingHours-Morning.pcap_ISCX.csv",
             "Friday-WorkingHours-Afternoon-PortScan.pcap_ISCX.csv", "Friday-WorkingHours-Afternoon-DDos.pcap_ISCX.csv"]
DROP_CIC = {"flow id", "source ip", "destination ip", "source port", "destination port", "timestamp"}
CIC_LABEL_ALIASES = {
    f"Web Attack {dash} {attack}": f"Web Attack - {attack}"
    for dash in ("\ufffd", "–")
    for attack in ("Brute Force", "Sql Injection", "XSS")
}
SPLITS = ("fit", "validation", "test")
CIC_DUPLICATE_NAME = "Fwd Header Length"
CIC_DUPLICATE_INDICES = (34, 55)


def _raw_csv_header(path: Path, dataset: str, *,
                    strict_source_contract: bool = False) -> tuple[list[str], int | None]:
    """Read physical CSV names without pandas duplicate-name mangling."""
    if dataset == "nslkdd":
        return [], None
    with Path(path).open("r", encoding="utf-8", errors="strict", newline="") as stream:
        try:
            raw = next(csv.reader(stream))
        except StopIteration as exc:
            raise ContractError(f"Empty CSV: {path}") from exc
    # The pinned UNSW CSVs carry a UTF-8 BOM on the first header token.  Strip
    # exactly that transport marker, not arbitrary replacement characters.
    if raw:
        raw[0] = raw[0].removeprefix("\ufeff")
    names = [str(name).strip() for name in raw]
    positions: dict[str, list[int]] = {}
    for index, name in enumerate(names):
        positions.setdefault(name, []).append(index)
    duplicates = {name: value for name, value in positions.items() if len(value) > 1}
    if dataset == "cicids2017" and strict_source_contract:
        require(len(names) == 79,
                f"{path.name}: formal CIC source must have 79 physical columns")
    if dataset == "cicids2017" and len(names) == 79:
        require(duplicates == {CIC_DUPLICATE_NAME: list(CIC_DUPLICATE_INDICES)},
                f"{path.name}: CIC physical duplicate contract differs: {duplicates}")
        return names, CIC_DUPLICATE_INDICES[1]
    require(not duplicates, f"{path.name}: unexpected duplicate physical CSV names: {duplicates}")
    return names, None


def source_files(dataset: str, root: Path, spec_path: Path | None = None) -> list[tuple[Path, str]]:
    require(dataset in CLASSES, f"Unknown dataset {dataset}")
    root = Path(root).resolve()
    if spec_path:
        spec = load_json(spec_path)
        require(spec.get("dataset") == dataset, "Raw-source manifest dataset mismatch")
        require(bool(spec.get("provenance_note")), "Raw-source manifest needs a provenance_note")
        rows = spec.get("files")
        require(isinstance(rows, list) and rows, "Raw-source manifest needs a non-empty files list")
        items = []
        for row in rows:
            require(isinstance(row, dict), "Raw-source file records must be objects")
            require({"path", "role", "sha256", "bytes"} <= set(row),
                    "Each raw-source file needs path, role, sha256, and bytes")
            require(isinstance(row["path"], str) and isinstance(row["role"], str),
                    "Raw-source path and role must be strings")
            relative = Path(row["path"])
            require(".." not in relative.parts,
                    f"Raw-source path escapes data-dir: {relative}")
            require(not relative.is_absolute() and relative.as_posix() not in ("", "."),
                    "Raw-source paths must be non-empty and relative to data-dir")
            requested_path = root / relative
            require(requested_path.absolute() == requested_path.resolve(),
                    f"Raw-source path traverses a symlink: {relative}")
            path = requested_path.resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ContractError(f"Raw-source path escapes data-dir: {relative}") from exc
            expected_hash = row["sha256"]
            require(isinstance(expected_hash, str) and re.fullmatch(r"[0-9a-f]{64}", expected_hash) is not None,
                    f"Invalid SHA-256 in raw-source record: {relative}")
            require(type(row["bytes"]) is int and row["bytes"] >= 0,
                    f"Invalid byte count in raw-source record: {relative}")
            require(path.is_file(), f"Required raw shard missing: {path}; no shards are silently skipped")
            require(path.stat().st_size == row["bytes"], f"Raw-source byte count mismatch: {relative}")
            require(sha256(path) == expected_hash, f"Raw-source SHA-256 mismatch: {relative}")
            items.append((path, row["role"]))
    elif dataset == "nslkdd":
        items = [(root / "KDDTrain+.txt", "train"), (root / "KDDTest+.txt", "test")]
    elif dataset == "unsw":
        extension = ".parquet" if (root / "UNSW_NB15_training-set.parquet").exists() else ".csv"
        items = [(root / (f"UNSW_NB15_{role}ing-set" + extension), role) for role in ("train", "test")]
    elif dataset == "cicids2017":
        directory = root / "cicids2017"
        combined = directory / "cicids2017_combined.csv"
        if combined.exists():
            items = [(combined, "combined")]
        elif all((directory / name).is_file() for name in CIC_FILES):
            items = [(directory / name, "combined") for name in CIC_FILES]
        elif (directory / "cicids2017_combined.parquet").exists():
            raise ContractError(
                "CIC Parquet cannot attest physical duplicate-column identity; use pinned raw CSVs")
        else:
            raise FileNotFoundError(f"Missing complete raw CIC CSV set under {directory}")
    else:
        directory = root / "iot23"
        base = directory / "iot23_combined"
        if base.with_suffix(".parquet").exists():
            items = [(base.with_suffix(".parquet"), "combined")]
        elif base.with_suffix(".csv").exists():
            items = [(base.with_suffix(".csv"), "combined")]
        else:
            raise FileNotFoundError(f"Missing raw IoT table under {directory}; automatic downloads are disabled")
    require(items and len({str(p.resolve()) for p, _ in items}) == len(items), "Duplicate/empty raw source set")
    roles = {r for _, r in items}
    require(roles == ({"train", "test"} if dataset in ("nslkdd", "unsw") else {"combined"}), "Invalid file roles")
    # A deterministic role order makes official-train rows a contiguous prefix.
    items.sort(key=lambda item: ({"train": 0, "test": 1, "combined": 0}[item[1]], item[0].as_posix()))
    for p, _ in items:
        require(p.absolute() == p.resolve(), f"Raw source traverses a symlink: {p}")
        require(p.is_file(), f"Required raw shard missing: {p}; no shards are silently skipped")
    return items


def _batches(items, dataset, chunksize, *,
             strict_source_contract: bool = False) -> Iterator[tuple[pd.DataFrame, str]]:
    for path, role in items:
        physical_header, duplicate_drop = ([], None)
        if path.suffix.lower() == ".parquet":
            require(dataset != "cicids2017",
                    "CIC Parquet cannot attest physical duplicate-column identity; use pinned raw CSVs")
            try:
                import pyarrow.parquet as pq
            except ImportError as exc:
                raise RuntimeError("Parquet input requires pyarrow. Install it in the selected uv environment.") from exc
            parquet = pq.ParquetFile(path)
            parquet_header = [str(name).strip() for name in parquet.schema.names]
            require(len(set(parquet_header)) == len(parquet_header),
                    f"{path.name}: duplicate Parquet field names after whitespace normalization")
            columns = IOT_NUM + CATS[dataset] + ["label"] if dataset == "iot23" else None
            require(columns is None or set(columns) <= set(parquet_header),
                    f"{path.name}: required projected Parquet field is absent")
            physical_header = parquet_header if columns is None else columns
            iterator = (batch.to_pandas() for batch in parquet.iter_batches(batch_size=chunksize,
                         columns=columns, use_threads=False))
        else:
            physical_header, duplicate_drop = _raw_csv_header(
                path, dataset, strict_source_contract=strict_source_contract,
            )
            iterator = pd.read_csv(path, header=None if dataset == "nslkdd" else "infer",
                                   chunksize=chunksize, dtype=str, keep_default_na=False,
                                   encoding="utf-8", encoding_errors="strict")
        for frame in iterator:
            if dataset == "nslkdd":
                require(frame.shape[1] == 43, f"NSL requires 43 columns, found {frame.shape[1]}")
                frame.columns = NSL_FEATURES + ["label", "difficulty"]
            else:
                require(frame.shape[1] == len(physical_header),
                        f"{path.name}: parsed column count differs from physical header")
                if duplicate_drop is not None:
                    left, right = CIC_DUPLICATE_INDICES
                    left_values = frame.iloc[:, left].astype(str).to_numpy()
                    right_values = frame.iloc[:, right].astype(str).to_numpy()
                    require(np.array_equal(left_values, right_values),
                            f"{path.name}: duplicated CIC {CIC_DUPLICATE_NAME} values differ")
                    frame = frame.drop(frame.columns[duplicate_drop], axis=1)
                    frame.columns = [name for index, name in enumerate(physical_header)
                                     if index != duplicate_drop]
                else:
                    frame.columns = physical_header
            require(len(set(frame.columns)) == len(frame.columns), "Column collision after whitespace normalization")
            require(len(frame) > 0, "Unexpected empty raw chunk")
            yield frame, role


def _labels_and_features(frame, dataset):
    label_col = "attack_cat" if dataset == "unsw" else ("Label" if dataset == "cicids2017" and "Label" in frame else "label")
    require(label_col in frame, f"Missing label column {label_col}")
    require(not frame[label_col].isna().any(), "Null labels cannot be mapped to a class")
    if dataset == "cicids2017":
        require(not ("Label" in frame and "label" in frame), "Ambiguous duplicate label columns")
    raw = frame[label_col].astype(str).str.strip()
    if dataset == "nslkdd":
        labels, features = raw.map(NSL_MAP), NSL_FEATURES
    elif dataset == "iot23":
        labels, features = raw.map(IOT_MAP), IOT_NUM + CATS[dataset]
    elif dataset == "unsw":
        labels = raw.replace({"Backdoors": "Backdoor"})
        require("label" in frame and "id" in frame, "Expected official UNSW split with id and binary label columns")
        features = [c for c in frame if c not in ("attack_cat", "label", "id")]
        # The binary target is a redundant label, never a model input.
        binary = pd.to_numeric(frame["label"], errors="raise").to_numpy()
        require(np.array_equal(binary, (labels != "Normal").to_numpy().astype(int)), "UNSW label/attack_cat conflict")
    else:
        # The pinned official MachineLearningCSV.zip already contains UTF-8
        # U+FFFD in place of the dash in exactly these three established class
        # names.  Normalize only the enumerated full labels; never broadly
        # erase replacement characters or accept fuzzy label spellings.
        labels = raw.replace(CIC_LABEL_ALIASES)
        require(not labels.str.contains("\ufffd", regex=False).any(),
                "Unexpected replacement character in CICIDS2017 label")
        features = [c for c in frame if c not in ("Label", "label") and c.lower() not in DROP_CIC]
    require(labels.notna().all(), f"Unmapped labels: {sorted(raw[labels.isna()].unique().tolist())}")
    mapping = {name: i for i, name in enumerate(CLASSES[dataset])}
    y = labels.map(mapping)
    require(y.notna().all(), f"Labels outside fixed task: {sorted(labels[y.isna()].unique().tolist())}")
    require(features and len(features) <= 512 and all(c in frame for c in features),
            "Missing feature or unexpectedly wide schema (>512); inspect the raw data contract")
    require(all(c in features for c in CATS[dataset]), "Required categorical feature missing")
    # Reject pre-encoded categorical parquet columns: these have unknown fit provenance.
    for col in CATS[dataset]:
        require(not pd.api.types.is_numeric_dtype(frame[col].dtype),
                f"{col} is already numeric/encoded; raw category tokens with fit provenance are required")
        tokens = frame[col].dropna().astype(str)
        require(not (len(tokens) and tokens.str.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)").all()),
                f"{col} contains only numeric category codes; verify raw-token provenance")
    return y.to_numpy(dtype=np.int64), features


def _tokens(series: pd.Series) -> pd.Series:
    # Prefix non-null strings so an actual '<missing>' value cannot alias null.
    nonnull = series[~series.isna()]
    require(bool(nonnull.map(lambda value: isinstance(value, str)).all()),
            f"Categorical model field {series.name} contains a non-string token")
    return series.astype(object).map(lambda v: "M:" if pd.isna(v) else "V:" + str(v))


def _encode(frame, features, dataset, categories, diagnostics):
    x = np.empty((len(frame), len(features)), dtype=np.float32)
    for j, col in enumerate(features):
        if col in CATS[dataset]:
            tokens = _tokens(frame[col])
            x[:, j] = tokens.map({v: i for i, v in enumerate(categories[col])}).fillna(-1).to_numpy(dtype=np.float32)
        else:
            values = frame[col]
            # Missing-value policy is fixed before seeing any outcome. Arbitrary text is not silently zeroed.
            cleaned = values.replace({"-": np.nan, "": np.nan, "NaN": np.nan, "nan": np.nan,
                                      "Infinity": np.inf, "-Infinity": -np.inf})
            # Pandas 3 may expose a read-only NumPy view here.  The fixed
            # non-finite-value policy below intentionally edits this buffer,
            # so request an owned, writable array explicitly.
            numeric = pd.to_numeric(cleaned, errors="raise").to_numpy(dtype=np.float64, copy=True)
            bad = ~np.isfinite(numeric)
            diagnostics[col] = diagnostics.get(col, 0) + int(bad.sum())
            if dataset == "nslkdd":
                require(not bad.any(), f"NSL non-finite/missing feature: {col}")
            else:
                numeric[bad] = 0.0
            # Keep measured negative values. Do not infer a data-cleaning policy from test minima.
            require((np.abs(numeric) <= np.finfo(np.float32).max).all(), f"FP32 overflow in {col}")
            x[:, j] = numeric
    return x


def _stable_regular_file(path: Path) -> tuple[int, os.stat_result]:
    """Open one immutable-evidence file without following links."""
    path = Path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
            f"Cache evidence must be a regular non-symlink, non-hardlinked file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    opened = os.fstat(descriptor)
    if (not _same_file_snapshot(before, opened) or
            not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1):
        os.close(descriptor)
        raise ContractError(f"Cache evidence identity changed while opening: {path}")
    return descriptor, opened


def _same_file_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    fields = ("st_dev", "st_ino", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    return all(getattr(left, field) == getattr(right, field) for field in fields)


def _source_snapshot(path: Path) -> dict:
    path = Path(path).absolute()
    require(path.resolve() == path, f"Evidence input traverses a symlink: {path}")
    descriptor, before = _stable_regular_file(path)
    with os.fdopen(descriptor, "rb") as stream:
        h = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
        after = os.fstat(stream.fileno())
    require(_same_file_snapshot(before, after) and
            _same_file_snapshot(after, path.lstat()),
            f"Evidence input changed during snapshot: {path}")
    return {"device": after.st_dev, "inode": after.st_ino, "links": after.st_nlink,
            "bytes": after.st_size, "mtime_ns": after.st_mtime_ns,
            "ctime_ns": after.st_ctime_ns, "sha256": h.hexdigest()}


def _stable_json(path: Path, expected_sha256: str | None = None) -> dict:
    descriptor, before = _stable_regular_file(path)
    with os.fdopen(descriptor, "rb") as stream:
        payload = stream.read()
        after = os.fstat(stream.fileno())
    require(_same_file_snapshot(before, after) and
            _same_file_snapshot(after, Path(path).lstat()),
            f"Cache JSON changed while reading: {path}")
    actual = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None:
        require(actual == expected_sha256, f"Cache file changed: {Path(path).name}")
    value = loads_json(payload, str(path))
    require(isinstance(value, dict), f"Cache JSON must contain an object: {path}")
    return value


def _stable_npy(path: Path, expected_sha256: str) -> np.ndarray:
    """Hash and copy an NPY through one FD; never return a mutable file mapping."""
    descriptor, before = _stable_regular_file(path)
    with os.fdopen(descriptor, "rb") as stream:
        h = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
        require(h.hexdigest() == expected_sha256,
                f"Cache file changed: {Path(path).name}")
        stream.seek(0)
        array = np.load(stream, allow_pickle=False)
        after = os.fstat(stream.fileno())
    require(_same_file_snapshot(before, after) and
            _same_file_snapshot(after, Path(path).lstat()),
            f"Cache array changed while reading: {path}")
    require(isinstance(array, np.ndarray) and not isinstance(array, np.memmap),
            f"Cache array was not materialized privately: {path}")
    return array


def _cache_metadata(path: Path):
    requested = Path(path).absolute()
    require(requested.resolve() == requested and requested.is_dir() and
            not requested.is_symlink(),
            "Cache directory must be canonical and may not traverse symlinks")
    path = requested
    metadata = _stable_json(path / "metadata.json")
    check_seal(metadata)
    require(metadata["schema"] == SCHEMA, "Cache schema mismatch")
    require(metadata["data_fingerprint"] == digest({k:v for k,v in metadata.items()
             if k not in ("content_sha256","data_fingerprint")}), "Cache semantic fingerprint invalid")
    require(metadata["request_sha256"] == digest(metadata["raw_binding"]), "Cache request binding invalid")
    require(metadata["raw_binding"]["implementation_sha256"] == sha256(Path(__file__)) and
            metadata["raw_binding"]["contracts_sha256"] == sha256(Path(__file__).with_name("contracts.py")) and
            metadata["raw_binding"]["group_protocol_sha256"] == sha256(Path(__file__).with_name("group_protocol.py")),
            "Preprocessor code changed; rebuild into a fresh cache directory")
    expected={f"{p}_{s}.npy" for s in SPLITS for p in
              ("x", "y", "ids", "identity_groups", "assignment_components",
               "multiplicity")} | {
                  "excluded_ids.npy", "excluded_reasons.npy",
                  "raw_unique_ids.npy", "raw_unique_identity_groups.npy",
                  "raw_unique_assignment_components.npy",
                  "raw_unique_labels.npy", "raw_unique_multiplicity.npy",
                  "preprocessing_fit_ids.npy", "final_dedup_ids.npy",
                  "final_dedup_representative_ids.npy",
                  "final_dedup_origin_splits.npy", "preprocessing.json"}
    require(set(metadata["files_sha256"]) == expected, "Incomplete/unexpected cache file inventory")
    require({item.name for item in path.iterdir()} == expected | {"metadata.json"},
            "Cache directory contains missing or unplanned files")
    return path, metadata


def load_preprocessing(path: Path, metadata: dict) -> dict:
    return _stable_json(Path(path) / "preprocessing.json",
                        metadata["files_sha256"]["preprocessing.json"])


def open_fit_cache(path: Path):
    """Load accepted fit/validation data without reading any test/global array.

    The separate acceptance gate performs whole-dataset semantic checks before
    plan freeze. This runtime path checks the exact accepted metadata/code
    binding and private copies of only the two permitted training partitions.
    """
    path, metadata = _cache_metadata(path)
    selected = ("fit", "validation")
    names = [f"{prefix}_{split}" for split in selected for prefix in
             ("x", "y", "ids", "identity_groups", "assignment_components", "multiplicity")]
    names.append("preprocessing_fit_ids")
    arrays = {name: _stable_npy(path / (name + ".npy"),
                               metadata["files_sha256"][name + ".npy"])
              for name in names}
    for split in selected:
        count = metadata["counts"][split]
        x, y, ids = (arrays[f"{prefix}_{split}"] for prefix in ("x", "y", "ids"))
        require(x.shape == (count, len(metadata["features"])) and x.dtype == np.float32,
                f"Invalid {split} feature shape/dtype")
        for start in range(0, count, 65536):
            block = x[start:start + 65536]
            require(np.isfinite(block).all() and not np.signbit(block[block == 0]).any(),
                    f"Non-finite or noncanonical {split} features")
        for prefix in ("y", "ids", "identity_groups", "assignment_components", "multiplicity"):
            values = arrays[f"{prefix}_{split}"]
            require(values.shape == (count,) and values.dtype == np.int64,
                    f"Invalid {split} {prefix} shape/dtype")
        require(len(ids) > 0 and ids[0] >= 0 and ids[-1] < metadata["raw_rows"] and
                (np.diff(ids) > 0).all(), f"Invalid {split} row IDs")
        require((y >= 0).all() and (y < len(metadata["class_names"])).all(),
                f"Invalid {split} class IDs")
        support = np.bincount(y, minlength=len(metadata["class_names"]))
        require((support > 0).all() and support.tolist() == metadata["partition"]["support"][split],
                f"Invalid {split} class support")
        require((arrays[f"multiplicity_{split}"] > 0).all() and
                int(arrays[f"multiplicity_{split}"].sum()) ==
                metadata["partition"]["source_multiplicity"][split],
                f"Invalid {split} multiplicity")
        if metadata["dataset"] in ("nslkdd", "unsw"):
            require((ids < metadata["official_train_raw_rows"]).all(),
                    "Training partitions crossed official train role")
    for prefix in ("ids", "identity_groups", "assignment_components"):
        require(not np.intersect1d(arrays[f"{prefix}_fit"],
                                  arrays[f"{prefix}_validation"]).size,
                f"Cached fit/validation {prefix} overlap")
    prep = load_preprocessing(path, metadata)
    fit_ids = arrays["preprocessing_fit_ids"]
    require(fit_ids.ndim == 1 and fit_ids.dtype == np.int64 and len(fit_ids) > 0 and
            (np.diff(fit_ids) > 0).all() and prep["n_fit"] == len(fit_ids) and
            np.isin(arrays["ids_fit"], fit_ids).all(),
            "Preprocessing fit population is invalid")
    return metadata, arrays


def open_cache(path: Path, verify: bool = True):
    require(verify is True, "Unverified cache loading is prohibited")
    path, metadata = _cache_metadata(path)
    array_names = ([f"{prefix}_{split}" for split in SPLITS for prefix in
                    ("x", "y", "ids", "identity_groups", "assignment_components",
                     "multiplicity")] +
                   ["excluded_ids", "excluded_reasons", "raw_unique_ids",
                    "raw_unique_identity_groups", "raw_unique_assignment_components",
                    "raw_unique_labels",
                    "raw_unique_multiplicity", "preprocessing_fit_ids",
                    "final_dedup_ids", "final_dedup_representative_ids",
                    "final_dedup_origin_splits"])
    arrays = {name: _stable_npy(path / (name + ".npy"),
                                metadata["files_sha256"][name + ".npy"])
              for name in array_names}
    for split in SPLITS:
        n, d = metadata["counts"][split], len(metadata["features"])
        require(arrays[f"x_{split}"].shape == (n, d) and arrays[f"x_{split}"].dtype == np.float32, "Cache feature shape/dtype invalid")
        for start in range(0, n, 65536):
            block = np.asarray(arrays[f"x_{split}"][start:start + 65536])
            require(np.isfinite(block).all(), f"Cache {split} features contain NaN or infinity")
            require(not np.signbit(block[block == 0]).any(),
                    f"Cache {split} features contain noncanonical negative zero")
        require(arrays[f"y_{split}"].shape == arrays[f"ids_{split}"].shape ==
                arrays[f"identity_groups_{split}"].shape ==
                arrays[f"assignment_components_{split}"].shape ==
                arrays[f"multiplicity_{split}"].shape == (n,),
                "Cache label/id/identity/component/multiplicity shape invalid")
        require(all(arrays[f"{prefix}_{split}"].dtype == np.int64 for prefix in
                    ("y", "ids", "identity_groups", "assignment_components",
                     "multiplicity")),
                "Cache labels/IDs/identities/components/multiplicity must be int64")
        require((arrays[f"identity_groups_{split}"] >= 0).all() and
                (arrays[f"assignment_components_{split}"] >= 0).all(),
                "Identity/component IDs must be nonnegative")
        require((arrays[f"multiplicity_{split}"] > 0).all(),
                "Retained source multiplicity must be positive")
        require(final_xy_duplicate_count(arrays[f"x_{split}"], arrays[f"y_{split}"]) == 0,
                f"Cache {split} contains duplicate stable final (X,label) patterns")
    n=metadata["raw_rows"]
    require(metadata["n_train_validation_patterns"] ==
            metadata["counts"]["fit"] + metadata["counts"]["validation"],
            "Training/validation pattern counts do not reconcile")
    if metadata["dataset"] in ("nslkdd", "unsw"):
        require(type(metadata["official_train_raw_rows"]) is int and
                metadata["official_train_raw_rows"] >=
                metadata["n_train_validation_patterns"],
                "Official-train raw-row count is invalid")
    else:
        require(metadata["official_train_raw_rows"] is None,
                "Combined datasets must not claim an official train role")
    seen=np.zeros(n,dtype=bool)
    for split in SPLITS:
        ids=arrays[f"ids_{split}"];y=arrays[f"y_{split}"]
        require(len(ids)>0 and ids[0]>=0 and ids[-1]<n and (np.diff(ids)>0).all(), "Invalid/duplicate/unsorted row IDs")
        require(not seen[ids].any(), "Row identity occurs in more than one split")
        seen[ids]=True
        require((y>=0).all() and (y<len(metadata["class_names"])).all(), "Label outside cached class schema")
    excluded_ids, excluded_reasons = arrays["excluded_ids"], arrays["excluded_reasons"]
    require(excluded_ids.shape == excluded_reasons.shape and excluded_ids.dtype == np.int64 and
            excluded_reasons.dtype == np.uint8, "Excluded-row evidence shape/dtype invalid")
    require((not len(excluded_ids)) or
            (excluded_ids[0] >= 0 and excluded_ids[-1] < n and (np.diff(excluded_ids) > 0).all()),
            "Excluded row IDs must be sorted, unique, and in range")
    require(not seen[excluded_ids].any(), "Excluded row is also retained")
    seen[excluded_ids] = True
    require(seen.all(), "Retained and excluded IDs do not account for every raw row")
    require(set(np.unique(excluded_reasons).tolist()) <= set(EXCLUSION_REASONS),
            "Unknown excluded-row reason code")
    raw_unique_ids = arrays["raw_unique_ids"]
    raw_unique_shape = raw_unique_ids.shape
    require(raw_unique_ids.dtype == np.int64 and raw_unique_ids.ndim == 1 and
            all(arrays[name].shape == raw_unique_shape for name in
                ("raw_unique_identity_groups", "raw_unique_assignment_components",
                 "raw_unique_labels",
                 "raw_unique_multiplicity")) and
            all(arrays[name].dtype == np.int64 for name in
                ("raw_unique_identity_groups", "raw_unique_assignment_components",
                 "raw_unique_labels",
                 "raw_unique_multiplicity")),
            "Raw-unique evidence shape/dtype invalid")
    require(len(raw_unique_ids) > 0 and raw_unique_ids[0] >= 0 and
            raw_unique_ids[-1] < n and (np.diff(raw_unique_ids) > 0).all(),
            "Raw-unique IDs must be sorted, unique, and in range")
    require((arrays["raw_unique_identity_groups"] >= 0).all() and
            (arrays["raw_unique_assignment_components"] >= 0).all() and
            (arrays["raw_unique_labels"] >= 0).all() and
            (arrays["raw_unique_labels"] < len(metadata["class_names"])).all() and
            (arrays["raw_unique_multiplicity"] > 0).all() and
            int(arrays["raw_unique_multiplicity"].sum()) == n,
            "Raw-unique identity/label/multiplicity evidence invalid")
    identity_order = np.argsort(arrays["raw_unique_identity_groups"], kind="stable")
    ordered_identities = arrays["raw_unique_identity_groups"][identity_order]
    ordered_components = arrays["raw_unique_assignment_components"][identity_order]
    same_identity = ordered_identities[1:] == ordered_identities[:-1]
    require(not np.any(same_identity &
                       (ordered_components[1:] != ordered_components[:-1])),
            "Cached assignment components are not a coarsening of raw identities")
    raw_unique_reason_lookup = np.zeros(n, dtype=np.uint8)
    raw_unique_reason_lookup[excluded_ids] = excluded_reasons
    if metadata["dataset"] in ("nslkdd", "unsw"):
        official_boundary = metadata["official_train_raw_rows"]
        raw_train = raw_unique_ids < official_boundary
        training_components = np.unique(
            arrays["raw_unique_assignment_components"][raw_train]
        )
        expected_overlap = (~raw_train) & np.isin(
            arrays["raw_unique_assignment_components"], training_components,
        )
        require(np.array_equal(
            raw_unique_reason_lookup[raw_unique_ids] == 2, expected_overlap,
        ), "Official-test reason-2 exclusions do not match final train components")
        require((arrays["ids_fit"] < official_boundary).all() and
                (arrays["ids_validation"] < official_boundary).all() and
                (arrays["ids_test"] >= official_boundary).all(),
                "Official train/test row roles were crossed")
    else:
        require(not (excluded_reasons == 2).any(),
                "Combined dataset cannot have official-test exclusions")
    final_ids = arrays["final_dedup_ids"]
    final_representatives = arrays["final_dedup_representative_ids"]
    final_origins = arrays["final_dedup_origin_splits"]
    require(final_ids.shape == final_representatives.shape == final_origins.shape and
            final_ids.dtype == final_representatives.dtype == np.int64 and
            final_origins.dtype == np.uint8 and
            ((not len(final_ids)) or (final_ids[0] >= 0 and final_ids[-1] < n and
                                      (np.diff(final_ids) > 0).all())) and
            set(np.unique(final_origins).tolist()) <= {0, 1, 2},
            "Stable final-dedup evidence invalid")
    require(np.isin(final_ids, raw_unique_ids).all() and
            (final_representatives < final_ids).all(),
            "Stable final-dedup IDs/mappings do not bind raw-unique patterns")
    require(np.array_equal(final_ids, excluded_ids[excluded_reasons == 4]),
            "Stable final-dedup IDs do not match exclusion reason 4")
    for split_code, split in enumerate(SPLITS):
        removed = final_ids[final_origins == split_code]
        representatives = final_representatives[final_origins == split_code]
        require(np.isin(representatives, arrays[f"ids_{split}"]).all(),
                f"Stable final-dedup representative is absent from {split}")
        if split == "fit":
            expected_preprocessing_ids = np.sort(np.r_[arrays["ids_fit"], removed])
    preprocessing_fit_ids = arrays["preprocessing_fit_ids"]
    require(preprocessing_fit_ids.dtype == np.int64 and preprocessing_fit_ids.ndim == 1 and
            len(preprocessing_fit_ids) > 0 and (np.diff(preprocessing_fit_ids) > 0).all() and
            np.array_equal(preprocessing_fit_ids, expected_preprocessing_ids),
            "Preprocessing-fit IDs differ from raw-unique fit population")
    group_overlap = {}
    for left, right in (("fit", "validation"), ("fit", "test"), ("validation", "test")):
        overlap = int(np.intersect1d(
            arrays[f"assignment_components_{left}"],
            arrays[f"assignment_components_{right}"],
        ).size)
        group_overlap[f"{left}_vs_{right}"] = overlap
        require(overlap == 0, f"Assignment component crosses cached {left}/{right}")
    require(group_overlap == metadata["groups"]["split_assignment_component_overlap"],
            "Cached assignment-component overlap metadata mismatch")
    initial_components = len(np.unique(arrays["raw_unique_identity_groups"]))
    final_components = len(np.unique(arrays["raw_unique_assignment_components"]))
    require(metadata["groups"]["raw_identity_groups"] == initial_components and
            metadata["groups"]["final_assignment_components"] == final_components,
            "Cached global identity/component counts differ")
    validate_collision_trace(metadata.get("collision_iterations"),
                             initial_components, final_components)
    overlaps = exact_overlap_counts({split: arrays[f"x_{split}"] for split in SPLITS})
    require(all(value == 0 for value in overlaps.values()),
            f"Final FP32 inputs overlap across cache splits: {overlaps}")
    require(overlaps == metadata["final_fp32_overlap"], "Cached overlap metadata mismatch")
    actual_reasons = {EXCLUSION_REASONS[code]: int((excluded_reasons == code).sum())
                      for code in EXCLUSION_REASONS}
    require(actual_reasons == metadata["partition"]["exclusion_reason_counts"],
            "Excluded-row reason counts mismatch")
    require(len(excluded_ids) == metadata["partition"]["excluded_rows"] and
            sum(metadata["counts"].values()) == metadata["partition"]["retained_rows"],
            "Retained/excluded count metadata mismatch")
    actual_support = {split: np.bincount(arrays[f"y_{split}"],
                      minlength=len(metadata["class_names"])).astype(int).tolist()
                      for split in SPLITS}
    require(actual_support == metadata["partition"]["support"], "Cached class support mismatch")
    actual_multiplicity = {split: int(arrays[f"multiplicity_{split}"].sum())
                           for split in SPLITS}
    require(actual_multiplicity == metadata["partition"]["source_multiplicity"],
            "Cached source multiplicity mismatch")
    for split_code, split in enumerate(SPLITS):
        ids = arrays[f"ids_{split}"]
        raw_positions = np.searchsorted(raw_unique_ids, ids)
        require((raw_positions < len(raw_unique_ids)).all() and
                np.array_equal(raw_unique_ids[raw_positions], ids) and
                np.array_equal(arrays["raw_unique_labels"][raw_positions],
                               arrays[f"y_{split}"]) and
                np.array_equal(arrays["raw_unique_identity_groups"][raw_positions],
                               arrays[f"identity_groups_{split}"]) and
                np.array_equal(arrays["raw_unique_assignment_components"][raw_positions],
                               arrays[f"assignment_components_{split}"]),
                f"Retained {split} rows do not match raw-unique evidence")
        expected_multiplicity = arrays["raw_unique_multiplicity"][raw_positions].copy()
        removed_mask = final_origins == split_code
        if removed_mask.any():
            removed_positions = np.searchsorted(
                raw_unique_ids, final_ids[removed_mask],
            )
            representative_positions = np.searchsorted(
                ids, final_representatives[removed_mask],
            )
            np.add.at(expected_multiplicity, representative_positions,
                      arrays["raw_unique_multiplicity"][removed_positions])
        require(np.array_equal(expected_multiplicity, arrays[f"multiplicity_{split}"]),
                f"Final {split} source multiplicity aggregation is invalid")
    raw_unique_reasons = np.zeros(n, dtype=np.uint8)
    raw_unique_reasons[excluded_ids] = excluded_reasons
    official_overlap_source_rows = int(arrays["raw_unique_multiplicity"][
        raw_unique_reasons[raw_unique_ids] == 2
    ].sum())
    require(sum(actual_multiplicity.values()) + official_overlap_source_rows == n and
            official_overlap_source_rows ==
            metadata["partition"]["official_overlap_source_rows"] and
            metadata["partition"]["source_rows_reconciled"] == n,
            "Source multiplicity and official overlap do not reconcile to raw rows")
    prep=_stable_json(path/"preprocessing.json",
                      metadata["files_sha256"]["preprocessing.json"])
    require(prep["n_fit"] == len(preprocessing_fit_ids),
            "Scaler fit count differs from sealed preprocessing-fit IDs")
    semantic={k:v for k,v in prep.items() if k not in
              ("nonfinite_replacements", "unknown_categories_pre_final_raw_unique")}
    require(metadata["preprocessor_sha256"]==digest(semantic), "Preprocessor semantic digest invalid")
    return metadata, arrays


def prepare(dataset: str, data_dir: Path, cache: Path, *, val_fraction=.2, split_seed=20260920,
            test_seed=42, chunksize=65536, source_spec: Path | None = None,
            raw_audit: Path | None = None):
    require(val_fraction == .2 and split_seed == VALIDATION_SEED and test_seed == TEST_SEED,
            "Split objective, 5-fold fold-zero rule, and seeds are frozen by protocol")
    require(chunksize >= 2, "Invalid preparation chunk size")
    control_paths = [Path(__file__), Path(__file__).with_name("contracts.py"),
                     Path(__file__).with_name("group_protocol.py")]
    if source_spec is not None:
        control_paths.append(Path(source_spec))
    if raw_audit is not None:
        control_paths.append(Path(raw_audit))
    input_snapshots = {path.absolute(): _source_snapshot(path) for path in control_paths}
    data_dir, cache = Path(data_dir).resolve(), Path(cache).resolve()
    items = source_files(dataset, data_dir, source_spec)
    input_snapshots.update({path: _source_snapshot(path) for path, _ in items})
    audit_record = None
    if raw_audit is not None:
        audit_path = Path(raw_audit).absolute()
        require(audit_path.resolve() == audit_path and audit_path.is_file() and
                not audit_path.is_symlink() and audit_path.stat().st_nlink == 1,
                "Raw audit must be a regular canonical non-hardlinked file")
        audit = load_json(audit_path)
        check_seal(audit)
        require(audit.get("raw_source_audit_passed") is True and
                audit.get("data_acceptance_passed") is False and
                set(audit.get("datasets", {})) == set(CLASSES),
                "Raw-source audit scope/status is invalid")
        audit_record = audit["datasets"][dataset]
        actual_sources = [{"path": p.relative_to(data_dir).as_posix(), "role": role,
                           "bytes": p.stat().st_size, "sha256": sha256(p)}
                          for p, role in items]
        audited_sources = [{key: row[key] for key in ("path", "role", "bytes", "sha256")}
                           for row in audit_record["files"]]
        require(actual_sources == audited_sources,
                f"{dataset} current sources differ from the sealed raw audit")
    binding = {"schema": SCHEMA, "dataset": dataset,
               "files": [{"path": p.relative_to(data_dir).as_posix(), "role": role,
                          "bytes": p.stat().st_size, "sha256": sha256(p)}
                         for p, role in items],
               "val_fraction": val_fraction, "split_seed": split_seed, "test_seed": test_seed,
               "chunksize": chunksize, "implementation_sha256": sha256(Path(__file__)),
               "contracts_sha256": sha256(Path(__file__).with_name("contracts.py")),
               "group_protocol_sha256": sha256(Path(__file__).with_name("group_protocol.py")),
               "numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__,
               "source_spec": load_json(source_spec) if source_spec else None,
               "source_spec_sha256": sha256(source_spec) if source_spec else None,
               "raw_audit": ({"path": str(audit_path), "sha256": sha256(audit_path),
                              "content_sha256": audit["content_sha256"],
                              "audit_implementation_sha256":
                              audit["audit_implementation_sha256"]}
                             if raw_audit is not None else None),
               "policy": PROTOCOL_VERSION + "; frozen_fold_zero; fit_only_ordinal_minus1; fit_only_incremental_standard_scaler; final_fp32_fixed_point"}
    if any(p.suffix == ".parquet" for p, _ in items):
        import pyarrow
        binding["pyarrow"] = pyarrow.__version__
    request_hash = digest(binding)
    with file_lock(cache.with_name(cache.name + ".lock")):
        if cache.exists():
            meta, arrays = open_cache(cache)
            require(meta["request_sha256"] == request_hash, "Existing cache belongs to another raw input/protocol/software version")
            return meta, arrays
        cache.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=cache.name + ".tmp-", dir=cache.parent))
        try:
            n, official_n, features = 0, 0, None
            identity_sets = {column: set() for column in CATS[dataset]}
            with (staging / "labels.raw").open("wb") as f:
                for frame, role in _batches(
                        items, dataset, chunksize,
                        strict_source_contract=source_spec is not None):
                    y_chunk, fcols = _labels_and_features(frame, dataset)
                    if features is None: features = fcols
                    require(features == fcols, "Raw feature schema/order differs between chunks/shards")
                    for column, values in identity_sets.items():
                        values.update(categorical_identity_tokens(frame[column]).tolist())
                        require(len(values) <= 100000,
                                f"Unexpected high-cardinality categorical identity field {column}")
                    y_chunk.tofile(f); n += len(frame)
                    if role == "train": official_n += len(frame)
            require(n > 0, "Empty dataset")
            if audit_record is not None:
                require(n == audit_record["rows"] and features == audit_record["features"] and
                        CLASSES[dataset] == audit_record["classes"],
                        f"{dataset} parsed rows/schema differ from sealed raw audit")
            y_all = np.memmap(staging / "labels.raw", mode="r", dtype=np.int64, shape=(n,))
            identity_categories = {column: sorted(values)
                                   for column, values in identity_sets.items()}
            group_view = np.lib.format.open_memmap(
                staging / "group_view.npy", mode="w+", dtype=np.float32,
                shape=(n, len(features)),
            )
            offset = 0
            for frame, _ in _batches(
                    items, dataset, chunksize,
                    strict_source_contract=source_spec is not None):
                group_view[offset:offset + len(frame)] = canonical_model_view(
                    frame, features, CATS[dataset], identity_categories,
                    reject_nonfinite=(dataset == "nslkdd"),
                )
                offset += len(frame)
            group_view.flush()
            raw_model_view_sha256 = group_fingerprint(group_view)
            identity_groups, initial_group_counts = exact_group_ids(group_view)
            assignment_components = identity_groups.copy()
            collision_iterations = []
            stable = False
            iteration_bound = collision_iteration_bound(len(initial_group_counts))
            for iteration in range(iteration_bound):
                partition = build_partition(
                    identity_groups, y_all, len(CLASSES[dataset]),
                    official_n if dataset in ("nslkdd", "unsw") else None,
                    assignment_components=assignment_components,
                )
                indices = partition.splits
                preprocessing_fit_ids = indices["fit"].copy()
                assignment = np.full(n, 255, dtype=np.uint8)
                for code, split in enumerate(SPLITS):
                    assignment[indices[split]] = code

                vocab = {column: set() for column in CATS[dataset]}
                offset = 0
                for frame, _ in _batches(
                        items, dataset, chunksize,
                        strict_source_contract=source_spec is not None):
                    fit_mask = assignment[offset:offset + len(frame)] == 0
                    for column, values in vocab.items():
                        values.update(_tokens(frame.loc[fit_mask, column]).tolist())
                        require(len(values) <= 100000,
                                f"Unexpected high-cardinality fitted field {column}")
                    offset += len(frame)
                categories = {column: sorted(values) for column, values in vocab.items()}
                require(all(categories.values()), "A categorical fit vocabulary is empty")

                scaler = StandardScaler()
                raw_x = np.lib.format.open_memmap(
                    staging / "unscaled.npy", mode="w+", dtype=np.float32,
                    shape=(n, len(features)),
                )
                offset, diagnostics = 0, {}
                for frame, _ in _batches(
                        items, dataset, chunksize,
                        strict_source_contract=source_spec is not None):
                    x = _encode(frame, features, dataset, categories, diagnostics)
                    raw_x[offset:offset + len(x)] = x
                    fit_mask = assignment[offset:offset + len(x)] == 0
                    if fit_mask.any():
                        scaler.partial_fit(x[fit_mask])
                    offset += len(x)
                raw_x.flush()
                require(int(np.asarray(scaler.n_samples_seen_).min()) == len(indices["fit"]),
                        "Scaler was not fitted on exactly the retained fit rows")

                outputs, positions = {}, {split: 0 for split in SPLITS}
                for split in SPLITS:
                    ids = indices[split]
                    np.save(staging / f"ids_{split}.npy", ids, allow_pickle=False)
                    np.save(staging / f"y_{split}.npy", np.asarray(y_all[ids]), allow_pickle=False)
                    np.save(staging / f"identity_groups_{split}.npy",
                            identity_groups[ids], allow_pickle=False)
                    np.save(staging / f"assignment_components_{split}.npy",
                            assignment_components[ids], allow_pickle=False)
                    np.save(staging / f"multiplicity_{split}.npy",
                            partition.multiplicity[split], allow_pickle=False)
                    outputs[split] = np.lib.format.open_memmap(
                        staging / f"x_{split}.npy", mode="w+", dtype=np.float32,
                        shape=(len(ids), len(features)),
                    )
                unknown_counts = {split: {column: 0 for column in CATS[dataset]}
                                  for split in SPLITS}
                for start in range(0, n, chunksize):
                    stop = min(n, start + chunksize)
                    transformed = np.ascontiguousarray(
                        scaler.transform(raw_x[start:stop]), dtype=np.float32,
                    )
                    transformed[transformed == 0] = np.float32(0.0)
                    require(np.isfinite(transformed).all(), "Non-finite scaled feature")
                    for code, split in enumerate(SPLITS):
                        keep = assignment[start:stop] == code
                        count = int(keep.sum())
                        position = positions[split]
                        outputs[split][position:position + count] = transformed[keep]
                        positions[split] += count
                        for column in CATS[dataset]:
                            unknown_counts[split][column] += int(
                                (raw_x[start:stop, features.index(column)][keep] == -1).sum())
                require(all(positions[split] == len(indices[split]) for split in SPLITS),
                        "Output partition write was incomplete")
                for output in outputs.values():
                    output.flush()
                del output

                input_group_count = len(np.unique(assignment_components))
                merged_components, merge_count = merge_final_collisions(
                    outputs, indices, assignment_components,
                )
                output_group_count = len(np.unique(merged_components))
                require((merge_count == 0 and output_group_count == input_group_count) or
                        (merge_count > 0 and output_group_count == input_group_count - merge_count),
                        "Final-FP32 collision closure was not a monotonic group union")
                collision_iterations.append({
                    "iteration": iteration,
                    "input_groups": input_group_count,
                    "output_groups": output_group_count,
                    "new_group_unions": int(merge_count),
                })
                print(json.dumps({"dataset": dataset, "phase": "collision_closure",
                                  **collision_iterations[-1]}, sort_keys=True), flush=True)
                if merge_count == 0:
                    validate_collision_trace(collision_iterations,
                                             len(initial_group_counts), output_group_count)
                    final_overlap = exact_overlap_counts(outputs)
                    require(all(value == 0 for value in final_overlap.values()),
                            f"Stable partition still has final-FP32 overlap: {final_overlap}")
                    finalized = finalize_partition(
                        partition, y_all, outputs, len(CLASSES[dataset]),
                    )
                    # The scaler/vocabulary population is the pre-final-dedup
                    # raw-unique fit set. Model/evaluation arrays are the stable
                    # final-(X,label)-unique subsets. Rewrite only after the
                    # collision fixed point has converged.
                    final_paths = {}
                    for split in SPLITS:
                        keep = finalized.keep_positions[split]
                        target = staging / f"x_{split}.final.npy"
                        final_output = np.lib.format.open_memmap(
                            target, mode="w+", dtype=np.float32,
                            shape=(len(keep), len(features)),
                        )
                        for start in range(0, len(keep), chunksize):
                            stop = min(len(keep), start + chunksize)
                            final_output[start:stop] = outputs[split][keep[start:stop]]
                        final_output.flush()
                        del final_output
                        final_paths[split] = target
                    del outputs
                    gc.collect()
                    for split, target in final_paths.items():
                        os.replace(target, staging / f"x_{split}.npy")
                    partition = finalized.partition
                    indices = partition.splits
                    for split in SPLITS:
                        ids = indices[split]
                        np.save(staging / f"ids_{split}.npy", ids, allow_pickle=False)
                        np.save(staging / f"y_{split}.npy", np.asarray(y_all[ids]),
                                allow_pickle=False)
                        np.save(staging / f"identity_groups_{split}.npy",
                                identity_groups[ids], allow_pickle=False)
                        np.save(staging / f"assignment_components_{split}.npy",
                                assignment_components[ids], allow_pickle=False)
                        np.save(staging / f"multiplicity_{split}.npy",
                                partition.multiplicity[split], allow_pickle=False)
                    np.save(staging / "final_dedup_ids.npy", finalized.removed_ids,
                            allow_pickle=False)
                    np.save(staging / "final_dedup_representative_ids.npy",
                            finalized.representative_ids, allow_pickle=False)
                    np.save(staging / "final_dedup_origin_splits.npy",
                            finalized.origin_splits, allow_pickle=False)
                    stable = True
                    del raw_x
                    break
                assignment_components = merged_components
                del outputs, raw_x
                gc.collect()
            require(stable, f"Final-FP32 collision closure violated its finite-progress bound of {iteration_bound} iterations")

            np.save(staging / "excluded_ids.npy", partition.excluded_ids, allow_pickle=False)
            np.save(staging / "excluded_reasons.npy", partition.excluded_reasons, allow_pickle=False)
            np.save(staging / "raw_unique_ids.npy", partition.raw_unique_ids,
                    allow_pickle=False)
            np.save(staging / "raw_unique_identity_groups.npy",
                    identity_groups[partition.raw_unique_ids], allow_pickle=False)
            np.save(staging / "raw_unique_assignment_components.npy",
                    assignment_components[partition.raw_unique_ids], allow_pickle=False)
            np.save(staging / "raw_unique_labels.npy",
                    np.asarray(y_all[partition.raw_unique_ids]), allow_pickle=False)
            np.save(staging / "raw_unique_multiplicity.npy",
                    partition.raw_unique_multiplicity, allow_pickle=False)
            np.save(staging / "preprocessing_fit_ids.npy", preprocessing_fit_ids,
                    allow_pickle=False)
            unique_components = np.unique(assignment_components)
            unique_identity_labels = np.unique(
                identity_groups.astype(np.int64) * len(CLASSES[dataset]) + np.asarray(y_all),
            ) // len(CLASSES[dataset])
            mixed_counts = np.bincount(
                unique_identity_labels, minlength=int(identity_groups.max()) + 1,
            )
            group_report = {
                "raw_identity_groups": len(initial_group_counts),
                "final_assignment_components": len(unique_components),
                "mixed_label_raw_identity_groups": int((mixed_counts > 1).sum()),
                "maximum_raw_identity_group_rows": int(initial_group_counts.max()),
                "split_raw_identity_group_counts": {
                    split: len(np.unique(identity_groups[indices[split]])) for split in SPLITS
                },
                "split_assignment_component_counts": {
                    split: len(np.unique(assignment_components[indices[split]]))
                    for split in SPLITS
                },
                "split_assignment_component_overlap": {
                    f"{left}_vs_{right}": int(np.intersect1d(
                        assignment_components[indices[left]],
                        assignment_components[indices[right]],
                    ).size)
                    for left, right in (("fit", "validation"), ("fit", "test"),
                                        ("validation", "test"))
                },
            }
            preprocessor = {
                "feature_columns": features, "categorical_columns": CATS[dataset],
                "categories": categories, "mean": scaler.mean_.tolist(),
                "var": scaler.var_.tolist(), "scale": scaler.scale_.tolist(),
                "n_fit": int(np.asarray(scaler.n_samples_seen_).min()),
                "class_names": CLASSES[dataset],
                "class_grouping": IOT_MAP if dataset == "iot23" else None,
                "grouping_note": "C&C is the historical aggregate including Attack/FileDownload, not a pure C&C taxonomy" if dataset == "iot23" else None,
                "nonfinite_replacements": diagnostics,
                "unknown_categories_pre_final_raw_unique": unknown_counts,
                "fit_population": "canonical-raw-(X,label)-unique assigned fit patterns before stable-final-(X,label) dedup",
                "model_population": "stable-final-FP32-(X,label)-unique patterns",
            }
            write_json(staging / "preprocessing.json", preprocessor)
            del group_view, y_all
            gc.collect()
            (staging / "labels.raw").unlink()
            (staging / "unscaled.npy").unlink()
            (staging / "group_view.npy").unlink()
            files = {p.name: sha256(p) for p in sorted(staging.glob("*")) if p.is_file()}
            metadata = {"schema": SCHEMA, "dataset": dataset, "request_sha256": request_hash,
                        "raw_binding": binding, "features": features, "class_names": CLASSES[dataset],
                        "raw_rows": n, "official_train_raw_rows": official_n or None,
                        "counts": {s: len(indices[s]) for s in SPLITS},
                        "n_train_validation_patterns": len(indices["fit"]) + len(indices["validation"]),
                        "files_sha256": files,
                        "scope": "official roles; raw-identity-deduplicated train grouped fit/validation; official test assignment components touching train excluded" if dataset in ("nslkdd", "unsw") else "raw-identity-deduplicated, final-input-grouped target-64/16/20 benchmark; NOT capture/device/time holdout",
                        "upstream_preprocessing_verified": False,
                        "exact_model_input_group_leakage_excluded": True,
                        "capture_device_time_group_generalization_established": False,
                        "raw_model_view_sha256": raw_model_view_sha256,
                        "partition": partition.report,
                        "groups": group_report,
                        "collision_iterations": collision_iterations,
                        "final_fp32_overlap": final_overlap,
                        "exclusion_reason_codes": {str(code): reason for code, reason in EXCLUSION_REASONS.items()},
                        "preprocessor_sha256": digest({k: v for k, v in preprocessor.items()
                                                       if k not in ("nonfinite_replacements", "unknown_categories_pre_final_raw_unique")})}
            metadata["data_fingerprint"] = digest(metadata)
            write_json(staging / "metadata.json", seal(metadata))
            # Detect input modification across multi-pass preparation.
            for (path, _), record in zip(items, binding["files"]):
                require(sha256(path) == record["sha256"], f"Raw source changed during preparation: {path}")
            if raw_audit is not None:
                require(sha256(audit_path) == binding["raw_audit"]["sha256"],
                        "Raw audit changed during preparation")
            for input_path, original_snapshot in input_snapshots.items():
                require(_source_snapshot(input_path) == original_snapshot,
                        f"Input/code/spec identity changed during preparation: {input_path}")
            os.replace(staging, cache)
        finally:
            if staging.exists(): shutil.rmtree(staging)
    return open_cache(cache)


def main():
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--dataset", required=True, choices=tuple(CLASSES))
    p.add_argument("--data-dir", required=True, type=Path)
    p.add_argument("--cache", required=True, type=Path)
    p.add_argument("--source-spec", required=True, type=Path)
    p.add_argument("--raw-audit", required=True, type=Path)
    p.add_argument("--chunksize", type=int, default=65536)
    a = p.parse_args()
    meta, _ = prepare(a.dataset, a.data_dir, a.cache, source_spec=a.source_spec,
                      raw_audit=a.raw_audit, chunksize=a.chunksize)
    print(meta["data_fingerprint"], meta["counts"], len(meta["features"]))

if __name__ == "__main__": main()
