#!/usr/bin/env python3
"""Fail-closed comparison of the pinned IoT-23 shards and local Parquet.

The resulting unkeyed seal detects accidental changes.  It is not a digital
signature and does not establish authenticity outside this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, cast

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
TOOL_PATH = Path(__file__).resolve()
FORMAL_SPEC = ROOT / "spikeids_v5/audit/source_specs/iot23.json"
FORMAL_ORIGIN_ROOT = ROOT / "data/iot23_origin"
FORMAL_DATA_ROOT = ROOT / "data"
FORMAL_OUTPUT = ROOT / "spikeids_v5/audit/iot23_provenance.json"
PINNED_REPOSITORY = "19kmunz/iot-23-preprocessed-allcolumns"
PINNED_REVISION = "04de595b618478668d5974a861a9f4f7305814b1"
PINNED_SHARDS = (
    (
        "data/train-00000-of-00003-47134d3a10206e3c.parquet",
        91377382,
        "6e34d6e6b20e55b096315bd0b5873dd61a98c8a1b64b6d10da158569cc5018b5",
    ),
    (
        "data/train-00001-of-00003-7fb0937ba34dd762.parquet",
        94804621,
        "8f3e5fd699213d31f6ea21f3406c5b046a83c724fd4953233191aef51e8c6283",
    ),
    (
        "data/train-00002-of-00003-78be3fca5c692525.parquet",
        88036992,
        "e227f605a0e10e22c5cc8d8783ee81ca779a25834c293b43de4aa69255630b45",
    ),
)
PINNED_SHARD_PATHS = tuple(record[0] for record in PINNED_SHARDS)
PINNED_COMBINED = (
    "iot23/iot23_combined.parquet",
    208124338,
    "8b40d893d47127fa7ac3cafd59b745f1100c403202cad5de0177fb0ebc4c2050",
    6046623,
    21,
)
EXPECTED_COLUMNS = (
    "ts",
    "uid",
    "id.orig_h",
    "id.orig_p",
    "id.resp_h",
    "id.resp_p",
    "proto",
    "service",
    "duration",
    "orig_bytes",
    "resp_bytes",
    "conn_state",
    "local_orig",
    "local_resp",
    "missed_bytes",
    "history",
    "orig_pkts",
    "orig_ip_bytes",
    "resp_pkts",
    "resp_ip_bytes",
    "label",
)
ORIGIN_TYPES = {
    "ts": "double",
    "uid": "string",
    "id.orig_h": "string",
    "id.orig_p": "int64",
    "id.resp_h": "string",
    "id.resp_p": "int64",
    "proto": "string",
    "service": "string",
    "duration": "double",
    "orig_bytes": "int64",
    "resp_bytes": "int64",
    "conn_state": "string",
    "local_orig": "double",
    "local_resp": "double",
    "missed_bytes": "int64",
    "history": "string",
    "orig_pkts": "int64",
    "orig_ip_bytes": "int64",
    "resp_pkts": "int64",
    "resp_ip_bytes": "int64",
    "label": "string",
}
COMBINED_TYPES = {
    name: (
        "large_string"
        if type_name == "string"
        else "double"
        if name in ("orig_bytes", "resp_bytes")
        else type_name
    )
    for name, type_name in ORIGIN_TYPES.items()
}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")


class VerificationError(ValueError):
    """A provenance input or semantic comparison is unsafe or inconsistent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json_bytes(payload: bytes, label: str) -> Any:
    def bad_constant(value: str) -> None:
        raise VerificationError(f"Non-finite JSON constant {value}: {label}")

    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_json_pairs,
            parse_constant=bad_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"Cannot read strict JSON {label}: {exc}") from exc


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VerificationError(f"Value is not canonical finite JSON: {exc}") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    require("content_sha256" not in value, "Cannot seal an already sealed report")
    return {**value, "content_sha256": _digest(value)}


def _assert_no_symlink_components(path: Path, *, include_leaf: bool = True) -> None:
    absolute = path.absolute()
    parts = absolute.parts
    current = Path(parts[0])
    stop = len(parts) if include_leaf else len(parts) - 1
    for part in parts[1:stop]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise VerificationError(f"Missing/unreadable path component: {current}") from exc
        require(not stat.S_ISLNK(mode), f"Symlink path component is forbidden: {current}")


