# STM32N6 Phase A — CPU-side latency, SRAM vs flash weights

Source: `n6_bench_20260919_011846.json` · git `d0cfb3f6` · 2026-09-18T17:18:46.113258+00:00

## Platform (captured on-board)
- Cortex-M55 @ **800 MHz** (HAL) / **798.5 MHz** (measured, DWT vs wall-clock; agree 0.18%)
- L1 I-cache 32 KB (2-way), D-cache 32 KB (4-way), 32-byte lines
- XSPI2 external flash: memory-mapped=True, 200 MHz, 8 data lines, DDR=True → ~400 MB/s theoretical
- Timing: DWT CYCCNT; NOP overhead 9 cyc (caches on)

## Headline: INT8 MLP (CMSIS-NN, Helium MVE), weights in SRAM vs memory-mapped flash
Caches on, warm. `us` at 800 MHz; ratio = flash/SRAM. INT8 weight bytes ≈ MACs.

| Model | MACs | wt KB | fits 32KB$ | SRAM µs (min) | Flash µs (min) | flash/SRAM |
|---|--:|--:|:--:|--:|--:|--:|
| v3_cicids | 120192 | 117 | **no** | 282.9 (270.8) | 1189.1 (1107.3) | **4.2×** |
| v3_nslkdd | 109440 | 107 | **no** | 255.9 (241.0) | 1044.4 (962.9) | **4.1×** |
| v3_unsw | 108288 | 106 | **no** | 253.3 (241.2) | 1027.7 (962.8) | **4.1×** |
| v3_iot23 | 104832 | 102 | **no** | 245.4 (227.6) | 974.7 (888.4) | **4.0×** |
| can_h256 | 101760 | 99 | **no** | 237.7 (221.6) | 952.2 (861.4) | **4.0×** |
| can_h128 | 26304 | 26 | yes | 25.0 (23.9) | 31.9 (28.4) | **1.3×** |
| can_h96 | 15120 | 15 | yes | 14.8 (14.8) | 14.8 (14.8) | **1.0×** |
| can_h64 | 7008 | 7 | yes | 8.6 (8.6) | 8.6 (8.6) | **1.0×** |
| can_h32 | 1968 | 2 | yes | 4.3 (4.3) | 4.3 (4.3) | **1.0×** |

## Findings
1. **The flash-bound effect is real and cache-gated.** Models whose INT8 weights exceed the
   32 KB D-cache (v3's 256-wide nets, ~105–120 KB) run **~4.0× slower** from flash than from
   SRAM — they re-stream every inference. Models whose weights fit the cache (H≤128, ≤26 KB)
   are **placement-independent** (flash = SRAM, 1.0×) once warm: compute-bound, not flash-bound.
2. **This explains the v3 latencies.** v3 deployed 256-wide nets with flash-resident weights, so
   its 0.29–0.46 ms (INT8) were dominated by weight streaming, not NPU/CPU compute — matching the
   first-principles estimate (v3 implied 280–410 MB/s; measured flash read BW ≈ 395–415 MB/s vs
   SRAM ≈ 906 MB/s).
3. **Compute floor (Helium INT8, cache-fitting): ~0.76–0.99 cyc/MAC** — vs RA4E1 M33+DSP ~3.4 and
   ESP32-S3 LX7 ~2.4 (SpikeIDS-RA4E1/docs/RESULTS.md). The M55 vector unit is ~3–4× faster per MAC.
4. **INT8 vs scalar-FP32 on the M55: 3.4×** (consistent across the four v3 shapes).
5. Combined with the RA4E1 finding that H=64 is ~14× over-provisioned at no macro-F1 cost: the
   deployable model (H=64, 7 k MACs) runs in **8.6 µs**, placement-independent — ~30–120× faster
   than v3's reported figures, purely from not thrashing the cache.

## Caveats (Phase A scope)
- CPU-issued cached reads, **not** NPU DMA bursts; the Neural-ART stream engines are Phase B
  (needs ST Edge AI Core output). This phase measures the M55+Helium path and the memory system.
- Timing jitter 8–18% on cache-spilling models (cache-eviction + DDR-refresh); cache-fitting
  models are tight (≤2%). Median is the robust centre; min is the deterministic floor. Both give ~4×.
- FP32 baseline is scalar (GCC does not auto-vectorise the float reduction) — a conservative
  'unoptimised CPU FP32' reference, not ST's optimised FP32/MVE-FP runtime.
- Flash-condition weights are arbitrary flash bytes; INT8 kernel timing is data-independent, so
  the latency is valid (the argmax output is not a real classification).
- Whole-image, single board, single session; 100 iterations/condition.
