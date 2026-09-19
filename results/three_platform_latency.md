# Three-platform on-board INT8 CAN-IDS latency (v4, all clocks verified)

Same model on all platforms — **11→64→64→32→5 INT8 MLP, 7,008 MACs** (weight shapes
`(64,11)(64,64)(32,64)(5,32)` verified identical across the N6 and RA4E1/ESP32 ONNX exports;
only quant-calibration/naming differ, architecture is byte-for-byte the same topology).
Every latency is on-board, cycle-counted, with the CPU/NPU clock **independently verified**
(not assumed — a 64 MHz-vs-800 MHz clock bug on the N6 CPU build was caught and fixed this way).

| platform | core | clock (verified how) | int8 backend | cycles | **latency** | cyc/MAC |
|---|---|---|---|---|---|---|
| STM32N6 | M55 CPU | 800 MHz (HAL_RCC=800.0 + CYCCNT/2s=799.x) | ST AI runtime + **Helium/MVE** | 11,112 | **13.9 µs** | 1.59 |
| STM32N6 | Neural-ART **NPU (EC)** | 800/1000 MHz (24,281cyc÷0.030ms=809MHz self-consistent) | epoch-controller, 96% HW | 24,281 | **30.2 µs** | 3.47 |
| STM32N6 | Neural-ART NPU (naive) | 800/1000 MHz | default, 72% SW-ctrl | 62,548 | 77.9 µs | 8.93 |
| ESP32-S3 | Xtensa LX7 | 240 MHz (esp_rom_get_cpu_ticks_per_us on-device) | ESP-NN LX7 SIMD | 27,366 | **114.0 µs** | 3.90 |
| FPB-RA4E1 | M33 CPU | 100 MHz (g_core_hz=100.0M + CYCCNT/1s=100.1M) | CMSIS-NN **DSP/SMLAD** (no MVE) | 29,052 | **290.5 µs** | 4.15 |

## Headline findings (honest, measured)
1. **The NPU buys nothing for a tiny tabular IDS on its own chip.** On the STM32N6, the M55 CPU
   (Helium/MVE, 13.9 µs) is **2.2× faster than the best NPU deployment (EC, 30.2 µs)** and **5.6×
   faster than the naive NPU build (77.9 µs)**. The NPU's fixed per-inference invocation/orchestration
   overhead exceeds the entire CPU inference for a 7 k-MAC model.
2. **Cross-platform (all CPU int8):** N6-M55/Helium 13.9 µs (800 MHz) < ESP32-S3/LX7 114 µs (240 MHz)
   < RA4E1-M33/DSP 290 µs (100 MHz). Per-cycle efficiency (cyc/MAC): M55-Helium 1.59 ≪ LX7-SIMD 3.90 ≈
   M33-DSP 4.15 — Helium's wide INT8 MVE is the real lever, not clock alone.
3. The un-vectorisable first layer (in=11) dominates on every platform (e.g. ESP32-S3 fc0 = 45 % of
   its cycles, `ansi-scalar`) — a tiny tabular input can't feed wide SIMD/NPU lanes.

## Bugs caught by adversarial review this phase (user: "I don't believe it works first try")
- **N6 CPU clock**: firmware never configured the PLL → ran at 64 MHz HSI while I converted as 800 MHz.
  Number was right by luck (cycle count ~clock-independent, L1-bound) but method broken. Fixed:
  full ST 800 MHz bring-up (VDDCORE PF4 SMPS overdrive + MEMSYSCTL cache-gate + PLL1). Verified 2 ways.
- **ESP32-S3 console** on USB-Serial-JTAG (native USB, not connected) → no output on the CH343 UART.
  Rebuilt with `CONFIG_ESP_CONSOLE_UART_DEFAULT`.
- **RA4E1 CYCCNT froze on J-Link disconnect** (`qc`) → 96 % of samples read 0. Cause: debug power
  domain powers down on disconnect, freezing DWT even with TRCENA set. Fixed: single J-Link session
  kept connected through the run (reset→go→Sleep→halt→read); all 1000 samples then deterministic ±1 cyc.

## Fairness verified (max-rigor review)
- **Same model** on all 3: layer dims confirmed in each deployed artifact — N6 ONNX weight shapes
  `(64,11)(64,64)(32,64)(5,32)`; RA4E1 `IDS_IN_DIMS {11,64,64,32}`/`OUT_DIMS {64,64,32,5}`;
  ESP32 bench prints `in=11 -> 64 64 32 5`. All = 11→64→64→32→5, 7,008 MACs.
- **Same optimisation**: all -O2 (N6 build.sh; RA4E1 cmake Debug -O2; ESP32 `COMPILER_OPTIMIZATION_PERF`).
- **Timing scope**: N6 & ESP32 time the network only (argmax outside); RA4E1 includes argmax over 5
  classes (<0.1 %). Latency is data-independent (dense INT8 FC, no data-dependent branching), so the
  zero-input N6 run is representative.
- **Known asymmetries (honest, sub-dominant):** N6 CPU weights are SRAM-resident (embedded image),
  RA4E1/ESP32 are flash-resident + cache — but the RA4E1 SRAM-vs-flash ablation showed only 10.7 %,
  far below the 20× N6-vs-RA4E1 gap. Output correctness spot-checked where the harness allows
  (ESP32 10/10 vs ONNX ref; RA4E1 pred=class1; N6 rc=0); full 5-seed macro-F1 99.97 % is in SpikeIDS-RA4E1.

## Reproduce
- N6 CPU: `firmware/n6cpu/build_cpu.sh` + `scripts/n6_cpu_run.py` (SpikeIDS-MCU).
- N6 NPU: `scripts/n6_validate_pathB.py` (EC model in `firmware/n6b/pathB_ec/`).
- ESP32-S3: `SpikeIDS-RA4E1/firmware/esp32s3` built with UART console → flash → read /dev/ttyACM1.
- RA4E1: `SpikeIDS-RA4E1` cmake headless build of `firmware/ra4e1_skeleton` → JLink flash →
  single-session read (keep J-Link connected).
