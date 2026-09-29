# Independent adversarial review: ESP32-S3 EM01 formal sessions (build_04)

Reviewer: independent re-analysis, 2026-09-30. Read-only on the repo except this folder.

- **Code.** `indep_check.py` is my own decoder: D0 runs, telemetry bits, CRC-32, header and window-table parse, FNV checksums, energies, sham, and C1–C3. The only import is `ppk2_session.Converter`, and it agrees exactly with my own Nordic formula (max relative difference 0).
- **Outputs.** `indep_esp_session_0{1,2,3}.json`.

## VERDICT: CLEAN

No blockers: every number and every registered gate reproduces. Three MAJOR reporting/wording fixes are needed before the claim is published.

## Independent numbers vs pipeline

| | Session 1 | Session 2 | Session 3 |
|---|---|---|---|
| Segment sha256 vs `segment_stop` | match (4607cf02…) | match (ea6eff5b…) | match (8f12c15c…) |
| Frames | 44 014 080 | 44 146 528 | 44 013 312 |
| D0 runs after ON + 1.5 s | 41 486 | 41 486 | 41 486 |
| Headline gross, mJ (mine = pipeline) | 7.921166 | 8.000894 | 8.006057 |
| Per repeat schedule, mJ | 7.9057 / 7.9272 / 7.9305 | 7.9865 / 8.0055 / 8.0106 | 8.0041 / 8.0083 / 8.0058 |
| Drift, schedule 0 → 2 | +0.31 % | +0.30 % | +0.02 % |
| Max relative difference, 30 BENCH windows | 2.2e-16 | 4.4e-16 | 2.2e-16 |
| Incremental, mJ (max relative difference) | 0.10650 (4e-14) | 0.11038 (7e-14) | 0.10720 (4e-14) |
| Sham ΔI, mA (95 % CI) | +0.021 (−0.051…+0.093) | +0.025 (−0.057…+0.107) | **+0.120 (+0.037…+0.204)** |
| C1 range, mA | −0.173…+0.067 | −0.109…+0.062 | −0.159…+0.134 |
| C2, mA | +0.198 | +0.149 | +0.096 |
| C3 (before / after), mA | −0.008 / +0.017 | −0.138 / +0.062 | **−0.420** / −0.042 |
| CPU clock (PPK2 time base), MHz | 240.00495 | 240.00492 | 240.00490 |

- The **pipeline has 1 D0 run per event**: the 41 486 D0 runs per session are 140 window runs, 1 sync run, 41 344 telemetry bits and 1 DONE run. There are no glitch runs or gaps ≤ 3 samples.
- **Sham and C1–C3 match the pipeline**: sham ΔI to max absolute difference 0, and C1–C3 to ≤ 3e-14 mA.

**Aggregate (mine = pipeline)**
- Gross 7.97604 mJ, sd 0.04759 mJ, 95 % CI (t₂ = 4.3027) 7.85782–8.09426 mJ, CV 0.60 %.
- Time per inference 24.85196 ms (sd 1.8e-5 ms).
- Incremental 0.10803 mJ (95 % CI 0.10288–0.11317).
- P_BENCH 0.32094 W.

**Type-B** (recomputed from the summaries):
- The VOUT band including the S4 term is −3.63 % / +2.44 %: S4·ΔV is −0.414 / +0.276 mA at 63.75 mA.
- Worst case −22.90 % / +22.93 %, i.e. 6.15–9.80 mJ. RSS −20.33 % / +20.15 %. Both match the summaries.

## Gates verified per session (all pass, all three sessions)

**Boot level.** Telemetry decoded independently: 1292 words, CRC-32 ok, bit widths 24–26 / 74–76 samples. Header:
- EM01 v1; stage TELEMETRY; error 0; pq_env 1; timer CCNT; 5/5 schedules;
- APB 80 / XTAL 40 / CPU 240 MHz; **marker_gpio 5**; **POWERON**; core 0; 16 MiB;
- CPU_PER_CONF 0x6 (CPUPERIOD_SEL 2, PLL_FREQ_SEL 1); SYSCLK_CONF 0xa8400 (SOC_CLK_SEL 1);
- model prefix 22dc7979…, vectors prefix cb5b3415…;
- parity: 1024 rows, 0 mismatches, **FNV 0xccc5eb8b**. I recomputed this independently as the FNV-1a of the embedded `rm_expected` (vectors sha cb5b3415…).

