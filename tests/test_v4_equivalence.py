"""Guards for scripts/run_v4_equivalence.py: the training-budget table must
match the experiment scripts, confounded pairs must be flagged and kept out
of the Holm family, and the end-to-end run must reproduce the report."""

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

_TRAIN_LOADER = re.compile(r"batch_size=(\d+),\s*shuffle=True")


@pytest.mark.parametrize("ds", sorted(v4.TRAIN_BATCH))
def test_train_batch_table_matches_scripts(ds):
    for arm, (script, batch) in v4.TRAIN_BATCH[ds].items():
        src = (ROOT / "src" / script).read_text()
        found = {int(m) for m in _TRAIN_LOADER.findall(src)}
        assert found == {batch}, f"{script}: training batch sizes {found} != table {batch}"


def test_pair_validity_flags_budget_mismatch():
    ok = v4.pair_validity("unsw", {"epochs": 80, "n_train": 1, "n_test": 2},
                          {"epochs": 80, "n_train": 1, "n_test": 2})
    assert ok == {"valid": True, "confounds": []}
    bad = v4.pair_validity("cicids2017", {"epochs": 80, "n_train": 1, "n_test": 2},
                           {"epochs": 40, "n_train": 1, "n_test": 2})
    assert bad["valid"] is False
    assert bad["confounds"] == ["epochs 80 vs 40", "batch_size 512 vs 1024"]


def test_loaded_arms_flag_only_cicids():
    arms = v4.load_arms()
    invalid = {ds for ds, a in arms.items() if not a["validity"]["valid"]}
    assert invalid == {"cicids2017"}
    assert arms["nslkdd"]["n"] == 20 and arms["unsw"]["n"] == 10
    assert arms["iot23"]["n"] == 5 and arms["cicids2017"]["n"] == 5


def test_end_to_end_report(tmp_path):
    out = tmp_path / "eq"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "run_v4_equivalence.py"),
                    "--out", str(out)], check=True, capture_output=True)
    rep = json.loads((out.with_suffix(".json")).read_text())
    assert set(rep["holm_bonferroni_tost_t"]) == {
        "nslkdd:overall_acc", "nslkdd:macro_f1", "unsw:overall_acc",
        "unsw:macro_f1", "iot23:overall_acc", "iot23:macro_f1"}
    assert "cicids2017:overall_acc" in rep["pairs"]          # analysed
    assert "cicids2017:overall_acc" not in rep["holm_bonferroni_tost_t"]  # not claimed
    assert rep["holm_bonferroni_tost_t"]["unsw:overall_acc"]["equivalent"] is True
    assert rep["seed_pairing"]["cicids2017"]["valid"] is False
    md = out.with_suffix(".md").read_text()
    assert "confounded" in md and "cicids2017 ⚠️" in md
