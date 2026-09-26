# Secure SRAM-only N6 platform recipe — read-only design review

2026-09-25. No target, USB, power, compiler, model, flash, XSPI, OTP or watchdog operation was performed. This is an implementable **candidate**, not hardware acceptance. Existing firmware and vendor artifacts remain unchanged.

## Selected profile and prerequisites

Use the repository HAL/LL **1.4.0** and its matching CMSIS definitions, not the installed ST example's HAL **0.5.0**. A small secure privileged SRAM stage should establish clocks/memory/access, then publish register readbacks and wait for the loader. Only after that should the host load and byte-verify weights/activations/adapter. Do not power down/reset RAM after loading it.

Logical layout from both the CMSIS header and installed compiler memory pool:

| Object | Inclusive range | Scope |
|---|---|---|
| CPU adapter | starts `0x34064000` | AXISRAM1; exact end must come from its new ELF/linker manifest |
| Reserved weights | `0x34200000–0x3423ffff` | 256 KiB, inside AXISRAM3 |
| Reserved activations | `0x34240000–0x34243fff` | 16 KiB, inside AXISRAM3 |
| AXISRAM3 logical bank | `0x34200000–0x3426ffff` | 448 KiB |

The proposed allocations do not need XSPI. This does **not** substitute the old `0x71000000` binary: the new generated model, weight bytes, pool map and adapter must be bound together. Stage code/stack/mailbox must be disjoint from all these ranges.

Before changing registers, require an explicitly established secure privileged entry and quiescent exclusive target, retain CONTROL/IPSR/PRIMASK, RCC, PWR status, MPU/SAU and cache state, and RIF configuration/error registers. Compile-time `CPU_IN_SECURE_STATE` is not evidence of actual entry state. Enable CP10/CP11 before any hard-float C/library code. The loader must establish CPU I/D-cache-off **before** writing executable/data payloads; do not clean unknown dirty cache lines onto newly loaded bytes. Reject an incompatible MPU/SAU or locked RIF profile; do not silently dismantle it.

