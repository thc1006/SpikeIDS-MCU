# SM07M board-level energy measurement: pre-registered protocol

Written 2026-09-29, **before** any SM07M hardware measurement. Changes after
data collection must be listed in a dated amendment section. They must not
be made silently.

## Question

What is the board-input energy per inference of the frozen, bit-exact SM06
deployment of the v5 NSL-KDD QCFS primary seed-0 model on an unmodified
STM32N6570-DK, in its validated configuration?

## Fixed setup (not varied)

**Board**
- STM32N6570-DK (MB1939-C02), unmodified (no R23/R24/C27 rework).
- Dev boot. The LCD, camera, Ethernet and microSD are left uninitialized.

**Power path**
- PPK2 (serial F4728E9B55E0) in Ampere Meter mode, in series at JP2.
  - VIN is connected to JP2-1 (5V_STLK).
  - VOUT is connected to JP2-2 (board 5 V bus).
- No JP2 jumpers. PPK2 GND goes to CN8-6.
- CN6 connects the ST-LINK to the host. CN18 is not connected.
- Power-up order: the PPK2 path is closed while 5V_STLK is dead, then CN6 is plugged in.

**Marker**
- PH8 = Arduino D12 = CN12-5, feeding PPK2 D0.
- Logic VCC comes from CN2 VDDIO; logic GND from CN2 GND.
- Not PE15/D13, because UM3300 wires that pin to LED LD6.

**Firmware**
- SM07M `firmware_sram_measure/build_03` over SM06.
- Object-level identity with SM06 is verified by `test_objects.py`.
- Platform stage is unchanged: nominal HSI 64 MHz, I-cache and D-cache off, NPU polling.

**Rows**
- The first 16 of the frozen 1024 validation rows, cycled.
- Timing does not depend on the data: 1024-row cycle SD is 0.03 %.

## Sequence per power-on (one "session")

1. **Parity.** All 1024 rows run through the measured batch path. Any bit
   that differs from the accepted SM06 run08 outputs, or any failure of the
   original `evaluate()` policy, means **no measurement**.
2. **Wiring.** Five 0.1 s marker pulses. D0 must show exactly 5 clean pulses.
3. **Sham (null control).** Twenty 1 s HIGH / 1 s LOW periods. The CPU runs
   the same busy-wait in both states.
   - |mean ΔI| ≥ 0.5 mA means **no measurement**, because the marker pin is loading the board.
   - The sham ΔP and its CI are reported as the method floor.
4. **Calibration.** Firmware timing only, no capture. It sizes the windows so
   that BENCH ≈ 1.5 s and OVERHEAD ≈ 1.0 s.
5. **Schedules.** Each schedule is: 3 preamble pulses, then 10 cycles of
   [IDLE 1 s, BENCH, IDLE 1 s, OVERHEAD], then a final IDLE.
   - 3 repeat schedules (×1).
   - 2 dose schedules (×2 and ×4 inferences per BENCH window).

## Quantities

- **Scope.** Whole-board 5 V input downstream of JP2, minus the ST-LINK.
  This is **not** the SoC core or NPU.
- **Voltage.** V = 5.0 V is assumed; 5V_STLK is not measured.
- **Energy per inference**, where N is inferences per window and T is window duration:
  - gross = V·∫I dt / N
  - incremental = (P_BENCH − P_IDLE)·T / N
  - P_IDLE is the mean of the two adjacent busy-wait gaps, each trimmed by 50 ms guards.
  - Incremental is therefore the cost over a CPU **spin**, a lower bound on marginal cost versus sleep.
  - vs-overhead = (P_BENCH − P_OVERHEAD)·T / N, reported as a sensitivity.
- **Also reported:**
  - charge per inference;
  - ΔI in mA and in ADC codes (about 0.78 mA per code in R5 for this unit);
  - OVERHEAD ΔP;
  - sham ΔP;
  - the CPU clock estimate from DWT cycles against PPK2 window duration.

## Validity rules

