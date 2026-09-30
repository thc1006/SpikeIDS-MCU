from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "verify_iot23_provenance.py"
SPEC = importlib.util.spec_from_file_location("verify_iot23_provenance_under_test", TOOL_PATH)
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def _sha(path: Path) -> str:
    result = hashlib.sha256()
    result.update(path.read_bytes())
    return result.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _source_schema() -> pa.Schema:
    return pa.schema([
        pa.field(name, pa.type_for_alias(type_name))
        for name, type_name in tool.ORIGIN_TYPES.items()
    ])


def _combined_schema() -> pa.Schema:
    return pa.schema([
        pa.field(name, pa.type_for_alias(type_name))
        for name, type_name in tool.COMBINED_TYPES.items()
    ])


def _source_table(shard: int) -> pa.Table:
    first = 2 * shard
    rows: dict[str, list[object]] = {}
    for name, type_name in tool.ORIGIN_TYPES.items():
        if type_name == "string":
            rows[name] = [f"{name}:{first}", None if name in {"service", "history"} else f"{name}:{first + 1}"]
        elif type_name == "double":
            if name in {"local_orig", "local_resp"}:
                rows[name] = [None, None]
            else:
                rows[name] = [float(first) + 0.25, None if name == "duration" else float(first + 1) + 0.25]
        else:
            rows[name] = [first + 10, None if name in {"orig_bytes", "resp_bytes"} else first + 11]
    return pa.Table.from_pydict(rows, schema=_source_schema())


def _rewrite_combined(path: Path, table: pa.Table, spec_path: Path) -> None:
    pq.write_table(table, path, row_group_size=2)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["files"][0]["bytes"] = path.stat().st_size
    spec["files"][0]["sha256"] = _sha(path)
    _write_json(spec_path, spec)
    tool.PINNED_COMBINED = (
        spec["files"][0]["path"],
        spec["files"][0]["bytes"],
        spec["files"][0]["sha256"],
        spec["files"][0]["expected_rows"],
        spec["files"][0]["expected_columns"],
    )


def _rewrite_shard(path: Path, table: pa.Table, spec_path: Path, index: int) -> None:
    pq.write_table(table, path, row_group_size=1)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["origin_shards"][index]["bytes"] = path.stat().st_size
    spec["origin_shards"][index]["lfs_sha256"] = _sha(path)
    _write_json(spec_path, spec)
    bindings = list(tool.PINNED_SHARDS)
    bindings[index] = (
        spec["origin_shards"][index]["path"],
        spec["origin_shards"][index]["bytes"],
        spec["origin_shards"][index]["lfs_sha256"],
    )
    tool.PINNED_SHARDS = tuple(bindings)


@pytest.fixture
def provenance_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    origin_root = tmp_path / "origin"
    data_root = tmp_path / "local"
    spec_path = tmp_path / "audit" / "source_specs" / "iot23.json"
    output = tmp_path / "evidence" / "iot23_provenance.json"
    output.parent.mkdir(parents=True)
    tables = [_source_table(index) for index in range(3)]
    shard_records = []
    shard_paths = []
    for relative, table in zip(tool.PINNED_SHARD_PATHS, tables, strict=True):
        path = origin_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, row_group_size=1)
        shard_paths.append(path)
        shard_records.append({
            "path": relative,
            "bytes": path.stat().st_size,
            "lfs_sha256": _sha(path),
        })
    combined = pa.concat_tables(tables).cast(_combined_schema(), safe=True)
    combined_path = data_root / "iot23" / "iot23_combined.parquet"
    combined_path.parent.mkdir(parents=True)
    pq.write_table(combined, combined_path, row_group_size=2)
    spec = {
        "dataset": "iot23",
        "source_contract_version": 1,
        "provenance_note": "synthetic unit-test fixture",
        "origin": {
            "repository": tool.PINNED_REPOSITORY,
            "revision": tool.PINNED_REVISION,
            "url": "https://example.invalid/pinned",
            "upstream_dataset": "IoT-23",
            "upstream_url": "https://example.invalid/upstream",
        },
        "origin_verification": {
            "method": "synthetic",
            "verified_revision": tool.PINNED_REVISION,
        },
        "origin_shards": shard_records,
        "upstream_preprocessing": {
            "global_exact_row_deduplication": True,
            "categorical_tokens_preserved": True,
            "group_ids_sufficient_for_device_capture_time_holdout": False,
            "fully_reproducible_from_original_IoT23": False,
        },
        "files": [{
            "path": "iot23/iot23_combined.parquet",
            "role": "combined",
            "bytes": combined_path.stat().st_size,
            "sha256": _sha(combined_path),
            "expected_rows": combined.num_rows,
            "expected_columns": combined.num_columns,
            "local_generation": "synthetic",
        }],
        "expected_total_rows": combined.num_rows,
    }
    _write_json(spec_path, spec)
    monkeypatch.setattr(
        tool,
        "PINNED_SHARDS",
        tuple((row["path"], row["bytes"], row["lfs_sha256"]) for row in shard_records),
    )
    monkeypatch.setattr(
        tool,
        "PINNED_COMBINED",
        (
            spec["files"][0]["path"],
            spec["files"][0]["bytes"],
            spec["files"][0]["sha256"],
            spec["files"][0]["expected_rows"],
            spec["files"][0]["expected_columns"],
        ),
    )
    return {
        "origin_root": origin_root,
        "data_root": data_root,
        "spec": spec_path,
        "output": output,
        "combined": combined_path,
        "combined_table": combined,
        "shards": shard_paths,
        "tables": tables,
    }