def _stat_identity(status: os.stat_result) -> tuple[int, ...]:
    return (
        status.st_dev,
        status.st_ino,
        status.st_mode,
        status.st_nlink,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _directory_identity(status: os.stat_result) -> tuple[int, int, int]:
    return (status.st_dev, status.st_ino, status.st_mode)


def _file_object_identity(status: os.stat_result) -> tuple[int, int]:
    return (status.st_dev, status.st_ino)


def _sha256_stream(stream: BinaryIO) -> str:
    position = stream.tell()
    stream.seek(0)
    result = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        result.update(block)
    stream.seek(position)
    return result.hexdigest()


class SafeInput:
    """An opened regular file whose bytes and pathname are rechecked at EOF."""

    def __init__(self, path: Path) -> None:
        self.path = path.absolute()
        _assert_no_symlink_components(self.path)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags)
        except OSError as exc:
            raise VerificationError(f"Cannot safely open input: {self.path}: {exc}") from exc
        self.stream = os.fdopen(descriptor, "rb")
        try:
            status = os.fstat(self.stream.fileno())
            require(stat.S_ISREG(status.st_mode), f"Input is not a regular file: {self.path}")
            require(status.st_nlink == 1, f"Hard-linked input is forbidden: {self.path}")
            path_status = self.path.lstat()
            require(_stat_identity(path_status) == _stat_identity(status),
                    f"Input pathname changed during open: {self.path}")
            self.identity = _stat_identity(status)
            self.bytes = status.st_size
            self.sha256 = _sha256_stream(self.stream)
        except BaseException:
            self.stream.close()
            raise

    def read_bytes(self) -> bytes:
        self.stream.seek(0)
        payload = self.stream.read()
        self.stream.seek(0)
        require(len(payload) == self.bytes, f"Short read: {self.path}")
        return payload

    def recheck(self) -> None:
        _assert_no_symlink_components(self.path)
        try:
            descriptor_status = os.fstat(self.stream.fileno())
            path_status = self.path.lstat()
        except OSError as exc:
            raise VerificationError(f"Input disappeared during verification: {self.path}") from exc
        require(_stat_identity(descriptor_status) == self.identity,
                f"Open input changed during verification: {self.path}")
        require(_stat_identity(path_status) == self.identity,
                f"Input pathname was replaced during verification: {self.path}")
        require(_sha256_stream(self.stream) == self.sha256,
                f"Input bytes changed during verification: {self.path}")

    def close(self) -> None:
        self.stream.close()

    def __enter__(self) -> SafeInput:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _safe_relative(value: object, label: str) -> str:
    if not isinstance(value, str) or value in ("", "."):
        raise VerificationError(f"{label} must be a nonempty relative POSIX path")
    require("\\" not in value, f"{label} must use POSIX separators")
    relative = PurePosixPath(value)
    require(not relative.is_absolute() and ".." not in relative.parts and
            str(relative) == value,
            f"{label} is absolute, escaping, or non-canonical: {value}")
    return value


