"""Deterministic exact-input grouping and split protocol.

The unit of inference is a unique labelled model-input pattern.  Rows with the
same model-view X are never split, including rows whose labels disagree.  This
module deliberately contains no model or test-metric code: split decisions use
only X groups, labels for stratification, frozen seeds, and a fixed fold index.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from contracts import require

PROTOCOL_VERSION = "raw_identity_assignment_component_final_xy_v2"
FOLDS = 5
FOLD_INDEX = 0
TEST_SEED = 42
VALIDATION_SEED = 20260920

EXCLUSION_REASONS = {
    1: "duplicate_xy_training_or_combined",
    2: "official_test_assignment_component_touches_official_train",
    3: "duplicate_raw_xy_within_official_test",
    4: "duplicate_final_xy_within_split",
}


def collision_iteration_bound(initial_groups: int) -> int:
    """At most G0-1 strict union rounds, followed by one stable scan.

    Eight rounds had no mathematical justification and truncated a genuine
    18-round UNSW closure. This bound follows from finite monotonic coarsening;
    it does not relax equality, change the split, or accept a partial closure.
    """
    require(type(initial_groups) is int and initial_groups > 0,
            "Collision closure requires a positive integer initial group count")
    return initial_groups


def validate_collision_trace(trace: list[dict], initial_groups: int,
                             final_groups: int) -> None:
    """Validate strict progress and the first (and only) terminal stable scan.

    This is a structural certificate, not independent replay of historical
    collision edges. The separate raw-data verifier must establish that replay.
    """
    bound = collision_iteration_bound(initial_groups)
    require(type(final_groups) is int and 0 < final_groups <= initial_groups,
            "Invalid final assignment component count")
    require(isinstance(trace, list) and 1 <= len(trace) <= bound and
            len(trace) <= initial_groups - final_groups + 1,
            "Collision-closure trace violates its finite-progress bound")
    expected_input = initial_groups
    fields = {"iteration", "input_groups", "output_groups", "new_group_unions"}
    for iteration, row in enumerate(trace):
        require(isinstance(row, dict) and set(row) == fields and
                all(type(row[key]) is int for key in fields),
                "Collision-closure trace fields must be exact integers")
        terminal = iteration == len(trace) - 1
        require(row["iteration"] == iteration and
                row["input_groups"] == expected_input and
                0 < row["output_groups"] <= row["input_groups"] and
                row["input_groups"] - row["output_groups"] == row["new_group_unions"] and
                (row["new_group_unions"] == 0 if terminal else row["new_group_unions"] > 0),
                "Collision-closure trace has discontinuous or non-strict progress")
        expected_input = row["output_groups"]
    require(expected_input == final_groups,
            "Collision-closure terminal component count differs")


def _row_bytes(matrix: np.ndarray) -> np.ndarray:
    """Collision-free keys for a fixed-width C-contiguous numeric matrix."""
    array = np.ascontiguousarray(matrix)
    require(array.ndim == 2 and len(array) > 0 and array.shape[1] > 0,
            "Grouping needs a non-empty two-dimensional matrix")
    return array.view(np.dtype((np.void, array.dtype.itemsize * array.shape[1]))).reshape(-1)


def canonical_numeric(series: pd.Series, reject_nonfinite: bool) -> np.ndarray:
    """Declared numeric cleaning followed by the model's FP32 input cast.

    Signed zero is canonicalized because +0 and -0 are numerically identical to
    the model.  No scaler statistics participate in this pre-split identity.
    """
    cleaned = series.replace({
        "-": np.nan, "": np.nan, "NaN": np.nan, "nan": np.nan,
        "Infinity": np.inf, "-Infinity": -np.inf,
    })
    numeric = pd.to_numeric(cleaned, errors="raise").to_numpy(dtype=np.float64, copy=True)
    bad = ~np.isfinite(numeric)
    require(not (reject_nonfinite and bad.any()),
            f"Non-finite/missing numeric value in canonical group view: {series.name}")
    numeric[bad] = 0.0
    require((np.abs(numeric) <= np.finfo(np.float32).max).all(),
            f"FP32 overflow in canonical group view: {series.name}")
    result = numeric.astype(np.float32)
    result[result == 0] = np.float32(0.0)  # erase the sign bit of negative zero
    return result


def categorical_identity_tokens(series: pd.Series) -> pd.Series:
    """Preserve exact string tokens while keeping null distinct from text.

    Refuse implicit ``str()`` coercion: otherwise a typed value such as integer
    1 would alias the literal raw token ``"1"`` before split construction.
    """
    nonnull = series[~series.isna()]
    require(bool(nonnull.map(lambda value: isinstance(value, str)).all()),
            f"Categorical identity field {series.name} contains a non-string token")
    return series.astype(object).map(lambda value: "M:" if pd.isna(value) else "V:" + str(value))


def canonical_model_view(
    frame: pd.DataFrame,
    features: list[str],
    categorical: list[str],
    identity_categories: Mapping[str, list[str]],
    *,
    reject_nonfinite: bool,
) -> np.ndarray:
    """Create the pre-split exact model view.

    Category IDs come from a global lexical *identity* dictionary.  This is not
    the fitted model encoder and is never exported as preprocessing state; it
    merely gives equal raw tokens equal fixed-width values for exact grouping.
    """
    require(len(features) > 0 and len(set(features)) == len(features),
            "Canonical group view requires unique ordered features")
    output = np.empty((len(frame), len(features)), dtype=np.float32)
    categorical_set = set(categorical)
    for column_index, column in enumerate(features):
        require(column in frame, f"Canonical group feature missing: {column}")
        if column in categorical_set:
            vocabulary = identity_categories.get(column)
            require(isinstance(vocabulary, list) and vocabulary,
                    f"Missing identity vocabulary for {column}")
            require(len(vocabulary) <= 2**24,
                    f"Identity vocabulary for {column} cannot be represented exactly in FP32")
            mapping = {token: index for index, token in enumerate(vocabulary)}
            encoded = categorical_identity_tokens(frame[column]).map(mapping)
            require(encoded.notna().all(), f"Identity vocabulary omitted raw token in {column}")
            output[:, column_index] = encoded.to_numpy(dtype=np.float32)
        else:
            output[:, column_index] = canonical_numeric(frame[column], reject_nonfinite)
    output[output == 0] = np.float32(0.0)
    return output


def exact_group_ids(model_view: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return dense deterministic group IDs and multiplicity by group."""
    _, inverse, counts = np.unique(_row_bytes(model_view), return_inverse=True, return_counts=True)
    return inverse.astype(np.int64, copy=False), counts.astype(np.int64, copy=False)


