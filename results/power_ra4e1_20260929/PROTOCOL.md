# RM01 board-level energy measurement on FPB-RA4E1: pre-registered protocol

Written 2026-09-29, **before** any PPK2-powered RM01 measurement. The only
earlier runs were J9-powered bring-up boots with the PPK2 output OFF; they
produced no energy data. Changes after data collection must be listed in a dated
amendment section. They must not be made silently. This protocol mirrors the
STM32N6 protocol (`results/power_n6_20260929/PROTOCOL.md`, amendments 1–4a) and
uses the same per-schedule analysis code (`tools/ppk2_energy/analyze_schedule.py`).

## Question

What is the board-input energy per inference of the v5 NSL-KDD QCFS primary
seed-0 model (41→256→256→128→5, INT8 QDQ, portable FP32 arithmetic; bit-exact
with the ORT QDQ reference on all 1024 validation rows) on an unmodified
FPB-RA4E1 at its validated configuration?

## Fixed setup (not varied)

**Board**
- FPB-RA4E1 v1 (R7FA4E10D2CFM), unmodified. R3 (0 Ω MCU supply) is fitted, CN1 is unused, and J7 is open.
- The on-board J-Link OB (J9) is **unplugged** during every measurement session.

**Power path**
- PPK2 serial F4728E9B55E0 in **Source Meter** mode.
- The setpoint is **5000 mV**, set by the Nordic byte sequence `0C 00`, `11 02`, `0D 13 88` (pc-nrfconnect-ppk main@881d596) and verified from the metadata of a fresh connection (mode 2, VDD 5000).
- VOUT goes to CN2-2 (+5 V) and GND to CN2-1 (UM r20ut4958eg0100 §5.1.1.2).
- Reverse-current protection sits between CN2 and the main 5 V, and between J9 and the main 5 V.
- The recorder refuses output ON while the J-Link OB (USB serial 000831033862) is on the USB bus. It switches the output OFF if the J-Link appears.

**Marker**
- P107 = J5-5 (Arduino D4) → PPK2 D0. P107 has no LED or other on-board load.
- Logic VCC ← J2-4 (3.3 V); logic GND ← J2-6.

**Firmware**
- RM01 `tools/ra4e1_deployment/firmware_measure/build_03`:
  - `firmware.bin` sha256 19532b80…cb7f;
  - flashed with J-Link `verifybin` "Verify successful".
- The model objects (portable_qdq.c, model.c) and the whole FSP are byte-identical to Codex's RA01 cross-build objects. All 90 build dependencies are hashed in `RESULT.json`.
- Clock: HOCO 20 MHz → PLL ×10 (HOCO/2 ×20) = 200 MHz → ICLK = PCLKD = 100 MHz. Flash cache is on (FCACHEE = 1).
  - These are snapshot per boot (SCKSCR, SCKDIVCR, PLLCCR, OFS1_SEC HOCOFRQ, FLWT) and checked.
- Time base: GPT321 (32-bit) at PCLKD/1. One count equals one CPU cycle by configuration.
  - The DWT is not used: it does not count while SYOCDCR.DBGEN = 0, as observed on this board.
  - Enabling on-chip debug would change the board's power state.
- No interrupts are used. Only P107 and GPT321 are configured beyond the FSP BSP startup.

**Rows**
- The first 16 of the frozen 1024 validation rows, cycled.
- The per-inference cycle count is data-independent. On the build_03 J9-powered bring-up (readback
  `readback/rm01_result_bringup_build03_boot1.bin`), it was 2 888 441–2 888 447 cycles across all 50 BENCH windows.
  - On the same bring-up, OVERHEAD windows were 0.988 s, all 100 checksums matched, and the clock snapshot passed.
  - build_02 gave 2 888 458 ± 5; its OVERHEAD calibration defect is fixed in build_03.

## Sequence per power-on (one "session"; fully autonomous, no host link)

1. **Settle** 2 s.
2. **Self-parity.** All 1024 rows run through the measured inference path and are compared bitwise with the embedded QDQ reference outputs (5120 FP32 words).
   - Any mismatch means **fail closed**: no windows are run, and telemetry reports the error.