def _strict_int(value: object, label: str, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise VerificationError(f"{label} must be an integer >= {minimum}")
    return value


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _parse_spec(spec_input: SafeInput) -> dict[str, Any]:
    value = _load_json_bytes(spec_input.read_bytes(), str(spec_input.path))
    require(isinstance(value, dict), "IoT provenance source spec must be an object")
    spec: dict[str, Any] = value
    require(spec.get("dataset") == "iot23", "Source spec dataset must be iot23")
    require(spec.get("source_contract_version") == 1,
            "Unsupported IoT source contract version")

    origin_value = spec.get("origin")
    require(isinstance(origin_value, dict), "Source spec origin must be an object")
    origin = cast(dict[str, Any], origin_value)
    require(origin.get("repository") == PINNED_REPOSITORY,
            "IoT origin repository differs from the pinned repository")
    revision = origin.get("revision")
    require(isinstance(revision, str) and HEX40.fullmatch(revision) is not None and
            revision == PINNED_REVISION,
            "IoT origin revision differs from the pinned revision")
    verification_value = spec.get("origin_verification")
    require(isinstance(verification_value, dict),
            "Origin verification record must be an object")
    verification = cast(dict[str, Any], verification_value)
    require(verification.get("verified_revision") == revision,
            "Origin verification revision is absent or inconsistent")

    shards_value = spec.get("origin_shards")
    require(isinstance(shards_value, list) and len(shards_value) == len(PINNED_SHARDS),
            "Source spec must declare exactly the three pinned shards")
    shards = cast(list[Any], shards_value)
    for index, (record, expected) in enumerate(zip(shards, PINNED_SHARDS, strict=True)):
        require(isinstance(record, dict), f"origin_shards[{index}] must be an object")
        require(set(record) == {"path", "bytes", "lfs_sha256"},
                f"origin_shards[{index}] has unexpected or missing fields")
        path = _safe_relative(record.get("path"), f"origin_shards[{index}].path")
        require(path == expected[0], f"Pinned shard order/path differs at index {index}")
        size = _strict_int(record.get("bytes"), f"origin_shards[{index}].bytes")
        shard_hash = record.get("lfs_sha256")
        require(isinstance(shard_hash, str) and HEX64.fullmatch(shard_hash) is not None,
                f"origin_shards[{index}].lfs_sha256 is malformed")
        require((size, shard_hash) == expected[1:],
                f"Pinned shard byte contract differs at index {index}")

    files_value = spec.get("files")
    require(isinstance(files_value, list) and len(files_value) == 1 and
            isinstance(files_value[0], dict),
            "Source spec must declare exactly one local combined file")
    files = cast(list[Any], files_value)
    combined = files[0]
    require(combined.get("role") == "combined", "Local IoT file role must be combined")
    combined_path = _safe_relative(combined.get("path"), "files[0].path")
    combined_bytes = _strict_int(combined.get("bytes"), "files[0].bytes")
    combined_hash = combined.get("sha256")
    require(isinstance(combined_hash, str) and HEX64.fullmatch(combined_hash) is not None,
            "files[0].sha256 is malformed")
    combined_rows = _strict_int(combined.get("expected_rows"), "files[0].expected_rows")
    require(combined.get("expected_columns") == len(EXPECTED_COLUMNS),
            "Local combined expected column count differs")
    require((combined_path, combined_bytes, combined_hash, combined_rows,
             combined.get("expected_columns")) == PINNED_COMBINED,
            "Local combined byte contract differs from the pinned artifact")
    require(spec.get("expected_total_rows") == combined["expected_rows"],
            "Source spec total rows and combined rows differ")
    return spec


def _schema_record(schema: pa.Schema) -> dict[str, Any]:
    metadata = schema.metadata or {}
    return {
        "fields": [
            {"name": field.name, "type": str(field.type), "nullable": field.nullable}
            for field in schema
        ],
        "metadata": [
            {
                "key_hex": key.hex(),
                "value_bytes": len(value),
                "value_sha256": hashlib.sha256(value).hexdigest(),
            }
            for key, value in sorted(metadata.items())
        ],
    }


def _validate_schema(schema: pa.Schema, expected_types: dict[str, str], label: str) -> None:
    require(tuple(schema.names) == EXPECTED_COLUMNS,
            f"{label} column names/order differ from the pinned schema")
    require(len(schema) == len(EXPECTED_COLUMNS), f"{label} has an unexpected field count")
    for field in schema:
        require(str(field.type) == expected_types[field.name],
                f"{label} type differs for {field.name}: {field.type}")


def _all_true(array: pa.Array) -> bool:
    value = pc.all(pc.fill_null(array, True)).as_py()
    return value is True


def _compare_column(left: pa.Array, right: pa.Array, name: str, first_row: int) -> None:
    require(left.is_null().equals(right.is_null()),
            f"Missingness differs at/after row {first_row}, column {name}")
    left_type = str(left.type)
    right_type = str(right.type)
    if left_type == right_type:
        if pa.types.is_floating(left.type):
            require(_all_true(pc.is_finite(left)) and _all_true(pc.is_finite(right)),
                    f"Non-finite value is forbidden at/after row {first_row}, column {name}")
        require(left.equals(right),
                f"Value differs at/after row {first_row}, column {name}")
        return
    if left_type == "string" and right_type == "large_string":
        require(left.cast(pa.large_string()).equals(right),
                f"UTF-8 value differs at/after row {first_row}, column {name}")
        return
    if name in ("orig_bytes", "resp_bytes") and left_type == "int64" and right_type == "double":
        require(_all_true(pc.is_finite(right)),
                f"Non-finite numeric value at/after row {first_row}, column {name}")
        try:
            integer_right = pc.cast(right, pa.int64(), safe=True)
        except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as exc:
            raise VerificationError(
                f"Non-integral/out-of-range numeric value at/after row {first_row}, column {name}"
            ) from exc
        require(left.equals(integer_right) and
                pc.cast(integer_right, pa.float64(), safe=True).equals(right),
                f"Integer-to-float value differs at/after row {first_row}, column {name}")
        return
    raise VerificationError(
        f"Undeclared type normalization at column {name}: {left.type} -> {right.type}"
    )


class _BatchCursor:
    def __init__(self, iterator: Iterator[pa.RecordBatch]) -> None:
        self.iterator = iterator
        self.batch: pa.RecordBatch | None = None
        self.offset = 0
        self.exhausted = False

    def available(self) -> int:
        while not self.exhausted and (self.batch is None or self.offset == self.batch.num_rows):
            try:
                self.batch = next(self.iterator)
            except StopIteration:
                self.exhausted = True
                self.batch = None
                return 0
            self.offset = 0
            require(self.batch.num_rows > 0, "Parquet iterator yielded an empty record batch")
        return 0 if self.batch is None else self.batch.num_rows - self.offset

    def take(self, rows: int) -> pa.RecordBatch:
        require(self.batch is not None and 0 < rows <= self.available(),
                "Invalid bounded-batch cursor request")
        batch = self.batch
        if batch is None:  # pragma: no cover - defensive type narrowing
            raise VerificationError("Bounded-batch cursor lost its current batch")
        result = batch.slice(self.offset, rows)
        self.offset += rows
        return result


def _origin_batches(files: list[pq.ParquetFile], chunk_rows: int) -> Iterator[pa.RecordBatch]:
    for parquet in files:
        yield from parquet.iter_batches(batch_size=chunk_rows, use_threads=True)


def _compare_parquets(
    origin_files: list[pq.ParquetFile],
    combined_file: pq.ParquetFile,
    chunk_rows: int,
) -> tuple[int, int]:
    left = _BatchCursor(_origin_batches(origin_files, chunk_rows))
    right = _BatchCursor(combined_file.iter_batches(batch_size=chunk_rows, use_threads=True))
    rows = 0
    chunks = 0
    while True:
        left_rows = left.available()
        right_rows = right.available()
        if left_rows == 0 or right_rows == 0:
            require(left_rows == right_rows and left.exhausted and right.exhausted,
                    f"Concatenated row count differs after row {rows}")
            break
        count = min(left_rows, right_rows)
        left_batch = left.take(count)
        right_batch = right.take(count)
        require(tuple(left_batch.schema.names) == tuple(right_batch.schema.names) == EXPECTED_COLUMNS,
                f"Batch column order differs at row {rows}")
        for index, name in enumerate(EXPECTED_COLUMNS):
            _compare_column(left_batch.column(index), right_batch.column(index), name, rows)
        rows += count
        chunks += 1
    return rows, chunks


def _open_parquet(value: SafeInput, label: str) -> pq.ParquetFile:
    value.stream.seek(0)
    try:
        return pq.ParquetFile(value.stream)
    except (pa.ArrowException, OSError) as exc:
        raise VerificationError(f"Cannot open {label} Parquet: {value.path}: {exc}") from exc


def _directory_entry_status(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _write_new_json(path: Path, value: dict[str, Any], recheck: Any) -> None:
    require(path.name == "iot23_provenance.json",
            "Provenance output path must end in iot23_provenance.json")
    _assert_no_symlink_components(path, include_leaf=False)
    try:
        parent_status = path.parent.lstat()
    except OSError as exc:
        raise VerificationError(f"Output parent is missing/unreadable: {path.parent}") from exc
    require(stat.S_ISDIR(parent_status.st_mode), "Output parent must be a real directory")
    parent_identity = _directory_identity(parent_status)
    payload = json.dumps(
        value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False,
    ).encode("utf-8") + b"\n"
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(path.parent, flags)
    temporary = f".{path.name}.{secrets.token_hex(16)}.tmp"
    published = False
    published_identity: tuple[int, int] | None = None
    try:
        require(_directory_identity(os.fstat(directory_fd)) == parent_identity,
                "Output parent changed during open")
        require(_directory_entry_status(directory_fd, path.name) is None,
                "Provenance output must be a fresh path")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        recheck()
        require(_directory_identity(os.fstat(directory_fd)) == parent_identity and
                _directory_identity(path.parent.lstat()) == parent_identity,
                "Output parent changed during verification")
        require(_directory_entry_status(directory_fd, path.name) is None,
                "Provenance output appeared during verification")
        try:
            published_identity = _file_object_identity(
                os.stat(temporary, dir_fd=directory_fd, follow_symlinks=False)
            )
            os.link(
                temporary,
                path.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
            published = True
        except FileExistsError as exc:
            raise VerificationError("Provenance output appeared during atomic publication") from exc
        os.unlink(temporary, dir_fd=directory_fd)
        output_status = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        require(stat.S_ISREG(output_status.st_mode) and output_status.st_nlink == 1,
                "Published provenance output is not a private regular file")
        os.fsync(directory_fd)
    except BaseException:
        current_output_status = _directory_entry_status(directory_fd, path.name)
        if published and current_output_status is not None and \
                _file_object_identity(current_output_status) == published_identity:
            os.unlink(path.name, dir_fd=directory_fd)
            os.fsync(directory_fd)
        raise
    finally:
        if _directory_entry_status(directory_fd, temporary) is not None:
            os.unlink(temporary, dir_fd=directory_fd)
        os.close(directory_fd)


def verify(
    spec_path: Path,
    origin_root: Path,
    data_root: Path,
    output: Path,
    *,
    chunk_rows: int = 65536,
) -> dict[str, Any]:
    """Compare all declared rows and atomically write a sealed provenance report."""
    require(type(chunk_rows) is int and 1 <= chunk_rows <= 1_048_576,
            "chunk_rows must be an integer in [1, 1048576]")
    _assert_no_symlink_components(origin_root)
    _assert_no_symlink_components(data_root)
    require(origin_root.is_dir() and data_root.is_dir(), "Input roots must be real directories")

    opened: list[SafeInput] = []
    try:
        tool_input = SafeInput(TOOL_PATH)
        opened.append(tool_input)
        spec_input = SafeInput(spec_path)
        opened.append(spec_input)
        spec = _parse_spec(spec_input)

        shard_inputs: list[SafeInput] = []
        for record in spec["origin_shards"]:
            shard = SafeInput(origin_root / record["path"])
            opened.append(shard)
            shard_inputs.append(shard)
            require(shard.bytes == record["bytes"] and shard.sha256 == record["lfs_sha256"],
                    f"Pinned shard bytes differ: {record['path']}")
        combined_record = spec["files"][0]
        combined_input = SafeInput(data_root / combined_record["path"])
        opened.append(combined_input)
        require(combined_input.bytes == combined_record["bytes"] and
                combined_input.sha256 == combined_record["sha256"],
                f"Local combined bytes differ: {combined_record['path']}")

        origin_parquets = [
            _open_parquet(value, f"origin shard {index}")
            for index, value in enumerate(shard_inputs)
        ]
        combined_parquet = _open_parquet(combined_input, "local combined")
        first_schema = origin_parquets[0].schema_arrow
        _validate_schema(first_schema, ORIGIN_TYPES, "origin shard 0")
        for index, parquet in enumerate(origin_parquets[1:], start=1):
            _validate_schema(parquet.schema_arrow, ORIGIN_TYPES, f"origin shard {index}")
            require(parquet.schema_arrow.equals(first_schema, check_metadata=True),
                    f"Origin physical schema/metadata differs at shard {index}")
        _validate_schema(combined_parquet.schema_arrow, COMBINED_TYPES, "local combined")

        origin_rows = [parquet.metadata.num_rows for parquet in origin_parquets]
        require(sum(origin_rows) == spec["expected_total_rows"],
                "Origin shard metadata row total differs from the source spec")
        require(combined_parquet.metadata.num_rows == combined_record["expected_rows"],
                "Combined Parquet metadata row count differs from the source spec")
        rows, chunks = _compare_parquets(origin_parquets, combined_parquet, chunk_rows)
        require(rows == sum(origin_rows) == combined_parquet.metadata.num_rows,
                "Compared row total is inconsistent")

        normalizations = [
            {
                "columns": [name for name in EXPECTED_COLUMNS if ORIGIN_TYPES[name] == "string"],
                "origin_type": "string",
                "combined_type": "large_string",
                "policy": "offset_width_only; UTF-8 values and null positions must be identical",
            },
            {
                "columns": ["orig_bytes", "resp_bytes"],
                "origin_type": "int64",
                "combined_type": "double",
                "policy": (
                    "nullable integer-to-float representation only; each non-null double must be "
                    "finite, integral, in int64 range, exactly round-trip to double, and equal int64"
                ),
            },
        ]
        shard_reports = [
            {
                "path": record["path"],
                "bytes": value.bytes,
                "sha256": value.sha256,
                "rows": origin_rows[index],
                "physical_schema": _schema_record(origin_parquets[index].schema_arrow),
            }
            for index, (record, value) in enumerate(
                zip(spec["origin_shards"], shard_inputs, strict=True)
            )
        ]
        report = _seal({
            "kind": "spikeids_v5_iot23_provenance",
            "schema": 1,
            "comparison_passed": True,
            "passed": True,
            "tool": {"path": _display_path(TOOL_PATH), "sha256": tool_input.sha256},
            "source_spec": {
                "path": _display_path(spec_input.path),
                "bytes": spec_input.bytes,
                "sha256": spec_input.sha256,
            },
            "origin_revision": PINNED_REVISION,
            "origin_shards": shard_reports,
            "combined": {
                "path": combined_record["path"],
                "bytes": combined_input.bytes,
                "sha256": combined_input.sha256,
                "rows": combined_parquet.metadata.num_rows,
                "physical_schema": _schema_record(combined_parquet.schema_arrow),
            },
            "semantic_comparison": {
                "rows": rows,
                "columns": list(EXPECTED_COLUMNS),
                "chunk_rows": chunk_rows,
                "chunks": chunks,
                "column_order_equal": True,
                "row_order_equal": True,
                "values_equal": True,
                "missingness_equal": True,
                "normalizations": normalizations,
                "parquet_schema_metadata_equal": first_schema.metadata == combined_parquet.schema_arrow.metadata,
                "parquet_schema_metadata_is_semantic": False,
            },
            "limitations": {
                "original_iot23_reconstruction_established": False,
                "upstream_publisher_preprocessing_reproduced": False,
                "device_group_generalization_established": False,
                "capture_group_generalization_established": False,
                "time_group_generalization_established": False,
                "external_authenticity_established": False,
            },
        })

        def recheck() -> None:
            for item in opened:
                item.recheck()

        _write_new_json(output, report, recheck)
        return report
    finally:
        for item in reversed(opened):
            item.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spec",
        type=Path,
        default=FORMAL_SPEC,
    )
    parser.add_argument("--origin-root", type=Path, default=FORMAL_ORIGIN_ROOT)
    parser.add_argument("--data-root", type=Path, default=FORMAL_DATA_ROOT)
    parser.add_argument("--output", type=Path, default=FORMAL_OUTPUT)
    parser.add_argument("--chunk-rows", type=int, default=65536)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        require(args.spec.absolute() == FORMAL_SPEC.absolute(),
                "Formal CLI source spec path cannot be redirected")
        require(args.origin_root.absolute() == FORMAL_ORIGIN_ROOT.absolute(),
                "Formal CLI origin root cannot be redirected")
        require(args.data_root.absolute() == FORMAL_DATA_ROOT.absolute(),
                "Formal CLI data root cannot be redirected")
        require(args.output.absolute() == FORMAL_OUTPUT.absolute(),
                "Formal CLI report path cannot be redirected")
        report = verify(
            args.spec,
            args.origin_root,
            args.data_root,
            args.output,
            chunk_rows=args.chunk_rows,
        )
    except (VerificationError, OSError, pa.ArrowException) as exc:
        print(f"IoT-23 provenance verification failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"comparison_passed=true rows={report['semantic_comparison']['rows']} "
        f"evidence={args.output.resolve()} content_sha256={report['content_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
