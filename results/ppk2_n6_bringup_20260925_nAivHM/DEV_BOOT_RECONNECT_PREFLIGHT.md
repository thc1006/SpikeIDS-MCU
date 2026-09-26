# DEV_BOOT reconnect — preflight, no third ON yet

2026-09-25, after the user stated SW1=H / SW2=L was set and the STM32 USB
was reconnected. Switch positions, physical wiring and power cycling are
user-reported, not independently photographed or measured. Earlier failed
pulses remain unchanged. No boot-mode change is claimed to cure inrush.

## Observed checks

- `cfaadb / 0`: USB enumeration shows PPK2 and STLINK-V3; stable serial links
  identify F4728E9B55E0 on ttyACM0 and 004000183234510E37333934 on ttyACM1.
- `4bd5a2 / 1`: fuser found no owner of the two ports and current ST-LINK
  USB device. `dd3a5e / 1` found no matching power/probe/programmer process.
  These are point-in-time observations, not exclusive ownership indefinitely.
- `5df612 / 0`: original pulse, v2 wrapper and Decoder match held SHA-256
  c74d945e..., bb15b725... and 7eae8347..., respectively.
- `485f66 / 0`: all 68 offline unit tests pass. These are not hardware tests.
- Metadata-only check `d4a06d / 0`, UTC 00:38:22.293108: exact PPK serial,
  fresh `mode: 1`; only command 0x19. Report and observed execution are saved
  in `dev_boot_reconnect_metadata.json` and its `_execution.json` sibling.
  `VDD: 4000` remains a regulator setting, not measured Ampere input voltage.
- Low-level ST-LINK reference check `490182 / 0`, UTC 00:39:30.196322:
  only f7, no debug entry/reset/flash. Reply `e205000077000000` gives
  reference estimate **0.189641434 V**. This is not VIN or normal target
  supply; it does not establish the state of the upstream protection.
  Exact receipt is `dev_boot_reconnect_reference_execution.json`.

## Finite independent pre-review

Reviewer `lifecycle_integration_redteam` checked the unchanged source bytes
(`6454b5 / 0`) and one-shot policy. A new test would keep the original current,
ADC, missing-data, counter, reference, time and stopped-stream-retention limits,
use a fresh output directory, preserve any failure and never retry ON. USB
power cycling and DEV_BOOT are new conditions, not proven corrective actions.

The reviewer initially suggested treating orange LD3 as an absolute no-ON
condition, then rechecked the official text and withdrew that extra blanket
restriction: orange is a budget warning, while steady red is detected
overcurrent with automatic target-power shutdown. Orange alone does not prove
that a bounded diagnostic is prohibited, nor that supply is sufficient. The
700 mA host cutoff cannot be presumed to precede the approximately 550 mA
board-side USB-A protection. No protection or threshold has been bypassed.

**Current unresolved prerequisite:** this reconnect's LD3 color has been
requested but not yet received. Prior steady-red observation cannot be silently
replaced with a healthy-state assumption. Steady/blinking red means no new ON.
An unlit LED is not positive evidence of healthy target supply either.

No third pulse has been executed or armed as of this note. No flashing,
inference, power acceptance or research result follows from this preflight.

Sources: [UM3300, sections 6.1, 7.7 and Table 8](https://www.st.com/resource/en/user_manual/um3300-discovery-kit-with-stm32n657x0-mcu-stmicroelectronics.pdf),
[TN1235, section 7](https://www.st.com/resource/en/technical_note/tn1235-overview-of-stlink-derivatives-stmicroelectronics.pdf),
[ST H/L explanation](https://community.st.com/stm32-mcus-boards-and-hardware-tools-26/stm32n6-boot-pins-153371).

## Subsequent color report and bounded test decision

Before any new ON, the user replied that LD3 looks yellow/green, uncertain,
but explicitly not red. Retain this uncertainty: it is not a confirmed green
LED or proof of adequate power budget. Root will perform exactly one fresh
DEV_BOOT diagnostic under the unchanged reviewed policy, retaining USB-A,
reported HL and all existing source/instrument protections. No automatic retry.
The earlier no-third-pulse statement describes the checks above, not a future
claim; the separate execution receipt must establish whether the test ran.
