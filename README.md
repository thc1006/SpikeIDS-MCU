# SNN-IDS: Sub-Millijoule Intrusion Detection on the STM32N6 Neural-ART NPU

[![Preprint v3](https://img.shields.io/badge/Preprint-10.20944%2Fpreprints202603.0817.v3-orange.svg)](https://doi.org/10.20944/preprints202603.0817.v3)
[![Software DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.18906060.svg)](https://doi.org/10.5281/zenodo.18906060)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Target](https://img.shields.io/badge/Target-STM32N6570--DK-03234B.svg)](https://www.st.com/en/evaluation-tools/stm32n6570-dk.html)
[![NPU](https://img.shields.io/badge/NPU-Neural--ART_600_GOPS-green.svg)](#)
[![Inference](https://img.shields.io/badge/Inference-0.29--0.46ms_@_800MHz-brightgreen.svg)](#key-results)

To our knowledge, the first publicly documented IDS classifier deployment on a Cortex-M class MCU paired with a general-purpose NPU (Neural-ART), evaluated across four datasets and bounded by the systematic literature search documented in [Supplementary File S1](paper/preprint_v3/Supplementary_S1_novelty_search_protocol.md).

## Key Results

Multi-seed runs with paired Wilcoxon signed-rank tests and Holm-Bonferroni family-wise error correction. INT8 deployment numbers from STMicroelectronics ST Edge AI Developer Cloud on STM32N6570-DK.

| Metric                    | NSL-KDD (5-class) | UNSW-NB15 (10-class) | CICIDS2017 (15-class) | IoT-23 (5-class) |
|---------------------------|------------------:|---------------------:|----------------------:|-----------------:|
| Overall Accuracy          | 78.57 ± 1.28%     | 64.67 ± 0.55%        | 91.89 ± 1.21%         | 75.59 ± 2.71%    |
| Macro F1                  | 58.91 ± 2.80%     | 40.18 ± 1.02%        | 56.35 ± 2.80%         | 66.41 ± 1.50%    |
| Seeds                     | 20                | 20                   | 10                    | 10               |
| QCFS vs ReLU Wilcoxon p   | 0.227             | 0.846                | 0.312                 | 0.438            |
| INT8 Latency (ms)         | 0.46              | **0.29**             | 0.42                  | 0.38             |
| CPU FP32 Latency (ms)     | 1.24              | 1.23                 | 1.16                  | 1.04             |
| Speed-up over CPU         | 2.7×              | **4.2×**             | 2.8×                  | 2.7×             |
| Energy / inference (est.) | 69 µJ             | 44 µJ                | 63 µJ                 | 57 µJ            |
| Flash / RAM               | 137.7 / 1.25 KB   | 120.6 / 0.50 KB      | 120.6 / 0.50 KB       | 105.0 / 0.50 KB  |

The non-significant Wilcoxon tests above do **not** by themselves establish equivalence (absence of evidence is not evidence of absence). The v4 re-analysis with paired TOST (two one-sided tests, ±1 pp margin, [`results/equivalence_v4.md`](results/equivalence_v4.md)) shows a more nuanced picture: **UNSW-NB15** is equivalent within ±0.32 pp (accuracy) / ±0.72 pp (macro-F1); **NSL-KDD** supports equivalence only within ±1.1 / ±1.9 pp; **IoT-23** (now n = 10 matched) is **not** equivalent — QCFS is modestly but consistently **better** than ReLU (accuracy +1.8 pp, 90 % CI [−2.9, −0.6] excludes 0; QCFS wins 8/10 seeds), a difference v3's own data also shows (ReLU 75.6 vs QCFS 77.7) but could not detect at its underpowered n = 5; **CICIDS2017** is confounded (QCFS arm 40 ep/batch 1024 vs ReLU 80/512) and excluded until re-run. The honest conclusion is therefore **T = 1 SNN-equivalent QCFS is statistically indistinguishable from, or modestly better than, INT8 ReLU — never worse** at the T = 1 approximation. v3's blanket "indistinguishable on all four datasets" was in part an underpowered Type II error on IoT-23.

Energy is estimated from STMicroelectronics application note AN5946 (~150 mW nominal) rather than direct on-board measurement; STLINK-V3PWR measurement is listed as future work.

**Target Board:** STM32N6570-DK (ARM Cortex-M55 @ 800 MHz + Neural-ART NPU 600 GOPS INT8).

## v4 (in progress, branch `v4`)

Work following the GLOBECOM 2026 reviews. Done so far:

1. **Equivalence testing done properly** — paired TOST (parametric primary, Wilcoxon signed-rank secondary with Hodges-Lehmann location) replaces "p > 0.05 ⇒ indistinguishable"; reports δ_min (the tightest margin the data support), Shapiro-Wilk on the differences, Holm-Bonferroni over the family of valid equivalence claims, and the seed count needed for 80 %/90 % power. `uv run scripts/run_v4_equivalence.py` → `results/equivalence_v4.{json,md}`; tests in `tests/test_tost.py`, `tests/test_v4_equivalence.py`.
2. **Training-budget guard** — `run_v4_equivalence.py` refuses to pool a ReLU/QCFS pair trained under different epochs or batch sizes, which caught the CICIDS2017 mismatch inherited from v3.

Planned: re-run CICIDS2017 QCFS at 80 epochs / batch 512 and extend the QCFS arms (IoT-23, CICIDS2017 → 10+ seeds, UNSW → 20) so every dataset reaches the power the table in `results/equivalence_v4.md` asks for; on-board energy measurement; end-to-end pipeline latency; stronger baselines.

## What's New in v3

Compared with [preprint v2](https://doi.org/10.20944/preprints202603.0817.v2):

1. **Statistical correction** — v2's 10-seed Wilcoxon p = 0.037 on NSL-KDD flips to p = 0.227 with 20 seeds. The v3 conclusion is the opposite of v2 and **supports** the T = 1 equivalence rather than contradicting it. All paired tests now apply Holm-Bonferroni correction; effect sizes (Cohen's d_z) and 95% percentile-bootstrap confidence intervals (10,000 resamples) are reported alongside p-values.
2. **Two more datasets** — CICIDS2017 (HuggingFace cleaned version, 15-class) and IoT-23 (5-class) added to the existing NSL-KDD and UNSW-NB15.
3. **Energy claim downgraded** — "energy-efficient" wording removed from the title; energy reported as an AN5946-derived estimate rather than direct on-board measurement.
4. **Novelty claim narrowed and bounded** — broad "first" wording replaced by a tightly-scoped claim, supported by a systematic literature search of 5 databases and 8 query variants (~320 records inspected) in [Supplementary File S1](paper/preprint_v3/Supplementary_S1_novelty_search_protocol.md).
5. **QCFS Floor → CPU fallback as deployment finding** — QCFS adds 17.6 % latency overhead because the `Floor` operator falls back to CPU on Neural-ART; documented with an L-sweep ablation that justifies L = 4 as Pareto-optimal on operator cost.
6. **Format change** — IEEEtran 6-page conference build added under `paper/globecom/`; the same content was submitted to IEEE GLOBECOM 2026 (Communication and Information System Security Symposium) on 2026-04-15. The full v2 → v3 changelog lives in [`paper/preprint_v3/Details_of_Changes_v2_to_v3.md`](paper/preprint_v3/Details_of_Changes_v2_to_v3.md).

## Theoretical Basis

A single-timestep (T = 1) SNN with zero initial membrane potential produces a forward pass approximately equivalent to an INT8 quantized ANN with ReLU activation:

```
T = 1 SNN inference  ≈  INT8 quantized ANN inference
```

Key references:

- Bu et al., "Optimal ANN-SNN Conversion" (QCFS), **ICLR 2022**
- Jiang et al., "Unified Optimization Framework", **ICML 2023**
- Bu et al., "Inference-Scale Complexity in ANN-SNN Conversion", **CVPR 2025**

## Architecture

```
IDS_MLP: Linear(d → 256) → BN → σ → Linear(256 → 256) → BN → σ → Linear(256 → 128) → BN → σ → Linear(128 → C)
```

- `d ∈ {41, 34, 78, 23}` for NSL-KDD / UNSW-NB15 / CICIDS2017 / IoT-23
- `C ∈ {5, 10, 15, 5}` (number of classes)
- `σ` = ReLU (Path B) or QCFS L = 4 (Path A)
- BatchNorm fused into Linear at export → ONNX graph: `Gemm` + `Relu` only
- Inverse-frequency class weighting for extreme imbalance

## NPU Hardware Benchmark

All models benchmarked on STM32N6570-DK via ST Edge AI Developer Cloud:

| Model               | Dataset     | Inference  | HW | Hyb | SW | Flash    | RAM     |
|---------------------|-------------|-----------:|---:|----:|---:|---------:|--------:|
| ReLU FP32 (CPU)     | NSL-KDD     | 1.24 ms    | 0  | 0   | 11 | 466.4 KB | 2.17 KB |
| **ReLU INT8 (NPU)** | **NSL-KDD** | **0.46 ms (2.7×)** | 5  | 1   | 2  | 137.7 KB | 1.25 KB |
| ReLU FP32 (CPU)     | UNSW-NB15   | 1.23 ms    | 0  | 0   | 11 | 461.9 KB | 2.14 KB |
| **ReLU INT8 (NPU)** | **UNSW-NB15** | **0.29 ms (4.2×)** | 4  | 0   | 0  | 120.6 KB | 0.50 KB |
| **ReLU INT8 (NPU)** | **CICIDS2017** | **0.42 ms (2.8×)** | 4  | 0   | 0  | 120.6 KB | 0.50 KB |
| **ReLU INT8 (NPU)** | **IoT-23**  | **0.38 ms (2.7×)** | 4  | 0   | 0  | 105.0 KB | 0.50 KB |
| QCFS INT8           | NSL-KDD     | 0.54 ms    | 13 | 1   | 14 | 138.0 KB | 2.00 KB |

Key findings:

- **NPU gives 2.7-4.2× speed-up** over Cortex-M55 CPU on the same model.
- **Estimated energy 44-69 µJ per inference** (AN5946-based), implying a 114-179× envelope relative to STM32F7 (Chehade et al., 7.86 mJ).
- **`Floor` operator is not in the Neural-ART operator set** — QCFS falls back to CPU at every activation, costing 17.6 % latency.
- **ReLU INT8 is the optimal NPU path** — `Gemm` + `Relu` only, no CPU fallback.
- **Tree-based models (RF, XGBoost) cannot run on STM32N6** — `TreeEnsembleClassifier` rejected by ST Edge AI Core.

## Reproduce

```bash
# Setup
python3 -m venv snn-ids-env
source snn-ids-env/bin/activate
pip install -r requirements.txt

# Datasets — place raw files in data/
#   NSL-KDD     : KDDTrain+.txt, KDDTest+.txt
#   UNSW-NB15   : parquet files
#   CICIDS2017  : HuggingFace rdpahalavan/CICIDS2017 cleaned version
#   IoT-23      : Stratosphere IPS captures

# Multi-seed experiments (4 datasets)
make multiseed         # NSL-KDD (20 seeds)
make unsw              # UNSW-NB15 (20 seeds)
make cicids            # CICIDS2017 (10 seeds)
make iot23             # IoT-23 (10 seeds)

# Ablations and baselines
make qcfs-lsweep       # QCFS L in {2, 4, 8, 16}
make tree-baseline     # RF + XGBoost (CPU-only sanity)
make cnn-baseline      # TinyCNN (Conv2D 1x3, NPU-compatible)
make layerwise         # FP32 vs INT8 layer-wise analysis
make quant-ablation    # 24-config quantization ablation

# Statistics + paper
make stats             # Paired Wilcoxon + Holm-Bonferroni
make paper             # Compile preprint v3 (paper/preprint_v3)
make globecom          # Compile IEEEtran 6-page (paper/globecom)

# Tests
pytest tests/

# NPU benchmark (browser; requires STMicroelectronics account)
# Upload models/*.onnx to https://stedgeai-dc.st.com
# Select target: STM32N6570-DK -> Benchmark
```

## Project Structure

```
.
├── src/
│   ├── config.py              # Centralized hyperparameters and dataset configs
│   ├── data_loaders.py        # Dataset loaders (NSL-KDD / UNSW / CICIDS / IoT-23)
│   ├── models.py              # IDS_MLP, TinyCNN, QCFS activation
│   ├── metrics.py             # Per-class P/R/F1, macro F1, false-alarm rate
│   ├── quantize_utils.py      # INT8 PTQ helpers (MinMax / Entropy / Percentile)
│   ├── train_utils.py         # Training loops with class weighting / focal loss
│   ├── stats_tests.py         # Wilcoxon, Holm-Bonferroni, TOST, bootstrap CI
│   ├── train.py               # ReLU model training (Path B)
│   ├── train_qcfs.py          # QCFS model training (Path A)
│   ├── experiment_multiseed.py / experiment_unsw.py
│   │                          # NSL-KDD / UNSW multi-seed (20 seeds)
│   ├── experiment_cicids2017.py / experiment_cicids_qcfs.py
│   ├── experiment_iot23.py    / experiment_iot23_qcfs.py
│   ├── experiment_qcfs_lsweep.py / experiment_unsw_qcfs.py
│   ├── experiment_baselines.py / experiment_focal.py / experiment_cnn_baseline.py
│   ├── export_onnx.py / export_qcfs_onnx.py
│   │                          # ONNX export with BN fusion
│   ├── export_unsw_onnx.py / export_cicids_onnx.py / export_iot23_onnx.py / export_baselines_onnx.py
│   ├── quantize.py / quantize_qcfs.py / quantize_ablation.py
│   ├── layerwise_analysis.py  # FP32 vs INT8 layer-wise MSE / cosine
│   └── tree_baseline.py       # RF + XGBoost
├── scripts/
│   ├── emit_paper_macros.py   # Lock paper numbers to source JSONs
│   ├── run_globecom_stats.py  # Cross-dataset stats report
│   ├── iot23_equivalence_test.py
│   ├── finalize_globecom.py
│   ├── run_cicids_pipeline.sh
│   └── run_gate7_review.sh
├── tests/                     # pytest unit tests for metrics, focal, QCFS, stats
├── results/                   # Per-seed JSONs backing every paper number
│   ├── multiseed_20.json                    # NSL-KDD 20-seed
│   ├── unsw_multiseed_20.json               # UNSW-NB15 20-seed
│   ├── cicids2017_multiseed_experiment.json # CICIDS2017 10-seed
│   ├── iot23_multiseed.json                 # IoT-23 10-seed
│   ├── qcfs_lsweep.json                     # L in {2, 4, 8, 16}
│   ├── st_cloud_benchmarks.json             # ST Edge AI Cloud measurements
│   ├── stats_report_globecom.json           # Cross-dataset Wilcoxon report
│   └── ...
├── paper/
│   ├── preprint_v3/           # preprints.org v3 (PDF + source + supplementary)
│   ├── globecom/              # IEEEtran 6-page (GLOBECOM 2026 submission)
│   ├── aicas/                 # AICAS 2026 build
│   ├── main.tex               # Original v1 preprint source
│   └── main.pdf
├── docs/
│   ├── ADR-001-SNN-NPU-GoNoGo-Verification.md
│   ├── SNN_RTOS_Telecom_Analysis.md
│   └── novelty_search_protocol.md   # Source of Supplementary File S1
├── configs/default.yaml
├── CITATION.cff
├── requirements.txt
├── Makefile
└── LICENSE
```

## Citation

Cite both the preprint and the software entry. The preprint is the primary scholarly artifact; the software DOI provides version-locked code reproducibility.

**Preprint (v3):**

```bibtex
@article{tsai2026snnids_v3,
  title   = {Sub-Millijoule Intrusion Detection on a Commodity MCU Neural Processing Unit: A Four-Dataset Deployment Study},
  author  = {Tsai, Hsiu-Chi},
  journal = {Preprints.org},
  year    = {2026},
  month   = {April},
  doi     = {10.20944/preprints202603.0817.v3},
  url     = {https://doi.org/10.20944/preprints202603.0817.v3}
}
```

**Software:**

```bibtex
@software{tsai2026snnids_software,
  title   = {SNN-IDS: SNN-Equivalent Intrusion Detection on the STM32N6 Neural-ART NPU},
  author  = {Tsai, Hsiu-Chi},
  year    = {2026},
  url     = {https://github.com/thc1006/SpikeIDS-MCU},
  doi     = {10.5281/zenodo.18906060},
  version = {3.0.0}
}
```

## References

- **QCFS Activation**: Bu et al., "Optimal ANN-SNN Conversion for High-accuracy and Ultra-low-latency Spiking Neural Networks," *ICLR 2022*.
- **Unified ANN-SNN Framework**: Jiang et al., "A Unified Optimization Framework of ANN-SNN Conversion," *ICML 2023*.
- **Inference-Scale Complexity**: Bu et al., "Inference-Scale Complexity in ANN-SNN Conversion," *CVPR 2025*.
- **NSL-KDD**: Tavallaee et al., *IEEE CISDA*, 2009.
- **UNSW-NB15**: Moustafa & Slay, *MilCIS*, 2015.
- **CICIDS2017**: Sharafaldin et al., *ICISSP*, 2018; cleaned version per Engelen et al., 2021.
- **IoT-23**: Garcia, Parmisano & Erquiaga, Stratosphere Lab, 2020.
- **HH-NIDS (MAX78000)**: Ngo et al., *Future Internet* 15(1):9, 2022.
- **Akida IDS**: Zahm et al., *CSIAC*, 2024.
- **STM32F7 IDS**: Chehade et al., *ISCC*, 2025.
- **Neural-ART NPU**: STMicroelectronics, STM32N6 Application Note UM3225.
- **Energy estimation**: STMicroelectronics, Application Note AN5946.

## License

Apache License 2.0. See [LICENSE](LICENSE).
