# ESP32-S3 N16R8 board-level energy per inference — result (2026-09-30)

## Headline (as registered)

**Setup.** One ESP32-S3 N16R8 DevKitC-1-compatible board: vendor code IC22071, CH343P bridge, ESP32-S3 rev v0.2, 16 MB flash, embedded 8 MB PSRAM.
- CPU 240 MHz from the 40 MHz crystal via the PLL.
- Radios off, no power management.
- Model weights flash-resident, read through the data cache (DIO 80 MHz). Code runs through the instruction cache.
- Firmware EM01 **build_04**.
- The model is v5 NSL-KDD QCFS primary seed-0, 41→256→256→128→5, strict FP32 portable-QDQ C. It is bit-exact on all 1024 validation rows, and its parity output FNV 0xccc5eb8b is the same as on RA4E1, N6 and the host.

**Measurement.** Energy was measured at the board's **5V pin** with a PPK2 Source Meter at a 5.000 V setpoint, both USB ports unplugged. Whole-board energy is **7.98 mJ per inference**.
- The three power-on sessions gave 7.921 / 8.001 / 8.006 mJ.
- The mean is **7.976 mJ**, 95 % t-CI 7.858–8.094 mJ (n = 3). This is repeatability only, over one cold and two warm starts (see *Sessions*).
- **Systematic (Type-B), typical-spec envelope: 6.15–9.80 mJ** (−22.9 %/+22.9 %). This is not a guaranteed bound.
  - PPK2 gain in UG range R5 is ±15 % accuracy plus ±5 % offset, both typical, summed.
  - VOUT was **not measured**: its −3 %/+2 % band is an unverified assumption. At 4.918 V, the value one user reported, the headline would be 7.82 mJ.
  - The lead drop makes the figure 0.1–0.4 % higher than the energy at the board pin.
  - A known-load check with a DMM would replace these assumptions.
- The registered marker-state band is at most ±0.015 mJ.
- Each inference took **24.852 ms** at **0.321 W** (≈ 64.2 mA).
- All three sessions were eligible, with no instrument faults. Every registered gate passed, as did the Amendment 3 code-placement checks C1–C3.
- The logic port was powered in 100 % of the analysed frames after the mask.

**Re-analysis.** Separate automated re-analyses (AI agents run under the same operator) reproduce the result:
- The formal re-analysis (`analysis/review_formal/`) used its own decoder, with the pipeline's current conversion. It reproduced every session headline to ≤ 4.4e-16 relative, the aggregate, the sham values, C1–C3, the telemetry (CRC ok; 245 windows, 115 run edges, BENCH checksums) and every registered gate.
- The final instrument review (`analysis/review_final/A_instrument/`) re-implemented the current conversion from Nordic's official source (pc-nrfconnect-ppk `serialDevice.ts`, v4.4.1 = main@881d596). All 345 windows matched to ≤ 4.3e-16, and the official spike filter has no effect on any window.

## Sessions

| Session | Output OFF before ON | Gross per schedule, mJ (rep1, rep2, rep3, dose2, dose4) | Headline, mJ (between-schedule 95 % CI) | Sham ΔI, mA (95 % CI) | Worst C3, mA | Inrush peak |
|---|---|---|---|---|---|---|
| esp_session_01 | 1103 s (**cold**) | 7.906, 7.927, 7.931, 7.961, 7.985 | 7.921 (7.888–7.955) | +0.021 (−0.051, +0.093) | 0.017 | 0.325 A @ ON+143 ms |
| esp_session_02 | 24.0 s (warm) | 7.987, 8.006, 8.011, 7.997, 8.007 | 8.001 (7.969–8.032) | +0.025 (−0.057, +0.107) | 0.138 | ≥ 1.025 A @ ON+6.9 ms |
| esp_session_03 | 23.6 s (warm) | 8.004, 8.008, 8.006, 8.021, 8.017 | 8.006 (8.001–8.011) | **+0.120 (+0.037, +0.204)** | **0.420** | 0.989 A @ ON+8.4 ms |

- **Cold vs warm (post-hoc reading).** The cold start is 1.03 % below the warm mean (8.0035 mJ).
  - The registered per-schedule CPU-clock estimates span only 1.8 ppm (240.00467–240.00510 MHz), so the clock is not the cause.
  - Session 1's IDLE current is 0.5–0.9 mA lower during its repeat schedules and has nearly caught up by 335–372 s. This is consistent with thermal warm-up, but temperature was not measured.
  - Session 2 also drifts +0.30 % within its repeat schedules.
  - This reading was made after the data were seen. Observation 1 pre-fixed only the reporting of within-session drift.