3. **Wiring.** 5 × 0.1 s marker pulses.
4. **Sham (null control).** 20 × (1 s HIGH, 1 s LOW). The same busy-wait runs in both states.
5. **Calibration.** Marker LOW. The loops are identical to the schedule loops. They size BENCH ≈ 1.5 s and OVERHEAD ≈ 1.0 s.
6. **Schedules.** 3 repeat (×1) and 2 dose (×2, ×4) schedules. Each is 3 preamble pulses (20 ms), then 10 × [IDLE 1 s, BENCH, IDLE 1 s, OVERHEAD], then a final IDLE.
   - There is a 2 s LOW gap between phases.
7. **Telemetry.** The full header (incl. clock snapshot) and the window table go out on the marker, CRC-32 protected. After that the marker is held HIGH (DONE).

Three sessions are power cycles by the PPK2 output (OFF ≥ 10 s between), with no manual handling.

## Quantities

- **Scope.** Whole FPB-RA4E1 board at CN2 (5 V input). This includes the regulator, any board circuitry powered from the main rails (incl. whatever part of the J-Link OB section is), and the PPK2 logic-port load on 3.3 V.
  - It is **not** the MCU core.
- **Voltage.** V = 5.000 V setpoint, **not measured**; no multimeter is available.
- **Gross** = V·∫I dt / N over each BENCH window (headline).
- **Incremental** = (P_BENCH − P_IDLE)·T / N, over a CPU spin that polls GPT321.
  - It is reported only for windows whose BENCH span and both trimmed IDLE spans share one dominant PPK2 range with no range switch.
  - It is not comparable across boards, because the spin loops differ.
- **Also reported:**
  - sham-corrected incremental;
  - vs-OVERHEAD;
  - charge per inference;
  - time per inference from the PPK2 timebase;
  - the GPT321 clock estimate against the PPK2 timebase;
  - range histograms and switches per window;
  - PPK2 rate against the host clock (descriptive).

## Validity rules

A session is **ineligible** (reported, not pooled) if any of these hold:

- **Telemetry and firmware state:**
  - telemetry is missing or fails its CRC;
  - firmware stage is not TELEMETRY or error ≠ 0;
  - FP environment check failed;
  - any self-parity mismatch;
  - fewer than 5 schedules done;
  - model or vector identity prefix mismatch;
  - time base is not GPT321;
  - clock snapshot differs from the configuration above.
- **Marker and logic port:**
  - D0 HIGH runs before telemetry ≠ firmware marker-HIGH windows;
  - the logic port is unpowered, or D1–D7 are not LOW, inside any analyzed slice;
  - wiring gate fails;
  - sham |mean ΔI| ≥ 0.5 mA.
- **Schedules:** fewer than 2 valid repeat schedules. A schedule is invalid under the SM07M rules:
  - PPK2 counter discontinuity or host reader gap;
  - D0 HIGH at a slice edge;
  - HIGH-run order mismatch;
  - checksum mismatch against the values expected from the bitwise-verified outputs;
  - any sample above 1 A;
  - sum-based and counter-time energy differ by more than 0.5 %.
- **PPK2 and interlock:**
  - output dropped or guard tripped (300 mA mean over 100 ms);
  - the J-Link appeared on USB while the output was ON.
- **DONE detection:** DONE requires D0 HIGH with the logic port powered for ≥ 12 s, after ≥ 100 marker rises.
- **Ranges:** PPK2 auto-ranging is permitted, which is a change from the N6 protocol's R5-only rule because the RA board current is lower.

No window is excluded by hand, and warm-up is not trimmed.

## Statistics

- **Headline.** Gross energy per inference. For each session, take the mean over its valid repeat schedules' means. Across the three sessions, report the mean with a t-interval (n = 3).
- **Also reported:**
  - window-level repeatability CIs, labelled within-session;
  - dose linearity: OLS of window gross and (range-consistent) incremental energy against N;
  - the per-cycle series, lag-1 autocorrelation and trend.
- **Type-B**, reported separately and never merged into the CIs. It uses multiplicative worst-case bounds with RSS shown as secondary:
  - **PPK2 gain ±20 %.** The Nordic PPK2 UG v1.0.1 intro says "better than ±20 %". Table 9 lists ±10 % (R1–R4) and ±15 % (R5) for average readout. The conservative figure is used.
  - **VOUT band 4.85–5.10 V (−3 %/+2 %).** This is an **assumption**: Nordic gives no Source Meter accuracy, and one DevZone user measured 4.918 V at 5000 mV.
  - **S-term** at the setpoint, for the dominant range.
  - Same-setup ratios cancel gain and VOUT; absolute values do not.

