# Pulse02 — independent saved-only review

Saved-evidence consistency PASS; the actual power probe remains a failed diagnostic, `85a957 / exit 1`. Independent read-only recomputation completed as `1d9957 / exit 0`. No USB, serial, pyOCD, model, or additional power operation was performed.

## Fixed evidence and reproducible checks

The actual raw filename is [power_pulse_02/samples.u32le](power_pulse_02/samples.u32le), not raw.ppk2. Exact two-file output namespace: that file and report.json. Six files (raw, report, external execution receipt, wrapper, original pulse and Decoder source) passed before/after byte and stat checks, with ordinary single-link canonical files.

- Raw: 149504 bytes, SHA `ed084a0e12abc0b566965d17e466a980cb57bf247430a7940bd452c1e8c73ada`.
- Report: SHA `3e0413c17c5706fd8396906577dcde8609b5f6a67dfa6ed84d2b29ea0c3f1762`.
- External receipt: SHA `7e72cc523b8ca5106f491db5d78e92782cdd74446bc07e4b8f6263a4c307c04e`; its parsed stdout equals report.json, with integer exit 1.
- Wrapper `bb15b725a0aa63dab6c8c12f1564d7ebefc3805a090749aa096b9d1576a8152f`; original pulse `c74d945e81dce5f5647d3795e4f70bdcf0ebae3ccf27cca37daf6d3a00ef4e8f`; Decoder `7eae8347391b11e747be73a7368f55587a9f154e7749f622844e5fae8a9869a9`.
- Original raw metadata equals parsed fields; exact PPK2/ST-LINK serials and Ampere mode 1 match. No new coefficient, voltage, threshold or model selection was introduced.

Each little-endian uint32 was independently split into ADC bits 0–13, range bits 14–16, modulo-64 counter bits 18–23 and digital byte bits 24–31. Current was recomputed without importing the producer or Decoder: exact decimal rational coefficients, GUI zero-default substitution (only GS0 becomes 1), assumed correction voltage 5 V, no filter. With `x=(4*ADC-O[r])*(9/5)/(163840*R[r])`, evaluate `UG[r]*(GS[r]*x*x+GI[r]*x+5*S[r]+I[r])*1e6`. Floating report prefix min/max/sum agree within 1e-7 microampere absolute / 1e-12 relative tolerance.

All 37376 frames are range 0, with no range transition or observed counter discontinuity. Digital bytes are all 255. ADC spans 0–37: three ADC-zero samples, no upper-rail sample. No raw sample reaches either current cutoff. Whole-file corrected values are min -1.395520742927 uA, max 0.233779524983 uA, mean -0.153829388068 uA. These are near-zero offset/noise-level decoded values under an unmeasured-voltage assumption, not negative board power or proof of zero physical current.

The producer processed 34816 frames (139264 bytes); post-STOP drain retained another 2560 frames (10240 bytes), exactly totaling the saved file. Drain records an empty read after 0.040520820 seconds. The report's current statistics describe only the processed prefix, whose mean is -0.161656923133 uA, not the complete drained file.

## Command, reference and failure boundaries

Exactly one ON appears in the five command receipts: initial OFF, START, ON, final OFF, STOP. All write-completed fields are true; cleanup_errors is empty. Host ON-to-OFF attempt timestamps differ by 0.305199158 seconds. These are host command timestamps, not electrical switch readback.

Before/during/after references all contain `e205000002000000`: little-endian a0=1506 and a1=2, so `2*a1*1.2/a0=0.003187250996015936 V`. Their timestamps surround the commands correctly. The during value violates the unchanged 2.7–3.6 V guard; the original failure message survives the successful drain and post-reference. It is not a current-threshold failure in pulse02.

Nominal saved duration is 0.37376 s, whereas host START-to-STOP attempts span 0.405579796 s. Startup, buffering and command timing prevent an exact electrical time mapping. No observed counter gap does not exclude missing whole multiples of 64 samples. Empty-read drain does not independently prove every firmware/USB buffer was captured. OFF/STOP write completion and low target reference do not measure VIN or certify all power rails off. Research, firmware-changed, physical-VIN, electrical-OFF and probe-completed flags remain false.

## Separate user observation and interpretation

During this review the root relayed the user's current observation: **LD3 red continuously**. This is not part of the pulse02 raw stream, not synchronized to it, and was not independently photographed or observed by this reviewer.

[UM3300 Table 8](https://www.st.com/resource/en/user_manual/um3300-discovery-kit-with-stm32n657x0-mcu-stmicroelectronics.pdf) identifies LD3 as STLINK-V3EC power status and distinguishes steady red from blinking red and from the separate COM LED. [TN1235 Rev 7, section 7](https://www.st.com/resource/en/technical_note/tn1235-overview-of-stlink-derivatives-stmicroelectronics.pdf) defines steady-red power status as detected overcurrent with automatic target-power shutdown. Conditional on the reported LED identity/state, this supports ST-LINK supply protection being active; it does not determine the triggering current, exact trip time, eFuse latch/register state, board damage, or a unique cause such as inadequate source capacity.

No new saved-artifact/software blocker was found. Hardware startup remains unaccepted. Preserve both negative pulses; no third ON, threshold increase or more-capable supply through the existing PPK2 path is authorized by this review. Further source/cable options and any physical configuration change require separate review; the retained measurements do not settle those decisions.

