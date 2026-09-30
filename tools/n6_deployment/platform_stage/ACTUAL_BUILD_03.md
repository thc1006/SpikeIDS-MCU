# Offline stage build 03

The additive `build_v3.py` / `linker_v2.ld` build completed with actual external tool chunk `1dcd14`, return code 0, systemd invocation `6e8eb389d27b41fa9af7301be4fd10d5`. Seventeen retained build commands returned zero. The original two failures remain preserved: tool hardlink rejection before compilation (01), then linker token syntax after three successful C compilations (02). No historical source or result was replaced.

Output: `results/ppk2_n6_bringup_20260925_nAivHM/platform_stage_actual_03/`.

- ELF SHA-256: `cc3fef71e251ce26e6b024067e673408c0f0bbc323aa985b0987019cb7567ec5`.
- BIN SHA-256: `2c8857750005ee5ca13f634b6d45a3b18a8b5b9d935a67e40ac817a446a3bfaa`.
- RESULT whole-file SHA-256: `f61956f96cc3a13f690ec75cd17355048cae9eb3e80b4444ed5f84b31676bf73`.

ELF32 ARM soft-float has exactly three load segments: 2,760-byte RX code at `0x34180400`, 4,096-byte NOBITS mailbox at `0x34188000`, and 8,192-byte NOBITS stack at `0x34189000`. Initial MSP is `0x3418b000`; Thumb entry is `0x34180539`. These are linker/layout observations, not evidence that the target has executed them.

Post-exit check `275c9b` returned 0: all 33 original input/header/tool pins and 63 output files match full SHA and original metadata, including final stat bookends and exact namespace. External receipt and raw postcheck are in the result parent: `PLATFORM_STAGE_ACTUAL_03_EXIT.json` and `PLATFORM_STAGE_ACTUAL_03_POSTCHECK.json`. The successful transient unit had already unloaded at a later `systemctl show`; its default fields were not used as original resource evidence. The receipt separates requested limits from the launch output's actual resource summary.

Independent saved-artifact review is separate. This stage **replaces**, rather than coexists with, the older minimal probe because their code/RAM reservations overlap; see `STAGE_REPLACEMENT_ADDENDUM.md`. No USB, SWD, target initialization, model inference, flash, OTP, or energy measurement was performed by this build. Compilation does not establish secure entry, supply quality, platform readiness, NPU behavior, or board acceptance.