def _verify(fixture: dict[str, object]) -> dict:
    return tool.verify(
        fixture["spec"],
        fixture["origin_root"],
        fixture["data_root"],
        fixture["output"],
        chunk_rows=2,
    )


def test_exact_comparison_emits_bound_sealed_report(provenance_fixture) -> None:
    report = _verify(provenance_fixture)
    output = provenance_fixture["output"]
    stored = json.loads(output.read_text(encoding="utf-8"))
    assert stored == report
    seal = stored.pop("content_sha256")
    assert seal == tool._digest(stored)
    assert report["kind"] == "spikeids_v5_iot23_provenance"
    assert report["schema"] == 1
    assert report["comparison_passed"] is True
    assert report["semantic_comparison"] == {
        **report["semantic_comparison"],
        "rows": 6,
        "columns": list(tool.EXPECTED_COLUMNS),
        "column_order_equal": True,
        "row_order_equal": True,
        "values_equal": True,
        "missingness_equal": True,
    }
    assert [row["sha256"] for row in report["origin_shards"]] == [
        _sha(path) for path in provenance_fixture["shards"]
    ]
    assert report["combined"]["sha256"] == _sha(provenance_fixture["combined"])
    assert set(report["limitations"].values()) == {False}


@pytest.mark.parametrize("mutation", ["row", "column", "value", "null"])
def test_semantic_mutations_fail_after_combined_byte_contract_is_updated(
    provenance_fixture,
    mutation: str,
) -> None:
    table = provenance_fixture["combined_table"]
    if mutation == "row":
        table = table.take(pa.array([1, 0, 2, 3, 4, 5], type=pa.int64()))
    elif mutation == "column":
        names = list(table.column_names)
        names[0], names[1] = names[1], names[0]
        table = table.select(names)
    elif mutation == "value":
        index = table.schema.get_field_index("uid")
        values = table.column(index).to_pylist()
        values[0] = "mutated"
        table = table.set_column(index, "uid", pa.array(values, type=pa.large_string()))
    else:
        index = table.schema.get_field_index("id.orig_p")
        values = table.column(index).to_pylist()
        values[0] = None
        table = table.set_column(index, "id.orig_p", pa.array(values, type=pa.int64()))
    _rewrite_combined(
        provenance_fixture["combined"], table, provenance_fixture["spec"]
    )
    with pytest.raises(tool.VerificationError):
        _verify(provenance_fixture)
    assert not provenance_fixture["output"].exists()


def test_wrong_shard_fails_even_if_spec_byte_record_is_coordinated(provenance_fixture) -> None:
    _rewrite_shard(
        provenance_fixture["shards"][1],
        provenance_fixture["tables"][0],
        provenance_fixture["spec"],
        1,
    )
    with pytest.raises(tool.VerificationError, match="Value differs|UTF-8 value differs"):
        _verify(provenance_fixture)


