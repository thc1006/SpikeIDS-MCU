# STM32N6 Phase B2 — on-board Neural-ART measurement plan

Goal: real on-board NPU inference latency (+ per-epoch profile), then the NPU-vs-Helium-vs-flash
comparison that answers "what does the NPU buy". Toolchain fully installed & verified (Phase B1).

## Hard constraint (from ST NPU_Validation README)
**Weights MUST live in external flash (0x7000_0000–0x7FFF_FFFF); internal-RAM weights are not
supported.** So B2 unavoidably needs: flash the weights blob to XSPI2 via CubeProgrammer
(`MX66UW1G45G_STM32N6570-DK.stldr`, in hand) + likely a one-time **BOOT-switch** action on the DK
so the ST-LINK can program external flash. Activations go in SRAM (POOL_INTERNAL 0x34100000 /
POOL_NPU 0x34200000 — regions the pyOCD takeover harness controls).

## Artifacts produced (this dir, from `stedgeai generate ... --binary --memory-pool mypool_n6.json`)
- `model/stai_ids.{c,h}`, `model/ids.{c,h}` — STAI + LL_ATON deployable model (H=64 INT8).
  NOTE: built from a **random-weight** topology model — valid for latency/epoch bring-up (timing is
  data-independent); a real trained model is swapped in for the accuracy run.
- `model/ids_atonbuf.xSPI2.raw` — 7,761 B weights → flash at **0x71000000** (the address
  baked into ids.c: octoFlash 0x71000000-0x71001E60; NOT 0x70000000 — deep-review DC7).
- `model/ids_c_info.json` — validation descriptor (for `stedgeai validate --val-json`).
- `mypool_n6.json` — memory pool (weights ext-flash, activations SRAM2/SRAM3).

## NPU init sequence (from ST hello_world main_stai.c — to reuse verbatim)
1. `NPU_Config()`: `__HAL_RCC_NPU_CLK_ENABLE()` + NPU force/release reset + `npu_cache_enable()`
   (HAL_CACHEAXI) + RIF master (NPU CID=1, secure priv) + RISC slave secure attrs.
2. `RISAF_Config()`: `set_risaf_default()` for SRAM1/2, NPU MST0/1, SRAM3-6, FLEXMEM, NPU_CACHE,
   OCTOSPI2 (0x70000000). Opens the memory firewall for the NPU bus master.
3. STAI run (timed, DWT): `stai_runtime_init()` → `stai_network_init()` → `stai_network_get_inputs/outputs`
   → loop `stai_ext_network_run_continue()` until STAI_DONE. Wraps `LL_ATON_RT_RunEpochBlock`.
HAL drivers needed (all present in firmware/n6/third_party/stm32n6xx-hal-driver): rif, cacheaxi,
rcc(+ex), cortex, pwr(+ex). Runtime lib: `NetworkRuntime1100_CM55_GCC.a` (in the stedgeai install).

## Two deployment sub-paths (decide at board time)
- **A (preferred): my pyOCD harness + ST init.** Extend firmware/n6 with a CMD_NPU_INFER: compile
  ST's NPU_Config/RISAF_Config/npu_cache + generated stai_ids/ids + link the ATON runtime; load to
  SRAM via the proven takeover; results over the SWD mailbox; time with DWT. Lighter than
  NPU_Validation (no USBX/BSP bulk), reuses the robust harness. Weights still flashed to XSPI2.
- **B (turnkey, ST-proven): `stedgeai validate --mode target --desc serial:921600`.** Build ST's
  NPU_Validation firmware (heavy: BSP+HAL+USBX+ATON) + CM55_loader to flash, measure over serial.
  More integration + a full flash/boot flow, but ST-maintained.

## Board actions required from the user (when we deploy)
1. Set the DK BOOT switch to the mode that lets the ST-LINK program external flash (one-time).
2. Approve the CubeProgrammer external-flash write of `ids_atonbuf.xSPI2.raw` to **0x71000000**
   (`STM32_Programmer_CLI -c port=SWD mode=HOTPLUG -el MX66UW1G45G_STM32N6570-DK.stldr -w ids_atonbuf.xSPI2.raw 0x71000000`).
(As before, I arm the pyOCD watcher first; a takeover replug may also be needed.)

