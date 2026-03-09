# SNN-IDS: Hardware-Verified SNN-Equivalent Intrusion Detection on a Commodity MCU NPU

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.18906060.svg)](https://doi.org/10.5281/zenodo.18906060)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Target](https://img.shields.io/badge/Target-STM32N6570--DK-03234B.svg)](https://www.st.com/en/evaluation-tools/stm32n6570-dk.html)
[![NPU](https://img.shields.io/badge/NPU-Neural--ART_600_GOPS-green.svg)](#)
[![Inference](https://img.shields.io/badge/Inference-0.29--0.46ms_@_800MHz-brightgreen.svg)](#key-results)

**To our knowledge, the first publicly documented deployment of an INT8 quantized ANN (approximately equivalent to T=1 SNN) for real-time network intrusion detection on a general-purpose MCU NPU.**

## Key Results

| Metric | NSL-KDD (5-class) | UNSW-NB15 (10-class) |
|--------|-------------------|----------------------|
| **Overall Accuracy** | 78.86 ± 1.32% | 64.75 ± 0.61% |
| **Macro F1** | 59.20 ± 2.80% | 40.29 ± 0.90% |
| **Inference Latency** | 0.46 ms | **0.29 ms** |
| **NPU Execution** | 5 HW + 1 Hyb + 2 SW | 4 HW (100% NPU) |
| **Flash / RAM** | 137.7 KB / 1.25 KB | 120.6 KB / 0.50 KB |
| **Evaluation** | 10 seeds, mean ± std | 10 seeds, mean ± std |

**Target Board:** STM32N6570-DK (ARM Cortex-M55 @ 800 MHz + Neural-ART NPU 600 GOPS INT8)

## What's New

To our knowledge, this is:

1. **First publicly documented IDS deployment on an ARM Cortex-M NPU (Neural-ART)** — prior MCU-class IDS work used the MAX78000 (Ngo et al., 2022), an AI-specialized MCU with a fixed CNN accelerator
2. **First publicly documented empirical validation of T=1 SNN–ANN equivalence on commercial NPU silicon** — 99% final prediction agreement between FP32 and INT8 models
3. **First QCFS activation compiled for Neural-ART target** — Floor operator confirmed CPU fallback, adding 17.4% latency

## Theoretical Basis

A single-timestep (T=1) SNN with zero initial membrane potential produces a forward pass approximately equivalent to an INT8 quantized ANN with ReLU activation:

```
T=1 SNN inference ≈ INT8 Quantized ANN inference
```

Key references:
- Bu et al., "Optimal ANN-SNN Conversion" (QCFS), **ICLR 2022**
- Jiang et al., "Unified Optimization Framework", **ICML 2023**
- Bu et al., "Inference-Scale Complexity", **CVPR 2025**

## Architecture

```
IDS_MLP: Linear(d→256) → BN → σ → Linear(256→256) → BN → σ → Linear(256→128) → BN → σ → Linear(128→C)
```

- `d` = 41 (NSL-KDD) or 34 (UNSW-NB15), `C` = 5 or 10
- `σ` = ReLU (Path B) or QCFS L=4 (Path A)
- BatchNorm fused into Linear at export → ONNX graph: `Gemm` + `Relu` only
- 111,365 (NSL-KDD) or 110,218 (UNSW-NB15) parameters
- Inverse-frequency class weighting for extreme imbalance

## NPU Hardware Benchmark

All models benchmarked on STM32N6570-DK via ST Edge AI Developer Cloud v4.0.0:

| Model | Dataset | Inference | HW | Hyb | SW | Flash | RAM |
|-------|---------|-----------|---:|----:|---:|-------|-----|
| ReLU FP32 (CPU) | NSL-KDD | 1.24 ms | 0 | 0 | 11 | 466.4 KB | 2.17 KB |
| **ReLU INT8 (NPU)** | **NSL-KDD** | **0.46 ms (2.7×)** | 5 | 1 | 2 | 137.7 KB | 1.25 KB |
| ReLU FP32 (CPU) | UNSW-NB15 | 1.23 ms | 0 | 0 | 11 | 461.9 KB | 2.14 KB |
| **ReLU INT8 (NPU)** | **UNSW-NB15** | **0.29 ms (4.2×)** | 4 | 0 | 0 | 120.6 KB | 0.50 KB |
| QCFS INT8 | NSL-KDD | 0.54 ms | 13 | 1 | 14 | 138.0 KB | 2.00 KB |

Key findings:
- **NPU gives 2.7–4.2× speedup** over CPU-only execution on the same model
- **Floor operator is NOT supported by Neural-ART NPU** — falls back to CPU as `Floor(float)`
- **ReLU INT8 is the optimal NPU path** — all Gemm+Relu on NPU, no CPU fallback for activations
- **Tree-based models (RF, XGBoost) cannot run on STM32N6** — `TreeEnsembleClassifier` rejected by ST Edge AI Core ("NOT IMPLEMENTED")

## Reproduce

```bash
# Setup
python3 -m venv snn-ids-env
source snn-ids-env/bin/activate
pip install -r requirements.txt

# Download datasets
mkdir -p data
# NSL-KDD: Place KDDTrain+.txt and KDDTest+.txt in data/
# UNSW-NB15: Place parquet files in data/

# Run experiments
make train           # Train ReLU model (single seed, NSL-KDD)
make multiseed       # 10-seed experiment (NSL-KDD, ReLU vs QCFS)
make unsw            # 10-seed experiment (UNSW-NB15)
make unsw-export     # ONNX + INT8 for UNSW-NB15
make tree-baseline   # RF + XGBoost baselines
make layerwise       # FP32 vs INT8 layer-wise analysis
make quant-ablation  # 24-config quantization ablation
make paper           # Compile LaTeX paper

# NPU validation (requires browser)
# Upload models/*.onnx to https://stedgeai-dc.st.com
# Select target: STM32N6570-DK → Benchmark
```

## Project Structure

```
├── src/
│   ├── train.py               # ReLU model training (Path B)
│   ├── train_qcfs.py          # QCFS model training (Path A)
│   ├── export_onnx.py         # ONNX export with BN fusion (NSL-KDD)
│   ├── export_qcfs_onnx.py    # QCFS ONNX export
│   ├── export_unsw_onnx.py    # ONNX export + INT8 PTQ (UNSW-NB15)
│   ├── quantize.py            # INT8 PTQ (ReLU, NSL-KDD)
│   ├── quantize_qcfs.py       # INT8 PTQ (QCFS)
│   ├── quantize_ablation.py   # 24-config quantization ablation
│   ├── experiment_multiseed.py # 10-seed experiment (NSL-KDD)
│   ├── experiment_unsw.py     # 10-seed experiment (UNSW-NB15)
│   ├── tree_baseline.py       # RF + XGBoost baselines
│   └── layerwise_analysis.py  # FP32 vs INT8 layer-wise comparison
├── results/
│   ├── multiseed_experiment.json   # NSL-KDD 10-seed results
│   ├── unsw_multiseed_experiment.json # UNSW-NB15 10-seed results
│   ├── tree_baseline.json         # RF + XGBoost results
│   ├── layerwise_analysis.json     # FP32 vs INT8 analysis
│   ├── quantize_ablation.json      # Quantization ablation
│   └── related_work_table.json     # Related work comparison
├── paper/                     # LaTeX paper
├── configs/
│   └── default.yaml           # Experiment configuration
├── docs/
│   ├── ADR-001-SNN-NPU-GoNoGo-Verification.md
│   └── SNN_RTOS_Telecom_Analysis.md
├── CITATION.cff               # Citation metadata
├── requirements.txt           # Pinned dependencies
├── Makefile                   # One-command reproducibility
└── LICENSE                    # Apache 2.0
```

## Citation

```bibtex
@software{tsai2026snnids,
  title = {SNN-IDS: Deploying SNN-Equivalent Intrusion Detection on a Commodity MCU NPU},
  author = {Tsai, Hsiu-Chi},
  year = {2026},
  url = {https://github.com/thc1006/SpikeIDS-MCU},
  doi = {10.5281/zenodo.18906060},
  version = {1.0.0}
}
```

## References

- **QCFS Activation**: Bu et al., "Optimal ANN-SNN Conversion for High-accuracy and Ultra-low-latency Spiking Neural Networks," *ICLR 2022*.
- **Unified ANN-SNN Framework**: Jiang et al., "A Unified Optimization Framework of ANN-SNN Conversion," *ICML 2023*.
- **Inference-Scale Complexity**: Bu et al., "Inference-Scale Complexity in ANN-SNN Conversion," *CVPR 2025*.
- **NSL-KDD Dataset**: Tavallaee et al., *IEEE CISDA*, 2009.
- **UNSW-NB15 Dataset**: Moustafa & Slay, *MilCIS*, 2015.
- **Neural-ART NPU**: STMicroelectronics, STM32N6 Application Note UM3225.
- **HH-NIDS (MAX78000)**: Ngo et al., *Future Internet* 15(1):9, 2022.
- **Akida IDS**: Zahm et al., *CSIAC*, 2024.

## License

Apache License 2.0. See [LICENSE](LICENSE).