def test_unlisted_combined_byte_change_fails_before_comparison(provenance_fixture) -> None:
    path = provenance_fixture["combined"]
    with path.open("r+b") as stream:
        stream.seek(-1, os.SEEK_END)
        value = stream.read(1)
        stream.seek(-1, os.SEEK_END)
        stream.write(bytes([value[0] ^ 1]))
    with pytest.raises(tool.VerificationError, match="Local combined bytes differ"):
        _verify(provenance_fixture)


def test_spec_cannot_repoint_pinned_shard_bytes(provenance_fixture) -> None:
    spec_path = provenance_fixture["spec"]
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["origin_shards"][0]["bytes"] += 1
    _write_json(spec_path, spec)
    with pytest.raises(tool.VerificationError, match="Pinned shard byte contract differs"):
        _verify(provenance_fixture)


def test_hard_linked_input_is_rejected(provenance_fixture, tmp_path: Path) -> None:
    os.link(provenance_fixture["combined"], tmp_path / "second-link.parquet")
    with pytest.raises(tool.VerificationError, match="Hard-linked input is forbidden"):
        _verify(provenance_fixture)


def test_symlinked_origin_component_is_rejected(provenance_fixture, tmp_path: Path) -> None:
    link = tmp_path / "origin-link"
    link.symlink_to(provenance_fixture["origin_root"], target_is_directory=True)
    provenance_fixture["origin_root"] = link
    with pytest.raises(tool.VerificationError, match="Symlink path component is forbidden"):
        _verify(provenance_fixture)


def test_post_scan_input_mutation_is_detected(
    provenance_fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tool._compare_parquets

    def compare_then_mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        path = provenance_fixture["combined"]
        with path.open("r+b") as stream:
            stream.seek(-1, os.SEEK_END)
            value = stream.read(1)
            stream.seek(-1, os.SEEK_END)
            stream.write(bytes([value[0] ^ 1]))
            stream.flush()
            os.fsync(stream.fileno())
        return result

    monkeypatch.setattr(tool, "_compare_parquets", compare_then_mutate)
    with pytest.raises(tool.VerificationError, match="changed during verification"):
        _verify(provenance_fixture)
    assert not provenance_fixture["output"].exists()


def test_existing_output_is_never_overwritten(provenance_fixture) -> None:
    output = provenance_fixture["output"]
    output.write_text("keep\n", encoding="utf-8")
    with pytest.raises(tool.VerificationError, match="fresh path"):
        _verify(provenance_fixture)
    assert output.read_text(encoding="utf-8") == "keep\n"


def test_publication_failure_removes_only_its_own_output(
    provenance_fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_fsync = tool.os.fsync

    def fail_directory_fsync(descriptor: int) -> None:
        if tool.stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("injected directory fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr(tool.os, "fsync", fail_directory_fsync)
    with pytest.raises(OSError, match="injected directory fsync failure"):
        _verify(provenance_fixture)
    assert not provenance_fixture["output"].exists()


def test_formal_cli_report_path_cannot_be_redirected(tmp_path: Path, capsys) -> None:
    redirected = tmp_path / "iot23_provenance.json"
    assert tool.main(["--output", str(redirected)]) == 2
    assert "report path cannot be redirected" in capsys.readouterr().err
    assert not redirected.exists()


def test_revision_cannot_be_repointed_by_editing_spec(provenance_fixture) -> None:
    spec_path = provenance_fixture["spec"]
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["origin"]["revision"] = "0" * 40
    spec["origin_verification"]["verified_revision"] = "0" * 40
    _write_json(spec_path, spec)
    with pytest.raises(tool.VerificationError, match="pinned revision"):
        _verify(provenance_fixture)


def test_non_integral_int_to_float_representation_is_rejected(provenance_fixture) -> None:
    table = provenance_fixture["combined_table"]
    index = table.schema.get_field_index("orig_bytes")
    values = table.column(index).to_pylist()
    values[0] = 10.5
    table = table.set_column(index, "orig_bytes", pa.array(values, type=pa.float64()))
    _rewrite_combined(
        provenance_fixture["combined"], table, provenance_fixture["spec"]
    )
    with pytest.raises(tool.VerificationError, match="Non-integral/out-of-range"):
        _verify(provenance_fixture)
