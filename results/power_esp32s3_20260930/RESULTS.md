# ESP32-S3 N16R8 board-level energy per inference — result (2026-09-30)

## Headline (as registered)

**Setup.** One ESP32-S3 N16R8 DevKitC-1-compatible board: vendor code IC22071, CH343P bridge, ESP32-S3 rev v0.2, 16 MB flash, embedded 8 MB PSRAM.
- CPU 240 MHz from the 40 MHz crystal via the PLL.
- Radios off, no power management.
- Model weights flash-resident, read through the cache (DIO 80 MHz).
- Firmware EM01 **build_04**.
- The model is v5 NSL-KDD QCFS primary seed-0, 41→256→256→128→5, strict FP32 portable-QDQ C. It is bit-exact on all 1024 validation rows, and its parity output FNV 0xccc5eb8b is the same as on RA4E1, N6 and the host.

**Measurement.** Energy was measured at the board's **5V pin** with a PPK2 Source Meter at a 5.000 V setpoint, both USB ports unplugged. Whole-board energy is **7.98 mJ per inference**.
- The three power-on sessions gave 7.921 / 8.001 / 8.006 mJ.
- The mean is **7.976 mJ**, 95 % t-CI 7.858–8.094 mJ (n = 3). This is repeatability only, over one cold and two warm starts (see *Sessions*).
- **Systematic:** Type-B worst case **6.15–9.80 mJ** (−22.9 %/+22.9 %; PPK2 gain ±20 % plus the assumed VOUT band). The registered marker-state band is at most ±0.015 mJ.
- Each inference took **24.852 ms** at **0.321 W** (≈ 64.2 mA).
- All three sessions were eligible and there were no instrument faults. Every registered gate passed, as did the Amendment 3 code-placement checks C1–C3.

An independent reviewer used their own decoder on the raw frames (`analysis/review_formal/REVIEW.md`, verdict CLEAN).
- It reproduced every session headline to ≤ 4.4e-16 relative, the aggregate and its t-CI, the sham values, C1–C3 and the Type-B range.
- It independently decoded the telemetry (CRC ok) and verified all 245 windows and 115 run edges, and every registered gate in all three sessions.

## Sessions

| Session | Output OFF before ON | Gross per schedule, mJ (rep1, rep2, rep3, dose2, dose4) | Headline, mJ | Sham ΔI, mA (95 % CI) | Worst C3, mA | Inrush peak |
|---|---|---|---|---|---|---|
| esp_session_01 | 1103 s (**cold**) | 7.906, 7.927, 7.931, 7.961, 7.985 | 7.921 | +0.021 (−0.051, +0.093) | 0.017 | 0.325 A @ ON+143 ms |
| esp_session_02 | 24.0 s (warm) | 7.987, 8.006, 8.011, 7.997, 8.007 | 8.001 | +0.025 (−0.057, +0.107) | 0.138 | 1.025 A @ ON+6.9 ms |
| esp_session_03 | 23.6 s (warm) | 8.004, 8.008, 8.006, 8.021, 8.017 | 8.006 | **+0.120 (+0.037, +0.204)** | **0.420** | 0.989 A @ ON+8.4 ms |

- **Clock is not the cause.** The cold start is 1.03 % below the warm mean (8.0035 mJ), while the three sessions' CPU clocks agree to 0.2 ppm.
  - Session 1's IDLE current is 0.5–0.9 mA lower during its repeat schedules and has nearly caught up by 335–372 s. This is consistent with thermal warm-up, but temperature was not measured.
  - Session 2 also drifts +0.30 % within its repeat schedules.
- **Session 3 sham.** Its ΔI is small but its CI excludes 0. The gate (|ΔI| < 0.5 mA) passes; this is reported, not corrected.
- **Session 3 C3.** It is 0.420 mA against the 0.5 mA limit. A C3 failure would only have made that session's incremental uninterpretable.
- **Inrush.** The peaks are single samples within 150 ms of ON, inside the 1.5 s mask. Session 2's 1.025 A is slightly above the PPK2 1 A rating; the 300 mA/100 ms guard did not trip.
- **Counter gaps.** Session 2's 4 PPK2 counter discontinuities are single corrupted frames at ON + 6.7 and ON + 141.8 ms. They also lie inside the mask, and no samples were lost from any analysed window.

## Mandatory caveats

1. **Type-B worst case ±22.9 %, i.e. 6.15–9.80 mJ.** PPK2 gain accounts for ±20 %; the RSS bound is −20.3 %/+20.1 %.
   - VOUT was not measured; its band of −3 %/+2 % is an assumption. The S-term is taken in range R4.
   - Same-setup ratios cancel the gain only within the same PPK2 range.
2. **Board-level, not the SoC core.** The IRAM CPU-spin baseline is 0.314–0.318 W, 98.6 % of the BENCH power.
   - Incremental energy over the spin is **0.108 mJ/inference** (0.1065 / 0.1104 / 0.1072; CV 1.9 %).
   - Sham-corrected, it is 0.104 / 0.107 / 0.092 mJ.
   - As registered, incrementals are not comparable across boards.
3. **Warm-up drift**, reported as fixed in Observation 1 before any formal result.
   - Gross rises within a power-on: session 1 goes 7.906 → 7.927 → 7.931 mJ over its repeat schedules and reaches 7.985 at the last dose schedule.
   - Session 1 started cold, after 18.4 min unpowered. It is 1.03 % below sessions 2–3, which started warm after 24 s OFF (table above).
   - The between-session CI (±1.5 %) therefore contains this warm-up effect.
   - The dose-response intercepts are confounded by the drift, because the dose schedules run last, so they are not interpreted. Example, session 2: intercept −0.64 mJ with a CI excluding 0; slope 8.008 mJ/inference, CI 8.004–8.012.