A capture is invalid, and is reported but not pooled, if any of these hold:

- PPK2 counter discontinuity.
- A window's clock estimate differs from the median by more than the tolerance.
- Any analyzed span leaves range R5, or any sample exceeds 1 A.
- D0 is HIGH at segment start or end.
- The number or order of HIGH runs differs from the firmware window table.
- A BENCH or OVERHEAD checksum differs from the value expected from the
  bitwise-verified parity outputs, or checksums differ between repeated windows.
- The first host poll finds the command still running, meaning SWD traffic
  may have fallen inside a window.
- The PPK2 output dropped or the guard tripped.

No window is excluded by hand. Warm-up is not trimmed. The per-cycle series,
trend and lag-1 diagnostics are reported instead.

## Statistics

- **Headline.** Incremental and gross energy per inference, with a t-interval
  over the **schedule means** of the valid repeat schedules.
- **Across power cycles.** With ≥ 3 power-cycled sessions, the headline
  becomes a two-stage t-interval over the session means (`aggregate_sessions.py`).
- **Repeatability.** Window-level t-intervals, labelled as within-session repeatability.
- **Linearity.** OLS of window incremental energy against N, over all valid
  schedules. The intercept's CI must contain 0, or the intercept must be
  below 2 % of the smallest window's energy.
- **Type-B budget**, reported separately and never merged into the CIs:

  | Source | Bound | Applies to |
  |---|---|---|
  | PPK2 R5 gain | ±15 % typ | all |
  | VIN band 4.4–5.25 V | −12 / +5 % | all |
  | S-term voltage convention | ≈1.1 % | gross only |

  Same-setup ratios cancel the gain and VIN terms. Absolute values do not.

## Not claimable from this data

- SoC, core or NPU energy.
- Energy at a deployment operating point (800 MHz, caches on).
- CPU-versus-NPU attribution, since there is no CPU-only variant.
- Any cross-board ranking (ESP32-S3, RA4E1) unless those boards are measured
  with the same scope, method and model.
- "The PPK2 is calibrated": the metadata `Calibrated: 0` is undocumented.

## Board state to document with the results

- LCD backlight not driven.
- Camera, Ethernet and SD not initialized.
- Debugger attached with TRCENA on.
- PPK2 logic-port VCC load on VDDIO.
- Room temperature not controlled.

## Amendment 1 (2026-09-29 17:25, before any schedule/sham capture)

Made after runs 01 and 02 stopped at the wiring gate. That stop was traced to an
intermittent contact of the D0 jumper at D12: SWD toggling of PH8 changed the pin
(IDR) but not PPK2 D0; after re-seating, 8/8 toggles followed. No energy window has
been captured yet. Pilot observation from the bring-up/parity stream, found by the
round-2 reviewer: board current ≈ 108.5 mA during inference, busy-wait spin and main
loop alike (core halted ≈ 107.3 mA). Incremental-over-spin is therefore ≈ 0 at board level.

**Headline.** Changed to **gross board-input energy per inference**. The CI is over
the schedule means of the valid repeat schedules, with the Type-B budget reported
separately.

**Reported as bounds, not as the headline:**
- incremental-over-spin
- sham-corrected incremental
- vs-overhead

**Resolution.** R4/R5 top-range ADC code = 0.7455 mA for this unit (4·1.8/163840/R·GI).
This replaces the earlier rough value of 0.78.

**Lost-sample rule.** Per-kind, in samples: a window is invalid if
|N_meas − N_pred| > 32 + 2e-5·N_pred, where N_pred comes from DWT cycles and that
kind's median clock. Each segment is also invalid if |frames/100 kS/s − host
duration| ≥ 0.1 s.

**Type-B budget.** Computed at the measured current. For gross energy the S-term
enters as S4·(V_a − V_true)/I. The Nordic-app convention (S-term at VDD = 4.0 V)
is reported as a separate offset.

**Validity additions:**
- The sham must also end with D0 LOW.
- All captures are valid only if wiring passed, sham valid, ≥ 2 valid repeat
  schedules, and gross dose-response linear.