**Window table and checksums**
- My decoded 245-window table equals the pipeline's exactly.
- 140 HIGH windows map one-to-one onto 140 D0 runs. Run length vs CCOUNT/f residual is ≤ 1.05 samples.
- All 115 schedule run edges equal the pipeline's slice plus offset.
- BENCH checksums were recomputed from `rm_expected`: ×1 3467897573, ×2 2184088197, ×4 100179781. All windows match, with 64 / 128 / 256 iterations.

**Wiring and sham**
- Wiring: 5 × 0.100 s.
- Sham |ΔI| < 0.5 mA in all three sessions.
- All 3 repeat schedules are valid in every session.

**Logic port**
- It is powered in every frame from ON + 1.5 s to the end of each segment, and in every 10 ms bin until OFF.
- After the mask it is 100 % powered. The pipeline's 0.9943 counts masked frames as unpowered; raw values are 0.99770 / 1.0 / 1.0.

**Pre-ON board state** (`summary_10ms.csv`)
- Session 1: 0xFF (255, 255) in all 65 187 bins from recorder start, at −0.21 to −0.29 µA.
- Sessions 2 and 3: (1, 1) in all 2300 / 2263 bins from OFF + 1 s to ON, and also from OFF to OFF + 1 s, at 0.01–0.08 µA.
- Each session is a fresh POWERON boot. The masked region holds exactly one D0 run, the power-on artifact: 8.16 / 7.13 / 8.54 ms.

**Counter gaps**
- Sessions 1 and 3 have none.
- Session 2 has 4, at ON + 6.71, 6.72, 141.81 and 141.82 ms. They are single-frame counter corruptions (jumps +32/+34 and +2/0), so no frames were lost.
- The analysed extent starts at ON + 28.6 s, so all four gaps are outside every slice.

**Ranges**
- The whole analysed extent is 100 % R4 in every session: 35.5 M frames each, 0 switches.
- All 30 BENCH windows are range-consistent. The maximum sample is 77.0 mA.

**DONE.** The final D0 run lasts 13.52 / 14.86 / 13.51 s to the end of the segment and is fully powered. The driver's live values were 12.49 / 13.83 / 12.45 s, all ≥ 12 s.

**Protocol chain**
- Prefix hashes: 145 lines → cca7ecb8, 207 → e73f3cfb, 264 → 81436b20, 306 → 7509bf44, full file → c94e91fc.
- GitHub server-side push times (repository activity API) are 19:21:05, 21:38:50, 22:20:39, 22:36:50 and 23:03:50Z. Each is within 2 s of the logged time.
- The Amendment 3 push was 20 s before diag_esp_02 ON (22:37:10Z).
- The OFF gaps were 24.0 and 23.6 s, both ≥ 10 s.

## MAJOR

**M1. "Same model/protocol as RA4E1 3.4785 mJ and N6 49.41 mJ" is overstated for the N6 and misleading as a ranking.**
- The N6 figure used a different protocol and operating point:
  - PPK2 in **Ampere Meter** mode at JP2, with VIN assumed (band −12/+5 %);
  - scope is the whole board minus the ST-LINK;
  - R5-only rule;
  - **HSI 64 MHz with caches off**;
  - the **SM06 NPU deployment**, which its protocol says has "no CPU-only variant", not the portable C path.
- It is the same trained model with bit-exact outputs, but a different implementation.
- The ESP result is PPK2 R4 and the RA4E1 result is R3. Per-range calibrations are independent, so the ESP/RA ratio (2.29×) does **not** cancel the gain Type-B. "Same-setup ratios cancel" does not apply across boards.
- The gross is 98.6 % board baseline (0.321 W × 24.85 ms); the incremental is 0.108 mJ.
- The ESP protocol's own "Not claimable" section allows only "same model, same protocol, different board scope, clock and operating point".
- **Fix:** reword along the lines of the RA RESULTS item 7. Name the N6 protocol, mode, clock and NPU. State "board power × latency, not chip efficiency". Do not quote cross-board ratios as Type-B-free.

