from pathlib import Path
import os

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import StandardScaler

import contracts as c
import data_loaders as dl
from group_protocol import (
    build_partition,
    categorical_identity_tokens,
    canonical_numeric,
    deduplicate_xy,
    exact_group_ids,
    finalize_partition,
    merge_final_collisions,
)


def _cic_header() -> list[str]:
    names = [f"column_{index}" for index in range(79)]
    names[34] = names[55] = dl.CIC_DUPLICATE_NAME
    names[-1] = "Label"
    return names


def _write_cic(path: Path, *, right_value: str = "7", duplicate_attack=False):
    names = _cic_header()
    if duplicate_attack:
        names[20] = names[21]
    values = [str(index) for index in range(79)]
    values[34], values[55], values[-1] = "7", right_value, "BENIGN"
    path.write_text(",".join(names) + "\n" + ",".join(values) + "\n", encoding="utf-8")


def test_duplicate_header_is_observed_before_pandas_mangling(tmp_path):
    path = tmp_path / "cic.csv"
    _write_cic(path)
    frame, _ = next(dl._batches([(path, "combined")], "cicids2017", 8))
    assert frame.shape[1] == 78
    assert frame.columns.tolist().count(dl.CIC_DUPLICATE_NAME) == 1
    assert not any(name.endswith(".1") for name in frame.columns)


def test_only_first_header_utf8_bom_is_normalized(tmp_path):
    path = tmp_path / "unsw.csv"
    path.write_text("\ufeffid,dur,attack_cat,label\n1,0,Normal,0\n", encoding="utf-8")
    frame, _ = next(dl._batches([(path, "train")], "unsw", 8))
    assert frame.columns.tolist() == ["id", "dur", "attack_cat", "label"]


@pytest.mark.parametrize("attack", ["value", "position"])
def test_duplicate_header_or_value_attack_fails_closed(tmp_path, attack):
    path = tmp_path / "cic.csv"
    _write_cic(path, right_value="8" if attack == "value" else "7",
               duplicate_attack=attack == "position")
    with pytest.raises(c.ContractError, match="duplicate|duplicated"):
        next(dl._batches([(path, "combined")], "cicids2017", 8))


def test_formal_cic_source_rejects_noncanonical_physical_schema(tmp_path):
    path = tmp_path / "reduced.csv"
    path.write_text("a,b,Label\n1,2,BENIGN\n", encoding="utf-8")
    with pytest.raises(c.ContractError, match="79 physical columns"):
        next(dl._batches(
            [(path, "combined")], "cicids2017", 8,
            strict_source_contract=True,
        ))


def _balanced_groups(classes=2, groups_per_class=20):
    labels = np.repeat(np.arange(classes), groups_per_class)
    groups = np.arange(len(labels), dtype=np.int64)
    return groups, labels


def test_same_x_different_label_group_is_never_split():
    groups, labels = _balanced_groups()
    groups = np.r_[groups, 0]
    labels = np.r_[labels, 1]
    partition = build_partition(groups, labels, 2, None)
    placements = [name for name, ids in partition.splits.items()
                  if np.isin(ids, np.flatnonzero(groups == 0)).any()]
    assert len(placements) == 1
    assert set(labels[partition.splits[placements[0]]][
        groups[partition.splits[placements[0]]] == 0]) == {0, 1}


def test_group_label_renaming_cannot_change_frozen_split():
    groups, labels = _balanced_groups(groups_per_class=40)
    permutation = np.random.default_rng(19).permutation(len(groups))
    renamed = permutation[groups]
    original = build_partition(groups, labels, 2, None)
    attacked = build_partition(renamed, labels, 2, None)
    for split in ("fit", "validation", "test"):
        assert np.array_equal(original.splits[split], attacked.splits[split])


