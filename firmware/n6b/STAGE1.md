# Stage 1 — on-board NPU latency (ready to run)

Path A firmware (custom, reuses ST's NPU init) + pyOCD takeover. Measures `stai_ids_run` on the
Neural-ART with DWT. Built with **LL_ATON_RT_POLLING** so the CPU busy-polls the NPU and DWT counts
the true inference time (no WFE-sleep undercount).

## Board flow (your actions in **bold**)
1. **Set BOOT1 switch → DEV mode (position 1-3).**
2. `bash firmware/n6b/flash_weights.sh` — flashes weights to XSPI2 **0x71000000** (MX66 loader).
3. **Set BOOT1 → NORMAL, power-cycle the board** (OOB boots, maps XSPI2, enables the NPU).
4. `uv run scripts/n6b_run.py --iters 100` — arms the pyOCD watcher; it takes over (IWDG-defanged),
   loads `build/n6b.elf` into AXISRAM1, runs the NPU, prints median cycles → µs, writes results JSON.
   (A takeover replug may be needed, as in Phase A — the script waits for it.)

## Build (regenerate)
`bash firmware/n6b/build.sh` → n6b.elf (26 KB, code in AXISRAM1 0x34064000, mailbox 0x340F8000,
activations in NPU SRAM, weights XSPI2). Deps: arm-gcc 13.2, ST Edge AI runtime .a, N6 HAL.

## Adversarial review (this phase)
- **R-M1 (DWT undercount if CPU WFE-sleeps during NPU epochs) — FIXED**: built LL_ATON_RT_POLLING
  (busy-poll), so DWT counts real NPU time. Cross-check on-board: median µs should be the same order
  as v3's cloud figures for a comparable model.
- **R-M2 (HAL cache/RIF ops without HAL_Init tick)** — low risk (ops ready quickly); if
  npu_cache_enable hangs, add a minimal SysTick/HAL_InitTick.
- **R9 (runtime unproven on-board)** — inherent; can only be confirmed on the board. If stai_ids_run
  faults, fall back to Path B (`validate --mode target`).
- Verified at build: 25 objs, 0 undefined, ABI (hard-float VFP+MVE) matches the runtime .a; code
  clear of the NPU activation region (0x342e0000) and weights (0x71000000).

## On-board acceptance checks (when it runs)
- boot snapshot: stai_init_rc==0, CPUID==0x411FD2xx, in=11/out=5 bytes.
- inference rc==0, argmax in [0,4], median cycles stable (low spread) — that's the NPU latency.
