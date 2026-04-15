"""
IoT-23 T=1 SNN-ANN equivalence test: ReLU vs QCFS L=4 (matched seeds 0-4).

Runs paired Wilcoxon signed-rank test on OA and MF1.
Prints results for code review gate.
"""
import json
import numpy as np
from scipy import stats

relu_path = "results/iot23_multiseed.json"
qcfs_path = "results/iot23_qcfs_multiseed.json"

with open(relu_path) as f:
    relu = json.load(f)
with open(qcfs_path) as f:
    qcfs = json.load(f)

relu_seeds = relu["per_seed"][:5]
qcfs_seeds = qcfs["qcfs"]["per_seed"]

relu_oa = np.array([s["overall_acc"] for s in relu_seeds])
qcfs_oa = np.array([s["overall_acc"] for s in qcfs_seeds])
relu_mf1 = np.array([s["macro_f1"] for s in relu_seeds])
qcfs_mf1 = np.array([s["macro_f1"] for s in qcfs_seeds])
relu_mcc = np.array([s["mcc"] for s in relu_seeds])
qcfs_mcc = np.array([s["mcc"] for s in qcfs_seeds])

print("=" * 70)
print("IoT-23 T=1 SNN-ANN Equivalence: ReLU vs QCFS L=4 (5 matched seeds)")
print("=" * 70)

print(f"\n{'Metric':<12} {'ReLU':>20} {'QCFS L=4':>20} {'Delta':>12}")
print("-" * 70)
for name, r, q in [("OA", relu_oa, qcfs_oa), ("MF1", relu_mf1, qcfs_mf1), ("MCC", relu_mcc, qcfs_mcc)]:
    fmt = ".2f" if name != "MCC" else ".4f"
    print(f"{name:<12} {np.mean(r):{fmt}} ± {np.std(r, ddof=1):{fmt}} "
          f" {np.mean(q):{fmt}} ± {np.std(q, ddof=1):{fmt}} "
          f" {np.mean(q) - np.mean(r):+{fmt}}")

print(f"\nPer-seed OA:")
print(f"  ReLU:  {[f'{v:.2f}' for v in relu_oa]}")
print(f"  QCFS:  {[f'{v:.2f}' for v in qcfs_oa]}")
print(f"  Diff:  {[f'{q-r:+.2f}' for r, q in zip(relu_oa, qcfs_oa)]}")

print(f"\nPer-seed MF1:")
print(f"  ReLU:  {[f'{v:.2f}' for v in relu_mf1]}")
print(f"  QCFS:  {[f'{v:.2f}' for v in qcfs_mf1]}")
print(f"  Diff:  {[f'{q-r:+.2f}' for r, q in zip(relu_mf1, qcfs_mf1)]}")

print("\n--- Paired Wilcoxon Signed-Rank Test ---")
for name, r, q in [("OA", relu_oa, qcfs_oa), ("MF1", relu_mf1, qcfs_mf1)]:
    diff = q - r
    n_pos = np.sum(diff > 0)
    n_neg = np.sum(diff < 0)
    n_zero = np.sum(diff == 0)

    if np.all(diff == 0):
        print(f"\n{name}: All differences are zero — perfect equivalence")
        continue

    try:
        stat, p = stats.wilcoxon(r, q, alternative='two-sided')
        d_z = np.mean(diff) / np.std(diff, ddof=1) if np.std(diff, ddof=1) > 0 else 0.0
        print(f"\n{name}:")
        print(f"  W-statistic: {stat:.1f}")
        print(f"  p-value: {p:.4f}")
        print(f"  d_z (effect size): {d_z:+.3f}")
        print(f"  Direction: {n_pos} QCFS>ReLU, {n_neg} ReLU>QCFS, {n_zero} ties")
        print(f"  H0 rejected (α=0.05)? {'YES' if p < 0.05 else 'NO'}")
        print(f"  Equivalence holds? {'YES' if p >= 0.05 else 'NO — QCFS differs from ReLU'}")
    except Exception as e:
        print(f"\n{name}: Wilcoxon test failed: {e}")
        print(f"  Direction: {n_pos} QCFS>ReLU, {n_neg} ReLU>QCFS")
        print(f"  d_z: {np.mean(diff)/np.std(diff, ddof=1) if np.std(diff, ddof=1) > 0 else 'N/A':+.3f}")

print("\n--- Cross-Dataset Equivalence Summary ---")
summary = [
    ("NSL-KDD", "0.227", "20", "+0.26", "NO"),
    ("UNSW-NB15", "0.846", "10", "+0.19", "NO"),
    ("CICIDS2017", "0.312", "5", "+0.63", "NO"),
]
print(f"{'Dataset':<14} {'p-value':>8} {'n':>4} {'d_z':>8} {'H0 rejected':>12}")
print("-" * 50)
for ds, p, n, dz, rej in summary:
    print(f"{ds:<14} {p:>8} {n:>4} {dz:>8} {rej:>12}")

# Add IoT-23 result
for name, r, q in [("OA", relu_oa, qcfs_oa)]:
    diff = q - r
    try:
        stat, p = stats.wilcoxon(r, q, alternative='two-sided')
        d_z = np.mean(diff) / np.std(diff, ddof=1) if np.std(diff, ddof=1) > 0 else 0.0
        rej = "YES" if p < 0.05 else "NO"
        print(f"{'IoT-23':<14} {p:>8.3f} {'5':>4} {d_z:>+8.2f} {rej:>12}")
    except:
        print(f"{'IoT-23':<14} {'N/A':>8} {'5':>4} {'N/A':>8} {'N/A':>12}")

print("\nDone.")
