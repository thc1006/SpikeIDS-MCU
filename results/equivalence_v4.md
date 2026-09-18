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
| nslkdd | overall_acc | 20 | 78.57 | 78.14 | +0.43 | [-0.21, +1.07] | 0.186 | 0.069 | 0.038 | ❌ (0.277) | ±1.07 | 24/30 |
| nslkdd | macro_f1 | 20 | 58.91 | 58.28 | +0.63 | [-0.64, +1.90] | 0.043 | 0.311 | 0.101 | ❌ (0.933) | ±1.90 | 93/118 |
| unsw | overall_acc | 10 | 64.75 | 64.67 | +0.08 | [-0.16, +0.32] | 0.377 | 0.000 | 0.001 | ✅ (0.000) | ±0.32 | 2/2 |
| unsw | macro_f1 | 10 | 40.29 | 39.94 | +0.34 | [-0.03, +0.72] | 0.285 | 0.005 | 0.010 | ✅ (0.027) | ±0.72 | 4/5 |
| iot23 | overall_acc | 10 | 76.65 | 78.42 | -1.77 | [-2.93, -0.60] | 0.640 | 0.871 | 0.839 | ❌ (0.933) | ±2.93 | 35/44 |
| iot23 | macro_f1 | 10 | 66.95 | 67.79 | -0.84 | [-1.52, -0.16] | 0.099 | 0.337 | 0.216 | ❌ (0.933) | ±1.52 | 12/15 |
| cicids2017 ⚠️ | overall_acc | 5 | 91.90 | 90.99 | +0.91 | [-0.47, +2.29] | 0.459 | 0.448 | 0.500 | ⚠️ excluded | ±2.29 | 18/23 |
| cicids2017 ⚠️ | macro_f1 | 5 | 56.78 | 57.65 | -0.87 | [-3.30, +1.56] | 0.984 | 0.458 | 0.500 | ⚠️ excluded | ±3.30 | 56/71 |

⚠️ **cicids2017: pair is confounded — epochs 80 vs 40, batch_size 512 vs 1024 — shown for reference, excluded from the Holm family; no equivalence or difference claim is valid until both arms are re-run under the same training budget.**

## Margin sensitivity (parametric TOST, uncorrected)

| Pair | δ=0.5 | δ=1 | δ=2 | δ=3 |
|---|---|---|---|---|
| nslkdd:overall_acc | ❌ | ❌ | ✅ | ✅ |
| nslkdd:macro_f1 | ❌ | ❌ | ✅ | ✅ |
| unsw:overall_acc | ✅ | ✅ | ✅ | ✅ |
| unsw:macro_f1 | ❌ | ✅ | ✅ | ✅ |
| iot23:overall_acc | ❌ | ❌ | ❌ | ✅ |
| iot23:macro_f1 | ❌ | ❌ | ✅ | ✅ |
| cicids2017:overall_acc | ❌ | ❌ | ❌ | ✅ |
| cicids2017:macro_f1 | ❌ | ❌ | ❌ | ❌ |

Seed pairing uses the recorded seed lists (identical prefixes, 0, 1, 2, …).
The test split is fixed per dataset (official split or random_state=42), so
seed-to-seed variance reflects initialisation and shuffling only; the
inference is about this split, not about resampling the data.
n★ is a plug-in estimate using the observed SD of the differences.
