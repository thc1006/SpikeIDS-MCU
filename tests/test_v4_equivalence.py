"""Guards for scripts/run_v4_equivalence.py: the training-budget table must match
the experiment scripts, pair_validity must detect any budget mismatch, and after the
CICIDS2017 QCFS re-run at the matched 80 ep / batch 512 / 10-seed budget every arm is
budget-matched and enters the Holm family (the earlier CICIDS confound is fixed)."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import run_v4_equivalence as v4  # noqa: E402

# A script declares its training batch either as a DataLoader literal
# (batch_size=N, shuffle=True) or, for the refactored CICIDS QCFS runner, as the
# argparse default (default=N, dest="batch_size").
_BATCH_PATS = [
    re.compile(r"batch_size=(\d+),\s*shuffle=True"),
    re.compile(r'default=(\d+),\s*dest="batch_size"'),
]


@pytest.mark.parametrize("ds", sorted(v4.TRAIN_BATCH))
def test_train_batch_table_matches_scripts(ds):
    for arm, (script, batch) in v4.TRAIN_BATCH[ds].items():
        src = (ROOT / "src" / script).read_text()
        found = {int(m) for pat in _BATCH_PATS for m in pat.findall(src)}
        assert batch in found, f"{script}: table batch {batch} not among script batches {found}"


def test_pair_validity_flags_budget_mismatch():
    # matched budget -> valid
    ok = v4.pair_validity("cicids2017", {"epochs": 80, "n_train": 1, "n_test": 2},
                          {"epochs": 80, "n_train": 1, "n_test": 2})
    assert ok == {"valid": True, "confounds": []}
    # an epoch mismatch is still detected (both arms are batch 512 now, so no batch confound)
    bad = v4.pair_validity("cicids2017", {"epochs": 80, "n_train": 1, "n_test": 2},
                           {"epochs": 40, "n_train": 1, "n_test": 2})
    assert bad["valid"] is False
    assert bad["confounds"] == ["epochs 80 vs 40"]
    # a sample-count mismatch is detected too
    bad2 = v4.pair_validity("unsw", {"epochs": 80, "n_train": 1, "n_test": 2},
                            {"epochs": 80, "n_train": 9, "n_test": 2})
    assert bad2["valid"] is False and "n_train 1 vs 9" in bad2["confounds"]


def test_loaded_arms_all_matched():
    arms = v4.load_arms()
    invalid = {ds for ds, a in arms.items() if not a["validity"]["valid"]}
    assert invalid == set(), f"unexpected confounded arms: {invalid}"
    # All four datasets re-run to 20 deterministic seeds with the shared train_fast
    # trainer (NSL migrated too); every ReLU-vs-QCFS pair is now 20 matched seeds.
    assert arms["nslkdd"]["n"] == 20 and arms["unsw"]["n"] == 20
    assert arms["cicids2017"]["n"] == 20 and arms["iot23"]["n"] == 20


def test_end_to_end_report(tmp_path):
    out = tmp_path / "eq"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "run_v4_equivalence.py"),
                    "--out", str(out)], check=True, capture_output=True)
    rep = json.loads((out.with_suffix(".json")).read_text())
    # all four datasets now enter the Holm family (both metrics each)
    assert set(rep["holm_bonferroni_tost_t"]) == {
        "nslkdd:overall_acc", "nslkdd:macro_f1", "unsw:overall_acc", "unsw:macro_f1",
        "cicids2017:overall_acc", "cicids2017:macro_f1", "iot23:overall_acc", "iot23:macro_f1"}
    assert "cicids2017:overall_acc" in rep["pairs"]
    assert rep["holm_bonferroni_tost_t"]["unsw:overall_acc"]["equivalent"] is True
    assert rep["seed_pairing"]["cicids2017"]["valid"] is True
    assert rep["seed_pairing"]["cicids2017"]["confounds"] == []
    md = out.with_suffix(".md").read_text()
    assert "cicids2017 ⚠️" not in md  # no longer flagged as confounded