## Not claimable from this data

- MCU core energy; the MCU-only point R3/CN1 is not used.
- Optimized-kernel energy. This is a strict FP32 portable QDQ implementation, not CMSIS-NN INT8.
- Energy at any other clock or cache configuration.
- A cross-board ranking against the N6 beyond "same model, same protocol, different board scope". The N6 scope is 5 V downstream of JP2 with an assumed VIN; the RA scope is the CN2 input at a PPK2 setpoint.
- Board sleep-mode energy, since the spin baseline is not sleep.

## Board state to document with the results

- J9 unplugged. The J-Link OB section's power state from CN2 alone is not characterized; the DEBUG/POWER LED is to be observed and recorded.
- P107 marker only; no other I/O.
- PPK2 logic port powered from J2-4.
- Room temperature not controlled.

## Amendment 1 (2026-09-29 22:20 +08, before any PPK2-powered run)

Made because CN2 is an unfitted 2-pin footprint, so dupont contacts there are
unreliable. J9 is no longer needed: build_03 is flashed and verified, and its
J9-powered bring-up is read back.

**Power entry changes from CN2 to the Arduino header.**
- PPK2 VOUT → J2-5 (+5 V) and PPK2 GND → J2-7 (GND). This is UM r20ut4958eg0100 Table 7 / Figure 12.
- J2-5 is the board's main 5 V net downstream of the CN2/J9 reverse-current protection.
  - Scope becomes "whole FPB-RA4E1 board at its main 5 V net". The protection element's own drop and loss are excluded.
- **Rule: J9 must stay unplugged whenever VOUT is on J2-5.** There is no protection between J9 and J2-5 in that direction, so J9 would back-feed the PPK2 VOUT.
  - The recorder refuses ON and switches OFF while the J-Link OB is on USB, but it cannot prevent a manual plug.

**Guard.** The overcurrent guard is lowered from 300 mA to **150 mA** (mean over 100 ms). The board is expected to draw well below 100 mA, and a lower guard limits the damage of a miswire.

**Diagnostic power-on.** One diagnostic power-on (`diag_01`) precedes the sessions. It is recorded and analyzed with the same pipeline, but it is **not pooled**. It establishes whether the logic port is powered (it read 0xFF during all J9-powered bring-up), the D0 marker path, the board current level and range, and end-to-end telemetry decoding on real hardware.
- If the logic port stays unpowered while the board runs from the PPK2, no D0-based measurement is possible. A further amendment would then be required before any measurement.

Everything else is unchanged.

## Amendment 2 (2026-09-30 00:08 +08, after diagnostic runs, before any formal session)

**Diagnostic history.** None of these runs is pooled; all raw data is retained.
- **diag_01–03, diag_05, diag_06 (ppk_main*, 22:20–23:11): 0 mA drawn at output ON.**
  - The board-side leads had no electrical contact: PPK2 female leads were pushed into the board's female J2/J5 headers, and some leads sat on wrong pins.
  - A PPK2-only self-test proved the PPK2 source output and logic port work: VOUT at 3.3 V into logic VCC gave logic byte 0x00 at ON.
- **diag_04 (22:47): board powered but miswired, excluded.** It drew 45–61 mA while D0 had no contact.
  - The extra ~40 mA relative to the corrected wiring came from that miswiring.
- **Stepwise bring-up with an independent probe (no recorder)** fixed and verified the wiring:
  1. Power only: 21 → 24 mA at the 2 s settle→parity transition.
  2. Logic VCC/GND added: logic powered 8.8 ms after ON.
  3. D0 added.
- **diag_07 (23:54–00:02): complete, all checks passed, not pooled.**
  - Telemetry CRC ok and 0 parity mismatches.
  - 5 wiring pulses at 0.0998 s; sham valid.
  - 5/5 schedules valid; 50/50 BENCH windows range-consistent.
  - Gross 3.476 mJ/inference, CV 0.03 %.

**Final wiring** (all board-side leads are male pins in the red female headers; J9 unplugged):

| PPK2 connection | Board connection |
|---|---|
| VOUT | J2-5 (+5 V) |
| Power GND | J2-7 **and** J1-7 (GND; two leads, same net) |
| Logic VCC | J2-4 (3.3 V) |
| Logic GND | J2-6 |
| Logic D0 | J5-5 (P107) |

This supersedes Amendment 1's single GND lead. The scope is unchanged: the board's main 5 V net.