- The aggregator pools only runs with MEASURE_RESULT.all_captures_valid and no FAILED.json.

**Wiring diagnosis.** PH8 is polled over SWD during the wiring pulses only. This is
not a measured window.

**Recorder provenance.** session_02 runs ppk2_session.py as it was at 16:20. The
current file only adds two file close() calls at exit. The exact running source is
saved as recorder_ppk2_session_<sha8>.py.

## Amendment 2 (2026-09-29, after run_03; applies to run_04 onward)

run_03 completed every phase. All five schedules were invalid under Amendment 1's
per-window sample-count rule, so **run_03 is a pilot and is never pooled.**

Its own data show two separate effects:

1. **HSI clock wander.** The HSI RC oscillator wanders by about 0.05–0.1 %
   between windows. BENCH window DWT cycles are constant to about 500 cycles,
   while sample counts differ by up to +244 samples. A loss can only remove
   samples, so a positive residual means the clock wandered. The per-window
   sample-count rule is therefore **not** a valid loss detector here. It is now
   descriptive only.
2. **Real sample loss.** dose×4 lost 5.8 s of samples: 111.275 s of frames
   against 117.049 s of host time. At the same moment there were host reader
   stalls of 0.3–1.9 s under disk-IO pressure (PSI io full avg60 ≈ 6 %), caused
   by concurrent workloads on the workstation.

New rules:

- **Recorder.** The recorder (ppk2_session.py) now drains USB in a dedicated
  thread that never touches the disk. Any gap longer than 0.1 s between reads is
  logged as a `reader_gap` event.
- **Reader gaps.** A capture containing any reader gap is invalid.
- **Host time.** A segment is invalid if |frames/100 kS/s − host duration| ≥ 0.05 s.
- **Energy cross-check.** Gross energy is also computed as mean power × DWT
  cycles / median clock. Sum-based and DWT-based must agree within 0.5 % per
  window.
- **Recorder version.** The driver refuses to run unless the recorder process
  runs the current ppk2_session.py.

A fresh power-on (session_03) is required, which is also the second independent power-on.

**Pilot values from run_03**, all schedules invalid and descriptive only:
- Gross board energy: 49.436–49.449 mJ per inference across 5 schedules.
- Incremental over spin: 0.03–0.04 mJ.
- HSI: 63.81–63.89 MHz.
- Sham ΔI: −0.058 mA (95 % CI −0.102 to −0.013).

## Amendment 3 (2026-09-29, after run_04, before run_05)

In run_04, dose×4 was invalid only because frames/100 kS/s differed from the
host time between the segment start and stop events by −0.987 s. The evidence
shows this was not data loss:

- The recorder logged no reader gap (> 0.1 s) in that segment, so the kernel
  buffer was drained continuously.
- Counters were continuous.
- The step appeared at the stop event.
- Sum-based and DWT-based energy agreed for every window.

With the threaded recorder, segment boundaries fall wherever the consumer thread
processes start/stop. Under disk stalls the consumer lags the reader, so queued
samples land outside the segment. The frames-vs-host check therefore measures
consumer backlog, not loss.

Changes:

- **Frames-vs-host is now descriptive.** Loss detection is reader gaps plus
  counters (unchanged).
- **Pooling eligibility** is based only on headline-relevant captures: wiring
  passed, sham valid, and ≥ 2 valid repeat schedules. Dose schedules are
  auxiliary linearity checks. Their validity and linearity are reported but do
  not gate a session's headline.
- **Applied to run_04's eligibility.** Its headline captures (wiring, sham,
  3/3 repeat) were all valid under the rules registered when it ran
  (Amendment 2). Its dose×4 stays reported as invalid under Amendment 2.
- **Next sessions.** run_05 and run_06, each on a fresh power-on (CN6
  replug), complete ≥ 3 power-cycled sessions: run_04, run_05, run_06.

## Amendment 4 (2026-09-29 evening): errata and corrections from the final independent review

