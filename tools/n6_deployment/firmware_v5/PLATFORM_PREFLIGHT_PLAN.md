# N6 platform preflight — read-only design, not bringup acceptance

2026-09-25. Scope: local installed ST sources, frozen firmware sources/map and
official documentation only. No compiler, loader, USB, serial, power, flash,
target memory access or model execution was invoked. This author also authored
the v5 adapter; this is platform-path research, not independent firmware approval.
Parent reports LD3 solid red and an overcurrent-protection investigation; that
hardware observation was not independently measured here. No further power or
hardware retry is proposed before that separate electrical issue is resolved.

## Result

There is **no reviewed drop-in platform loader for the frozen v5 ELF** among the
paths inspected. Installed ST examples contain the needed initialization logic,
but their entry addresses, board revisions, cache policy and side effects do not
match the v5 handoff contract. In particular, do not run an unreviewed official
example merely because it is named FSBL or NPU_Validation.

The narrow next software deliverable would be a separately reviewed, additive
secure RAM platform stage and explicit handoff record. This note neither
implements it nor authorizes its execution. Board readiness, numerical parity,
energy acceptance and deployment acceptance remain false.

## Existing paths and versions

Path prefixes used below expand exactly to:

- `ST` = `/home/thc1006/opt/stedgeai/3.0`
- `APP` = `ST/Projects/STM32N6570-DK/Applications`
- `REPO` = `/home/thc1006/dev/SpikeIDS-MCU`
- `CP` = `/home/thc1006/opt/STMicroelectronics/STM32CubeProgrammer`

Saved vendor `version.stdout` reports ST Edge AI Core **v3.0.0-20426**, build
123672867, STM32CubeAI **11.0.0-RC6**. This is not version 4. Installed APP HAL
header declares **0.5.0** and DK BSP header **0.5.1**; the frozen firmware actually
compiled against REPO HAL **1.4.0**, so old initialization code/API names cannot be
silently mixed into that build. `CP/bin/version` reports **2.23.0**; its CLI was
not invoked. No complete separately versioned STM32Cube_FW_N6 package was
established by this bounded inspection: these are ST Edge AI bundled examples,
not a claim that all current CubeN6 templates are locally installed.

Relevant boot paths:

- `APP/SNS/FSBL/Src/main.c`: power/voltage, clock, XSPI2, ExtMem, then
  `BOOT_Application`. Its **actual selected configuration is XIP**, because
  `FSBL/Inc/stm32_extmem_conf.h` includes `stm32_boot_xip.h` and specifies NOR
  offset `0x00100000` plus header `0x400`: vector at **0x70100400**, not v5
  **0x34064000**. The co-located `stm32_boot_lrun.c` is an alternate source, not
  evidence that LRUN is selected. The CubeIDE FSBL linker starts at
  **0x34180400**, length 511 KiB. These paths must not be interchanged.
- `APP/Drivers/CMSIS/Device/ST/STM32N6xx/Source/Templates/system_stm32n6xx_fsbl.c`
  explicitly targets secure startup after BootROM; security isolation setup is
  conditional on `USER_TZ_SAU_SETUP`, not automatically complete.
- `APP/NPU_Validation/armgcc/STM32N657xx.ld` uses **0x34000000**, 1 MiB RAM;
  its `set_vector_table_addr` also uses that address. It overlaps the v5 image,
  stack and mailbox domain: do not leave this application resident as a loader.
- `ST/scripts/N6_scripts/n6_loader.py` is an orchestration script which copies
  network files, converts memory images, builds and invokes target tools; it
  is not a read-only or v5-safe loader and was only read, not imported.
- `CP/bin/ExternalLoader/MX66UW1G45G_STM32N6570-DK.stldr` exists. It is a flash
  programming loader, not proof of runtime XSPI mapping after exit/reset or a
  suitable v5 boot image. The separate `OTP_FUSES_STM32N6xx.stldr` is out of scope.