- **Session 3 sham.** Its ΔI is small but its CI excludes 0. The gate (|ΔI| < 0.5 mA) passes; this is reported, not corrected.
- **Session 3 C3.** It is 0.420 mA against the 0.5 mA limit. A C3 failure would only have made that session's incremental uninterpretable.
- **No restart after ON.** In every session the first wiring pulse came 29.596–29.597 s after ON (all five PPK2-powered runs within 2.1 ms), so no restart followed the inrush.
- **Inrush.** The peaks are single samples inside the 1.5 s mask, and above the PPK2 **Source Meter rating of 600 mA** (1 A is the Ampere-mode rating).
  - Session 2's peak followed 5 saturated range-0 frames (ON + 6.54–6.62 ms), so its true value is unknown.
  - The 300 mA/100 ms guard did not trip.
  - Every analysed window is code 4 at ≤ 72 mA.
- **Counter gaps.** Session 2's 4 PPK2 counter discontinuities are 2 stale frames at range switches (ON + 6.7 and + 141.8 ms). They lie inside the mask, and no samples were lost from any analysed window.

## Mandatory caveats

1. **Type-B is a typical-spec envelope, not a guarantee.** It runs from −22.9 % to +22.9 % (the RSS combination gives −20.3 %/+20.1 %).
   - **PPK2 range naming.** ESP32-S3 is in code 4 = **UG R5**, where Table 9 gives ±15 % accuracy plus ±5 % offset, typical values for averaged readout.
   - **VOUT.** The band is an unverified assumption (see the headline). Its only cited source, DevZone thread 125227, is an unanswered report from one user of a low-reading unit.
   - **Zero offset.** The R5 zero offset cannot be checked from these data. One ADC code is 0.753 mA (1.18 %).
   - **ADC non-linearity.** Its effective step is ~1.5 mA. Gross is well dithered; the incremental (≈ 1 code) relies on the dither.
   - **Calibration flag.** The PPK2 metadata flag "Calibrated: 0" is undocumented.
2. **Board-level, not the SoC core.** The IRAM CPU-spin baseline is 0.314–0.318 W, 98.6 % of the BENCH power.
   - Incremental energy over the spin is **0.108 mJ/inference** (0.1065 / 0.1104 / 0.1072; CV 1.9 %).
   - Sham-corrected, it is 0.104 / 0.107 / 0.092 mJ.
   - As registered, incrementals are not comparable across boards.
3. **Within-session drift**, reported as fixed in Observation 1 before any formal result.
   - Gross rises within a power-on: session 1 goes 7.906 → 7.927 → 7.931 mJ over its repeat schedules and reaches 7.985 at the last dose schedule.
   - The between-session CI (±1.5 %) contains the cold/warm difference (post hoc; see *Sessions*).
   - All three dose-response intercepts exclude 0 (−5.51, −0.64, −0.81 mJ). Because the dose schedules run last, the drift confounds them, and they are not interpreted. Slopes: 8.006 / 8.008 / 8.021 mJ per inference.
4. **Marker-state band.** The sham ΔI was +0.021 / +0.025 / +0.120 mA, all ≪ 0.5 mA, giving ±0.003 / ±0.003 / ±0.015 mJ (at most ±0.19 %) on gross.
   - In build_04 the sham's HIGH and LOW halves run the same wait code, and C3 passes. The sham therefore measures the marker-state difference itself.
5. **Scope.** The figure covers the whole board at the 5V pin:
   - the 5 V → 3.3 V LDO;
   - the CH343P, whose power state with USB absent is unknown;
   - the PSRAM (powered, not initialised) and the 16 MB flash (weights streamed through the data cache);
   - the power LED, and the RGB LED (not driven);
   - the PPK2 logic-port load on 3V3 (VCC, GND and D0 by jumper leads).
6. **Conditional on build_04 and this configuration.**
   - **Build_04:** flash-resident weights at DIO 80 MHz, and one non-inlined IRAM busy-wait.
   - **Runtime:** FreeRTOS runs a 100 Hz tick on both cores; the measurement task is on core 0, and core 1 idles in WAITI. The figure is for back-to-back inference with a warm instruction cache; a cold-cache inference costs up to 0.8 % more cycles.
   - **Code-layout sensitivity is small.**
     - The weights sit at identical addresses in builds 02–04, and the hot 76-byte multiply-accumulate loop runs from the core's loop buffer.
     - Cycles per inference differ by ≤ 10 between build_02 and build_04.
     - BENCH − OVERHEAD current is −7.334 mA in build_02 and −7.286 to −7.340 mA in build_04, so the effect is ≤ ~0.05 mA (0.08 %).
   - **Not claimable:** QIO flash, DRAM-resident weights, PSRAM enabled, ESP-NN, radios on, other clocks.
