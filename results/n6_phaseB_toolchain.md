# STM32N6 Phase B — toolchain verified (2026-09-19)

All ST tooling installed locally and validated end-to-end; no cloud needed.

## Installed (verified)
- **STM32CubeProgrammer 2.23.0** (`~/opt/STMicroelectronics/STM32CubeProgrammer`).
  Download sha256 `6a9e60a5…7442a` matches the known-good v2.23.0. External-flash
  loader for our board present: `MX66UW1G45G_STM32N6570-DK.stldr`.
- **ST Edge AI Core 3.0.0** + **Neural-ART module v11.0.0** + STM32 MCU module v11.0.0
  (`~/opt/stedgeai/3.0`; CLI `Utilities/linux/stedgeai`). Core 4.0.1 exists but has no
  Neural-ART backend in the repo yet — 3.0.0 is the N6 path (matches ST's x-cube-n6 examples).

## ONNX validation (scripts/validate_onnx_neuralart.py) — ALL PASS
FP32 + INT8(QDQ) built for the four v3 shapes and H=64; onnx.checker (full) + ORT
inference + operator audit vs the Neural-ART support table:
- INT8 graph = **Gemm + QuantizeLinear/DequantizeLinear only** — every op HW-mapped,
  **zero unsupported, zero CPU-fallback ops** (no Floor, unlike the QCFS path v3 flagged).
- INT8 sizes: 109-125 KB (256-wide) ; **H=64 = 12.2 KB** (fits the 32 KB D-cache).

## Neural-ART compilation check (stedgeai analyze, H=64 INT8)
`stedgeai analyze --target stm32n6 --st-neural-art default@<N6 neural_art.json>`:
- **4 epochs, all pure HARDWARE (0 SW, 0 hybrid)** — 100% NPU mapping, matching v3's
  ReLU-INT8 claim. weights 7,761 B, ATON runtime 13.3 KB flash, activations 128 B RAM.

## Next (Phase B measurement, remaining)
1. `stedgeai generate` the deployable network.c + weights + ATON runtime for each model.
2. NPU inference firmware (call the generated network, time with DWT), deploy via
   CubeProgrammer (external flash) or the pyOCD RAM-takeover harness.
3. Measure NPU latency + epoch profile on-board → the column v3 could only get from the cloud,
   and the SRAM-vs-flash / NPU-vs-Helium comparison that answers "what does the NPU buy".
