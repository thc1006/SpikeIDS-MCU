#!/usr/bin/env bash
# Concurrent IoT-23 v4 re-run: 5 workers over disjoint seed pairs, both arms, batch 1024.
# Each worker is bit-faithful (own seeds/set_seed); concurrency just fills the launch-bound
# GPU idle time. Merges the 5 parts into the two schema-compatible JSONs at the end.
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
LOGD=/tmp/claude-1000/-home-thc1006-dev-SpikeIDS-MCU/e287e8df-b593-44ae-b9b0-05620b77d9a7/scratchpad
pids=()
for pair in "0 1" "2 3" "4 5" "6 7" "8 9"; do
  k=$(echo "$pair" | tr ' ' '_')
  CUDA_VISIBLE_DEVICES=0 $PY scripts/train_iot23_gpu.py --seeds $pair --epochs 40 --L 4 \
      --arms relu qcfs --tag "part_$k" > "$LOGD/iot23_v4_part_$k.log" 2>&1 &
  pids+=($!)
done
echo "launched ${#pids[@]} workers: ${pids[*]}"
fail=0
for p in "${pids[@]}"; do wait "$p" || fail=1; done
echo "all workers done (fail=$fail)"
# merge parts (seed order 0..9) into the two final files
$PY - <<'PYMERGE'
import json, glob, re
from pathlib import Path
R = Path("results")
def merge(pattern, key, outname, modelname):
    parts = {}
    for f in glob.glob(str(R / pattern)):
        d = json.loads(Path(f).read_text())
        seeds = d["seeds"]
        ps = d[key]["per_seed"] if key else d["per_seed"]
        for s, m in zip(seeds, ps):
            parts[s] = (m, d)
    if not parts:
        print("no parts for", pattern); return
    seeds = sorted(parts)
    base = parts[seeds[0]][1]
    per = [parts[s][0] for s in seeds]
    out = {k: v for k, v in base.items() if k not in ("per_seed", "qcfs", "seeds")}
    out["seeds"] = seeds; out["model"] = modelname
    if key:
        out[key] = {"per_seed": per}
    else:
        out["per_seed"] = per
    (R / outname).write_text(json.dumps(out, indent=1))
    print("wrote", outname, "n=", len(per))
merge("iot23_multiseed_part_*.json", None, "iot23_multiseed_v4.json", "IDS_MLP")
merge("iot23_qcfs_multiseed_part_*.json", "qcfs", "iot23_qcfs_multiseed_v4.json", "IDS_MLP_QCFS L=4")
PYMERGE
echo "MERGE_DONE"