def test_transient_assignment_union_never_becomes_dedup_identity():
    identity, labels = _balanced_groups(groups_per_class=30)
    components = identity.copy()
    components[1] = components[0]  # prior transform collision, now disappeared
    partition = build_partition(
        identity, labels, 2, None, assignment_components=components,
    )
    assert sum(np.isin([0, 1], ids).sum() for ids in partition.splits.values()) == 2
    assert any(np.isin([0, 1], ids).all() for ids in partition.splits.values())
    final_x = {
        split: partition.splits[split].astype(np.float32).reshape(-1, 1)
        for split in ("fit", "validation", "test")
    }
    finalized = finalize_partition(partition, labels, final_x, 2)
    assert not np.isin([0, 1], finalized.removed_ids).any()
    assert sum(np.isin([0, 1], ids).sum()
               for ids in finalized.partition.splits.values()) == 2


def test_assignment_components_must_coarsen_raw_identities():
    identity, labels = _balanced_groups(groups_per_class=30)
    identity = np.r_[identity, identity[0]]
    labels = np.r_[labels, labels[0]]
    components = np.arange(len(identity), dtype=np.int64)
    with pytest.raises(c.ContractError, match="coarsening"):
        build_partition(identity, labels, 2, None,
                        assignment_components=components)


def test_stable_final_xy_dedup_aggregates_multiplicity_and_keeps_mixed_labels():
    identity, labels = _balanced_groups(groups_per_class=30)
    # Make identities 0/1 (same label) and 30 (other label) one component.
    components = identity.copy()
    components[1] = components[0]
    components[30] = components[0]
    partition = build_partition(
        identity, labels, 2, None, assignment_components=components,
    )
    final_x = {
        split: partition.splits[split].astype(np.float32).reshape(-1, 1)
        for split in ("fit", "validation", "test")
    }
    origin = next(split for split, ids in partition.splits.items()
                  if np.isin([0, 1, 30], ids).all())
    positions = [int(np.flatnonzero(partition.splits[origin] == value)[0])
                 for value in (0, 1, 30)]
    final_x[origin][positions[1]] = final_x[origin][positions[0]]
    final_x[origin][positions[2]] = final_x[origin][positions[0]]
    finalized = finalize_partition(partition, labels, final_x, 2)
    assert 1 in finalized.removed_ids
    retained_position = int(np.flatnonzero(finalized.partition.splits[origin] == 0)[0])
    assert finalized.partition.multiplicity[origin][retained_position] == 2
    assert 30 in finalized.partition.splits[origin]  # same final X, different label


def test_giant_duplicate_group_becomes_one_weighted_representative():
    base_groups, base_labels = _balanced_groups(groups_per_class=25)
    groups = np.r_[base_groups, np.repeat(0, 10_000)]
    labels = np.r_[base_labels, np.repeat(0, 10_000)]
    kept, multiplicity, excluded = deduplicate_xy(
        np.arange(len(groups)), groups, labels,
    )
    representative = int(np.flatnonzero(kept == 0)[0])
    assert multiplicity[np.flatnonzero(kept == representative)[0]] == 10_001
    assert len(excluded) == 10_000
    partition = build_partition(groups, labels, 2, None)
    assert sum(np.count_nonzero(groups[ids] == 0) for ids in partition.splits.values()) == 1


def test_model_view_fp32_and_signed_zero_identity():
    series = pd.Series([1.0, 1.00000001, 0.0, -0.0], name="numeric")
    values = canonical_numeric(series, reject_nonfinite=True)
    assert values[0].view(np.uint32) == values[1].view(np.uint32)
    assert values[2].view(np.uint32) == values[3].view(np.uint32) == 0
    groups, _ = exact_group_ids(values.reshape(-1, 1))
    assert groups[0] == groups[1] and groups[2] == groups[3]


@pytest.mark.parametrize("tokenizer", [categorical_identity_tokens, dl._tokens])
def test_categorical_tokenizer_rejects_typed_string_collision(tokenizer):
    values = pd.Series(["1", 1], dtype=object, name="category")
    with pytest.raises(c.ContractError, match="non-string"):
        tokenizer(values)