BootROM state is not a universal reset-state guarantee: its MPU/SAU/cache and clock configuration varies with lifecycle/boot mode. Preserve regulator settings, factory oscillator trim and security lifecycle; software register readback cannot establish physical rail voltage. [ST BootROM manual](https://www.st.com/resource/en/user_manual/um3234-how-to-proceed-with-boot-rom-on-stm32n6-mcus-stmicroelectronics.pdf).

## Clock recipe: HSI, no overdrive or PLL reprogramming

Use HSI for CPU and all system clocks. Keep the existing HSI divider unchanged: accept a reviewed DIV1 or DIV2 entry profile, giving nominal 64 or 32 MHz CPU/NPU/NPU-RAM respectively; use HCLK divide-by-two and APB1/2/4/5 divide-by-one. Record which profile was observed. This refines the earlier DIV1-only suggestion: it need not reject a legitimate DIV2 development entry or change the input of a running PLL. Other divider profiles are an explicit preflight refusal, not an invitation to rewrite HSI.

HSI is nominally 64 MHz; ST also uses HSI as the transition clock before voltage changes. This candidate performs **no** voltage transition or PWR/SMPS/OTP write. The reported MHz values are derived nominal values, not measurements. [ST AN5967](https://www.st.com/resource/en/application_note/an5967-getting-started-with-hardware-development-for-stm32n6-mcus-stmicroelectronics.pdf), [ST AN6000](https://www.st.com/resource/en/application_note/an6000-how-to-build-the-discrete-power-supply-for-stm32n6-mcus-stmicroelectronics.pdf).

Implement with the pinned LL definitions, not `HAL_RCC_ClockConfig`, `HAL_Init` or `HAL_Delay`: those HAL paths use a tick timebase inappropriate with interrupts masked. Below is the C operation sequence; `REQUIRE`/`WAIT` must record the failed stage and stop without continuing. `WAIT` is a finite volatile-MMIO iteration budget (for example 1,000,000), **not** a claimed millisecond timeout. No SysTick interrupt, WFI or WFE is needed.

```c
uint32_t hsidiv = LL_RCC_HSI_GetDivider();
REQUIRE(hsidiv == LL_RCC_HSI_DIV_1 || hsidiv == LL_RCC_HSI_DIV_2);
LL_RCC_HSI_Enable();
WAIT(LL_RCC_HSI_IsReady() != 0);
LL_RCC_SetCpuClkSource(LL_RCC_CPU_CLKSOURCE_HSI);
WAIT(LL_RCC_GetCpuClkSource() == LL_RCC_CPU_CLKSOURCE_STATUS_HSI);
LL_RCC_SetSysClkSource(LL_RCC_SYS_CLKSOURCE_HSI);
WAIT(LL_RCC_GetSysClkSource() == LL_RCC_SYS_CLKSOURCE_STATUS_HSI);
/* Only lower/normalize bus rates after switching away from faster sources. */
LL_RCC_SetAHBPrescaler(LL_RCC_AHB_DIV_2);
LL_RCC_SetAPB1Prescaler(LL_RCC_APB1_DIV_1);
LL_RCC_SetAPB2Prescaler(LL_RCC_APB2_DIV_1);
LL_RCC_SetAPB4Prescaler(LL_RCC_APB4_DIV_1);
LL_RCC_SetAPB5Prescaler(LL_RCC_APB5_DIV_1);
__DSB(); __ISB();
/* Require all six source/divider readbacks, plus unchanged hsidiv. */
```

Keep NPU quiescent/in reset during this sequence. Do not call the old example's `ResetClocks()` (broad memory/XSPI changes) or its higher-frequency PLL recipes. `HAL_RCC_GetNPUClockFreq` and `GetNPURAMSClockFreq` source confirm SYSCLK=HSI selects the divided HSI directly, rather than the IC6/IC11 PLL path. Preserve inactive PLL configuration; disabling unused PLLs is not needed for this first bounded stage.

## RIF, SRAM and cache operation sequence

1. Enable RIFSC, RISAF and RAMCFG control clocks using `__HAL_RCC_RIFSC_CLK_ENABLE()`, `__HAL_RCC_RISAF_CLK_ENABLE()`, `__HAL_RCC_RAMCFG_CLK_ENABLE()`; read back their AHB enable bits. Capture RISC/RIMC locks and NPU peripheral lock before attempted configuration.
2. Adopt a narrow **default-filter profile**: read all valid base-region configurations for RISAF2/3 (7 each, CPU RAM) and RISAF4/5/6 (11 each, NPU entry ports), and reject any enabled base/subregion unless separately reviewed. Do not clear unexpected configuration or locks. Unconfigured RISAF permits secure privileged CID1; CPU CID is fixed at 1. This is sufficient for the chosen single secure-domain candidate, not a new multi-tenant isolation policy. If explicit NPU partitions are later needed, all three RISAF4/5/6 must agree; setting only RISAF6 is not correct. [ST RIF overview](https://wiki.st.com/stm32mcu/wiki/Security%3AResource_Isolation_Framework_%28RIF%29_overview_for_STM32N6).
3. Set NPU slave secure+privileged, then NPU master secure+privileged CID1, using the following pinned HAL operations. `RIF_CID_1` is a whitelist mask (`2`), **not** the raw MCID field value (`1`). These setters return void; exact readback is mandatory. If already correctly configured and locked, retain the state without trying to rewrite; if incompatible and locked, stop.

```c
HAL_RIF_RISC_SetSlaveSecureAttributes(RIF_RISC_PERIPH_INDEX_NPU,
                                     RIF_ATTRIBUTE_SEC | RIF_ATTRIBUTE_PRIV);
RIMC_MasterConfig_t npu = {
  .MasterCID = RIF_CID_1,
  .SecPriv = RIF_ATTRIBUTE_SEC | RIF_ATTRIBUTE_PRIV
};
HAL_RIF_RIMC_ConfigMasterAttributes(RIF_MASTER_INDEX_NPU, &npu);
/* Getter + register readback: NPU SEC/PRIV bits both set,
   RIMC_ATTRx[1] & 0x370 == 0x310. No DAPCID or global-lock writes. */
__HAL_RCC_NPU_CLK_ENABLE();
__HAL_RCC_NPU_FORCE_RESET();
/* Check NPU enable and reset readbacks before proceeding. */
```

NPU master secure attribution requires the NPU peripheral's slave secure attribution too; changing only MCID/MSEC is insufficient. [ST Neural-ART project guidance](https://stedgeai-dc.st.com/assets/embedded-docs/2.0.0/stneuralart_stm32n6_projects.html).

4. Enable AXISRAM3's memory clock and power before any weight loading:

```c
__HAL_RCC_AXISRAM3_MEM_CLK_ENABLE();
RAMCFG_HandleTypeDef ram3 = { .Instance = RAMCFG_SRAM3_AXI };
HAL_RAMCFG_EnableAXISRAM(&ram3); /* clears CR.SRAMSD; no erase/ECC-key write */
__DSB();
REQUIRE((RCC->MEMENR & RCC_MEMENR_AXISRAM3EN) != 0);
REQUIRE((RAMCFG_SRAM3_AXI->CR & RAMCFG_CR_SRAMSD) == 0);
```

The minimal logical allocation uses only AXISRAM3; this is not a measured power-optimal configuration. ST describes NPU RAM as interleaved/remapped across cuts. Therefore do not extrapolate from the logical address range to a proven physical bank power isolation claim: the first actual NPU access/readback remains a separate validation. Existing states of SRAM4–6 should be recorded and left unchanged; if the implementation instead enables all four for conservative bring-up, declare that larger power profile explicitly. No shutdown operation is part of this recipe.

5. With NPU held reset and no outstanding traffic, enable CACHEAXI control clock, force then release only CACHEAXI reset, and require `CACHEAXI->CR1 & CACHEAXI_CR1_EN == 0`. Retain CPU cache-off state. Do not call `npu_cache_init/enable` or rely on `npu_cache_disable`: its static handle may still be null, making it a no-op even if hardware was previously enabled. Reject incompatible RISAF15 cache-control protection instead of opening it broadly. Record/cache-check again before inference handoff. No external memory cache is needed for this SRAM-only layout.
6. After the reviewed clock, RIF, RAM and cache checks, release NPU reset, perform DSB/ISB, and read back enable/reset/security state. Preserve initial and final RISAF/IAC error status without silently clearing history. Publish READY_FOR_PAYLOAD plus these records; this must not mean NPU inference or board-power acceptance. Host then loads exact bytes and readbacks while CPU remains in the stage's command loop.

## Exact register checks (secure aliases, pinned CMSIS)

| Register | Address / mask | Expected check |
|---|---|---|
| RCC CR / SR | `0x56028000` / `0x56028004`, HSI bit 3 | enable/ready |
| RCC CFGR1 / CFGR2 | `0x56028020` / `0x56028024` | CPUSWS and SYSSWS both HSI; selected divisors |
| RCC HSICFGR | `0x56028048`, HSIDIV mask `0x180` | unchanged DIV1=`0`, DIV2=`0x80` |
| RCC MEMENR | `0x5602824c`, bit 0 | AXISRAM3 clock |
| RCC AHB2ENR / AHB3ENR | `0x56028254` bit12 / `0x56028258` bits9,14 | RAMCFG / RIFSC,RISAF control clocks |
| RCC AHB5ENR / AHB5RSTR | `0x56028260` / `0x56028220`, bits31,30 | NPU / CACHEAXI clock/reset |
| RAMCFG SRAM3 CR | `0x52023100`, bit20 | SRAMSD clear |
| RIFSC NPU slave SEC / PRIV | `0x5402401c` / `0x5402403c`, bit10 | both set |
| RIFSC NPU slave lock | `0x5402405c`, bit10 | inspect, never clear |
| RIFSC NPU master attrs | `0x54024c14`, mask `0x370` | `0x310` (CID1, secure, privileged) |
| RIFSC master global lock | `0x54024c00`, bit0 | inspect, never set/clear |
| RISAF2 / 3 / 4 / 5 / 6 | `0x54027000/28000/29000/2a000/2b000` | each base region starts +`0x40`, stride `0x40`; BREN bit0 |
| CACHEAXI CR1 | `0x580dfc00`, bit0 | disabled |
| NPU base | `0x580e0000` | not permission to launch an inference |

Prefer macros over these literals in C. Readbacks must cover the original register mask, not accidentally read the write-only SET/CLEAR alias. RISAF15 (cache-control filter) is `0x54034000`; its two valid base regions require compatible access. If cache RAM itself is accessed, RISAF8 (`0x5402d000`, seven regions) also needs review; the cache-off candidate does not use that RAM.

## Polling and remaining blockers

Compile the *new* adapter with `LL_ATON_RT_MODE=LL_ATON_RT_POLLING`, retain SW fallback, and do not emit IRQ-dependent WFE. The existing runtime's polling path calls `LL_Streng_Wait`/`LL_EpochCtrl_Wait`; selecting POLLING alone does **not** prove bounded runtime completion. Inspect its software watchdog/timebase implementation before actual inference: no hardware-watchdog writes are allowed, and a disabled/assert-elided timeout can hang. The initialization loops above can be independently bounded without SysTick. An external host timeout is a recovery observation, not proof that the target ceased execution.

There is presently no verified secure-entry/lifecycle/register snapshot, SRAM3 load/readback, RIF access, clock frequency, supply qualification, or NPU result. BootROM does not supply those facts by assumption. The unresolved physical supply/protection observations cannot be repaired or certified by this software recipe. No ON/retry/hardware action is authorized by this note.

## Current local source bindings

`HAL` below is `/home/thc1006/dev/SpikeIDS-MCU/firmware/n6/third_party/stm32n6xx-hal-driver`; `ST` is `/home/thc1006/opt/stedgeai/3.0`. Local read/hash commands completed with observed exits 0 (including `83ac4c`, `03d8ae`, `849228`); a lookup of a nonexistent old HAL path was corrected to `Applications/Drivers` and was not treated as evidence. No compile was attempted.

| Path | SHA-256 |
|---|---|
| `HAL/Inc/stm32n6xx_hal.h` (1.4.0) | `0bc08f69f86161be2d8bbdf123cf57aef4411286471892fb7c17131cd63f2a32` |
| `HAL/Inc/stm32n6xx_hal_rcc.h` | `a8b12df9bd695a8c9c8ff2b13f7d510ee44ead82260b635190d9436523ff67c6` |
| `HAL/Inc/stm32n6xx_ll_rcc.h` | `266f62d888a25022f7015c6694219a6f1e9dca671b6eb5578e2ba33166dc647e` |
| `HAL/Src/stm32n6xx_hal_rcc.c` | `88b27154fd077b8ca39964e49ce616735f98ba6415d6f19c17982c9900c4b4d5` |
| `HAL/Inc/stm32n6xx_hal_rif.h` | `ef9dd9ded93bc4256f5959776e91dfdf61b00fd7d9fc512762ea56fd93c6e29b` |
| `HAL/Src/stm32n6xx_hal_rif.c` | `c9fe5495e56cb75ec080f9a1e7a4683c6b87a340eb139639486b9ed84a8ad4e0` |
| `HAL/Src/stm32n6xx_hal_ramcfg.c` | `06c5b2f3db5cae3a0d9c7eccbd0e2a238a7d8301ddcb876404971aa8b4faa39b` |
| `firmware/n6/third_party/cmsis-device-n6/Include/stm32n657xx.h` | `559792ea50e7253ddb386bd77267e475c7f5ecbccfc917adeea9398ef3aaa689` |
| `ST/Projects/STM32N6570-DK/Applications/Drivers/STM32N6xx_HAL_Driver/Inc/stm32n6xx_hal.h` (0.5.0) | `9e1dfe1625670f2df205e573142d63ac99a33a1ac406b62ad45b979f5eda9b76` |
| `ST/Projects/STM32N6570-DK/Applications/NPU_Validation/Core/Src/system_clock_config.c` | `0386f0c53216301830bdec788a019e7b30617f4bdee46a091cf6b9d0d2ad4540` |
| `ST/Middlewares/ST/AI/Npu/Devices/STM32N6xx/npu_cache.c` | `5479b1d72134b61c61b2c0610825ed692515e911f3455b073c78f02d48400f35` |
| `ST/Middlewares/ST/AI/Npu/ll_aton/ll_aton_runtime.c` | `198a0a536e9db7427511ab41b95462c94caea07c47241840354e3ab7a259462d` |
| `ST/Middlewares/ST/AI/Npu/ll_aton/ll_aton.c` | `9cdd88f5ac450c65a48e164608b59ca215df3dd3afe74fd4572ebbe5b7b7f7e2` |
| `ST/Utilities/linux/targets/stm32/resources/NPU/STM32N6xx/stm32n6.mpool` | `85cbb7205023b482f1ae640fd0c02d6ccf9574ca4bf05abbe6640bf6a69acb49` |