## Known risks (max-rigor review, unverified until on-board)
1. **Activation alias (secure vs non-secure).** The pool places activations at the SECURE aliases
   0x34100000 / 0x34200000 to match the NPU being configured as a secure master (NPU_Config sets
   CID=1, secure+priv). ST's example used the NON-secure aliases (0x24…). Same physical SRAM, but
   this pairing is untested — if the NPU bus-faults on activations, switch the pool to 0x24… and/or
   revisit RISAF/RIF. Decide by testing both on-board.
2. **Path A is unproven.** Reusing ST's init inside the pyOCD harness assumes the ATON runtime does
   not require a fuller HAL/BSP init than NPU_Config/RISAF_Config/npu_cache provide. If it does,
   fall back to path B (NPU_Validation + `validate --mode target`), which is ST-maintained.
3. **ATON runtime ABI.** `NetworkRuntime1100_CM55_GCC.a` is prebuilt (≈gcc 12.3). Linking with the
   arm-gcc 13.2 here must use identical `-mcpu=cortex-m55 -mfloat-abi=hard -mfpu=auto`; a mismatch
   fails at link. Verify with a link smoke-test before trusting path A.
4. **Weights are external-flash-only** (ST constraint) — so a no-flash RAM-only NPU run is not
   possible; the flash+BOOT board step is mandatory for B2.

## Status: artifacts ready; firmware integration (path A) + flashing (board) remain.

## Deep adversarial review (2026-09-19, before firmware assembly)
- **DC7 (REAL BUG, fixed above):** generated ids.c expects weights at **0x71000000**, not
  0x70000000. Flashing to the wrong address = NPU reads garbage. All references corrected.
- **DC9 (cleared):** the 0x90000000 (PSRAM) references in ids.c are pool-descriptor **comments**,
  not accesses. The real activation buffer is 128 B at 0x342e0000 (AXISRAM5). No PSRAM init needed.
- **DC8:** `NPU_Config`/`RISAF_Config`/`set_risaf_default`/`get_risaf_max_addr` are HAL-only
  (HAL_RIF/RCC/CACHEAXI) — but `misc_toolbox.c` also carries UART/BSP/app_config deps, so EXTRACT
  just those four functions into an own file; do NOT compile misc_toolbox.c whole.
- **DC6 (verified):** ELF and the runtime .a share the hard-float VFP ABI + MVE (cortex-m55,
  v8.1-M); 5 .a objects are MVE-integer-only (a compatible subset). No silent hard/soft mismatch.
- **DC5 (build):** only the Devices/*.c (npu_cache, mcu_cache) need `-include stm32n6xx_hal.h`;
  the ATON runtime + model sources compile without it, so scope `-include` to those files only.
- **DC2 (residual):** the ATON runtime is table-driven; use `--gc-sections` cautiously in the
  deployable firmware (KEEP the runtime/operator sections) so live-via-pointer code is not dropped.
- **R-c (refined):** code must be linked clear of ALL declared pool regions (activation at
  0x342e0000). Put firmware code in SRAM1 (0x34064000); activations SRAM (per pool); weights XSPI2.

## Online research — the ST-CORRECT deployment method (2026-09-19)
Per ST docs (stneuralart_getting_started, stneuralart_reloc_mode):
- **DEV boot mode = BOOT1 switch position 1-3** (BOOT0 doesn't matter). In DEV mode the BootROM
  waits — no OOB demo runs — which ALSO fixes the earlier debug-sleep/watchdog problem. Board must
  NOT be powered off/disconnected after loading (to keep performing validations).
- **Weights at 0x71000000** (default `--address 0x71000000,0x71800000`); the first 1 MB (0x70000000)
  is the application region. Confirms DC7.
- **The ST-supported path is "runtime loadable (reloc) model" + a delivered DEV-mode environment**
  for the STM32N6570-DK, driven by `stedgeai validate --mode target`, which measures on-board
  latency directly. AI RAM regions are reserved and "must not be used by the application during
  inference" (confirms R-c: code in AXISRAM1/2, activations in NPURAM AXISRAM3-6).

## Revised recommendation
**Path B (ST DEV-mode reloc + `validate --mode target`) is the correct, lower-risk method** — ST
maintains the NPU init/RISAF/cache/boot. Path A (custom pyOCD firmware, link smoke-test PASSED) is
a valid lighter alternative but hand-rolls that init. Proceed with Path B for the first measurement;
keep Path A as a fallback / for a custom in-line-system app later. Both need BOOT1 dev mode +
weights flashed to 0x71000000 (a one-time board action).
