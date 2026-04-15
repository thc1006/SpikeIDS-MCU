# Details of Changes — v2 → v3

**Preprint base DOI**: 10.20944/preprints202603.0817
**v2 posted**: 2026-03 (initial revision with 2 datasets, 10-seed)
**v3 posted**: 2026-04-15

Version 3 substantially revises v2 in response to a self-discovered statistical
error and to broaden the empirical evidence. The principal changes are listed
below.

---

## 1. Statistical correction (NSL-KDD)

v2 reported a 10-seed paired Wilcoxon p-value of **0.037** for ReLU vs. QCFS on
NSL-KDD overall accuracy. Re-running the experiment with 20 seeds yields
**p = 0.227**. The v3 conclusion is therefore the opposite of v2's: the two
activations are statistically indistinguishable, which actually **supports** the
T = 1 SNN-ANN approximation thesis rather than contradicts it.

All paired tests in v3 now apply **Holm-Bonferroni** family-wise error
correction across the primary comparisons per dataset. Effect sizes
(Cohen's d_z) and 95% percentile-bootstrap confidence intervals (10,000
resamples) are reported alongside p-values.

## 2. Dataset coverage extended from 2 to 4

v2 covered NSL-KDD and UNSW-NB15 only. v3 adds:

- **CICIDS2017** (15-class, modern enterprise traffic; HuggingFace cleaned
  version that mitigates the TCP-splitting and label-alignment issues
  documented by Engelen et al., 2021)
- **IoT-23** (5-class, contemporary IoT botnet traffic from 2018-2019
  captures)

The non-rejection pattern for ReLU vs. QCFS holds on **all four datasets** at
alpha = 0.05:

| Dataset    | n  | Wilcoxon p | Holm-adj p | d_z   | Reject? |
|------------|----|-----------:|-----------:|------:|---------|
| NSL-KDD    | 20 | 0.227      | 0.227      | +0.26 | No      |
| UNSW-NB15  | 10 | 0.846      | 0.846      | +0.19 | No      |
| CICIDS2017 |  5 | 0.312      | 0.312      | +0.63 | No      |
| IoT-23     |  5 | 0.438      | 0.438      | -0.33 | No      |

A paired TOST with a pre-specified +/-1.0 pp bound is also reported; UNSW-NB15
passes equivalence under TOST while the other three datasets remain
inconclusive at current seed counts.

## 3. Energy claim downgraded from measured to estimated

v2's "energy-efficient" framing has been removed from the title and weakened in
the abstract. Energy is now reported as an **AN5946-derived estimate**
(44-69 microjoules/inference at ~150 mW nominal) rather than a direct on-board
measurement. The 114-179x energy comparison versus STM32F7 (Chehade et al.,
7.86 mJ) is now explicitly framed as an **envelope**, not a measurement. Direct
on-board STLINK-V3PWR measurement is listed as future work in Section IV-B.

## 4. Novelty claim narrowed and bounded by a documented search

v2 used broad "first" language in title and abstract. v3 retains a
tightly-scoped novelty claim only in the contributions list:

> "the first publicly documented IDS classifier deployment on a Cortex-M class
> MCU paired with a general-purpose NPU (Neural-ART)"

This claim is supported by a systematic literature search (**Supplementary
File S1**: 5 databases, 8 query variants, approximately 320 records inspected,
search window April 2026). Closely related but architecturally distinct work
is now cited and explicitly contrasted in Related Work and Table I:

- **Ngo et al. (HH-NIDS, MAX78000, Future Internet 2022)** — AI-specialized MCU
  with fixed CNN engine, not a general-purpose NPU
- **Zahm et al. (Akida AKD1000, CSIAC 2024)** — neuromorphic ASIC, not a
  commodity MCU
- **Chehade et al. (STM32F7, ISCC 2025)** — commodity MCU but no NPU
- **Diab et al. (Raspberry Pi 3B+, arXiv:2512.02272)** — single-board computer
  class
- **Farooq et al. (Xilinx FPGA, IPDPSW 2025)** — FPGA, ~10 W class

## 5. QCFS Floor CPU-fallback framed as a deployment finding

v2 mentioned QCFS as a side experiment. v3 elevates it to a documented
**negative result** with operational consequences: the Floor operator is absent
from the Neural-ART operator set, forcing CPU fallback at every QCFS
activation, with a measured **+17.6% latency overhead** (0.46 ms ReLU INT8 vs.
0.54 ms QCFS INT8 on NSL-KDD).

A QCFS L-sweep ablation (L in {2, 4, 8, 16}, 5 seeds on NSL-KDD and UNSW-NB15)
is added to justify L = 4 as Pareto-optimal: no accuracy gain from larger L,
half the CPU-fallback operator budget of L = 8 (Section IV-D, Table VI).

## 6. Manuscript reformatted to IEEEtran conference style (6 pages)

The v2 preprint used a generic two-column article class. v3 uses
**IEEEtran conference** because the same manuscript has been submitted to
**IEEE GLOBECOM 2026 (Communication and Information System Security Symposium)**
on 2026-04-15. IEEE author posting policy permits the preprint to remain online
during peer review (IEEE Publication Policy on author-posted versions). The
preprint will be updated with the journal-extension version after the GLOBECOM
review concludes (expected ~2026-07).

## 7. Keywords reduced from 10 to 6

To align with common journal guidelines (4-6 keywords), the keyword list is
reduced to:

> intrusion detection; spiking neural network; neural processing unit;
> INT8 quantization; edge AI; STM32N6

## 8. Additional minor corrections

- Bibliography entries now include full author lists (no "and others"
  abbreviations).
- All numerical claims in the abstract and conclusion are cross-verified
  against the per-seed result JSON files (multiseed_20.json,
  unsw_multiseed_20.json, cicids2017_multiseed_experiment.json,
  iot23_multiseed.json, qcfs_lsweep.json) to two-decimal precision.
- A non-MLP **TinyCNN baseline** (Conv2D 1x3 kernels, the only non-MLP
  topology compatible with Neural-ART's operator set) is added as a same-
  hardware comparison (Table III, Table VII).
- Added a model-capacity Pareto sweep (logistic regression, MLP 64-64,
  MLP 128-64, our 256-256-128) showing that within NPU-friendly MLP family,
  widening alone does not close the gap to tree ensembles (Section IV-G).
- "When INT8 equivalence breaks down" subsection added (Section IV-H)
  documenting that UNSW-NB15 shows greater quantization fragility than
  NSL-KDD (FP32/INT8 prediction agreement 75.2% vs. 99.0%), framed as a
  practical limit of the T = 1 approximation rather than a defect.

---

## New supplementary material in v3

- **Supplementary File S1**: `Supplementary_S1_novelty_search_protocol.md` —
  documents the systematic literature search methodology backing the narrowed
  novelty claim. Cited 3 times in the main text (contributions list, Related
  Work, Limitations).

## Files unchanged in spirit but rebuilt

- All figures regenerated from the latest JSON results.
- LaTeX source rebuilt with `latexmk -pdf` against the locked
  `result_macros.tex` (auto-generated by `scripts/emit_paper_macros.py`).

---

## Concurrent submission disclosure

The same manuscript has been submitted to **IEEE GLOBECOM 2026 (Communication
and Information System Security Symposium)** on 2026-04-15. This preprint is
posted in accordance with IEEE author posting policy, which permits authors to
post pre-acceptance versions on personal or institutional repositories
(including preprint servers) during peer review.
