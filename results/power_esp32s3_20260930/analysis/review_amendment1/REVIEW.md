# Independent adversarial review — ESP32-S3 EM01 Amendment 1 (2026-09-30)

Reviewer scripts and outputs are in this directory. They are self-contained: own Nordic conversion, own D0 run finder and own alignment, with no imports from `analysis/*.py`. Scripts: `indep_sham.py`, `indep_align.py`, `indep_setup_checks.py`, `indep_gpio5_edges.py`, `indep_first2.py`, `indep_phase_levels.py`, `indep_idle_split.py`, `disasm_compare.py`, plus a `.json` output for each.

Everything was read-only: no hardware, no `control` FIFO, no process control, no repository file modified.

**VERDICT: BLOCKERS**

## BLOCKER

### B1 — Amendment 1's causal claim is refuted by data it already holds; the GPIO5 remedy will not work

The amendment (PROTOCOL.md l.168) says the artifact is "a load on the board side of GPIO4 that draws ~0.62 mA more while GPIO4 is driven LOW". Four independent lines of evidence show instead that the sham HIGH and LOW spans run different machine code, and that this code-instance effect is at least as large as the artifact.

1. **The sham is not "the same busy-wait" at machine level.** `wait_cycles` is inlined twice in `pulses()` (build_02 and build_03 have identical addresses):
   - HIGH span: loop at `0x420061d4..de`, within one 32-byte ICache line;
   - LOW span: loop at `0x420061fd..207`, which crosses the line boundary at `0x42006200`.

   Every other busy-wait is its own inlined copy too: 12 loops in `hal_entry`, 2 in `tel_word`.
2. **Marker-LOW busy-waits differ by up to 3.5 mA depending only on which loop copy runs** (diag_esp_01, `indep_phase_levels.json`, `indep_idle_split.json`):
   - The same marker state (LOW) and the same preceding activity (an OVERHEAD window) give:
     - IDLE loop `0x42006aa1`: 65.13 ± 0.22 mA (n = 45);
     - final-IDLE loop `0x42006cba`: 67.91 ± 0.25 mA (n = 5), i.e. **+2.78 mA**.
   - Adjacent 2 s gaps, both LOW:
     - sham→cal gap (`0x420067d6`): 64.49 mA;
     - cal→schedule gap (`0x42006a32`): 67.81 mA.
   - The 100 ms time series (`indep_phase_levels` / stdout) steps −0.8 mA and then +3.2 mA at these boundaries while D0 stays LOW.
   - The telemetry sync (marker **HIGH**, 300 ms) draws **+1.41 mA more** than the adjacent LOW gap. That is the opposite sign to the sham.
   - attrib_nod0_01 reproduces all of this with D0 detached.
3. **GPIO5 shows the same artifact.** wiringcheck_esp_01 (build_03, D0 on GPIO5; recorded 05:35, before Amendment 1 was registered at 05:37:21) gives:
   - Sham windows (identical two-window estimator, `indep_first2.json`):
     - GPIO5: −0.526 and −0.815 mA, mean **−0.67**;
     - GPIO4 in diag, same estimator, sliding over all 19 pairs: −0.43 to −0.90 mA.
   - Local edge steps: GPIO5 −0.85/−0.82 mA, against GPIO4 −0.69 ± 0.19 mA.
   - Wiring pulses: GPIO5 −0.42 mA mean, GPIO4 −0.41 (diag) and −0.51 (attrib).
   - Phase levels match diag within 0.1 mA: sham HIGH 64.75/64.75, gap 65.57/65.59, gap 65.75/65.82 mA.
4. The step is not a clean resistive edge: an ~40 % overshoot with 5–8 ms settling, the same with and without D0 (`indep_align.json`). It does not discriminate between a pin load and a CPU/LDO load step.

**Consequences.**
- diag_esp_02 on GPIO5 will almost certainly fail |ΔI| < 0.5 mA. Under Amendment 1 no formal session can then run.
- If a diag passed by chance, formal sessions would be selected on a noisy, code-driven gate.
- The "Reporting" line (l.207, "a marker-pin load on this board") would register a false finding.
- The header comment in `em01.h` (l.26–27) repeats the same wrong cause.