**M2. The between-session CI mixes a cold start with two warm starts.**
- Session 1 started after **18.4 min** unpowered: diag_esp_02 OFF at 22:44:31.9Z, ON at 23:02:55.1Z. Sessions 2 and 3 started after about 24 s OFF.
- Session 1 is **1.03 % below** the warm mean (8.0035 mJ).
- **Not a clock effect:** the clocks agree to 0.2 ppm.
- **Idle-spin current:** in the repeat schedules (78–224 s after ON), session 1 idle-spin current is 0.49–0.89 mA below sessions 2 and 3. By 335–372 s the gap has closed to −0.04…+0.37 mA.
- **Dose schedules:** session 1's dose schedules (run last) give 7.961 / 7.985 mJ, approaching sessions 2 and 3 (7.997–8.021).
- **Dose intercept:** session 1's dose OLS intercept is −5.51 mJ, against −0.64 / −0.81 mJ in sessions 2 and 3.
- All of this is consistent with thermal warm-up, **but no temperature was measured**. Also, session 2 drifts as much as session 1 within its repeat schedules (+0.30 % vs +0.31 %), so the drift is not purely a cold-start effect.
- The registered statistic is valid. Its reading as i.i.d. power-on variation is not.
- **Fix:** report per-session values with the OFF time before each ON, the cold/warm split (7.921 vs 8.001 / 8.006), and "warm-up consistent, not measured". Report the per-schedule values and drift per Observation 1; these are currently absent from the aggregate and summaries.

**M3. The headline must carry its Type-B.**
- The ±1.5 % CI is precision only. The absolute value is known to −22.9 % / +22.9 % worst case (6.15–9.80 mJ).
- The aggregate JSON has no systematic entry, and neither does the claim sentence.
- **Fix:** add both, together with the registered marker-state band gross ± |ΔP_sham|·t_inf: 0.0026 / 0.0031 / **0.0150** mJ, ≤ 0.19 %.

## MINOR

- **m1. Session 3 sham.** ΔI is +0.120 mA with a CI that excludes 0. The gate passes; report it.
- **m2. Session 3 C3 margin.** C3-before is −0.420 mA against the 0.5 limit. It affects incremental interpretability only.
- **m3. Inrush over the PPK2 1 A rating.**
  - Session 2 peaked at **1.025 A** at ON + 6.94 ms, with 5 R0 upper-rail ADC frames at 6.54–6.62 ms. The session 2 counter glitches coincide with this.
  - Session 3 peaked at 0.989 A (8.35 ms); session 1 at 0.325 A (142.7 ms).
  - All of it is inside the mask. Document it as in RA Observation 2.
- **m4. Registered board-state items are missing from the formal record:** the LED states (never reported) and the operator's USB-removal confirmation. The instrumented pre-ON evidence above covers "no other supply"; the LEDs, which are inside the headline, remain unrecorded. State this.
- **m5. Conditionality needs spelling out.**
  - The result depends on: build_04 layout; flash-XIP weights through the 32 KB cache at DIO 80 MHz; 240 MHz; FreeRTOS 100 Hz ticks on both cores; PSRAM powered but not initialised; LDO about 1/3 of input power; CH343P state unknown.
  - Amendment 2 showed code placement moves wait-loop current by up to 3.1 mA. For BENCH, build_02 vs build_04 diagnostics gave 7.917 vs 7.937 mJ (single sessions, confounded with thermal state).
- **m6. Observation 1 timing.** It was registered and pushed (23:03:50Z) 55 s after the first formal ON. This is disclosed and changes no definition. Keep the disclosure.

## NOT DONE

- OVERHEAD checksum (2082339437): not recomputed independently.
- Driver, decoder and analysis sha256 values against the registered code, and the build_04 flash record, MAC and binary hashes: not re-verified.
- diag_esp_01/02 raw data: not re-analysed. Their values are quoted from the protocol.
- Sum-vs-counter-time 0.5 % rule: not recomputed explicitly. It is covered implicitly by the ≤ 1.05-sample run-length residual.