**Code changes before the formal sessions**, none of which changes the definition of any value:
- **ppk2_session.py** re-sends `11 02` (source mode) together with the regulator on every open, as in IRNAS ppk2-api; sha256 f92f3c16….
- **run_sessions.py**:
  - the between-schedule incremental aggregates only range-consistent windows, as Amendment 1 / Quantities require;
  - an analysis exception is recorded as a problem instead of aborting later sessions;
  - sha256 c14880da….
- rm01_decode.py (00c6bb38…) and analyze_schedule.py (782ed8ba…) are unchanged since registration except the scope string.

**Marker-state artifact (pre-registered reporting).** diag_07 showed sham ΔI = −0.137 mA (95 % CI −0.145 to −0.129), i.e. the board draws less current while P107 is HIGH.
- This is below the 0.5 mA gate. It comes from the PPK2 logic-port D0 input network, and the N6 showed the same sign at −0.03 to −0.09 mA.
- Its direction of attribution is unknown: it may be an extra draw while LOW, or a reduced draw while HIGH.
- Therefore the formal results additionally report **gross ± |ΔP_sham|·t_inf** as a marker-state sensitivity band, with the sham-corrected incremental as already registered. The headline definition is unchanged.

**Formal sessions:**
- 3 power-on sessions run by `run_sessions.py` on recorder `ppk_main7` (Source 5000 mV, guard 150 mA), with output OFF ≥ 10 s between sessions.
- Each session must pass every validity rule above.

## Amendment 3 (2026-09-30 00:35 +08, after an independent adversarial review of diag_07, before any formal session)

An independent reviewer wrote their own PPK2 decoder, found the D0 runs themselves, and decoded the telemetry. Recomputing all 50 BENCH windows of diag_07 from the raw frames, they matched the pipeline to a relative difference of at most 4e-16. The headline was 3.4764 mJ/inference; the sham ΔI was −0.1369 mA. Every checksum, including the parity FNV 0xccc5eb8b, was recomputed independently.

**Stale logic byte (B1, fixed).** After output OFF the PPK2 keeps its last logic byte, and never returns to 0xFF. After diag_07 it held 0x01, i.e. D0 HIGH, for more than 1000 s.
- A formal segment opened 1 s before ON would therefore start with a fake D0 HIGH run. Slicing would then fail (141 vs 140 runs), and every session would be ineligible.
- **Fix:** frames before (output-ON sample + 0.5 s) are treated as logic-unpowered in memory. The board is physically unpowered there because J9 is unplugged, and RM01 holds P107 LOW for the first 2 s.
- The fix lives in `rm01_decode.analyze_capture(unpowered_before=)` and `run_sessions.analyze`.
- `test_diag07_regression.py` puts a 0x01 prefix into the real diag_07 capture. Without the mask the capture fails; with the mask it reproduces the numbers above exactly.

**Eligibility rule (fixed now, before any formal data).** This is the same rule as the N6 Amendment 3. A session is eligible iff all of the following hold:
- there is no boot-level problem (telemetry, firmware header, slicing);
- the wiring gate and the sham control are valid;
- at least 2 of the 3 repeat schedules are valid.

Dose schedules are auxiliary linearity checks. They are reported, but do not affect eligibility. Per-phase failures are reported in `phase_problems`.

**Driver robustness.**
- A try/finally always sends stop and off.
- Partial trailing CSV/JSONL lines are skipped.
- A missing segment_stop event aborts cleanly.
- DONE's rise counter now counts LOW→HIGH transitions between whole 10 ms bins, instead of bins. It remains a stuck-HIGH guard; about 125 rises are expected before telemetry, and 100 are required.

**Wording corrections to the original protocol.**
- **Rows.** The per-inference cycle count is *nearly* data-independent. Over the 1024 parity rows it spans 2 887 072–2 889 292 cycles, a 0.077 % range. On the 16 rows cycled in the schedules it is 2 888 441.0–2 888 441.7.
- **BENCH length.** BENCH is 1.386 s, not ≈1.5 s: `bench_reps` rounds 3.25 down to 3. OVERHEAD is 0.988 s.

