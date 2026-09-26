"""Independent protocol replay tests, including real producer consumer boundaries."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("protocol_replay_under_test", ROOT / "tools/verify_v5_data.py")
assert SPEC is not None and SPEC.loader is not None
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def _trace(initial, unions):
    current = initial
    rows = []
    for index, count in enumerate(unions):
        rows.append({"iteration": index, "input_groups": current,
                     "output_groups": current - count, "new_group_unions": count})
        current -= count
    return {"dataset": "synthetic", "groups": {"raw_identity_groups": initial,
            "final_assignment_components": current}, "collision_iterations": rows}


def test_independent_frozen_fold_zero_known_answer_and_group_name_invariance():
    ids = np.arange(40, dtype=np.int64)
    labels = np.tile([0, 1], 20)
    fit, held = tool._independent_fold_zero(ids, labels, ids, 2, 20260920)
    assert held.tolist() == [8, 9, 10, 11, 19, 30, 36, 37]
    assert np.array_equal(np.sort(np.r_[fit, held]), ids)
    renamed = np.random.default_rng(59).permutation(40) * 17 + 1000
    other = tool._independent_fold_zero(ids, labels, renamed, 2, 20260920)
    assert np.array_equal(fit, other[0]) and np.array_equal(held, other[1])


def test_independent_collision_trace_accepts_more_than_eight_rounds():
    metadata = _trace(12, [1] * 9 + [0])
    tool._validate_collision_trace(metadata)


@pytest.mark.parametrize("attack", ["early_zero", "double_zero", "missing_terminal",
                                    "bool_index", "bool_count", "extra_key", "discontinuous",
                                    "wrong_final", "negative_output", "negative_union"])
def test_independent_collision_trace_rejects_invalid_histories(attack):
    metadata = _trace(12, [2, 1, 0])
    rows = metadata["collision_iterations"]
    if attack == "early_zero":
        metadata = _trace(12, [0, 2, 1, 0])
    elif attack == "double_zero":
        metadata = _trace(12, [2, 1, 0, 0])
    elif attack == "missing_terminal":
        metadata = _trace(12, [2, 1])
    elif attack == "bool_index":
        rows[0]["iteration"] = False
    elif attack == "bool_count":
        rows[1]["new_group_unions"] = True
    elif attack == "extra_key":
        rows[0]["unchecked"] = True
    elif attack == "discontinuous":
        rows[1]["input_groups"] += 1
    elif attack == "wrong_final":
        metadata["groups"]["final_assignment_components"] -= 1
    elif attack == "negative_output":
        rows[1]["output_groups"] = -1
    elif attack == "negative_union":
        rows[1]["new_group_unions"] = -1
    with pytest.raises(tool.VerificationError, match="Collision|collision"):
        tool._validate_collision_trace(metadata)


def test_independent_collision_union_all_observed_edges_and_transitive_components():
    # Components 0/1 share X=7 and components 1/2 share X=9, joining all three.
    matrix = np.array([[7], [7], [9], [9], [99]], dtype=np.float32)
    groups = np.array([0, 1, 1, 2, 3, 4], dtype=np.int64)
    retained = np.arange(5, dtype=np.int64)
    merged, count = tool._independent_collision_union(matrix, retained, groups)
    assert count == 2
    assert len(np.unique(merged[:4])) == 1
    assert merged[4] != merged[5] != merged[0]
    for old in np.unique(groups):
        assert len(np.unique(merged[groups == old])) == 1


def test_independent_collision_union_matches_separate_graph_reference():
    rng = np.random.default_rng(308)
    for _ in range(35):
        groups = rng.integers(0, 15, size=40, dtype=np.int64)
        retained = np.sort(rng.choice(40, 25, replace=False))
        matrix = rng.integers(0, 4, size=(25, 2)).astype(np.float32)
        neighbors = {int(group): {int(group)} for group in np.unique(groups)}
        key_members = {}
        for row, raw_id in zip(matrix.tolist(), retained):
            key_members.setdefault(tuple(row), set()).add(int(groups[raw_id]))
        for members in key_members.values():
            for member in members:
                neighbors[member].update(members)
        representatives = {}
        for group in neighbors:
            reached, queue = {group}, [group]
            while queue:
                next_group = queue.pop()
                unseen = neighbors[next_group] - reached
                reached.update(unseen)
                queue.extend(unseen)
            representatives[group] = min(reached)
        expected = np.array([representatives[int(group)] for group in groups])
        actual, unions = tool._independent_collision_union(matrix, retained, groups)
        assert np.array_equal(tool._first_occurrence_partition(actual),
                              tool._first_occurrence_partition(expected))
        assert unions == len(np.unique(groups)) - len(np.unique(expected))


def test_scaler_preserves_per_file_short_chunks_and_fp32_operation_order():
    from sklearn.preprocessing import StandardScaler
    rng = np.random.default_rng(91)
    matrix = np.c_[rng.uniform(-1000, 1000, 21), rng.uniform(-1, 1, 21)].astype(np.float32)
    fit = np.array([0, 2, 3, 6, 7, 10, 11, 14, 18, 20], dtype=np.int64)
    # Two files of 11/10 rows, each streamed with chunksize=7. The short
    # first-file tail must not be combined with the next file's first batch.
    bounds = [(0, 7), (7, 11), (11, 18), (18, 21)]
    observed_batches = []

    def encode(ids):
        observed_batches.append(ids.tolist())
        return matrix[ids].copy()

    actual = tool._fit_replay_scaler(encode, fit, bounds)
    assert observed_batches == [[0, 2, 3, 6], [7, 10], [11, 14], [18, 20]]
    expected = StandardScaler()
    for batch in ([0, 2, 3, 6], [7, 10], [11, 14], [18, 20]):
        expected.partial_fit(matrix[batch])
    assert np.array_equal(actual.mean_, expected.mean_)
    assert np.array_equal(actual.var_, expected.var_)
    assert np.array_equal(actual.scale_, expected.scale_)
    # This input genuinely distinguishes regrouped partial_fit arithmetic.
    assert not np.array_equal(actual.var_, StandardScaler().fit(matrix[fit]).var_)
    transformed = tool._scale_fp32_in_place(matrix.copy(), actual.mean_, actual.scale_)
    reference = actual.transform(matrix)
    assert np.array_equal(transformed.view(np.uint32), reference.view(np.uint32))
    wrong_precision = matrix.copy()
    wrong_precision -= actual.mean_
    wrong_precision /= actual.scale_
    assert not np.array_equal(wrong_precision.view(np.uint32), reference.view(np.uint32))


def _raw_context(raw_root, metadata):
    from data_loaders import NSL_FEATURES, source_files
    dataset = metadata["dataset"]
    files = []
    for path, role in source_files(dataset, raw_root, None):
        frame = pd.read_csv(path, header=None if dataset == "nslkdd" else "infer")
        columns = ([*NSL_FEATURES, "label", "difficulty"] if dataset == "nslkdd" else
                   [str(name).strip() for name in frame.columns])
        files.append({"path": path.relative_to(raw_root).as_posix(), "role": role,
                      "bytes": path.stat().st_size,
                      "sha256": tool.sha256(path),
                      "rows": len(frame),
                      "physical_columns": columns, "selected_columns": columns})
    return {"record": {"dataset": dataset, "features": metadata["features"],
                       "rows": metadata["raw_rows"], "files": files}, "source_spec": {}}


def _prepare(raw, temporary, *, collision=False, dataset="nslkdd"):
    import data_loaders as producer
    if collision:
        path = raw / "KDDTest+.txt"
        frame = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
        frame.iloc[5, :len(producer.NSL_FEATURES)] = frame.iloc[0, :len(producer.NSL_FEATURES)]
        column = producer.NSL_FEATURES.index("service")
        frame.iloc[0, column] = "held_only_a"
        frame.iloc[5, column] = "held_only_b"
        frame.to_csv(path, index=False, header=False)
    metadata, arrays = producer.prepare(dataset, raw, temporary / dataset, chunksize=65536)
    return metadata, arrays, _raw_context(raw, metadata)


@pytest.mark.parametrize("collision", [False, True])
def test_independent_replay_accepts_real_producer_with_raw_file_boundaries(raw, tmp_path, collision):
    metadata, arrays, raw_record = _prepare(raw, tmp_path, collision=collision)
    if collision:
        assert len(metadata["collision_iterations"]) > 1
    fingerprint = tool._verify_raw_identity_and_dedup(
        raw, raw_record, metadata, arrays, replay_protocol=True,
    )
    assert fingerprint == metadata["raw_model_view_sha256"]
    tool._verify_raw_cache_semantics(raw, raw_record, tmp_path, metadata, arrays)


@pytest.mark.parametrize("dataset", ["unsw", "cicids2017", "iot23"])
def test_independent_replay_other_official_and_combined_source_protocols(raw, tmp_path, dataset):
    metadata, arrays, raw_record = _prepare(raw, tmp_path, dataset=dataset)
    assert tool._verify_raw_identity_and_dedup(
        raw, raw_record, metadata, arrays, replay_protocol=True,
    ) == metadata["raw_model_view_sha256"]
    tool._verify_raw_cache_semantics(raw, raw_record, tmp_path, metadata, arrays)


def test_replay_fit_only_ordinal_remapping_is_not_global_raw_identity_code(raw, tmp_path):
    from data_loaders import NSL_FEATURES
    column = NSL_FEATURES.index("service")
    for filename, values in (("KDDTrain+.txt", ["a", "c", "z"]),
                             ("KDDTest+.txt", ["a", "b", "c", "y", "z"])):
        path = raw / filename
        frame = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
        frame.iloc[:, column] = np.resize(values, len(frame))
        frame.to_csv(path, index=False, header=False)
    metadata, arrays, raw_record = _prepare(raw, tmp_path)
    tool._verify_raw_identity_and_dedup(raw, raw_record, metadata, arrays, replay_protocol=True)
    tool._verify_raw_cache_semantics(raw, raw_record, tmp_path, metadata, arrays)


def test_independent_replay_rejects_actual_wrong_fold_with_correct_declaration(raw, tmp_path, monkeypatch):
    import group_protocol as producer_protocol
    original = producer_protocol._fold_zero

    def fourth(*args, **kwargs):
        before = producer_protocol.FOLD_INDEX
        try:
            producer_protocol.FOLD_INDEX = 4
            return original(*args, **kwargs)
        finally:
            producer_protocol.FOLD_INDEX = before

    with monkeypatch.context() as context:
        context.setattr(producer_protocol, "_fold_zero", fourth)
        metadata, arrays, raw_record = _prepare(raw, tmp_path)
    assert metadata["partition"]["fold_index"] == 0
    with pytest.raises(tool.VerificationError, match="Independent frozen pre-final split"):
        tool._verify_raw_identity_and_dedup(raw, raw_record, metadata, arrays, replay_protocol=True)


def test_independent_replay_rejects_forged_within_fit_union_and_valid_count_trace(raw, tmp_path):
    metadata, arrays, raw_record = _prepare(raw, tmp_path)
    metadata = copy.deepcopy(metadata)
    arrays = {key: np.array(value, copy=True) for key, value in arrays.items()}
    first, second = arrays["assignment_components_fit"][:2]
    assert first != second and not np.array_equal(arrays["x_fit"][0], arrays["x_fit"][1])
    for key in ("raw_unique_assignment_components", "assignment_components_fit"):
        arrays[key][arrays[key] == second] = first
    original_count = metadata["groups"]["raw_identity_groups"]
    metadata["groups"]["final_assignment_components"] -= 1
    metadata["collision_iterations"] = _trace(original_count, [1, 0])["collision_iterations"]
    tool._validate_collision_trace(metadata)
    with pytest.raises(tool.VerificationError, match="Independent collision-closure replay differs"):
        tool._verify_raw_identity_and_dedup(raw, raw_record, metadata, arrays, replay_protocol=True)


def test_replay_rejects_wrong_final_equivalence_even_with_correct_history_counts(raw, tmp_path):
    metadata, arrays, raw_record = _prepare(raw, tmp_path, collision=True)
    arrays = {name: np.array(value, copy=True) for name, value in arrays.items()}
    components = arrays["raw_unique_assignment_components"]
    values, counts = np.unique(components, return_counts=True)
    joined = values[counts == 2][0]
    switched = np.flatnonzero(components == joined)[1]
    target = np.flatnonzero(components != joined)[0]
    components[switched], components[target] = components[target], components[switched]
    assert len(np.unique(components)) == metadata["groups"]["final_assignment_components"]
    with pytest.raises(tool.VerificationError, match="Independent final component equivalence"):
        tool._verify_raw_identity_and_dedup(raw, raw_record, metadata, arrays, replay_protocol=True)


def test_independent_replay_accepts_arbitrary_component_name_renaming(raw, tmp_path):
    metadata, arrays, raw_record = _prepare(raw, tmp_path)
    renamed = dict(arrays)
    for name in ("raw_unique_assignment_components", *(f"assignment_components_{s}" for s in tool.SPLITS)):
        renamed[name] = (np.asarray(arrays[name]) * 17 + 5).astype(np.int64)
    tool._verify_raw_identity_and_dedup(raw, raw_record, metadata, renamed, replay_protocol=True)


def test_replay_official_boundary_comes_from_raw_files_not_cached_claim(raw, tmp_path):
    metadata, arrays, raw_record = _prepare(raw, tmp_path)
    metadata["official_train_raw_rows"] += 1
    with pytest.raises(tool.VerificationError, match="Official role boundary differs from pinned"):
        tool._verify_raw_identity_and_dedup(raw, raw_record, metadata, arrays, replay_protocol=True)


def test_official_test_raw_duplicates_inherit_excluded_representative_lineage(raw, tmp_path):
    # Test rows 0 and 5 are raw duplicates of an official-train row. Their
    # canonical test representative is reason 2, its duplicate reason 3; neither
    # needs a retained official-test final-X match because both are excluded.
    train = pd.read_csv(raw / "KDDTrain+.txt", header=None, dtype=str, keep_default_na=False)
    path = raw / "KDDTest+.txt"
    test = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    test.iloc[0] = train.iloc[0]
    test.iloc[5] = train.iloc[0]
    test.to_csv(path, index=False, header=False)
    metadata, arrays, raw_record = _prepare(raw, tmp_path)
    reasons = dict(zip(arrays["excluded_ids"].tolist(), arrays["excluded_reasons"].tolist()))
    boundary = len(train)
    assert reasons[boundary] == 2 and reasons[boundary + 5] == 3
    assert tool._verify_raw_identity_and_dedup(
        raw, raw_record, metadata, arrays, replay_protocol=True,
    ) == metadata["raw_model_view_sha256"]
    tool._verify_raw_cache_semantics(raw, raw_record, tmp_path, metadata, arrays)


def test_official_overlap_lineage_requires_exact_raw_identity_label_and_role(raw, tmp_path):
    train = pd.read_csv(raw / "KDDTrain+.txt", header=None, dtype=str, keep_default_na=False)
    path = raw / "KDDTest+.txt"
    test = pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    test.iloc[0] = train.iloc[0]
    test.to_csv(path, index=False, header=False)
    metadata, arrays, raw_record = _prepare(raw, tmp_path)
    index, mappings = tool._official_overlap_lineage_index(raw, raw_record, metadata, arrays)
    assert index is not None
    frame = next(tool._iter_raw_frames(raw, raw_record["record"]))
    original = frame.iloc[[0]].copy()
    matrix = tool._canonical_group_matrix(original, "nslkdd", metadata["features"], mappings)
    label = tool._mapped_labels(original, "nslkdd", metadata["class_names"], {})
    assert index.lookup(tool._xy_keys(matrix, label))[0].tolist() == [True]
    assert index.lookup(tool._xy_keys(matrix, (label + 1) % len(metadata["class_names"])))[0].tolist() == [False]
    changed = matrix.copy()
    changed[0, 0] += np.float32(1)
    assert index.lookup(tool._xy_keys(changed, label))[0].tolist() == [False]
    # Matching train rows must still count toward retained-train multiplicity;
    # the full semantic pass applies the official-test role mask to this index.
    tool._verify_raw_cache_semantics(raw, raw_record, tmp_path, metadata, arrays)


@pytest.mark.parametrize("change", [None, "different_raw_x", "different_label"])
@pytest.mark.parametrize("unknown_categories", [False, True])
def test_excluded_lineage_never_inflates_clean_test_final_collision_multiplicity(
    tmp_path, change, unknown_categories,
):
    """Focused raw-semantics fixture, not a claim about a full protocol history.

    Small held-out numbers 1/2 collapse under this real FP32 scaler. Historical
    component membership is a separate protocol-replay gate; here the source
    accounting must exclude raw (1,Normal) lineage without dropping (2,Normal).
    """
    from sklearn.preprocessing import StandardScaler
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    features = ["proto", "service", "state", "numeric"]
    large = np.float32(1e10)
    train = pd.DataFrame({"proto": ["tcp"] * 3, "service": ["http"] * 3,
                          "state": ["SF"] * 3,
                          "numeric": [large, large + np.float32(1024), large + np.float32(2048)],
                          "attack_cat": ["Normal", "Generic", "Normal"], "label": [0, 1, 0]})
    test = pd.DataFrame({"proto": ["tcp"] * 3, "service": ["http"] * 3,
                         "state": ["SF"] * 3, "numeric": [1.0, 1.0, 2.0],
                         "attack_cat": ["Normal"] * 3, "label": [0] * 3})
    if unknown_categories:
        # Distinct lexical tokens map to the same fitted unknown code (-1).
        # They must remain distinct in the *raw* source-lineage index.
        test["proto"] = ["held_a", "held_a", "held_b"]
    if change == "different_raw_x":
        test.loc[1, "numeric"] = 3.0
    if change == "different_label":
        test.loc[1, ["attack_cat", "label"]] = ["Generic", 1]
    files = []
    for role, frame in (("train", train), ("test", test)):
        path = raw_root / f"{role}.csv"
        frame.to_csv(path, index=False)
        files.append({"path": path.name, "role": role, "rows": len(frame),
                      "bytes": path.stat().st_size, "sha256": tool.sha256(path),
                      "physical_columns": frame.columns.tolist(),
                      "selected_columns": frame.columns.tolist()})
    record = {"record": {"dataset": "unsw", "features": features, "rows": 6,
                         "files": files}, "source_spec": {}}
    ids = {"fit": np.array([0, 1]), "validation": np.array([2]), "test": np.array([5])}
    unscaled = np.zeros((6, 4), dtype=np.float32)
    unscaled[:, -1] = np.r_[train["numeric"].to_numpy(), test["numeric"].to_numpy()]
    if unknown_categories:
        unscaled[3:, 0] = -1
    scaler = StandardScaler().fit(unscaled[:2])
    final = scaler.transform(unscaled)
    assert np.array_equal(final[3], final[5])  # excluded-vs-retained final-X collision
    prep = {"categories": {"proto": ["V:tcp"], "service": ["V:http"], "state": ["V:SF"]},
            "mean": scaler.mean_.tolist(), "var": scaler.var_.tolist(),
            "scale": scaler.scale_.tolist(), "n_fit": 2,
            "nonfinite_replacements": {"numeric": 0},
            "unknown_categories_pre_final_raw_unique": {
                split: {column: 0 for column in tool.CATEGORICAL["unsw"]} for split in tool.SPLITS}}
    if unknown_categories:
        prep["unknown_categories_pre_final_raw_unique"]["test"]["proto"] = 1
    cache = tmp_path / "cache"
    (cache / "unsw").mkdir(parents=True)
    (cache / "unsw/preprocessing.json").write_text(json.dumps(prep))
    arrays = {"excluded_ids": np.array([3, 4]), "excluded_reasons": np.array([2, 3], dtype=np.uint8),
              "preprocessing_fit_ids": ids["fit"], "final_dedup_ids": np.array([], dtype=np.int64),
              "final_dedup_origin_splits": np.array([], dtype=np.uint8)}
    all_labels = np.array([0, 1, 0, 0, 1 if change == "different_label" else 0, 0])
    for split, selected in ids.items():
        arrays.update({f"ids_{split}": selected, f"x_{split}": final[selected],
                       f"y_{split}": all_labels[selected],
                       f"multiplicity_{split}": np.ones(len(selected), dtype=np.int64)})
    metadata = {"dataset": "unsw", "raw_rows": 6, "official_train_raw_rows": 3,
                "features": features, "class_names": ["Normal", "Generic"],
                "counts": {name: len(selected) for name, selected in ids.items()},
                "exclusion_reason_codes": {str(key): value for key, value in tool.EXCLUSION_REASONS.items()}}
    if change is None:
        tool._verify_raw_cache_semantics(raw_root, record, cache, metadata, arrays)
    else:
        with pytest.raises(tool.VerificationError, match="multiplicity differs|distinct final"):
            tool._verify_raw_cache_semantics(raw_root, record, cache, metadata, arrays)


@pytest.mark.parametrize("field,value", [("fold_index", 4), ("fold_index", False),
                                          ("validation_seed", 999), ("n_splits", 6),
                                          ("test_seed", 42), ("protocol_version", "stale")])
def test_frozen_partition_declarations_are_strictly_checked(raw, tmp_path, field, value):
    metadata, _arrays, _raw = _prepare(raw, tmp_path)
    metadata["partition"][field] = value
    with pytest.raises(tool.VerificationError, match="Frozen partition declaration"):
        tool._validate_partition_contract(metadata)
