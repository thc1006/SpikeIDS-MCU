# B2 link smoke-test — result (2026-09-19)

`build.sh` compiles the generated model + the full ATON runtime + the HAL NPU-init layer with the
arm-gcc 13.2 toolchain here and links against `NetworkRuntime1100_CM55_GCC.a`.

## PROVEN (build integration)
- **17 objects, 0 compile warnings, 0 undefined references, 17.7 KB ELF.**
- ATON runtime (`ll_aton/*.c` + the `.a`) + generated `stai_ids.c/ids.c` + `npu_cache.c` all
  build and link. `nm` shows real implementations (`LL_ATON_RT_RunEpochBlock`, `__ll_aton_stai_run`,
  `LL_Convacc_Init`, `stai_ids_run` are defined `T` symbols) — not stubs.
- ⇒ **R10 (ATON runtime ABI vs arm-gcc 13.2) RESOLVED — path A is build-viable.**
- Build note: `-include stm32n6xx_hal.h` forces the HAL umbrella first, avoiding a re-entrant
  include-guard trap (`-DUSE_HAL_DRIVER` makes `stm32n6xx.h` pull `rcc.h` before `HAL_StatusTypeDef`).

## NOT proven (still on-board / next step)
- **Runtime correctness** — link ≠ run. The NPU actually executing needs the board.
- **R-c (new, from this review): code/activation memory collision.** The smoke link used a
  placeholder `-Ttext=0x34200000`, which OVERLAPS `POOL_NPU` (activations @0x34200000 in
  mypool_n6.json). The real firmware MUST use a linker script placing code in a region clear of the
  activation pools — e.g. code in SRAM1 (0x34064000), activations SRAM2 (0x34100000) / SRAM3
  (0x34200000), weights XSPI2 (0x70000000). Fix before building the deployable firmware.
- **R4 (activation secure/non-secure alias)** and **R9 (does the ATON runtime need more init than
  NPU_Config/RISAF_Config/npu_cache)** remain unverified until on-board.

## Next
Assemble the deployable firmware: my takeover startup + mailbox + `NPU_Config`/`RISAF_Config`
(from misc_toolbox.c) + `npu_cache` + `stai_ids_run` timed with DWT, under a proper linker script
(code clear of pools). Then flash weights to XSPI2 (CubeProgrammer + BOOT) and measure via pyOCD.