**Additionally reported, descriptive only; no effect on eligibility or the headline.**
- The estimated GPT321/HOCO frequency next to the headline. diag_07 ran at 100.08–100.19 MHz, i.e. +0.16 %, so 28.84 ms/inference was measured against 28.884 ms at nominal.
- The idle-baseline asymmetry. Idle after BENCH was 0.073 mA below idle after OVERHEAD in diag_07; this makes the incremental estimate uncertain by about ±1.1 %.
- The power-on inrush: a 0.75 A peak and 62 R4 samples, outside every analyzed slice.
- The DEBUG/POWER LED state during a PPK2-powered session, as observed by the operator.

**Known, unquantified.**
- The PPK2 logic-port static load on the board's 3.3 V, which is inside the headline and at most the FXMA108 VCCB quiescent current per its datasheet.
- The J-Link OB section's power state when powered via J2-5.
- VOUT at the 5.000 V setpoint, which is unmeasured because no multimeter is available.

**diag_04 wording.** The extra ~40 mA is *attributed to* miswiring during that run. D0 had no contact, and logic leads were being moved. diag_07's bit-exact parity and 21–24 mA currents show no sign of damage.

**Code hashes for the formal sessions (sha256 prefixes):**

| File | sha256 prefix |
|---|---|
| run_sessions.py | d30c0a8c |
| rm01_decode.py | 94ab0ec4 |
| test_diag07_regression.py | bbe3f7e5 |
| ppk2_session.py | f92f3c16, unchanged |
| analyze_schedule.py | 782ed8ba, unchanged |

160 offline tests pass.

## Observation 1 (2026-09-30 00:57 +08, after the formal sessions; descriptive, no change to any definition)

The board was powered from the PPK2 via J2-5 with J9 unplugged, exactly as in the formal sessions, for two non-pooled captures: `led_check_01` and `led_check_02` in `ppk_main7`.
- **LED.** The operator observed the yellow DEBUG/POWER LED **blinking**. Per UM §5.2.1, blinking means the J-Link OB is powered but not connected to a host.
- **Scope consequence.** The J-Link OB section is therefore powered from the main rails. It is inside the registered board-level scope and inside the headline.
- **Current signature.** In `led_check_02`, during the parity phase (constant CPU load), the current shows a ~9.95 Hz square-wave modulation (third harmonic at 29.9 Hz) of about 0.8 mA peak-to-peak, alternating between 23.7 and 24.5 mA in 10 ms bins.
- **Averaging.** In 100 ms bins it averages out to 24.09–24.16 mA. The shortest analyzed window is 0.988 s, which spans more than 9 modulation periods.
- **Edge-phase effect.** The residual effect is bounded at ≈0.06 % of the window mean, consistent with the observed between-window CV of about 0.03 %.

## Erratum 1 and Observation 2 (2026-09-30 01:15 +08, after the formal sessions; no change to any definition or number)

**Erratum.** The heading of Amendment 3 says "00:35 +08". It was in fact registered at **00:25:37 +08** (16:25:37Z, `PROTOCOL.sha256`), before the first formal output-ON at 16:26:38.6Z.
- The external timestamp is GitHub's server-side branch creation for `wip/power-ra4e1-20260930`, at 16:26:19Z.
- The local line in `PROTOCOL.sha256` (16:26:37Z) was written after the push.

**Observation 2 (independent post-data review, 01:10 +08).**
- **Reproduction.** An independent decoder reproduced all three sessions: per-window agreement ≤ 4.4e-16 relative, and telemetry decoded independently.
- **Fresh boots.** The first wiring pulse came 33.55 / 33.56 / 33.55 s after ON in the three sessions.
- **Latched logic byte.** It was 0x01 before ON in all three sessions and cleared 10–11 ms after ON. The Amendment 3 mask removed exactly one stale run per session.
- **Session-2 dose intercept (+0.121 mJ).** This is 0.073 % of the smallest window. It is explained by a −0.1 % drift in idle-spin power, because the dose schedules always run last. Per-window idle-drift correction gives a CI that contains 0.
  - Descriptive only: no linearity criterion was registered for RA. Applying the N6 2 % rule is post hoc.
- **Clock.** Pure 1/f clock variation explains about 82 % of the between-session variance.
  - Clock-normalized to 100 MHz nominal, the sessions give 3.4831 / 3.4823 / 3.4821 mJ.
  - At exactly 100 MHz the headline would be 0 to +0.12 % higher.
- **Inrush.** Peaks were 0.34 / 0.92 / 1.02 A for about 0.65 ms, outside all analyzed slices. Session 3 briefly exceeded the PPK2 1 A rating.
