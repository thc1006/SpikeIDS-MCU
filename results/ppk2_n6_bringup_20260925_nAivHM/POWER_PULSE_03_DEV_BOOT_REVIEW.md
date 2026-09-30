# Pulse03 DEV_BOOT — independent saved-only review

Saved-artifact consistency PASS; the actual pulse remains a failed diagnostic: producer `98d283 / exit 1`, wall time 0.555261992 s. Independent whole-stream read-only check: `f6d4f5 / exit 0`; focused tail/ADC check: `5537fa / exit 0`. No USB, serial, pyOCD, ON, firmware operation, or source modification was performed by this reviewer.

## Evidence and method

Exact output namespace is [power_pulse_03_dev_boot/report.json](power_pulse_03_dev_boot/report.json) and [power_pulse_03_dev_boot/samples.u32le](power_pulse_03_dev_boot/samples.u32le). Six canonical, regular, single-link files (these two, external receipt, wrapper, original pulse and decoder source) passed before/after SHA and stat bookends.

- Raw: 30720 bytes / 7680 complete frames; SHA `2c3dc1250d15ed3fe40576f218dd6618838a06598a2c857fb42f1ed29e160e23`.
- Report: SHA `539a0489bac5a647d662c1203153aa62a02c8d5e7add470d46046729df9648a1`.
- [External execution receipt](power_pulse_03_dev_boot_execution.json): SHA `c1596d1ababe595ac4d9f1f030405732b58d65b85da0b572abdbac2f14f7a8cf`; actual integer exit 1 and its parsed stdout equals the report.
- Wrapper: `bb15b725a0aa63dab6c8c12f1564d7ebefc3805a090749aa096b9d1576a8152f`; original pulse: `c74d945e81dce5f5647d3795e4f70bdcf0ebae3ccf27cca37daf6d3a00ef4e8f`; decoder: `7eae8347391b11e747be73a7368f55587a9f154e7749f622844e5fae8a9869a9`.

Strict JSON reads rejected duplicate keys and nonfinite constants. Original raw metadata equals its parsed fields; PPK serial `F4728E9B55E0`, ST-LINK serial `004000183234510E37333934`, and exact Ampere mode `"1"` match. The current-correction assumption remains nominal **5 V**, not measured VIN; metadata VDD4000 is not a VIN measurement.

