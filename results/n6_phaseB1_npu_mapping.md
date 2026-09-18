# STM32N6 Phase B1 — Neural-ART mapping (ST Edge AI Core 3.0.0, no board)

`stedgeai analyze --target stm32n6 --st-neural-art default@<STM32N6xx/neural_art.json>` on the
INT8 (QDQ) ONNX of each IDS_MLP shape. This reproduces v3's cloud epoch split bit-for-bit and
adds the on-host memory profile. Latency needs on-target `validate` (Phase B2).

| Model | MACs | NPU weights (B) | epochs | HW | Hyb | SW | RT flash (text) | RT RAM (bss) | 100% NPU? |
|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|
| NSL-KDD (41→256→…→5)   | 112,829 | 143,665 | 8 | 5 | 1 | 2 | 17,316 | 1,741 | no (input boundary) |
| UNSW-NB15 (34→…→10)    | 111,674 | 110,993 | 4 | 4 | 0 | 0 |  6,854 |    29 | **yes** |
| CICIDS2017 (78→…→15)   | 123,779 | 122,897 | 4 | 4 | 0 | 0 |  6,878 |    29 | **yes** |
| IoT-23 (23→…→5)        | 108,149 | 107,521 | 4 | 4 | 0 | 0 |  6,826 |    29 | **yes** |
| CAN H=64 (11→64→…→5)   |   7,877 |   7,761 | 4 | 4 | 0 | 0 |  6,770 |    29 | **yes** |

## Findings
- **Toolchain validated against v3.** The epoch split matches v3's reported numbers exactly:
  NSL-KDD 5 HW + 1 Hyb + 2 SW; UNSW/CICIDS/IoT-23 4 HW + 0 SW. Our local ONNX→Neural-ART
  pipeline is bit-faithful to the ST cloud results v3 published — the deployment claim is sound.
- **The ReLU INT8 IDS_MLP maps ~100% to the NPU** for 3 of 4 datasets (4 Gemm layers → 4 HW
  epochs, 0 CPU fallback). Only NSL-KDD spends CPU epochs, at the input dequantize boundary
  (2 SW + 1 hybrid), inflating its runtime footprint (17 KB vs 6.8 KB text, 1.7 KB vs 29 B RAM).
- The all-HW models carry a tiny ATON runtime (~6.8 KB flash, 29 B RAM) on top of the weights.

## Caveats / next (B2)
- `analyze` gives the mapping + memory but **not** a cycle/latency estimate for Neural-ART;
  on-board latency requires `stedgeai validate --mode target` (or a custom ATON-runtime firmware)
  flashed to the DK — Phase B2, needs the board + CubeProgrammer (external-flash loader in hand).
- Weights are random (topology-only) — timing/mapping is weight-independent, so B1 is valid;
  real trained weights are used for B2 accuracy/measurement.
