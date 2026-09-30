# ReLU vs QCFS (T=1 SNN) equivalence — paired TOST, margin ±1 pp, α = 0.05

Primary test: parametric paired TOST (Schuirmann 1987; Lakens 2017) on
d = ReLU − QCFS in percentage points (positive = ReLU higher); it passes
iff the 90 % t-CI of the mean difference lies inside (−δ, +δ). The
Wilcoxon TOST (two one-sided signed-rank tests, TOSTER::wilcox_TOST
convention, bounds on the Hodges-Lehmann pseudo-median) is a robustness
check only. δ = 1 pp was pre-specified in the GLOBECOM 2026 submission.
Holm-Bonferroni runs over one family = all valid dataset×metric
equivalence claims (IUT + Holm strongly controls FWER).
δ_min = smallest margin these data would pass at (uncorrected).
n★ = seeds needed for 80 % / 90 % power at δ if the true difference is 0.

SW p = Shapiro-Wilk normality of the differences (< 0.05 ⇒ prefer the Wilcoxon column).

| Dataset | Metric | n | ReLU | QCFS | mean diff | 90 % CI | SW p | p_TOST (t) | p_TOST (W) | Holm eq.@δ | δ_min | n★ 80/90 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---:|---:|
| nslkdd | overall_acc | 20 | 78.57 | 78.14 | +0.43 | [-0.21, +1.07] | 0.186 | 0.069 | 0.038 | ❌ (0.415) | ±1.07 | 24/30 |
| nslkdd | macro_f1 | 20 | 58.91 | 58.28 | +0.63 | [-0.64, +1.90] | 0.043 | 0.311 | 0.101 | ❌ (1.000) | ±1.90 | 93/118 |
| unsw | overall_acc | 10 | 64.75 | 64.67 | +0.08 | [-0.16, +0.32] | 0.377 | 0.000 | 0.001 | ✅ (0.000) | ±0.32 | 2/2 |
| unsw | macro_f1 | 10 | 40.29 | 39.94 | +0.34 | [-0.03, +0.72] | 0.285 | 0.005 | 0.010 | ✅ (0.038) | ±0.72 | 4/5 |
| cicids2017 | overall_acc | 10 | 91.89 | 91.60 | +0.29 | [-0.55, +1.12] | 0.200 | 0.075 | 0.065 | ❌ (0.415) | ±1.12 | 18/23 |
| cicids2017 | macro_f1 | 10 | 56.35 | 57.57 | -1.22 | [-3.36, +0.93] | 0.807 | 0.571 | 0.539 | ❌ (1.000) | ±3.36 | 118/149 |
| iot23 | overall_acc | 10 | 76.65 | 78.42 | -1.77 | [-2.93, -0.60] | 0.640 | 0.871 | 0.839 | ❌ (1.000) | ±2.93 | 35/44 |
| iot23 | macro_f1 | 10 | 66.95 | 67.79 | -0.84 | [-1.52, -0.16] | 0.099 | 0.337 | 0.216 | ❌ (1.000) | ±1.52 | 12/15 |

## Margin sensitivity (parametric TOST, uncorrected)

| Pair | δ=0.5 | δ=1 | δ=2 | δ=3 |
|---|---|---|---|---|
| nslkdd:overall_acc | ❌ | ❌ | ✅ | ✅ |
| nslkdd:macro_f1 | ❌ | ❌ | ✅ | ✅ |
| unsw:overall_acc | ✅ | ✅ | ✅ | ✅ |
| unsw:macro_f1 | ❌ | ✅ | ✅ | ✅ |
| cicids2017:overall_acc | ❌ | ❌ | ✅ | ✅ |
| cicids2017:macro_f1 | ❌ | ❌ | ❌ | ❌ |
| iot23:overall_acc | ❌ | ❌ | ❌ | ✅ |
| iot23:macro_f1 | ❌ | ❌ | ✅ | ✅ |

Seed pairing uses the recorded seed lists (identical prefixes, 0, 1, 2, …).
The test split is fixed per dataset (official split or random_state=42), so
seed-to-seed variance reflects initialisation and shuffling only; the
inference is about this split, not about resampling the data.
n★ is a plug-in estimate using the observed SD of the differences.