def test_scaler_can_collapse_distinct_fp32_rows_and_union_catches_it():
    fit = np.array([[1.0e10], [np.float32(1.0e10) + 1024]], dtype=np.float32)
    distinct = np.array([[1.0], [2.0]], dtype=np.float32)
    transformed = np.asarray(StandardScaler().fit(fit).transform(distinct), dtype=np.float32)
    assert distinct[0].view(np.uint32) != distinct[1].view(np.uint32)
    assert transformed[0].view(np.uint32) == transformed[1].view(np.uint32)
    final = {
        "fit": transformed[:1],
        "validation": np.array([[2.0]], dtype=np.float32),
        "test": transformed[1:],
    }
    splits = {"fit": np.array([0]), "validation": np.array([2]),
              "test": np.array([1])}
    merged, count = merge_final_collisions(final, splits, np.arange(4))
    assert count == 1 and merged[0] == merged[1]


def test_unknown_category_collision_reaches_fixed_point(raw, tmp_path):
    path = raw / "KDDTest+.txt"
    frame = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    first, second = 0, 5  # same tiled attack label
    frame.iloc[second, :len(dl.NSL_FEATURES)] = frame.iloc[first, :len(dl.NSL_FEATURES)]
    service = dl.NSL_FEATURES.index("service")
    frame.iloc[first, service] = "unknown_a"
    frame.iloc[second, service] = "unknown_b"
    frame.to_csv(path, index=False, header=False)
    metadata, arrays = dl.prepare("nslkdd", raw, tmp_path / "cache", chunksize=17)
    assert metadata["collision_iterations"][0]["new_group_unions"] >= 1
    assert metadata["collision_iterations"][-1]["new_group_unions"] == 0
    assert metadata["final_fp32_overlap"] == {
        "fit_vs_validation": 0, "fit_vs_test": 0, "validation_vs_test": 0,
    }
    assert len(arrays["excluded_ids"]) >= 1


def test_iot_projected_parquet_schema_matches_selected_batch(raw, tmp_path):
    pytest.importorskip("pyarrow")
    csv_path = raw / "iot23" / "iot23_combined.csv"
    parquet_path = csv_path.with_suffix(".parquet")
    pd.read_csv(csv_path).to_parquet(parquet_path, index=False)
    csv_path.unlink()
    metadata, arrays = dl.prepare("iot23", raw, tmp_path / "cache", chunksize=17)
    assert metadata["raw_rows"] == sum(metadata["counts"].values()) + len(arrays["excluded_ids"])


def test_official_test_overlap_and_internal_duplicate_reasons():
    train_groups, train_labels = _balanced_groups(groups_per_class=30)
    clean_groups = np.arange(60, 100, dtype=np.int64)
    clean_labels = np.tile([0, 1], 20)
    # Test rows: one train-X overlap, then two equal (X,label) clean rows.
    groups = np.r_[train_groups, 0, clean_groups, 99]
    labels = np.r_[train_labels, 0, clean_labels, clean_labels[-1]]
    partition = build_partition(groups, labels, 2, 60)
    reason_by_id = dict(zip(partition.excluded_ids, partition.excluded_reasons))
    assert reason_by_id[60] == 2
    assert reason_by_id[len(groups) - 1] == 3
    assert not np.intersect1d(groups[partition.splits["test"]], np.unique(groups[:60])).size