Each little-endian uint32 was independently split into ADC bits 0–13, range bits 14–16, modulo-64 counter bits 18–23 and digital byte bits 24–31. No producer/Decoder import was used. Exact-decimal rational coefficients implement the reviewed [Nordic v4.4.1 conversion](https://github.com/NordicSemiconductor/pc-nrfconnect-ppk/blob/4cbb4c41c420ddb8125638fffc6d72f6b21c5aaa/src/device/serialDevice.ts), including GUI zero-default substitution (only GS0 becomes 1 here), with no filter:

`x=(4*ADC-O[r])*(9/5)/(163840*R[r])`; `uA=UG[r]*(GS[r]*x*x+GI[r]*x+5*S[r]+I[r])*1e6`.

The report's processed-prefix min/max/sum agree within 1e-7 uA absolute / 1e-12 relative tolerance. All 7680 counter steps are consecutive modulo 64; digital bytes are all 255. This is not a GPIO measurement window or proof against loss of whole multiples of 64 samples.

## Complete stream observations

All indices below are zero-based, end exclusive.

| Interval | Range | Frames |
| --- | ---: | ---: |
| 0–5040 | 0 | 5040 |
| 5040–5042 | 1 | 2 |
| 5042–5044 | 2 | 2 |
| 5044–5063 | 3 | 19 |
| 5063–5121 | 4 | 58 |
| 5121–5122 | 3 | 1 |
| 5122–5124 | 2 | 2 |
| 5124–7680 | 0 | 2556 |

The first diagnostic stop is sample **5067**, the fifth range-4 point (nominally 40 us after its first point): ADC1065, raw word `ff330429`, unfiltered corrected value **834532.366712 uA**. Samples 5070 and 5071 decode to 711306.728638 and 721352.865025 uA. These are the only three values above 700000 uA; no decoded sample exceeds 1000000 uA. This does **not** establish either the true physical peak or a physical upper bound of 1 A.

Nordic confirms that automatic range switching can create false high peaks; that possibility applies to interpretation, but does not prove this particular peak or every subsequent point is an artifact. Being the fifth point in the same range is not an independently established settling guarantee. [Nordic technical support explanation](https://devzone.nordicsemi.com/f/nordic-q-a/109264/ppk2-52840-measure-the-current-in-rush-current).

The producer processed 5068 frames, but retained its complete 5120-frame read prefix: **52 additional frames** were saved without online evaluation. Post-STOP drain retained another **2560 frames**. The drained portion starts with one range-4 point (64883.896057 uA), one range-3 point and two range-2 points, then stays in range 0.

The final 2556 range-0 points have median -1.219380 uA; 2475 are at or below 10 uA. However, **69 points reach ADC16383**, and 80 decode above 100 uA. All 69 ADC-upper-rail points occur in this range-0 tail, not range 4: they are low-range clipping/rail-valued samples, not evidence of full-scale 1 A overload. The tail mean is 21.610952 uA and maximum 720.551501 uA; these are arithmetic summaries of a contaminated/clipped diagnostic tail, **not reliable standby current**. The last ten points decode between -1.395521 and -1.131310 uA: offset/noise-level values, not negative physical power. Thus the trace falls back to mostly near-zero low-range readings, but the entire tail must not be called clean or validated. No samples were removed to create an accepted mean.

## Commands, reference readings and experiment limits

Exactly one ON occurs: initial OFF → START → ON → final OFF → STOP. All five write-completed flags are true, with no cleanup errors. ON-to-OFF host attempt timestamps span **27.944626985 ms**. START-to-STOP spans 128.412069986 ms, whereas 7680 nominal 100 kHz frames span 76.8 ms. These do not provide synchronized electrical edges, prove complete firmware/USB buffer capture, or establish whether any physical protection acted before host OFF. The drain observed an empty read after 0.040407233 s; this is a bounded software observation, not a zero-loss certificate.

Before-reference `e205000077000000` decodes as a0=1506, a1=119: **0.189641434263 V**. After-reference `e205000002000000` gives a0=1506, a1=2: **0.003187250996 V**, sampled approximately 141.325 ms after the host OFF attempt. Both independently match `2*a1*1.2/a0`. There is **no during-reference** because the current stop happened before its 0.3 s schedule. These are target-reference estimates, not VIN or proof that every power rail is off.

The actual error remains `Current/ADC diagnostic stop threshold`; successful OFF/STOP, drain and post-reference did not erase it. Research acceptance, completed probe, measured input voltage, electrically verified OFF, and firmware-changed flags all remain false.

The **700 mA single-sample cutoff is an experiment-specific software stop**, not a Nordic overload specification, calibrated physical-current oracle or hardware limiter. Its implementation/tests show that the selected rule executes and retains failure evidence; they do not validate the rule's physical suitability for distinguishing startup, range-switch artifacts, protection events or sustained load. This run therefore does not answer whether the board would sustain DEV_BOOT or what its steady current would be. It does not justify increasing the cutoff, filtering away the failure, or repeating ON.

The root relayed the user's pretest observations as **SW1 H / SW2 L and CN6 USB unplug/replug**, with LD3 described as **“有點黃也綠、反正不是紅”**. This is not a verified green LED, measured boot-pin state, successful DEV_BOOT entry or synchronized power-status record. [TN1235 §7](https://www.st.com/resource/en/technical_note/tn1235-overview-of-stlink-derivatives-stmicroelectronics.pdf) distinguishes an orange power-budget warning from a steady-red detected-overcurrent shutdown; orange alone is not a manufacturer blanket prohibition of every bounded observation. This review does not infer board damage, an eFuse latch state, a unique power-supply cause, or that H/L fixed/reduced inrush. Comparing the decoded peak against pulse01 is not a controlled estimate of the boot-setting effect.

No new saved-artifact/software-contract blocker was found. **Hardware startup remains unaccepted.** Preserve all three negative pulses and the original thresholds; no further ON or hardware change is authorized by this saved-only review.