4. **Marker-state band.** The sham ΔI was +0.021 / +0.025 / +0.120 mA (all ≪ 0.5 mA). That gives ±0.003 / ±0.003 / ±0.015 mJ, at most ±0.19 %, on gross.
5. **Scope.** The figure covers the whole board at the 5V pin:
   - the 5 V → 3.3 V LDO;
   - the CH343P, whose power state with USB absent is unknown;
   - the PSRAM (powered, not initialised) and the 16 MB flash (weights streamed through the cache);
   - the power LED, and the RGB LED (not driven);
   - the PPK2 logic-port load on 3V3 (VCC, GND and D0 by jumper leads).
6. **Conditional on build_04 and this configuration.**
   - Build_04 has flash-resident weights at DIO 80 MHz, and one non-inlined IRAM busy-wait.
   - FreeRTOS runs a 100 Hz tick on both cores; the measurement task is on core 0, and core 1 idles in WAITI.
   - Not claimable: QIO flash, DRAM-resident weights, PSRAM enabled, ESP-NN, radios on, other clocks.
7. **Amendment history** (all registered and pushed before any formal session; `PROTOCOL.md`):
   - **Amendment 1.** The first diagnostic (build_02, marker GPIO4) failed the sham gate at −0.657 mA. The cause was first misattributed to a GPIO4 board load, and the marker was moved to GPIO5.
   - **Amendment 2.** An independent review traced the offset to a firmware code-placement effect: the busy-wait was inlined into 16–18 distinct copies whose currents differed by up to 3.1 mA, so the sham's HIGH and LOW halves ran different code. Amendment 2 withdrew the GPIO4 attribution and made the busy-wait a single IRAM function (build_04).
   - **Amendment 3.** It pre-registered neighbour-based checks C1–C3 of the marker-LOW wait spans.
   - **Results.** diag_esp_02 (build_04) and all formal sessions pass the unchanged 0.5 mA sham gate and C1–C3. diag_esp_01, attrib_nod0_01 and diag_esp_02 are not pooled.
8. **RA4E1 note.** RM01 (RA4E1) has the same inlined-wait structure: `pulses()` in build_03 holds two copies, at 0x1a0 and 0x1c4, each within one 16-byte line.
   - The attribution of the RA4E1 sham ΔI (−0.137 mA, passed) to the PPK2 D0 input network is therefore not established; it may include code placement.
   - The RA4E1 gross headline and eligibility are unaffected, because BENCH windows contain no wait.
9. **One board**, room temperature not controlled, ~23 minutes of formal sessions.
10. **Cross-board comparison: board power × latency, not chip efficiency.**
    - **RA4E1.** 3.4785 mJ (28.85 ms at 0.121 W), with the same portable-QDQ C and the same protocol template.
      - It was measured in PPK2 range R3 and the ESP32-S3 in R4, so the gain errors do not cancel: the ≈ 2.3× ratio carries both boards' Type-B terms.
      - About 99 % of the ESP32-S3 gross, and 86 % of the RA4E1 gross, is baseline board power × latency.
    - **N6.** 49.41 mJ, measured differently, so it is not a like-for-like comparison:
      - the NPU deployment (SM06), not the portable C;
      - HSI 64 MHz with the I- and D-caches off;
      - PPK2 Ampere Meter mode at JP2 with VIN assumed (−12/+5 %);
      - scope: whole board minus the ST-LINK.
11. **Board-state records.**
    - The operator did not report the LED states; the power LED and the undriven RGB LED are inside the headline.
    - USB removal is shown by instruments rather than by an operator record: the logic port read 0xFF from recorder start to session 1 ON, and stayed latched at (1, 1) over each OFF gap.
12. **Items the reviewer did not re-derive**, covered by the registered pipeline and driver:
    - the BENCH/OVERHEAD checksums and the sum- versus counter-time energy rule (0.5 %) are schedule-validity rules, and all 15 schedules are valid;
    - the driver/decoder/analysis hashes and the build_04 flash record are checked and logged by the driver preflight.

## Provenance

- **Protocol and amendments.** `PROTOCOL.md`: registered cca7ecb8, then Amendments 1–3 and Observation 1. Hashes and times are in `PROTOCOL.sha256`.
- **External timestamps.** GitHub `wip/esp32s3-em01-20260930`: ccef3a6, c582400, 0564ee8, 19016bc, f53097c.
  - Amendment 3 was pushed at 22:36:48Z, before the first formal ON at 23:02:55.1Z.
  - Observation 1 (reporting rules only) was pushed at 23:03:48Z during session 1, before any formal analysis output (23:10:28Z).
- **Firmware.** EM01 build_04: `em01.bin` 1dea01ce…, `em01.elf` 5a8c2233…, reproducible. It was flashed at 06:23:11 +08 (`flash_em01_build04/`); 3 regions verified, MAC e8:f6:0a:8b:40:80.
- **Code.** Driver `run_sessions_esp.py` f83ff633…; shared driver b974229e…; decoder 69e67852…; analysis 782ed8ba….
- **Data.** `formal_20260930/` holds the per-session analysis, summary, code-placement check (`*_lowspan.json`), aggregate and driver log. The raw frames are kept locally in `ppk_esp10/*.u32le` and are not in git.
- **Reviews.** `analysis/review_amendment1/`, `review_amendment2/`, `review_diag02/`, `review_formal/`.