def test_cache_rebuild_is_byte_identical(raw, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    dl.prepare("nslkdd", raw, first, chunksize=17)
    dl.prepare("nslkdd", raw, second, chunksize=17)
    files = sorted(path.name for path in first.iterdir())
    assert files == sorted(path.name for path in second.iterdir())
    assert all((first / name).read_bytes() == (second / name).read_bytes() for name in files)


@pytest.mark.parametrize("link_kind", ["hardlink", "symlink"])
def test_cache_rejects_linked_array_evidence(raw, tmp_path, link_kind):
    cache = tmp_path / "cache"
    dl.prepare("nslkdd", raw, cache, chunksize=17)
    path = cache / "x_fit.npy"
    alias = tmp_path / "outside.npy"
    if link_kind == "hardlink":
        os.link(path, alias)
    else:
        path.replace(alias)
        path.symlink_to(alias)
    with pytest.raises(c.ContractError, match="symlink|hardlinked|canonical"):
        dl.open_cache(cache)


def test_open_cache_arrays_are_private_after_verified_load(raw, tmp_path):
    cache = tmp_path / "cache"
    _, arrays = dl.prepare("nslkdd", raw, cache, chunksize=17)
    before = arrays["x_fit"].copy()
    mapped = np.load(cache / "x_fit.npy", mmap_mode="r+")
    mapped[0, 0] += np.float32(123.0)
    mapped.flush()
    del mapped
    assert np.array_equal(arrays["x_fit"], before)


def test_array_change_and_restore_during_load_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "array.npy"
    np.save(path, np.arange(12, dtype=np.float32).reshape(4, 3))
    expected = c.sha256(path)
    load = np.load
    def interrupted_read(stream, **kwargs):
        old = path.read_bytes()
        changed = bytearray(old)
        changed[-1] ^= 1
        path.write_bytes(changed)
        result = load(stream, **kwargs)
        path.write_bytes(old)
        return result
    monkeypatch.setattr(np, "load", interrupted_read)
    with pytest.raises(c.ContractError, match="changed while reading"):
        dl._stable_npy(path, expected)


def test_preparation_detects_mutate_restore_of_source(raw, tmp_path, monkeypatch):
    original_batches = dl._batches
    changed = False
    def batches(*args, **kwargs):
        nonlocal changed
        for frame, role in original_batches(*args, **kwargs):
            if not changed:
                changed = True
                path = raw / "KDDTrain+.txt"
                old = path.read_bytes()
                path.write_bytes(old + b"\n")
                path.write_bytes(old)
            yield frame, role
    monkeypatch.setattr(dl, "_batches", batches)
    with pytest.raises(c.ContractError, match="identity changed during preparation"):
        dl.prepare("nslkdd", raw, tmp_path / "cache", chunksize=17)
    assert not (tmp_path / "cache").exists()


def test_semantically_resealed_group_tamper_is_rejected(raw, tmp_path):
    cache = tmp_path / "cache"
    dl.prepare("nslkdd", raw, cache, chunksize=17)
    fit_group = int(np.load(cache / "assignment_components_fit.npy")[0])
    test_groups = np.load(cache / "assignment_components_test.npy")
    test_groups[0] = fit_group
    np.save(cache / "assignment_components_test.npy", test_groups, allow_pickle=False)
    metadata = c.load_json(cache / "metadata.json")
    metadata.pop("content_sha256")
    metadata["files_sha256"]["assignment_components_test.npy"] = c.sha256(
        cache / "assignment_components_test.npy"
    )
    metadata["data_fingerprint"] = c.digest({key: value for key, value in metadata.items()
                                             if key != "data_fingerprint"})
    c.write_json(cache / "metadata.json", c.seal(metadata))
    with pytest.raises(c.ContractError, match="component crosses"):
        dl.open_cache(cache)


@pytest.mark.parametrize("attack", ["nan", "positive_infinity", "negative_zero"])
def test_semantically_resealed_noncanonical_feature_is_rejected(raw, tmp_path, attack):
    cache = tmp_path / "cache"
    dl.prepare("nslkdd", raw, cache, chunksize=17)
    path = cache / "x_fit.npy"
    values = np.load(path)
    values[0, 0] = {
        "nan": np.float32(np.nan),
        "positive_infinity": np.float32(np.inf),
        "negative_zero": np.float32(-0.0),
    }[attack]
    np.save(path, values, allow_pickle=False)
    metadata = c.load_json(cache / "metadata.json")
    metadata.pop("content_sha256")
    metadata["files_sha256"][path.name] = c.sha256(path)
    metadata["data_fingerprint"] = c.digest({key: value for key, value in metadata.items()
                                             if key != "data_fingerprint"})
    c.write_json(cache / "metadata.json", c.seal(metadata))
    with pytest.raises(c.ContractError, match="NaN|infinity|negative zero"):
        dl.open_cache(cache)