**Fix, before diag_esp_02.**
1. Register a dated Amendment 2 (or erratum) that withdraws the GPIO4-load attribution and cites this evidence.
2. Build build_04 so that every busy-wait executes one loop instance: `wait_cycles` as `__attribute__((noinline))`, ideally `IRAM_ATTR` with fixed alignment, through `derive_em01.py` as platform plumbing.
3. Verify by disassembly that exactly one `rsr.ccount` wait loop exists.
4. Run a non-pooled diag that must show:
   - sham |ΔI| well below 0.5 mA;
   - no LOW→LOW steps between phases.
5. Only then register the formal runs.

GPIO4 or GPIO5 does not matter; keep the pin unchanged relative to what the diag verifies.

## MAJOR

### M1 — The "incremental over spin" has no physical meaning on this platform as built

- The IDLE baseline depends on the arbitrary loop copy: the same-state spread is 64.5–68.0 mA, and the IDLE copies alone read 65.13 vs 65.68 mA.
- ±3.5 mA × 5 V × 24.85 ms ≈ ±0.43 mJ/inference, against the reported incremental of −0.20 mJ (PROTOCOL l.161, "BENCH draws 1.65 mA less than the IDLE spin").
- The sign of the incremental is therefore not determined.

**Fix:** the single-instance wait of B1. Until then, report the incremental as "not interpretable (spin-loop placement)".

### M2 — "Board not USB-powered" evidence exists only for session 1 of a fresh recorder

- The live recorder `ppk_esp8` has held a latched logic byte of 0x00 since 58 s, while the board is unpowered (`summary_10ms.csv`).
- Sessions 2 and 3 start from a latched 0x01. The native USB port cannot be seen by the guard.

**Fix:**
1. Start a fresh recorder immediately before diag_esp_02 and before the formal run.
2. In `run_sessions_esp.py`, record and require:
   - session 1: every pre-ON frame reads 0xFF;
   - sessions 2 and 3: the logic byte is constant, with no D0 transitions, from the previous `segment_stop` to ON. A USB-powered board would boot and toggle D0 during OFF.

### M3 — Instrument-link failures are undocumented, and the driver does not fail cleanly

- 5 of 9 recorders ended with `SerialException ... device disconnected`: ppk_esp1, 2, 4, 5 and 6.
- The kernel log shows the PPK2 moving between root-hub ports 1-6, 1-5 and 1-1 (operator cable handling). The 04:26:17 stall preceded its USB reset by 4 s.
- The amendment mentions only the stall.
- In the driver, if the recorder dies mid-session:
  - with a failed final OFF write, the status still says `output_on: true`, so `wait_done` waits the full 900 s;
  - `rec.command('stop')` then raises ENXIO in the `finally` block (a FIFO with no reader), and the driver crashes without an abort log or summary.
  - This is still fail-safe for validity: nothing becomes eligible.

**Fix:**
- Document the disconnects.
- Keep the PPK2 on a fixed port and plug nothing during runs.
- In the driver:
  - treat a stale `status.json` (utc older than 3 s) or a dead FIFO as an immediate abort;
  - catch OSError on commands;
  - write an abort record.
- Pre-register the replacement rule for sessions lost to instrument faults: all attempts reported, at most N replacements.

## MINOR (claim accuracy and robustness)