def group_fingerprint(model_view: np.ndarray) -> str:
    """SHA-256 of the exact ordered canonical rows, shape, and dtype."""
    array = np.ascontiguousarray(model_view)
    digest = hashlib.sha256()
    digest.update(f"{array.dtype.str}:{array.shape[0]}:{array.shape[1]}".encode("ascii"))
    digest.update(memoryview(array).cast("B"))
    return digest.hexdigest()


def deduplicate_xy(indices: np.ndarray, groups: np.ndarray, labels: np.ndarray
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Keep the lowest raw row ID for each (X-group,label), with multiplicity."""
    indices = np.asarray(indices, dtype=np.int64)
    require(indices.ndim == 1 and len(indices) > 0, "Cannot deduplicate an empty row set")
    order = indices[np.lexsort((indices, labels[indices], groups[indices]))]
    ordered_groups, ordered_labels = groups[order], labels[order]
    first = np.r_[True, (ordered_groups[1:] != ordered_groups[:-1]) |
                  (ordered_labels[1:] != ordered_labels[:-1])]
    starts = np.flatnonzero(first)
    representatives = order[starts]
    multiplicity = np.diff(np.r_[starts, len(order)]).astype(np.int64)
    kept = np.zeros(len(groups), dtype=bool)
    kept[representatives] = True
    excluded = indices[~kept[indices]]
    return np.sort(representatives), multiplicity[np.argsort(representatives)], np.sort(excluded)


def _fold_zero(indices: np.ndarray, labels: np.ndarray, groups: np.ndarray, classes: int, seed: int
               ) -> tuple[np.ndarray, np.ndarray]:
    """Frozen SGKF objective and fold rule; no performance value is available."""
    indices = np.asarray(indices, dtype=np.int64)
    require(len(indices) > 0, "Cannot split an empty retained set")
    local_labels, arbitrary_groups = labels[indices], groups[indices]
    # StratifiedGroupKFold's shuffled tie handling is not invariant to an
    # arbitrary renaming of group labels. Canonicalize by first occurrence in
    # this already sorted candidate population so official-test-only tokens can
    # never perturb an official-train fit/validation split.
    _, first, inverse = np.unique(
        arbitrary_groups, return_index=True, return_inverse=True,
    )
    first_order = np.argsort(first, kind="stable")
    remap = np.empty(len(first_order), dtype=np.int64)
    remap[first_order] = np.arange(len(first_order), dtype=np.int64)
    local_groups = remap[inverse]
    support = np.bincount(local_labels, minlength=classes)
    require((support >= FOLDS).all(),
            f"Every class needs at least {FOLDS} retained labelled patterns for grouped splitting")
    group_support = np.array([
        len(np.unique(local_groups[local_labels == label])) for label in range(classes)
    ])
    require((group_support >= FOLDS).all(),
            f"Every class needs at least {FOLDS} distinct exact-X groups for grouped splitting")
    splitter = StratifiedGroupKFold(
        n_splits=FOLDS, shuffle=True, random_state=seed,
    )
    selected = None
    for fold_index, fold in enumerate(splitter.split(
            local_labels.reshape(-1, 1), local_labels, local_groups)):
        if fold_index == FOLD_INDEX:
            selected = fold
            break
    require(selected is not None, "Frozen grouped fold index is unavailable")
    train_local, held_local = selected
    train, held = np.sort(indices[train_local]), np.sort(indices[held_local])
    require(not np.intersect1d(groups[train], groups[held]).size,
            "A model-input group crossed a frozen fold boundary")
    return train, held


@dataclass(frozen=True)
class Partition:
    splits: dict[str, np.ndarray]
    multiplicity: dict[str, np.ndarray]
    excluded_ids: np.ndarray
    excluded_reasons: np.ndarray
    raw_unique_ids: np.ndarray
    raw_unique_multiplicity: np.ndarray
    report: dict


@dataclass(frozen=True)
class FinalizedPartition:
    partition: Partition
    keep_positions: dict[str, np.ndarray]
    removed_ids: np.ndarray
    representative_ids: np.ndarray
    origin_splits: np.ndarray


def _supports(labels: np.ndarray, indices: np.ndarray, classes: int) -> list[int]:
    return np.bincount(labels[indices], minlength=classes).astype(int).tolist()


def build_partition(identity_groups: np.ndarray, labels: np.ndarray, classes: int,
                    official_train_rows: int | None, *,
                    assignment_components: np.ndarray | None = None) -> Partition:
    """Apply immutable raw-identity dedup and grouped assignment.

    ``identity_groups`` never changes and is the only identity used for raw
    (X,label) deduplication. ``assignment_components`` may monotonically union
    identities whose transformed tensors collided, but is used only to keep
    them in one split. A transient collision must never delete a raw pattern.
    """
    identity_groups = np.asarray(identity_groups, dtype=np.int64)
    labels = np.asarray(labels, dtype=np.int64)
    assignment_components = (identity_groups if assignment_components is None
                             else np.asarray(assignment_components, dtype=np.int64))
    require(identity_groups.shape == labels.shape == assignment_components.shape and
            identity_groups.ndim == 1 and len(identity_groups) > 0,
            "Invalid identity/component/label arrays")
    require((identity_groups >= 0).all() and (assignment_components >= 0).all(),
            "Identity and assignment component IDs must be nonnegative")
    identity_order = np.argsort(identity_groups, kind="stable")
    ordered_identities = identity_groups[identity_order]
    ordered_components = assignment_components[identity_order]
    same_identity = ordered_identities[1:] == ordered_identities[:-1]
    require(not np.any(same_identity &
                       (ordered_components[1:] != ordered_components[:-1])),
            "Assignment components must be a coarsening of immutable raw identities")
    require((labels >= 0).all() and (labels < classes).all(), "Label outside declared schema")
    n = len(labels)
    multiplicity_by_id = np.zeros(n, dtype=np.int64)
    excluded_reason_by_id = np.zeros(n, dtype=np.uint8)

    if official_train_rows is not None:
        require(0 < official_train_rows < n, "Invalid official train boundary")
        official_train = np.arange(official_train_rows, dtype=np.int64)
        official_test = np.arange(official_train_rows, n, dtype=np.int64)
        train_representatives, train_multiplicity, train_duplicates = deduplicate_xy(
            official_train, identity_groups, labels,
        )
        multiplicity_by_id[train_representatives] = train_multiplicity
        excluded_reason_by_id[train_duplicates] = 1
        test_representatives, test_multiplicity, test_duplicates = deduplicate_xy(
            official_test, identity_groups, labels,
        )
        multiplicity_by_id[test_representatives] = test_multiplicity
        excluded_reason_by_id[test_duplicates] = 3

        training_components = np.unique(assignment_components[official_train])
        test_overlap = test_representatives[np.isin(
            assignment_components[test_representatives], training_components,
        )]
        excluded_reason_by_id[test_overlap] = 2
        clean_test = test_representatives[excluded_reason_by_id[test_representatives] == 0]
        require(len(clean_test) > 0, "Every official test pattern overlaps official training")
        fit, validation = _fold_zero(
            train_representatives, labels, assignment_components, classes, VALIDATION_SEED,
        )
        test = clean_test
        raw_unique_ids = np.sort(np.r_[train_representatives, test_representatives])
        role = "official_train_grouped_validation_and_clean_official_test"
    else:
        all_rows = np.arange(n, dtype=np.int64)
        representatives, retained_multiplicity, duplicates = deduplicate_xy(
            all_rows, identity_groups, labels,
        )
        multiplicity_by_id[representatives] = retained_multiplicity
        excluded_reason_by_id[duplicates] = 1
        train_validation, test = _fold_zero(
            representatives, labels, assignment_components, classes, TEST_SEED,
        )
        fit, validation = _fold_zero(
            train_validation, labels, assignment_components, classes, VALIDATION_SEED,
        )
        raw_unique_ids = representatives
        role = "xy_deduplicated_exact_x_grouped_target_64_16_20"

    splits = {"fit": fit, "validation": validation, "test": np.sort(test)}
    retained = np.concatenate(list(splits.values()))
    require(len(np.unique(retained)) == len(retained), "A retained row occurs in multiple splits")
    for left, right in (("fit", "validation"), ("fit", "test"), ("validation", "test")):
        require(not np.intersect1d(assignment_components[splits[left]],
                                   assignment_components[splits[right]]).size,
                f"Assignment component crosses {left}/{right}")
    excluded_ids = np.flatnonzero(excluded_reason_by_id).astype(np.int64)
    require(len(retained) + len(excluded_ids) == n and
            np.array_equal(np.sort(np.r_[retained, excluded_ids]), np.arange(n)),
            "Retained/excluded rows do not account for the raw dataset exactly once")
    for split, indices in splits.items():
        require(all(value > 0 for value in _supports(labels, indices, classes)),
                f"{split} lacks a declared class")
    multiplicity = {name: multiplicity_by_id[indices] for name, indices in splits.items()}
    require(all((values > 0).all() for values in multiplicity.values()),
            "Retained representatives need positive source multiplicity")
    reason_counts = {
        EXCLUSION_REASONS[code]: int((excluded_reason_by_id == code).sum())
        for code in EXCLUSION_REASONS
    }
    report = {
        "protocol_version": PROTOCOL_VERSION,
        "role": role,
        "stratifier": "sklearn.model_selection.StratifiedGroupKFold",
        "objective": "approximate per-class balance over retained labelled patterns",
        "n_splits": FOLDS,
        "fold_index": FOLD_INDEX,
        "test_seed": TEST_SEED if official_train_rows is None else None,
        "validation_seed": VALIDATION_SEED,
        "selection_prohibition": "fold zero is fixed before training; no model/test performance may select a fold",
        "raw_rows": n,
        "retained_rows": len(retained),
        "excluded_rows": len(excluded_ids),
        "exclusion_reason_counts": reason_counts,
        "support": {name: _supports(labels, indices, classes) for name, indices in splits.items()},
        "source_multiplicity": {name: int(values.sum()) for name, values in multiplicity.items()},
        "raw_unique_patterns": len(raw_unique_ids),
        "raw_unique_source_multiplicity": int(multiplicity_by_id[raw_unique_ids].sum()),
        "retained_pattern_fractions": {
            name: len(indices) / len(retained) for name, indices in splits.items()
        },
        "target_pattern_fractions": (
            {"fit": 0.64, "validation": 0.16, "test": 0.20}
            if official_train_rows is None else None
        ),
    }
    return Partition(
        splits=splits,
        multiplicity=multiplicity,
        excluded_ids=excluded_ids,
        excluded_reasons=excluded_reason_by_id[excluded_ids],
        raw_unique_ids=raw_unique_ids,
        raw_unique_multiplicity=multiplicity_by_id[raw_unique_ids],
        report=report,
    )


def _deduplicate_final_xy(matrix: np.ndarray, labels: np.ndarray, ids: np.ndarray,
                          multiplicity: np.ndarray,
                          ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Deduplicate stable final (FP32-X,label), retaining the lowest raw ID."""
    matrix = np.asarray(matrix)
    labels = np.asarray(labels, dtype=np.int64)
    ids = np.asarray(ids, dtype=np.int64)
    multiplicity = np.asarray(multiplicity, dtype=np.int64)
    require(matrix.dtype == np.float32 and matrix.ndim == 2 and
            labels.shape == ids.shape == multiplicity.shape == (len(matrix),),
            "Invalid stable final-dedup inputs")
    require(len(ids) > 0 and (np.diff(ids) > 0).all() and (multiplicity > 0).all(),
            "Stable final-dedup IDs/multiplicity are invalid")
    row_keys = _row_bytes(matrix)
    keys = np.empty(len(matrix), dtype=np.dtype([
        ("x", row_keys.dtype), ("label", np.dtype("<i8")),
    ]))
    keys["x"] = row_keys
    keys["label"] = labels
    _, first, inverse = np.unique(keys, return_index=True, return_inverse=True)
    keep = np.sort(first.astype(np.int64, copy=False))
    removed = np.setdiff1d(np.arange(len(ids), dtype=np.int64), keep,
                           assume_unique=True)
    # Sum int64 multiplicities without the float conversion performed by
    # np.bincount(weights=...). Unique-key IDs are dense 0..K-1.
    order = np.argsort(inverse, kind="stable")
    starts = np.r_[0, np.flatnonzero(np.diff(inverse[order])) + 1]
    sums = np.add.reduceat(multiplicity[order], starts)
    require(len(sums) == len(first) and (sums > 0).all(),
            "Final source multiplicity aggregation failed")
    retained_multiplicity = sums[inverse[keep]]
    removed_representatives = ids[first[inverse[removed]]]
    require((removed_representatives < ids[removed]).all(),
            "Final dedup did not retain the lowest raw ID")
    return keep, retained_multiplicity, removed, removed_representatives


def finalize_partition(partition: Partition, labels: np.ndarray,
                       final_x: Mapping[str, np.ndarray], classes: int) -> FinalizedPartition:
    """Deduplicate stable final tensors without refitting preprocessing."""
    labels = np.asarray(labels, dtype=np.int64)
    keep_positions: dict[str, np.ndarray] = {}
    final_splits: dict[str, np.ndarray] = {}
    final_multiplicity: dict[str, np.ndarray] = {}
    removed_ids, representative_ids, origin_splits = [], [], []
    for split_code, split in enumerate(("fit", "validation", "test")):
        ids = partition.splits[split]
        keep, multiplicity, removed, representatives = _deduplicate_final_xy(
            final_x[split], labels[ids], ids, partition.multiplicity[split],
        )
        keep_positions[split] = keep
        final_splits[split] = ids[keep]
        final_multiplicity[split] = multiplicity
        removed_ids.append(ids[removed])
        representative_ids.append(representatives)
        origin_splits.append(np.full(len(removed), split_code, dtype=np.uint8))
        require(all(value > 0 for value in _supports(labels, final_splits[split], classes)),
                f"{split} loses a declared class after stable final-X deduplication")
    removed_ids_array = np.concatenate(removed_ids).astype(np.int64, copy=False)
    representative_ids_array = np.concatenate(representative_ids).astype(np.int64, copy=False)
    origin_splits_array = np.concatenate(origin_splits).astype(np.uint8, copy=False)
    existing_reason = np.zeros(len(labels), dtype=np.uint8)
    existing_reason[partition.excluded_ids] = partition.excluded_reasons
    require(not existing_reason[removed_ids_array].any(),
            "Stable final duplicate was already excluded for another reason")
    existing_reason[removed_ids_array] = 4
    excluded_ids = np.flatnonzero(existing_reason).astype(np.int64)
    retained = np.concatenate(list(final_splits.values()))
    require(len(retained) + len(excluded_ids) == len(labels) and
            np.array_equal(np.sort(np.r_[retained, excluded_ids]), np.arange(len(labels))),
            "Final retained/excluded IDs do not account for every raw row")
    raw_unique_reason = existing_reason[partition.raw_unique_ids]
    official_overlap_source_rows = int(partition.raw_unique_multiplicity[
        raw_unique_reason == 2
    ].sum())
    retained_source_rows = sum(int(value.sum()) for value in final_multiplicity.values())
    require(retained_source_rows + official_overlap_source_rows == len(labels),
            "Final source multiplicity plus official overlap does not equal raw rows")
    reason_counts = {
        EXCLUSION_REASONS[code]: int((existing_reason == code).sum())
        for code in EXCLUSION_REASONS
    }
    report = {
        **partition.report,
        "retained_rows": len(retained),
        "excluded_rows": len(excluded_ids),
        "exclusion_reason_counts": reason_counts,
        "support": {name: _supports(labels, ids, classes)
                    for name, ids in final_splits.items()},
        "source_multiplicity": {name: int(values.sum())
                                for name, values in final_multiplicity.items()},
        "retained_pattern_fractions": {
            name: len(ids) / len(retained) for name, ids in final_splits.items()
        },
        "stable_final_xy_removed_patterns": len(removed_ids_array),
        "official_overlap_source_rows": official_overlap_source_rows,
        "retained_source_rows": retained_source_rows,
        "source_rows_reconciled": retained_source_rows + official_overlap_source_rows,
    }
    final_partition = Partition(
        splits=final_splits,
        multiplicity=final_multiplicity,
        excluded_ids=excluded_ids,
        excluded_reasons=existing_reason[excluded_ids],
        raw_unique_ids=partition.raw_unique_ids,
        raw_unique_multiplicity=partition.raw_unique_multiplicity,
        report=report,
    )
    order = np.argsort(removed_ids_array)
    return FinalizedPartition(
        partition=final_partition,
        keep_positions=keep_positions,
        removed_ids=removed_ids_array[order],
        representative_ids=representative_ids_array[order],
        origin_splits=origin_splits_array[order],
    )


def merge_final_collisions(final_x: Mapping[str, np.ndarray], splits: Mapping[str, np.ndarray],
                           groups: np.ndarray) -> tuple[np.ndarray, int]:
    """Monotonically union pre-split groups that collide in final FP32 space."""
    names = ("fit", "validation", "test")
    matrices = [np.asarray(final_x[name], dtype=np.float32) for name in names]
    require(all(matrix.ndim == 2 for matrix in matrices) and
            len({matrix.shape[1] for matrix in matrices}) == 1,
            "Final collision scan received incompatible matrices")
    raw_groups = np.asarray(groups, dtype=np.int64)
    require(raw_groups.ndim == 1 and len(raw_groups) > 0 and (raw_groups >= 0).all(),
            "Final collision scan received invalid assignment components")
    _, dense_groups = np.unique(raw_groups, return_inverse=True)
    dense_groups = dense_groups.astype(np.int64, copy=False)
    retained_ids = np.concatenate([np.asarray(splits[name], dtype=np.int64) for name in names])
    matrix = np.concatenate(matrices, axis=0)
    matrix[matrix == 0] = np.float32(0.0)
    keys = _row_bytes(matrix)
    current = dense_groups[retained_ids]
    order = np.argsort(keys, kind="stable")
    sorted_keys, sorted_groups = keys[order], current[order]
    same_key = sorted_keys[1:] == sorted_keys[:-1]
    distinct_group = sorted_groups[1:] != sorted_groups[:-1]
    locations = np.flatnonzero(same_key & distinct_group)
    if not len(locations):
        return dense_groups.copy(), 0

    parent = np.arange(int(dense_groups.max()) + 1, dtype=np.int64)

    def root(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = int(parent[value])
        return value

    merges = 0
    for location in locations:
        left, right = root(int(sorted_groups[location])), root(int(sorted_groups[location + 1]))
        if left != right:
            low, high = sorted((left, right))
            parent[high] = low
            merges += 1
    for value in range(len(parent)):
        parent[value] = root(value)
    merged = parent[dense_groups]
    _, dense = np.unique(merged, return_inverse=True)
    return dense.astype(np.int64, copy=False), merges


def exact_overlap_counts(final_x: Mapping[str, np.ndarray]) -> dict[str, int]:
    """Exact byte-overlap counts between every pair of final FP32 partitions."""
    keys = {name: np.unique(_row_bytes(np.asarray(matrix, dtype=np.float32)))
            for name, matrix in final_x.items()}
    return {
        f"{left}_vs_{right}": int(np.intersect1d(keys[left], keys[right]).size)
        for left, right in (("fit", "validation"), ("fit", "test"), ("validation", "test"))
    }


def final_xy_duplicate_count(matrix: np.ndarray, labels: np.ndarray) -> int:
    """Count rows beyond the first exact stable (FP32-X,label) occurrence."""
    matrix = np.asarray(matrix)
    labels = np.asarray(labels, dtype=np.int64)
    require(matrix.dtype == np.float32 and matrix.ndim == 2 and labels.shape == (len(matrix),),
            "Invalid final (X,label) duplicate scan")
    row_keys = _row_bytes(matrix)
    keys = np.empty(len(matrix), dtype=np.dtype([
        ("x", row_keys.dtype), ("label", np.dtype("<i8")),
    ]))
    keys["x"] = row_keys
    keys["label"] = labels
    return len(keys) - len(np.unique(keys))
