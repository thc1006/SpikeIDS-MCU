# On-board QCFS (T=1 SNN) `Floor` fallback — measured, not cloud-estimated (v4)

Replaces the v3 **cloud** estimate ("+17.6% latency") for the QCFS/`Floor` NPU penalty with
on-board evidence on the STM32N6570-DK, using the **same architecture** as the ReLU-INT8
baseline (**13→256→256→128→5**, IoT-23; the QCFS variant only swaps ReLU→QCFS(L=4), i.e.
`Clip`+`Floor`+`Mul` instead of `Relu`). Toolchain: **ST Edge AI Core v3.0.0-20426** (local,
not the cloud). QCFS weights: `models/iot23_qcfs_L4_best.pth`; INT8 QDQ via onnxruntime static
quant (random calibration — latency of dense INT8 + `Floor` is value-independent, so calibration
ranges do not affect timing).

## 1. NPU compile graph: `Floor` shatters the hardware graph (ST Edge AI Core 3.0, `test-ec` reloc)
| Model (same arch) | Total epochs | HW/EC | SW (fallback) | Structure |
|---|---|---|---|---|
| **ReLU-INT8**  | 4  | 4 (1 EC blob)  | **0**  | single 100%-HW graph |
| **QCFS-INT8**  | 24 | 12 (4 EC blobs)| **12** | 3× `DequantizeLinear→Floor(float)→QuantizeLinear→QuantizeLinear` interleaved with HW |

Each QCFS activation becomes a 4-epoch software island; the model has 3 of them → 12 SW epochs.
`Floor` is confirmed absent from the Neural-ART (NPU) operator set and is emitted as `Floor(float)`
SW epochs (`network_generate_report.txt`).

## 2. NPU deploy: the QCFS graph does not run on ST's standard validation runtime
Path B (ST-official `stm32n6570-dk-validation-reloc.elf` + `stm_ai_runner`, the flow that measured
every ReLU row) **fails for QCFS**: the runtime aborts during model instantiation.
- Root cause (pyOCD): the core is parked at `__exit` (`bkpt 0xAB`, semihosting `SYS_EXIT`, then spin)
  at `0x340152FC` for the whole run — a failed `assert()` in the ll_aton runtime while bringing up the
  12-SW-epoch schedule (`LL_ATON_ASSERT`≡`assert`; `__exit` PC held constant over 30 s, `CFSR=HFSR=0`,
  so it is a clean `abort()`, not a HardFault). `is_alive()`'s `CMD_SYNC` never gets served → the driver
  reports `E801 Invalid firmware`.
- Control: the **same-architecture ReLU-INT8** model on the same firmware/flow runs cleanly →
  **276.6 µs** (99.6% HW), re-verified this session. So the failure is specific to the QCFS/`Floor`
  (12-SW-epoch) graph, not the board, driver, or method.
- Corroboration that even a little SW-fallback is costly: **NSL-KDD ReLU** compiles to 2 SW epochs
  (`Dequant`→`Conv(float)`), runs, and is **1.6× slower on the NPU (518 µs) than on the INT8 CPU
  (323 µs)** — the only NPU-loss row in `tab:npu`. QCFS would add six times as many SW epochs.

## 3. CPU cost of `Floor`, measured on the M55 (both variants all-CPU, same session, DWT, clock-verified)
Deployed via the ST **CPU lite runtime** (`use-st-ai`, no NPU — the runtime the NPU falls back onto),
static firmware `firmware/n6cpu`, I-/D-cache ON, weights+acts SRAM-resident, clock verified 798.9–799.0 MHz.

| Model (IoT-23, same arch) | median cycles | median µs | Δ vs ReLU |
|---|---|---|---|
| **ReLU-INT8** CPU | 242,236 | **303.2** | — |
| **QCFS-INT8** CPU | 270,946 | **339.2** | **+28,710 cyc = +36.0 µs = +11.9%** |

Both `rc=0` (full model executed; QCFS `cpunet.c` contains 75 `floor` refs and runs ~9.6k extra
cycles per activation island, physically consistent with a 256-wide float `Dequant→Floor→Quant`
round-trip). This **+11.9% (≈12 µs per `Floor` island)** is the on-board replacement for the v3
cloud "+17.6%": the cost of the `Floor` operators when they execute on the CPU — which, on the NPU
path, is exactly what happens to all 12 SW epochs (when the graph deploys at all).

## Verdict for the paper
ReLU-INT8 is the only activation that deploys as a 100%-hardware NPU graph. QCFS/`Floor` (a) fragments
into 12 software epochs, (b) fails to instantiate on ST's standard NPU validation runtime, and
(c) costs +11.9% on the CPU fallback path. This is a stronger, honest, fully on-board result than the
v3 cloud "+17.6%" estimate.

## Reproduce
- Export+quantize QCFS: `src/export_qcfs_onnx.py` (input_dim=13) → INT8 QDQ (random calib).
- NPU compile: `stedgeai generate --target stm32n6 --st-neural-art test-ec@…/neural_art_reloc.json`.
- NPU deploy attempt: reloc build (`prepare_network.py` → `makefile_gcc` w/ Middlewares `RT_ATON_ROOT_DIR`
  + `NetworkRuntime1100_CM55_GCC_PIC.a` → `relocatable_pp.py`) → `scripts/n6_validate_pathB.py`.
- CPU measure: `stedgeai generate --target stm32n6` (no `--st-neural-art`) → `firmware/n6cpu`
  (`MODEL=<gen> B=<build> build_cpu.sh`) → `scripts/n6_cpu_run.py`.