This amendment only records corrections. No data were collected after Amendment 3
except run_05 and run_06, and none of the numbers below change the raw data or the
per-schedule analyses. An independent re-implementation of the decoder and window
logic reproduced all 15 schedules, the three session means and the headline to
≤ 1e-15 relative.

1. **Erratum, Amendment 1 header.** The header says "17:25". The authoritative
   registration time is the hash log: 17:13:30 local, before run_03's INTENT
   (17:13:41). The registered text itself is left unchanged.
2. **Correction, Amendment 2.** "Lost 5.8 s" overstates the loss. Compared with the
   same dose×4 schedule in later sessions, about 3.2 s of samples were lost. The
   other ~2.6 s was stop-timestamp latency.
3. **Correction, Amendment 3's explanation; the conclusion stands.** run_04 dose×4's
   −0.987 s came from `stop_segment()` running fsync before it took the stop
   timestamp. The control-stop event lagged by only +0.0028 s. That segment's frame
   span (114.476 s) matches the same schedule in run_05/run_06 within 8 ms, so no
   samples were lost.
4. **Type-B wording and values.** The earlier "−20 %/+16 % bounds" were a
   root-sum-square (RSS), not bounds. Nordic's product listing states the PPK2
   accuracy as "better than ±20 %"; the ±15 % figure could not be confirmed in the
   user guide. Using ±20 %:

   | Quantity | Combination | Range |
   |---|---|---|
   | Gross | RSS | −24 %/+21 % |
   | Gross | worst-case sum | −31 %/+27 % |
   | Incremental | RSS | −23 %/+21 % |
   | Incremental | worst-case sum | −32 %/+25 % |

   Worst-case figures are reported as bounds; RSS is labelled as such.
5. **Incremental wording.** Do not write "≈ 0". Report it as at most 0.1 mJ per
   inference (≤ 0.2 % of gross) over a CPU spin.
   - Sham-corrected incremental is positive: +0.027 / +0.044 / +0.070 mJ for run_04 /
     run_05 / run_06.
   - The originally pre-registered incremental dose-linearity check has not been a
     gate since Amendment 1. It fails in run_04 and run_06, and this is disclosed.
6. **ADC code scale.** 0.7455 mA/code is the first-order value. The local slope at
   108 mA is 0.7595 mA/code, so values quoted in codes are about 1.9 % too high.
   Values in mA are unaffected.
7. **Strict sensitivity for run_04's eligibility.** Amendment 3 changed eligibility
   after run_04's data were seen, so the headline is reported both ways:

   | Rule | Sessions | Gross energy per inference (95 % CI) |
   |---|---|---|
   | Amendment 3 | run_04, run_05, run_06 (n = 3) | 49.41 mJ (49.31–49.51) |
   | Strict | run_05, run_06 (n = 2, t₁ = 12.71) | 49.39 mJ (49.17–49.61) |

   Per session: run_05 49.37 mJ (49.30–49.44), run_06 49.41 mJ (49.36–49.45).
8. **run_07 not performed.** The PPK2 was moved to FPB-RA4E1. A further N6 session can
   be added later on a fresh power-on under the same rules.
9. **Known weakness, future work.** The sum-vs-DWT energy check cannot detect a single
   64-sample loss, because HSI wander of up to 900 ppm between windows exceeds it.
   The host-lag drift check (host time − sample time, linear fit) is the effective
   whole-session loss audit. It showed session_03 within ±0.8 ms of a 4.1 ppm line,
   and it should be added to the pipeline.

### Amendment 4a (erratum to Amendment 4, item 4)

Worst-case bounds must combine multiplicatively, because both terms are factors. The correct values are:

| Quantity | Worst-case bounds |
|---|---|
| Gross | −31 %/+27 % (unchanged) |
| Incremental | −30 %/+26 % (Amendment 4 wrongly gave −32 %/+25 %, an additive sum) |

`analyze_schedule.systematic_budget()` now reports these values directly, using ±20 %.
