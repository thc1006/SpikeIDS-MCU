"""Finite-progress closure must not confuse eight rounds with a proof."""
import copy

import numpy as np
import pytest

import contracts as c
import data_loaders as dl
from group_protocol import collision_iteration_bound, validate_collision_trace


def chain(initial=13, merges=11):
    rows = [{"iteration": i, "input_groups": initial-i,
             "output_groups": initial-i-1, "new_group_unions": 1}
            for i in range(merges)]
    rows.append({"iteration": merges, "input_groups": initial-merges,
                 "output_groups": initial-merges, "new_group_unions": 0})
    return rows


def test_long_closure_is_accepted_only_at_its_stable_scan():
    assert collision_iteration_bound(13) == 13
    validate_collision_trace(chain(), 13, 2)
    with pytest.raises(c.ContractError):
        validate_collision_trace(chain()[:8], 13, 5)


def test_tight_bound_includes_terminal_scan_and_singleton():
    validate_collision_trace(chain(initial=13, merges=12), 13, 1)
    validate_collision_trace(chain(initial=1, merges=0), 1, 1)


@pytest.mark.parametrize("initial", [0, -1, True, 1.0, "13", None])
def test_invalid_initial_component_count_is_rejected(initial):
    with pytest.raises(c.ContractError):
        collision_iteration_bound(initial)


@pytest.mark.parametrize("change", [
    "duplicate_terminal", "zero_then_progress", "discontinuous",
    "wrong_union_count", "negative_union_count", "boolean_iteration",
    "float_count", "extra_field", "wrong_final", "empty", "missing",
])
def test_invalid_progress_certificates_are_rejected(change):
    rows = copy.deepcopy(chain())
    final = 2
    if change == "duplicate_terminal":
        rows.append({**rows[-1], "iteration": len(rows)})
    elif change == "zero_then_progress":
        rows[0]["new_group_unions"] = 0
        rows[0]["output_groups"] = rows[0]["input_groups"]
    elif change == "discontinuous":
        rows[2]["input_groups"] -= 1
        rows[2]["output_groups"] -= 1
    elif change == "wrong_union_count":
        rows[2]["new_group_unions"] += 1
    elif change == "negative_union_count":
        rows[2]["new_group_unions"] = -1
    elif change == "boolean_iteration":
        rows[0]["iteration"] = False
    elif change == "float_count":
        rows[0]["input_groups"] = 13.0
    elif change == "extra_field":
        rows[0]["waived"] = True
    elif change == "wrong_final":
        final = 3
    elif change == "empty":
        rows = []
    elif change == "missing":
        rows = None
    with pytest.raises(c.ContractError):
        validate_collision_trace(rows, 13, final)


def test_prepare_does_not_truncate_a_valid_long_sequence(raw, tmp_path, monkeypatch):
    """Control-flow test: inject transient collisions, not scientific evidence.

    Nine genuine union operations on temporary transformed views model a long
    closure. The final scan uses actual tensors; real UNSW is separately checked
    end to end and must never be replaced by this synthetic control-flow case.
    """
    merge = dl.merge_final_collisions
    calls = 0

    def long_sequence(outputs, indices, groups):
        nonlocal calls
        calls += 1
        if calls <= 9:
            fit_groups = groups[indices["fit"]]
            _, first = np.unique(fit_groups, return_index=True)
            left, right = first[:2]
            temporary = {name: np.array(x, copy=True) for name, x in outputs.items()}
            temporary["fit"][right] = temporary["fit"][left]
            merged, unions = merge(temporary, indices, groups)
            assert unions > 0
            return merged, unions
        return merge(outputs, indices, groups)

    monkeypatch.setattr(dl, "merge_final_collisions", long_sequence)
    metadata, _ = dl.prepare("nslkdd", raw, tmp_path / "cache", chunksize=17)
    assert calls >= 10
    assert len(metadata["collision_iterations"]) == calls
    assert metadata["collision_iterations"][-1]["new_group_unions"] == 0
    assert all(row["new_group_unions"] > 0 for row in metadata["collision_iterations"][:-1])


def test_open_cache_rejects_resealed_extra_stable_iteration(raw, tmp_path):
    cache = tmp_path / "cache"
    metadata, _ = dl.prepare("nslkdd", raw, cache, chunksize=17)
    metadata.pop("content_sha256")
    metadata.pop("data_fingerprint")
    trace = metadata["collision_iterations"]
    trace.append({**trace[-1], "iteration": len(trace)})
    metadata["data_fingerprint"] = c.digest(metadata)
    c.write_json(cache / "metadata.json", c.seal(metadata))
    with pytest.raises(c.ContractError, match="Collision-closure"):
        dl.open_cache(cache)
