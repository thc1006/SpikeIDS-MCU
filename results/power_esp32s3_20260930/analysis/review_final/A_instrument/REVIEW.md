# Review A: instrument and conversion (ESP32-S3, 2026-09-30)

**VERDICT: CLEAN.** No BLOCKER. 2 MAJOR wording/basis fixes are needed before publication.

**Conversion.** `indep_decode.py` follows Nordic `serialDevice.ts` (identical at v4.4.1 and main@881d596) without importing the pipeline.
- **Windows.** All 345 windows match within 4.3e-16 relative.
- **Headlines.** 7.921166 / 8.000894 / 8.006057 mJ; aggregate 7.976039 mJ.
- **Coefficients.** Code 4 matches the Converter exactly; GS0 (0 vs the GUI's `0||1`) affects range 0 before ON only.
- **Nordic filters.** The spike filter changes no window (5–6 range switches per session, all at power-on). The <0.2 µA clamp is irrelevant.
- **Timing.** The sample residual against the ESP cycle counter is <0.94 samples in all 300 windows, so no hidden 64-frame losses.

## MAJOR
1. **The VOUT band has no valid basis.**
   - DevZone 125227 is "Not Answered". The poster reports a unit that "gives lower voltages": 5000→4.918 V and 800→0.605 V, with no load stated and no comment from Nordic on VOUT.
   - UG v1.0.1 gives no Source Meter voltage accuracy.
   - Energy scales with V: at 4.918 V the result would be −2.0 %.
   - **Fix:** measure VOUT at the 5V pin with a DMM, using the same PPK2 and leads, at 5000 mV and a load of about 64 mA. Recompute V and the S-term. Otherwise, call the band unsupported.
2. **The Type-B gain basis is misdescribed.**
   - At 64 mA the PPK2 is in code 4 = **UG R5**. Table 9 gives ±15 % accuracy **plus ±5 % offset**, both "Typ", "Readout on average value".
   - RESULTS omits the offset row and calls 20 % "conservative". It is the linear sum 15 + 5.
   - The values are typical, so "worst case" is not a guaranteed bound. The RSS is also called a "bound".
   - The ±22.9 % arithmetic is correct.
   - **Fix:** reword it accordingly. Better: check a known load at the operating point (0.1 % ≈75 Ω plus a series DMM).

## MINOR
3. **Wrong inrush rating.** UG Table 7 rates Source Meter mode at **600 mA**; 1 A is the Ampere-mode rating.
   - Sessions 2 and 3 each had one sample above 600 mA (1.025 A and 0.989 A), 0.22 ms after onset.
   - Session 2 had 5 saturated range-0 frames just before, so its true peak is unknown.
   - Windows are unaffected: all their samples are code 4, starting 77 s later.
   - **Fix:** correct the text; use a 600 mA gate.
4. **Range names.** "R3/R4" in RESULTS are codes; the UG calls them R4/R5. A reader would pick the ±10 % row. **Fix:** write "code 4 (UG R5)".
5. **Unstated series drop.** The PPK2 internal path plus jumpers is about 0.1–0.3 Ω, a 6–20 mV drop. Pin energy is therefore over by 0.1–0.4 %, in one direction only. The DMM measurement in fix #1 removes this.
6. **R5 zero offset unverifiable.** The data have no zero-current code-4 samples.
   - One code = 0.753 mA = 1.18 %.
   - S4·V+I4 = +5.03 mA, which is 7.9 % of the reading.
   - This is covered only by the typical spec.
7. **ADC DNL.** The histograms show paired codes (IDLE 22.88/23.26 %, 4.33/4.36 %), so the effective step is about 1.5 mA.
   - The gross is dithered (SD 1.8–2.3 codes).
   - The incremental (ΔI ≈ 1 code) relies on that dithering, and gain cancellation does not cover DNL.
   - **Fix:** disclose it.

## Not a threat
- **Logic VCC.**
  - The self-test drew 0.06 µA at 3.3 V, within the zero reading.
  - The pre-ON byte read 0xFF for 651 s, so the rail was not back-fed.
  - The post-OFF latch also appears in the self-test with no board attached.
- **Counter.** Session 2 had two single stale frames, both exactly at range switches (ON+6.7 ms and ON+141.8 ms). No samples were lost, and both are inside the mask.
- **Tick and aliasing.** The folded 10 ms bump is +2.5 mA, about 0.27 µC. Its effect is ≤2.7e-6 per window. The clocks are asynchronous and each window holds an integer 64 inferences.

## NOT DONE
- Schematic of the logic VCC stage (not documented).
- The meaning of "Calibrated: 0" and "IA" (not documented).
- A DNL figure for the incremental.