| Location | Problem | Fix |
|---|---|---|
| l.160 | "board current 63–66 mA" is wrong: OVERHEAD windows run 70.8–71.5 mA, and 1 s means reach 71.2 mA. | Say 63–71.5 mA. |
| l.160, l.161 | R4 except **0.14 s** (last non-R4 frame 0.1435 s), not 0.13 s. BENCH−IDLE is **−1.63 mA**, not 1.65. | Correct both numbers. |
| l.165, l.168 | The non-registered estimator gives −0.674 / −0.618 mA; the registered estimator gives −0.657 [−0.732, −0.581] (reproduced to 3e-14) and −0.604 [−0.674, −0.533]. The paired D0 share is **−0.053 mA (95 % CI −0.105 to −0.0005)**, so "≤ ~0.06 mA" understates the bound. The comparison uses one power-on per condition, and RA4E1's sham was −0.137 mA. | Report the registered numbers and the paired CI. |
| l.166 | The quadrature null is balanced by construction: each slot is half HIGH and half LOW. My value is +0.001/+0.003 mA. It tests only drift. | Say so. |
| l.167 | "Step completes within ~0.1 ms" is wrong: 75–92 % at 0.1 ms, then overshoot or undershoot, settling in 5–8 ms. | Reword. |
| l.171 | The "~0.25 mA offset in both states alike" holds only in the schedules (−0.24 mA). Sham and parity show −0.38/−0.43/−0.47 mA. | Report the phase dependence. |
| l.169 | The observation "GPIO4 read LOW while undriven" is correct (0 D0-HIGH samples from logic power-up at 8.97 ms to wiring), but "excludes" assumes a pull-up to an always-on rail. | Soften; the point is moot after B1. |
| l.192 | "~0.06 µA static VCC current" is not a measured current: the ON mean is 0.056 µA, but pre-ON was 0.104 µA and post-OFF 0.017 µA (R0 offset). | Say "indistinguishable from zero (≲0.1 µA)". |
| l.197, l.198 | 63.4–63.9 mA is the parity phase only (other phases 64.7–65.8 mA). Sham pulses are 1.000 s, not 1.01. Powered bins: my count is 3604/3605, first powered frame 7.09 ms. | Correct wording. |
| `live_sham.py` | No wiring/sham width checks, so any extra D0 run after the mask mis-indexes: a 0.1 s pulse with 50 ms guards gives a NaN mean, which prints "FAIL". Its LOW spans for j = 0 and j = 19 include other loop copies and the calibration (≈ −0.025 mA bias toward FAIL). It uses a z-CI. | Validate widths; refuse on NaN; use the registered span definition; abort only when the CI excludes the gate. |
| `run_sessions_esp.py` | Preflight does not check `guard_mA == 300`. `BUILD_MARKER_GPIO[a.build]` gives a KeyError (crash after the session) if a build is added to `esp_ops.BUILDS` only. No test covers the new check. | Add a guard check, `.get()` with a preflight refusal, and a unit test. |
| `analyze_diag_esp.py` | The diag "registered analysis" path lacks the driver's platform and marker-GPIO checks. | Apply the same checks. |
| `analyze_schedule.analyze_pulses` | The wiring gate ignores counter gaps. The self-test also had 2 counter discontinuities at OFF. | Include counter gaps in the gate; document the self-test gaps. |

## Verified correct

- **diag_esp_01 summary:** −0.657 [−0.732, −0.581], n = 20; 7.917 mJ, CV 0.14 %; 24.852 ms; 240.005 MHz; wiring 5 × 0.1000 s; no counter or reader gaps; the single ADC-rail frame at 8.45 ms (R0).
- **Attribution alignment:** −0.3 ms at 0.1 ms resolution (≈ −1 ms at 1 ms). BENCH-edge residual median +0.05 ms, max 4.6 ms, which is consistent with +0.75/5.3 ms at a −1 ms offset.
- **build_02 vs build_03:**
  - 768 functions, same names;
  - differences only in the marker constants in `window_begin`, `pulses`, `infer_row` (fail path) and `hal_entry`, plus the register reallocation in `tel_word` (one instruction fewer);
  - `pq_*` inference path and every loop address identical;
  - sdkconfig identical;
  - em01.bin differs in 114 bytes: `app_desc` SHA, one rodata byte 0x10→0x20 (the `gpio_config` mask), code, and the image checksum/SHA.
- **Flash record** matches `esp_ops.BUILDS['build_03']`: rc 0, 3 × "Hash of data verified", MAC ok, CH343P 5B5E017386.
- **Host code:**
  - The driver's marker check does make a session ineligible: it is appended to `res['problems']`, then `rd.eligible` excludes it from the aggregate.
  - There is no crash path when the header is None.
  - A wrong build is caught by the telemetry snapshot plus the flash-record binding.
- **Tests:** 22/22 pass (17 PPK2 + 5 EM01), run offline with no bytecode written.
- **Protocol hashes:** lines 1–145 hash to cca7ecb8; the full file to e73f3cfb. Working-tree code equals c582400.

## NOT DONE

- RA diag_07 regression and the RA formal re-analysis were not re-run.
- The second-directory reproducible rebuild was not re-verified.
- The physical mechanism behind the loop-instance current (cache bank/line or fetch alignment) is not established. Only the empirical effect is shown.
- RA4E1 `rm01` was not disassembled. `pulses()` has the same structure there, so the RA Amendment 2 attribution of −0.137 mA to "the PPK2 D0 input network" is also untested and should be checked.
- OFF ≥ 10 s was checked by code reading only: at least 12 s plus analysis time.
