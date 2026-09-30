# On-board INT8 IDS latency: same model, three MCU classes, width sweep (v4)

Same MLP family **11→W→W→W/2→5** (INT8 QDQ) swept over hidden width **W ∈ {64,128,256}**,
deployed on-board on every platform. All latencies are cycle-counted on hardware, every CPU/NPU
clock **independently verified** (a 64-vs-800 MHz clock bug on the N6 CPU build was caught this way),
and (for fairness) **weights are SRAM-resident on all platforms** so the comparison isolates compute,
not memory tier. Latency of dense INT8 fully-connected kernels is weight-value-independent (verified:
a random-weight W=64 model measured 13.91 µs vs the real deploy_h64's 13.9 µs), so architecture-matched
ONNX is used for the latency sweep; per-width **accuracy** comes from the SpikeIDS-RA4E1 real-data
ablation (platform-independent): W=256/128/64 → 79.99 / 79.70 / 79.60 % test acc.

## Latency sweep (µs, on-board, weights in SRAM, clocks verified)
| W | MACs | STM32N6 M55-CPU | STM32N6 NPU (EC) | ESP32-S3 LX7 | FPB-RA4E1 M33 |
|---|---|---|---|---|---|
| | | Helium/MVE @800MHz | Neural-ART @800/1000MHz | ESP-NN @240MHz | CMSIS-NN DSP @100MHz |
| 64  | 7,008   | **13.9** | 30.2 | 114.0 | 264.6 |
| 128 | 26,304  | **50.7** | 81.1 | 289.5 | 782.8 |
| 256 | 101,760 | 314.7 | **275.3** | 832.5 | 2627.5 |

cyc/MAC (clock-normalized architecture efficiency):
| W | N6-CPU | N6-NPU | ESP32-S3 | RA4E1 |
|---|---|---|---|---|
| 64  | 1.59 | 3.45 | 3.90 | 3.78 |
| 128 | 1.54 | 2.47 | 2.64 | 2.98 |
| 256 | 2.47 | 2.16 | 1.96 | 2.58 |

## Headline: the NPU crossover (answers "what does the NPU buy?")
On the **same STM32N6 chip**, the M55 CPU (Helium/MVE) vs the Neural-ART NPU:
- W=64  (7 k MAC):  CPU 13.9 µs **beats** NPU 30.2 µs — NPU **2.2× slower**.
- W=128 (26 k MAC): CPU 50.7 µs **beats** NPU 81.1 µs — NPU **1.6× slower**.
- W=256 (102 k MAC): NPU 275.3 µs **beats** CPU 314.7 µs — NPU **1.14× faster**.

**The NPU only pays off above ~10⁵ MACs.** Below that, its fixed per-inference orchestration
overhead exceeds the entire CPU inference. For a minimal tabular CAN/flow IDS the CPU wins outright.

**Honest nuance (why the crossover happens where it does):** the N6 CPU stays ~1.5 cyc/MAC until
W=256, where the weights (~100 KB) exceed the 32 KB L1 D-cache and it rises to 2.47 cyc/MAC; the NPU,
with its own npu_cache + XSPI weight-streaming path, does not hit that cliff (2.16 cyc/MAC). So the
NPU overtakes the CPU at W=256 partly because the CPU hits its L1 capacity, not purely by raw NPU
throughput. This is exactly the model-scale/memory-hierarchy interaction that a single-point
benchmark would miss — and it reconciles the paper's larger-model NPU wins with the tiny-model CPU wins.

## Cross-platform (same model, each at its rated clock, SRAM weights)
N6-CPU ≪ N6-NPU < ESP32-S3 ≪ RA4E1 at every width. The M55's wide INT8 Helium (MVE) is the real
lever: at W=64 it is 8× faster than the ESP32-S3 (240 MHz LX7 SIMD) and 19× faster than the RA4E1
(100 MHz M33 DSP). Per-cycle, ESP-NN's LX7 SIMD scales best with width (3.90→1.96 cyc/MAC) as its
vector lanes amortize; the M33 DSP (SMLAD) plateaus ~2.6–3.8.

## Methodology / bugs caught by adversarial review (user: "there is always a problem")
- **N6 CPU clock**: firmware never set the PLL → ran at 64 MHz HSI while I converted as 800 MHz.
  Fixed with the ST 800 MHz bring-up (VDDCORE PF4 SMPS + MEMSYSCTL cache-gate + PLL1); verified 2 ways.
- **ESP32 console** on USB-Serial-JTAG (native USB, not connected) → rebuilt with UART console.
- **ESP32 Task-WDT crash** at W=256 (1000 iters × 7 ms > 5 s, idle task starved) → periodic vTaskDelay.
- **ESP32 flash-cache thrash** at W=256 (65 KB weights > flash cache → 16 cyc/MAC, 6959 µs) → copy
  weights to internal SRAM (→ 1.5 cyc/MAC, 832 µs). N6/ESP32/RA4E1 now all SRAM-resident = fair.
- **RA4E1 DWT froze on J-Link disconnect** (`qc`) → single connected session (reset→go→Sleep→halt→read).
- **RA4E1 W=256 Sleep too short** (2.5 s < 2.6 s run) → longer Sleep; result then matches the ablation
  exactly (262,750 cyc, deterministic).

## Reproduce
- ONNX per width: `scripts/gen_width_onnx.py --width W` (SpikeIDS-MCU).
- N6 CPU: stedgeai `--target stm32n6` (no NPU) → `firmware/n6cpu` → `scripts/n6_cpu_run.py`.
- N6 NPU: stedgeai reloc `test-ec` → `scripts/n6_validate_pathB.py`.
- ESP32/RA4E1: `SpikeIDS-RA4E1/ml/export/onnx_to_cmsis.py` → shared `firmware/app/model` →
  ESP32 `firmware/esp32s3` (idf) / RA4E1 `firmware/ra4e1_skeleton` (cmake `-DIDS_WEIGHTS_IN_SRAM=1`, JLink).
- Data: `results/three_platform_sweep.tsv`.
