# Actual offline SRAM adapter build

**Build succeeded once**, session 84432, launch `7384b3`, completion `0386bb`,
actual outer exit 0. All **63 commands** exited 0. The dedicated scope used
4 GiB memory, zero swap, 128 tasks and 400% CPU quota. No hardware was accessed.

- [ELF](build_actual_01/n6_sram.elf): SHA `9a68e6893b59d3d8d0952b70ccecdae6af14c3f3561532bd2a22540d69b562ca`
- [BIN](build_actual_01/n6_sram.bin): **78,388 bytes**, SHA `59c61c71937eea2fd7d839b41cf84eb8e94e5b5517f4ccc5c3e1d3b4c34de41b`
- [Build result](build_actual_01/RESULT.json): whole SHA `49225e31bc906e86fe73c3ca7f5a0d18592411f7692fa4173fdbe83c059a2e01`, canonical seal `6c9ce6e585df38bc4e4e4c27194b46b695dd5f105c3ac18b82c92a6da2036b84`
- [Observed execution receipt](BUILD_ACTUAL_01_EXECUTION.json)

The build retained 281 input pins and 240 artifacts before RESULT. The builder
full-hashed/bookended these inputs and outputs; source hashes before/after were
unchanged (`99e7fa`, `10d6f1`). Independent saved-artifact review is a separate
reviewer's execution, not claimed as an additional author check here.

Author saved-only check `567e42`, exit 0, independently verified the canonical
result seal, exact BIN reconstruction from initialized PT_LOAD bytes, empty
undefined-symbol output, and all typed command exits. Disassembly/symbol read
`f35ce3`, exit 0, shows CPACR access enabled with DSB/ISB before entering C and
memset; runtime request checks, fixed mailbox and full reservation symbols exist.

The ELF has separate RX code, RW data, 32 KiB stack and 512-byte mailbox segments.
No load segment overlaps reserved weights `[0x34200000,0x34240000)` or activations
`[0x34240000,0x34244000)`. These are complete reservations, not merely used RAW/
activation sizes. Code RAM is an alternative to old v5, not co-resident with it.

The new mailbox retains all 41 input / five output FP32 words and distinct
S6 deployment identity. It waits for explicit platform prerequisites and never
writes its own acknowledgement. The ELF alone neither loads the separate RAW
weights nor initializes clocks, SRAM shutdown state, NPU/RIF, power, cache or
watchdog policy. Secure privileged entry remains a loader prerequisite.

The underlying generation history remains wrapper exit 1 / ST compiler exit 0,
followed by separately reviewed saved-output validation exit 0. This new ARM
compile success does not erase the original failure. No compile retry, model
regeneration, inference, target RAM upload, USB/SWD, flash, XSPI, OTP or voltage
operation occurred. Board readiness, numerical equivalence, hardware execution,
deployment acceptance and energy/performance claims remain false.
