#!/usr/bin/env bash
# Sequential CICIDS gap-fill pipeline.
# Waits for UNSW QCFS to finish, then runs:
#   (1) CICIDS QCFS L=4, 5 seeds, 40 epochs
#   (2) CICIDS TinyCNN, 5 seeds, 40 epochs (once loader bug fixed)
set -eo pipefail
cd "$(dirname "$0")/.."
source snn-ids-env/bin/activate

UNSW_MARKER=results/unsw_qcfs_multiseed.json
echo "[pipeline] waiting for $UNSW_MARKER..."
while [ ! -f "$UNSW_MARKER" ]; do
  sleep 30
done
echo "[pipeline] UNSW done, starting CICIDS QCFS..."

python3 src/experiment_cicids_qcfs.py \
  --seeds 0 1 2 3 4 \
  --epochs 40 \
  --output cicids_qcfs_multiseed.json 2>&1 | tee logs/cicids_qcfs.log

echo "[pipeline] CICIDS QCFS done, starting CICIDS TinyCNN..."

python3 src/experiment_cnn_baseline.py \
  --datasets cicids2017 \
  --seeds 0 1 2 3 4 \
  --epochs 40 \
  --output cnn_baseline_cicids.json 2>&1 | tee logs/cicids_cnn.log

echo "[pipeline] ALL DONE"
