# Secure SRAM-only platform stage (offline candidate)

This is a new initialization stage, not a modified frozen firmware or a model inference. It has a portable, host-tested MMIO sequence plus real Cortex-M55 startup/main/linker sources. The target callback executes DSB/ISB; an SWD transfer flush is not a substitute.

Entry requires externally established secure privileged Thread/MSP execution and exclusive target ownership. The startup refuses other Thread/privilege/SP states, masks IRQ, selects its own stack/vector table, and never calls SystemInit/HAL_Init. The software-only build uses soft/general-register-only flags; no FP/MVE enabling is needed for this stage. A later hard-float adapter has its own earlier CP10/CP11 requirement.

The runtime requires CPU I/D cache off, MPU disabled and SAU disabled/ALLNS clear. These are intentionally narrow admission conditions: incompatible inherited state yields REJECTED, not automatic reconfiguration. The RIF default-profile check refuses active regions and historical access-error status. Clocks use unchanged HSI DIV1/DIV2, nominal CPU/NPU/RAM 64/32 MHz; HCLK is half this and APB clocks equal HCLK. It powers AXISRAM3, assigns NPU secure privileged CID1, holds/releases NPU reset, resets CACHEAXI to cache-off and retains exact MMIO readbacks. RCC clocks/resets/HSI use their SET/CLEAR aliases, with readback from status registers.

The source does not alter PWR, PLLs, HSI divider/trim, XSPI, flash, OTP, hardware watchdog, RIF/DAP locks or debug configuration. It never writes weights, starts a model, enables IRQ, or reports energy/board acceptance. Initialization timeout is 65,536 read iterations per wait, not a calibrated time. It may leave partial initialization on rejection; it does not promise rollback or electrical shutdown.

ABI: code `0x34180400–0x34187fff`, mailbox `0x34188000–0x34188fff`, stack `0x34189000–0x3418afff`. This is separate from the old probe mailbox and the new adapter/weights/activations. `ABI.json` describes the 4096-byte mailbox. The only host-owned field after initial target clearing is the 4-byte nonce at offset 24. Wait for a stable even READY/REJECTED snapshot before issuing a fresh nonzero nonce; require changed heartbeat and its echo. Publications are event-driven: READY sequence 2 stays stable until a fresh nonce, and heartbeat counts processed nonce changes rather than periodic time. This permits a slow SWD reader to obtain a stable 4 KiB snapshot. READY means finite initialization readbacks passed, **not** NPU execution, memory payload validation or safe power. FAULT/REJECTED must never authorize a model launch. The stage does not launch one itself.

Root prereview required NPU reset assertion/readback **before** NPU security-attribution writes; this ordering is now explicit and tested. Only RISAF IASR error registers are retained, not the separate global IAC register bank; this implementation does not claim global IAC capture. The recipe's broader diagnostic suggestion remains a future addition, not an implemented guarantee.

Offline author test:

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --no-project --offline --python /usr/bin/python3 python tools/n6_deployment/platform_stage/test_platform_init.py
```

This compiles only `platform_init.c` for the host and executes it against synthetic MMIO, including read-only RCC status / SET/CLEAR alias semantics. It does not compile ARM startup or prove chip behavior. The first test run `cbdb89` exited 1 with two test/ABI entry mistakes (wrong decimal JSON addresses; incorrect synthetic divider bits). They were corrected, and `bcd53b` exited 0 with 12 tests and all source/test bookends equal. No target was used.

After independent source review, `build.py --output-dir /absolute/repository/results/fresh_child` can build the actual three-source ARM stage using installed GNU Arm 13.2.Rel1. It pins the writer, selected headers, expanded dependencies and tools, captures actual command exits/stdout/stderr and checks ELF/vector/segment/BIN layout. It has not been run at the time of this note. Parent process control and full tool/runtime closure are not claimed. A separate observed exit and ARM disassembly review remain required before any hardware-use decision.

See `SRAM_PLATFORM_RECIPE_REVIEW.md` for original source hashes, official ST links, register locations, physical memory-interleave caveat and remaining physical-power blockers. This candidate does not override the existing no-ON decision or authorize target access.