7. **Amendment history** (all registered and pushed before any formal session; `PROTOCOL.md`):
   - **Amendment 1.** The first diagnostic (build_02, marker GPIO4) failed the sham gate at −0.657 mA. The cause was first misattributed to a GPIO4 board load, and the marker was moved to GPIO5.
   - **Amendment 2.** A separate automated review traced the offset to a firmware code-placement effect.
     - The busy-wait was inlined into 16–18 distinct copies, so the sham's HIGH and LOW halves ran different code. The spread across the marker-LOW wait copies was 3.42 mA.
     - Amendment 2 withdrew the GPIO4 attribution and made the busy-wait a single IRAM function (build_04).
   - **Amendment 3.** It pre-registered neighbour-based checks C1–C3 of the marker-LOW wait spans.
   - **Result.** diag_esp_02 (build_04) and all formal sessions pass the unchanged 0.5 mA sham gate and C1–C3. diag_esp_01, attrib_nod0_01 and diag_esp_02 are not pooled.
   - **Erratum 1.** Written after the formal sessions, it corrects wording and the Type-B basis. It changes no definition, gate or number.
8. **Same confound on the other boards.** Both boards' gross headlines are unaffected, because BENCH windows contain no wait. Their incrementals and marker bands inherit the ambiguity.
   - **RA4E1.** RM01 build_03 `pulses()` has two inlined wait loops (0x1a0, 0x1c4). The attribution of the RA4E1 sham ΔI (formal: −0.139 / −0.138 / −0.142 mA) to the PPK2 D0 input network is therefore not established.
   - **N6.** SM07M build_03 `main()` has 7 inlined timer-wait loops, two of them 30 bytes apart. The same applies to its sham (−0.03…−0.09 mA).
   - Errata are recorded with the RA4E1 and N6 results.
9. **One board**, room temperature not controlled, ~23 minutes of formal sessions.
10. **Cross-board comparison: board power × latency, not chip efficiency.**
    - **RA4E1.** 3.4785 mJ (28.85 ms at 0.121 W), with the same portable-QDQ C and the same protocol template.
      - It was measured in PPK2 code 3 (UG R4) and the ESP32-S3 in code 4 (UG R5), so the gain errors do not cancel: the ≈ 2.3× ratio carries both boards' Type-B terms.
      - About 99 % of the ESP32-S3 gross, and 86 % of the RA4E1 gross, is baseline board power × latency.
    - **N6.** 49.41 mJ, measured differently, so it is not a like-for-like comparison:
      - the NPU deployment (SM06), not the portable C;
      - HSI 64 MHz with the I- and D-caches off;
      - PPK2 Ampere Meter mode at JP2 with VIN assumed (−12/+5 %);
      - scope: whole board minus the ST-LINK.
11. **Protocol deviations (board state).**
    - The operator's per-run confirmation of USB removal and the LED states were not recorded; the power LED and the undriven RGB LED are inside the headline.
    - USB removal is established instrumentally: the logic port read 0xFF from recorder start to session 1 ON, and stayed latched at (1, 1) over each OFF gap.
12. **Not re-derived independently**, but covered by the registered pipeline and driver:
    - the OVERHEAD checksums and the sum- versus counter-time energy rule (0.5 %) are schedule-validity rules, and all 15 schedules are valid;
    - the driver/decoder/analysis hashes and the build_04 flash record are checked and logged by the driver preflight.

## Provenance

- **Protocol and amendments.** `PROTOCOL.md`: registered cca7ecb8, then Amendments 1–3, Observation 1 and Erratum 1. Hashes and registration times are in `PROTOCOL.sha256`.
- **External timestamps.** GitHub `wip/esp32s3-em01-20260930`: ccef3a6, c582400, 0564ee8, 19016bc, f53097c, 35e60bc.
  - Commit times are quoted; GitHub's server-side push times are ~2 s later.
  - Amendment 3 was committed at 22:36:48Z, before the first formal ON at 23:02:55.1Z.
  - Observation 1 (reporting rules only) was committed at 23:03:48Z, 53 s after that ON and during session 1, but before any formal analysis output (23:10:28Z). The only formal data the author had seen by then were two live 1 s current readings.
- **Firmware.** EM01 build_04: `em01.bin` 1dea01ce…, `em01.elf` 5a8c2233…, reproducible. It was flashed at 06:23:11 +08 (`flash_em01_build04/`); 3 regions verified, MAC e8:f6:0a:8b:40:80.
- **Code.** Driver `run_sessions_esp.py` f83ff633…; shared driver b974229e…; decoder 69e67852…; analysis 782ed8ba….
- **Data.**
  - `formal_20260930/` holds the per-session analysis, summary, code-placement check (`*_lowspan.json`), aggregate and driver log.
  - The raw frames are kept locally in `ppk_esp10/*.u32le` and are not in git.
  - A post-measurement health check (`ppk_healthcheck_01/`, output ON 08:23:30–08:24:07 +08) confirmed that the PPK2 and the board are unchanged. It is not part of the result.
- **Reviews.** `analysis/review_amendment1/`, `review_amendment2/`, `review_diag02/`, `review_formal/`, `review_final/{A_instrument,B_firmware,C_documents}/`.