ST documentation distinguishes LRUN (copy application into SRAM) from XIP
(execute from mapped external memory), and says the application inherits clock
and MPU settings while level-1 caches are disabled before handoff. These are
architecture descriptions, not evidence of this board's state.
[ST UM3249, sections 4.2.1 and 5.3.1](https://www.st.com/resource/en/user_manual/um3249-getting-started-with-stm32cuben6-for-stm32n6-series-stmicroelectronics.pdf).
BootROM also handles lifecycle/security and developer mode; RAM loading must
respect the actual lifecycle/debug configuration, never change fuses to bypass
it. [ST BootROM overview](https://wiki.st.com/stm32mcu/wiki/Security:BootRom_for_STM32N6).

## Initialization gap and prohibited shortcuts

| Domain | Installed source evidence | v5 prerequisite / remaining gap |
| --- | --- | --- |
| Power and clock | NPU_Validation `main.c:58` resets clocks; `app_config.h:29` defaults to overdrive; `misc_toolbox.c:163` changes SMPS voltage according to board revision | No measured voltage/clock exists. Do not assume 800 MHz, select overdrive, or change SMPS while supply fault remains unresolved. Pin board revision and a supported non-overdrive clock/power design before implementing anything. |
| SRAM | `misc_toolbox.c:339` enables AXISRAM3–6/CACHEAXI RAM and removes RAM shutdown | Prove executable/data RAM, stack/mailbox and activation `0x342e0000..0x342e0800` are powered, accessible and nonoverlapping with platform-stage state. Linker assertions alone do not initialize RAM. |
| NPU and cache | `misc_toolbox.c:266` enables/resets NPU, initializes cache, assigns secure privileged CID1 | v5 does not call this. In installed `npu_cache.c`, board clock/reset hooks are weak no-ops unless overridden. Its functions are discarded from the current ELF map; compiling the file or defining USE_NPU_CACHE is not evidence of initialization. Generated weights are marked cacheable. A deliberate CACHEAXI state/coherency contract is required. |
| RIF/RISAF | `misc_toolbox.c:292` configures RAM, NPU masters, cache and XSPI domains; `set_risaf_default:53` grants every CID read/write in overlapping secure and nonsecure regions | Do not transplant this blanket policy or legacy `firmware/n6b/src/npu_init.c`. Derive only required secure CPU/NPU accesses to code/data, activations, cache and read-only weights; account for locks and read back actual configuration. |
| XSPI2 | `main.c:111` initializes DK NOR through BSP in octal DTR and enables mapped mode; `stm32n6570_discovery_xspi.c:335` selects XSPI2 | v5 needs exact raw weights at `0x71000000` (NOR offset 16 MiB), length 145457 bytes; ELF does not contain them. Need correct board/flash identity, reviewed XSPI clock/pin/voltage setup, mapped readback hash and no overlap with existing flash contents. A debugger external-loader operation does not establish persistent mapping. |
| CPU cache / handoff | Official FSBL disables I/D caches before jump; its jump sets VTOR/MSP and clears MSPLIM | v5 already establishes MSP/CPACR before C and masks IRQs, but inherits MPU/SAU/security state. Dirty caches must be handled before loading/acknowledging; CPU D-cache must remain off for this mailbox protocol. Platform initialization needing HAL SysTick/timeouts cannot simply be pasted after v5 masks all IRQs. |

**Never invoke the following without a separate, explicit review/authority:**

- NPU_Validation `main.c:94` calls `fuse_vddio` on the DK/Nucleo build path;
  `misc_toolbox.c:70–112` can execute **HAL_BSEC_OTP_Program** on OTP word 124,
  bits 15/16. SNS FSBL `main.c:93` calls `OTP_Config` unless `NO_OTP_FUSE` is set;
  that routine can execute **HAL_BSEC_ProgramOTPFuse**. These are irreversible
  writes, not harmless initialization. Compile-time suppression alone is not a
  reviewed replacement for required pad-voltage constraints.
- NPU_Validation also enables PSRAM and writes **16 MiB at 0x90000000** as a
  memory test. Do not execute this test or initialize unused PSRAM for this model.
- No blanket security opening, watchdog disabling, exception-skip recovery,
  OTP/lifecycle change, stock example flash, old CAN image, or automatic retry.

## Minimum staged bringup proposal (not executed or accepted)

1. Resolve the separate supply/LD3 issue, record exact board revision and safe
   power/cable topology. No software claim here diagnoses the overcurrent cause.
2. Offline, define an additive secure RAM platform-stage memory map and bounded
   initialization state machine. Reconcile HAL 0.5 examples with the pinned 1.4
   headers. Review call graph for zero OTP/flash-write/unused-PSRAM paths and
   bounded waits. Preserve frozen v5 source/ELF/model; use a new artifact if any
   adapter change becomes necessary.
3. Only in a later authorized hardware phase, establish actual debug/lifecycle
   state and RAM entry conditions without altering lifecycle or fuses. First
   demonstrate a non-inference ready/heartbeat/fault record; use independent host
   timeout. Record clock, RAM, security, cache and XSPI readbacks before handing
   off. Do not let a bare `platform_ack` substitute for this evidence.
4. Before inference, load the exact initialized ELF segments and verify their
   target bytes plus the exact 145457-byte weight range. Any flash programming
   requires its own explicit range/backup/erase-sector review; never automatically
   overwrite flash merely because the weights are absent. Verify the mailbox
   WAIT_PLATFORM state, exact memory pointers and all initialization statuses.
5. Once those gates pass, separately review one-request transport/status smoke,
   then all 1024 fixed validation vectors against the existing QDQ CPU reference,
   preserving all five logits and raw error/status records. No label-based
   selection or changing thresholds. Only after parity and deterministic run
   boundaries are established should triggers/timing/PPK2 energy be accepted.

Unknowns remain actual board revision/lifecycle, protection locks, NOR contents,
power rails, watchdog state, accessible SRAM, effective clocks, cache state and
real runtime completion. DWT remains a 32-bit wrap-prone diagnostic, not a proven
timebase. None can be inferred from successful host linking or no-load current.

## Exact local evidence hashes

Read-only SHA collection `fb9805`, exit 0; supplemental collection `243f29`, exit 0.
These are ordinary local file hashes, not authenticated package signatures or
hardware attestation. Paths use the exact prefixes above.

```text
c20227f061dd5aed9f1a92730e52e54796648f8712a683e49df754c4b3dccef9 APP/NPU_Validation/Core/Src/main.c
ac4b11921f09041448f1313af4f472d677af2dd8a9739b31875cc9c12ba4cf7a APP/NPU_Validation/Core/Src/misc_toolbox.c
0386f0c53216301830bdec788a019e7b30617f4bdee46a091cf6b9d0d2ad4540 APP/NPU_Validation/Core/Src/system_clock_config.c
23e4aedfe69f4209265e1159147ac40913b63b0fc69db7927b711bbf61d30504 APP/NPU_Validation/Core/Inc/app_config.h
de5424887dc7dc73e23caa5e1e463d830df8f681a02f206b6120e25d4d12b078 APP/NPU_Validation/armgcc/mk/N6-DK.mk
0759682827709a8734bc4f50df9e13ae25a8e3dbb77d1693e522d0aaaafdb677 APP/NPU_Validation/armgcc/STM32N657xx.ld
180b30dd083e028a1ee8869a2e4ee4ec143fd46d64e9b8e7c7db4264c94c9990 APP/SNS/FSBL/Src/main.c
d2907f7bf8f6868a010d9d735c8da2f0fe637b224d29c46f18b494128bfab9d1 APP/SNS/FSBL/Inc/stm32_extmem_conf.h
321e6275ad1fdbdc8b22b8f6ab0df2e39d022e7a68e45fa63cfd982a6de7da0c APP/SNS/cubeIDE/FSBL/STM32N657X0HXQ_RAM.ld
f23a59c1bd3674712a42b5dc2fc12a0110ec13a965ba18f71b5915110e92d263 APP/SNS/Middlewares/ST/STM32_ExtMem_Manager/boot/stm32_boot_xip.c
b3952e85e80c65cb17e8df653e7ac4960348bbc57f79373fd56008593259d889 APP/SNS/Middlewares/ST/STM32_ExtMem_Manager/boot/stm32_boot_lrun.c
a186cd2549a120f35c001bae4eaccf39c67c160b5d5dd5abf9b868c9c06405dc APP/Drivers/CMSIS/Device/ST/STM32N6xx/Source/Templates/system_stm32n6xx_fsbl.c
c6b3b9c9d6db0221562dd25d353ab1b3c2361964a63567ce48ac1cb5e6f4ff80 APP/Drivers/BSP/STM32N6570-DK/stm32n6570_discovery_xspi.c
d8cd1ec3756229de0a2c77be89367654fa614b4110fa66f49a57d54bc5e3fefc APP/Drivers/BSP/STM32N6570-DK/stm32n6570_discovery.h
9e1dfe1625670f2df205e573142d63ac99a33a1ac406b62ad45b979f5eda9b76 APP/Drivers/STM32N6xx_HAL_Driver/Inc/stm32n6xx_hal.h
5479b1d72134b61c61b2c0610825ed692515e911f3455b073c78f02d48400f35 ST/Middlewares/ST/AI/Npu/Devices/STM32N6xx/npu_cache.c
4c9f184d50f0241eb503aff97fe698ca89cb0a66f2115eee798bdb491eacb704 ST/scripts/N6_scripts/n6_loader.py
579c058e1ec7bd869f31186152dcce04324a5db3e6b81ec599f159ad3e1c3070 CP/bin/version
2be68eb7f9f02e348c29306280c535ec2573ec9e49b090dcf06fadff4a717755 CP/bin/ExternalLoader/MX66UW1G45G_STM32N6570-DK.stldr
0bc08f69f86161be2d8bbdf123cf57aef4411286471892fb7c17131cd63f2a32 REPO/firmware/n6/third_party/stm32n6xx-hal-driver/Inc/stm32n6xx_hal.h
452a79e261c17326e38ca70c951e9737e92f441315ae57e643c89e83c05344da REPO/firmware/n6b/src/npu_init.c
a1a0c7535af68a4a80ef6f9863af901ffb6a6f7024b46946014b692a02fab00b REPO/results/ppk2_n6_bringup_20260925_nAivHM/vendor_actual_01/version.stdout
```

Frozen baseline rechecked in `fb9805 / 0`: build03 RESULT whole
`3d4495b676421e56d4b30dd4e47c1fe9f9d052348a2b124102fa3e30b373021e`
and all seven authored source hashes still match BUILD_ACTUAL_03_EXECUTION.json.
This note is the only newly written file. No full research-archive revalidation
or whole-host inventory claim is made.
