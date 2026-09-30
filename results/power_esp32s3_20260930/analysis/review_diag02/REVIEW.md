# Review of diag_esp_02_01 (build_04, ppk_esp9)

VERDICT: CLEAN

Own code: `indep_check.py` (output in `indep_check_out.json`) and `tel_decode.py`. Neither imports the pipeline modules.

## Recomputed
- **Segment.** sha256 f1e25156… matches `segment_stop`. 44 162 304 frames, with 0 counter gaps.
- **Logic port.** Only 0xFF before ON. Powered 6.96 ms after ON, and 0 unpowered frames after the mask.
- **D0 after the mask.** 41 486 runs, all clean: 140 windows, a 0.3 s sync run, 41 344 telemetry bits and a 15.0 s DONE run. This equals the recorder's `d0_rising`.
- **Telemetry, own decode.** CRC ok. The window table matches the pipeline in 245/245 rows.
- **Sham ΔI.**
  - Pipeline-style estimator: −0.0621 mA (CI −0.140 to +0.015); it matches the pipeline within 8e-6 mA per window.
  - Interior, two-sided: −0.073 mA.
  - OLS with a quadratic trend: −0.058 ± 0.047 mA.
- **Gross.** For all 30 repeat BENCH windows, my value and the pipeline's differ by at most 7e-16 (relative). The headline is 7.93716 mJ, CV 0.22 %.
- **Clock.** 240.00525, 240.00527 and 240.00485 MHz. Once corrected for that clock, the run lengths match CCOUNT within 1.25 samples, so no sample block was dropped.
- **C1–C3.** They match `lowspan.json`, and all pass:
  - C1: −0.03, −0.10, −0.02, +0.11, +0.07 mA;
  - C2: +0.13 mA;
  - C3: −0.09 / −0.05 mA.

## Gates
All pass, checked against my own decode:
- EM01; TELEMETRY; error 0; pq_env 1; parity 0 mismatches and FNV 0xccc5eb8b; CCNT; POWERON; core 0;
- APB 80 / XTAL 40 / CPU 240 MHz; register values 6 and 0xa8400; GPIO5; 16 MiB;
- wiring 5 × 0.1 s;
- 5/5 schedules, with checksums unique and as expected;
- all non-R4 frames within 0.14 s of ON; BENCH and IDLE all R4 with no switch;
- DONE; logic port powered; eligible.

## Against diag_esp_01
- **Time per inference.** −1.7 ppm.
- **BENCH power and gross.** Both +0.26 % (+0.17 mA), within the power-on-to-power-on offset.
- **IDLE and incremental.** IDLE fell from 65.34 to 62.97 mA (the IRAM loop). BENCH−IDLE went from −1.63 to +0.91 mA and is stable across schedules. Incremental is 0.113 mJ and is now interpretable.

## BLOCKER
None.

## MAJOR
None.

## MINOR
1. **Drift in gross.**
   - Evidence: gross rises 7.922 → 7.933 → 7.956 → 7.965 → 7.974 mJ. That is +0.43 % over the repeats; diag_esp_01 showed +0.26 %. The drift is common-mode, since IDLE rises too, and it includes an unexplained common-mode step of about +0.25 mA at ~150 s. The dose intercept (−3.13 mJ, CI excluding 0) is confounded by this drift.
   - Fix: report the drift. Describe the n = 3 CI as a trend plus noise, and do not read the intercept as a per-window cost.
2. **Power-on artifact.**
   - Evidence: the artifact lasts 6.96 ms under PPK2 power, against the registered 3.79 ms. It is still inside the mask.
   - Fix: record the value in the next amendment.
3. **Errata.**
   - "OVERHEAD = 32 346 reps" is calibrated at run time; this run used 32 287.
   - The em01.c calibrate comment says build_02 ran 1.19 s OVERHEAD windows, but diag_esp_01 ran 0.968 s. It probably means build_01.
   - Fix: note both in the report.
4. **`logic_powered_fraction`.**
   - Evidence: the 0.9943 value includes the frames forced unpowered by the mask. The gate is the per-slice `all()`, and the post-mask fraction is 1.0.
   - Fix: relabel the field.
5. **Informational.**
   - IDLE span scatter (±0.3 mA) is larger than BENCH scatter (±0.1 mA); the cause is unknown.
   - The recorder's single rail frame lies outside this segment.

## NOT DONE
None.
