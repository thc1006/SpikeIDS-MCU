# SNN-IDS: Spiking Neural Network Intrusion Detection on STM32N6 Neural-ART NPU

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.18906060.svg)](https://doi.org/10.5281/zenodo.18906060)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Target](https://img.shields.io/badge/Target-STM32N6570--DK-03234B.svg)](https://www.st.com/en/evaluation-tools/stm32n6570-dk.html)
[![NPU](https://img.shields.io/badge/NPU-Neural--ART_600_GOPS-green.svg)](#)
[![Inference](https://img.shields.io/badge/Inference-0.4561ms_@_800MHz-brightgreen.svg)](#key-results)

**First hardware-verified deployment of an INT8 quantized ANN (mathematically equivalent to T=1 SNN) for real-time network intrusion detection on a general-purpose MCU NPU.**

## Key Results

| Metric | Value |
|--------|-------|
| **Target Board** | STM32N6570-DK (Cortex-M55 @ 800MHz + Neural-ART NPU) |
| **Inference Latency** | **0.4561 ms** (2,192 inferences/sec) |
| **Model Size** | 137.7 KB Flash, 1.25 KB RAM |
| **INT8 Accuracy** | 76.38% overall (0.08% drop from FP32) |
| **NPU Execution** | 5 HW + 1 Hybrid + 2 SW epochs (Gemm on NPU) |
| **Dataset** | NSL-KDD (5-class: normal, DoS, Probe, R2L, U2R) |

## What's New

To our knowledge, this is:

1. **First non-CV AI model deployed on STM32N6 Neural-ART NPU** — all prior public deployments are computer vision (YOLOv8n, image classification)
2. **First IDS deployed on a general-purpose MCU NPU** — prior work exists only on FPGA and neuromorphic chips (BrainChip Akida)
3. **First hardware verification of T=1 SNN equivalence theory** — arXiv:2510.23383 established the math; we provide the first NPU deployment
4. **First QCFS activation compiled for Neural-ART target** — Floor operator confirmed CPU fallback; Gemm layers accelerated on NPU

## Theoretical Basis

A single-timestep (T=1) SNN with Integrate-and-Fire neurons is mathematically equivalent to an INT8 quantized ANN with ReLU activation:

```
T=1 SNN inference ≡ INT8 Quantized ANN inference
```

This equivalence (arXiv:2510.23383, "One Timestep is Enough") means standard INT8 NPU hardware can execute SNN-equivalent computations without specialized neuromorphic chips.

## Architecture

```
IDS_MLP: Linear(41→256) → BN → ReLU → Linear(256→256) → BN → ReLU → Linear(256→128) → BN → ReLU → Linear(128→5)
```

- BatchNorm fused into Linear at export → ONNX graph: `Gemm` + `Relu` only
- 111,365 parameters, Gemm + Relu operators fully NPU-accelerated
- Inverse-frequency class weighting for extreme imbalance (U2R: 52/125,973 samples)

## QCFS Comparison Experiment

We additionally train with PASCAL QCFS activation (`floor(clip(x/step, 0, L)) * step`) as a direct SNN activation comparison:

| Model | Overall Acc. | Macro Acc. | ONNX Operators |
|-------|-------------|------------|----------------|
| ReLU (Path B) | 76.45% | 56.32% | Gemm, Relu |
| **QCFS L=4 (Path A)** | **79.75%** | **61.31%** | Clip, Floor, Gemm, Mul |
| QCFS L=8 | 78.79% | 59.33% | Clip, Floor, Gemm, Mul |
| QCFS L=16 | 79.39% | 60.26% | Clip, Floor, Gemm, Mul |

QCFS outperforms ReLU (+3.3pp overall, +5.0pp macro), likely due to quantization-induced regularization.

## NPU Hardware Benchmark

All models benchmarked on STM32N6570-DK (Cortex-M55 @ 800MHz + Neural-ART NPU) via ST Edge AI Developer Cloud v4.0.0:

| Model | Inference | Cycles | HW Epochs | SW Epochs | Flash | RAM |
|-------|-----------|--------|-----------|-----------|-------|-----|
| **ReLU INT8** | **0.4561 ms** | 364,913 | 5 | 2 | 137.7 KB | 1.25 KB |
| QCFS INT8 | 0.5364 ms | 429,080 | 13 | 14 | 138.0 KB | 2.00 KB |
| QCFS FP32 | 1.4156 ms | 1,132,485 | 0 | 20 | 430.1 KB | 3.17 KB |

Key findings:
- **Floor operator is NOT supported by Neural-ART NPU** — falls back to CPU as `Floor(float)`, requiring DequantizeLinear → Floor → QuantizeLinear round-trips
- **ReLU INT8 is the optimal NPU path** — all Gemm layers on NPU, no CPU fallback for activations
- **QCFS INT8 Gemm layers run on NPU** but Floor CPU round-trips add +0.08ms overhead (~17.6% slower)
- **QCFS FP32 runs entirely on CPU** (0% NPU) — 3.1x slower than ReLU INT8

## Reproduce

```bash
# Setup
python3 -m venv snn-ids-env
source snn-ids-env/bin/activate
pip install -r requirements.txt

# Download NSL-KDD dataset
mkdir -p data
# Place KDDTrain+.txt and KDDTest+.txt in data/
# Available at: https://www.unb.ca/cic/datasets/nsl.html

# Run full pipeline
make train        # Train ReLU model
make export       # Export to ONNX (with BN fusion)
make quantize     # INT8 post-training quantization
make qcfs         # Train + export QCFS models
make quantize-qcfs  # INT8 PTQ for QCFS L=4

# NPU validation (requires browser)
# Upload models/ids_model_int8.onnx to https://stedgeai-dc.st.com
# Select target: STM32N6570-DK → Benchmark
```

## Project Structure

```
├── src/
│   ├── train.py              # ReLU model training (Path B)
│   ├── train_qcfs.py         # QCFS model training (Path A)
│   ├── export_onnx.py        # ONNX export with BN fusion
│   ├── export_qcfs_onnx.py   # QCFS ONNX export (frozen thresholds)
│   ├── quantize.py           # INT8 post-training quantization (ReLU)
│   └── quantize_qcfs.py      # INT8 post-training quantization (QCFS)
├── results/
│   ├── relu_path_b.json      # Full experiment results (Path B)
│   └── qcfs_path_a.json      # Full experiment results (Path A)
├── configs/
│   └── default.yaml          # Experiment configuration
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
@software{snn_ids_stm32n6_2026,
  title = {SNN-IDS: Spiking Neural Network Intrusion Detection on STM32N6 Neural-ART NPU},
  author = {thc1006},
  year = {2026},
  url = {https://github.com/thc1006/SpikeIDS-MCU},
  doi = {10.5281/zenodo.18906060},
  version = {1.0.0},
  note = {First hardware-verified T=1 SNN-equivalent IDS on general-purpose MCU NPU}
}
```

## References

- **T=1 SNN Equivalence**: Q. Chen et al., "One-Timestep is Enough: Achieving High-performance ANN-to-SNN Conversion via Scale-and-Fire Neurons," arXiv:2510.23383, 2025.
- **QCFS Activation**: T. Bu et al., "Optimal ANN-SNN Conversion for High-accuracy and Ultra-low-latency Spiking Neural Networks," ICLR 2022.
- **NSL-KDD Dataset**: M. Tavallaee et al., "A Detailed Analysis of the KDD CUP 99 Data Set," IEEE CISDA, 2009.
- **Neural-ART NPU**: STMicroelectronics, STM32N6 Application Note UM3225.
- **Closest Prior Work**: CSIAC (Zahm, Nishibuchi et al.), "Low-Power Cybersecurity Attack Detection Using Deep Learning on Neuromorphic Technologies" (BrainChip Akida AKD1000, 98.4% accuracy, ~1W).

## License

Apache License 2.0. See [LICENSE](LICENSE).
