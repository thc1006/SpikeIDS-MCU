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
- `model/ids_atonbuf.xSPI2.raw` — 7,761 B weights → flash at 0x70000000.
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
2. Approve the CubeProgrammer external-flash write of `ids_atonbuf.xSPI2.raw` to 0x70000000.
(As before, I arm the pyOCD watcher first; a takeover replug may also be needed.)

## Status: artifacts ready; firmware integration (path A) + flashing (board) remain.
