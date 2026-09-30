# Correcting the meaning of the power diagnostic stop policy

2026-09-25, after the third pulse and the user's instruction not to invent
conditions. No new current threshold, smoothing window, startup allowance,
power-on operation or firmware change is introduced by this review.

## Issue and disposition

The unchanged v1/v2 diagnostic script aborts on any single unfiltered sample
above 700 mA, any ADC14 value 16383 (regardless of range), or a target-reference
outside 2.7–3.6 V once its 0.3 s startup delay expires. These are **authored
engineering stop rules**, not a manufacturer-specified physical fault oracle.
The 3 s requested interval and 6 s watchdog are also engineering choices.

Keeping parameters unchanged does not establish their scientific suitability.
Mocked tests establish implementation of the rules and cleanup paths, not that
the rules can distinguish real overload, autoranging artifacts, normal boot
or an adequately powered target. The three failed diagnostics must not be
reported as three independently established hardware failures.

Root will **not reuse this script for further normal-startup qualification**
without a separately reviewed acquisition protocol. Frozen v1/v2 source and
all three original failures stay intact as historical evidence. No success
flag is rewritten and no arbitrary larger cutoff replaces 700 mA.

## Manufacturer basis versus inference

| Item | Verified basis | Consequence for interpretation |
|---|---|---|
| PPK2 1 A | Nordic specifies Ampere mode maximum admissible current as 1 A continuous | Not a specification for aborting at one unfiltered 700 mA sample; also not permission to exceed the rating |
| Range-change peaks | Nordic staff confirms automatic range switching can create nonphysical current peaks | A peak may contain measurement artifacts; it is not valid to declare every peak false |
| Accuracy | Nordic specifies typical highest-range accuracy for the average readout | Not a precise confidence interval for each 10 us sample |
| Low-range ADC top value | Range code must be considered; 16383 at range0 is not the 1 A full-scale range | Does not prove the entire instrument exceeds 1 A; clipped samples still cannot be treated as accurate current |
| ST LD3 red | ST defines detected overcurrent with automatic target-power shutdown | Independent physical status observation, not interchangeable with the program's cutoff |
| ST LD3 orange | Requested budget exceeds available USB budget; ST-LINK can still operate | Warning, not the same condition as red and not a manufacturer blanket ban on every bounded diagnostic |

The script's host-side 700 mA cutoff is not hardware protection and is above
the board's documented approximate 550 mA USB-A limiting level. It cannot be
assumed to intervene before that hardware protection. No ST-LINK or PPK2
protection is disabled or bypassed here.

## Third pulse: observed, not accepted

- User reported SW1=H / SW2=L, a CN6 USB cycle, and a yellow/green LD3 that
  was explicitly not red before this test. Exact green was not established.
- Actual execution `98d283 / exit 1`, UTC 00:41:22.888919, only one ON;
  host ON-to-OFF attempts separated by 27.944627 ms. OFF and STOP writes
  completed; physical switch state was not independently read back.
- Saved raw 30,720 B / 7,680 frames, SHA-256
  `2c3dc1250d15ed3fe40576f218dd6618838a06598a2c857fb42f1ed29e160e23`;
  report SHA-256
  `539a0489bac5a647d662c1203153aa62a02c8d5e7add470d46046729df9648a1`.
- Root replay `bea2db / 0` and independent exact-arithmetic check `f6d4f5 / 0`
  agree on maximum decoded current 834532.366712 uA at index 5067, the fifth
  sample in range4. The same full-stream maximum survives the previously
  verified official-compatible filter. Three samples exceed 700 mA; none
  exceeds 1 A. This is not calibrated verification of true peak current.
- Range4 spans indices 5063..5120 (58 samples). All 69 ADC top values occur
  later in range0. The final range0 section contains clipped points and is
  **not** a clean idle-power measurement, despite its last samples near zero.
- No visible modulo-counter gaps; this does not exclude loss of whole
  multiples of 64. No GPIO timing markers establish exact electrical time.
- Before reference 0.189641434 V, after 0.003187251 V; no during reference
  because the authored current rule stopped the test first. Low post-OFF
  reference cannot determine whether upstream protection or software OFF
  caused the loss of target power. Post-test LD3 has not been observed here.

The immediate result is **software-aborted startup diagnostic**, not normal
boot, proven damage, or a measured 1 A overload. HL has not been proved to
fix the supply problem. No fourth pulse has been run or armed.

## Required correction before another hardware experiment

Separate acquisition integrity/job-control stops from physical operating
limits, operator fault observations, and scientific acceptance. State which
conditions come from manufacturer specifications and which are engineering
choices. Preserve raw/clipped/range-transition data and report their limits.
Do not select new cutoffs after observing data merely to obtain a pass.

One unconfirmed mechanism worth investigating offline is the supply sequence:
the tests enable PPK2 only after upstream ST-LINK power is already present.
That may create a different load step from powering the original complete
path together. Whether any particular C02 switch has a relevant soft-start
behavior must be checked against its circuit/datasheet before any new sequence
is proposed. This is a hypothesis, **not a confirmed root cause or instruction**.

Primary sources:
- [Nordic maximum admissible current](https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_max_dut_current.html)
- [Nordic range-switch peak explanation](https://devzone.nordicsemi.com/f/nordic-q-a/109264/ppk2-52840-measure-the-current-in-rush-current)
- [Nordic measurement accuracy](https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_measure_accuracy.html)
- [ST UM3300](https://www.st.com/resource/en/user_manual/um3300-discovery-kit-with-stm32n657x0-mcu-stmicroelectronics.pdf)
- [ST TN1235, section 7](https://www.st.com/resource/en/technical_note/tn1235-overview-of-stlink-derivatives-stmicroelectronics.pdf)
