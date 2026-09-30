# Independent adversarial re-review: ESP32-S3 EM01 Amendment 2 (2026-09-30)

**Scope.** This review checks the Amendment 2 fixes (PROTOCOL.md l.208–264, commit `0564ee8`) against every finding in `../review_amendment1/REVIEW.md`, and looks for any new bug those fixes introduce.

**Conduct.** Everything was read-only:
- no hardware, serial port, tmux session or `control` FIFO was touched;
- the test recorder overrides `command()` so it raises if called;
- no commit was made.

**Working tree.** It equals `0564ee8` for all 131 tracked files under `tools/{esp32s3,ra4e1}_deployment`, `tools/ppk2_energy` and `results/power_esp32s3_20260930`. The only differences are:
- the post-commit external-timestamp line appended to `PROTOCOL.sha256`;
- the `ppk_esp1` event and session files.

**Scripts** (all in this directory):
- `drv_exercise.py`: pure functions of the driver, run on recorded data;
- `wc_sham_recompute.py`: wiringcheck sham windows;
- `ls_harness.py`: live-sham harness;
- `fw_check_build04.txt`: disassembly and object evidence.

**VERDICT: CLEAN.** There is no blocker. One MAJOR item, a pre-registration gap, should be closed before diag_esp_02 starts. A fresh recorder, `ppk_esp9`, has been running since 22:25 Z.

## BLOCKER

None.

## MAJOR

### A2-M1: The B1 acceptance test for build_04 is not pre-registered

Review-1 B1 fix step 4 required a non-pooled diag that shows two things:
1. sham |ΔI| **well below** 0.5 mA;
2. **no LOW→LOW steps between phases**.

Only then were the formal runs to be registered.

Amendment 2 does not do this:
- It already registers the three formal sessions (Next 5).
- Its only condition is "If diag_esp_02 fails the sham gate (< 0.5 mA)".
- There is no criterion that the code-placement effect is gone: IDLE vs final-IDLE, gap vs gap, and sham-LOW vs IDLE were 64.5–68.0 mA in diag_esp_01.
- There is no rule for what happens to the incremental-over-spin if that effect persists.

Consequences:
- A sham that passes by chance, or a residual effect not caused by loop placement, would still admit formal sessions.
- The incremental would then be reported without a registered interpretability test. That is the M1 risk again.

**Fix.** Before diag_esp_02, add a short Amendment 3 that registers:
- a LOW-uniformity check with a threshold. For example, every marker-LOW wait span (sham LOW, gaps, IDLE, final IDLE) must lie within ±0.25 mA of the sham-LOW mean, computed in the registered analysis;
- the consequence of failing it: the incremental is reported as "not interpretable" and the gross headline is unaffected, or no formal sessions are run.

## MINOR

1. **The dead-recorder claim is broader than the code.**
   - The amendment says a stale or unreadable status "ends the run with an abort record". It doesn't in every case.
   - `wait_done_esp` does flag `instrument_fault`. But when the FIFO still has a reader, `stop` and `off` succeed and `alive` stays True, so the loop continues to the next session.
   - If `segment_stop` is missing, the loop breaks before `results.append`, so that fault is absent from `ESP_SESSIONS_AGGREGATE.instrument_faults`.
   - This is fail-safe: the session is not DONE and therefore ineligible.
   - Fix: after `wait_done_esp`, add `alive = alive and not done.get('instrument_fault')`, and append a stub result before every `break`. Alternatively, reword the text.
2. **The OFF-gap latch check has a blind spot.**
   - When the latched byte is 0x00, a USB-powered reboot also reads 0x00: D0 is LOW and D1–D7 are LOW.
   - Evidence from `ppk_esp8`: USB appeared at OFF + 2831.8 s, but the byte first changed at +2871.8 s, 40 s later, at the wiring pulses.
   - This does not matter for formal sessions. They end at DONE with the byte latched at 0x01, which is (1,1) in `ppk_esp2`, so a reboot shows up at once.
   - Fix: when the previous session was DONE, require the gap state to be exactly `[(1, 1)]`.
   - The session-1 window from preflight to ON (about 2 s) is not re-checked. Also run `logic_states(rec, 0, on_ev)` for k = 0.
3. **The USB-guard classification uses a cumulative counter.**
   - It relies on `usb_guard_present_while_on`, which counts over the recorder's lifetime.
   - After any earlier trip, a later OFF without a guard would be classed as a gate failure, not an instrument fault. That is the conservative direction.
   - Fix: compare against the value at session start.
4. **Review-1 minors still open:**
   - There is no unit test for the new driver checks.
   - The 5/9 `SerialException` disconnects and the "fixed port, plug nothing" rule are not documented. The replacement rule is registered.
   - The self-test's 2 counter gaps at OFF are not documented.
   - The l.197–198 wiringcheck wording still says 63.4–63.9 mA (that is the parity phase only), 1.01 s (actual 1.000 s) and 3602/3603.
   - The diag_esp_01 incremental is not labelled "not interpretable".
   - The `em01.h` l.26–27 comment still states the withdrawn GPIO4-load cause. It is part of the build_04 sources, so leave the file alone and note it in the protocol.
5. **Wording in Amendment 2:**
   - "The BENCH code is unchanged" is not exact:
     - the per-inference loop inlined in `hal_entry` has permuted registers and one moved stack slot;
     - it moved from 0x42006ade to 0x42006aaa (line offset 30 → 10);
     - every `pq_*` function moved by −164 B.

     Say "instruction-equivalent; placement differs".
   - "Inlined 19 times" counts the call sites in build_04. build_03 has 16–18 distinct CCOUNT loops (heuristic counts: pulses 2, tel_word 2–3, hal_entry 13).
   - The wiringcheck values −0.526 / −0.648 mA are correct for a two-sided-LOW estimator:
     - W0 uses the wiring→sham gap;
     - W1 uses a truncated 0.36 s after-span;
     - review 1's one-sided W1 is −0.815, and the registered-style W0 is −0.327.

     Name the estimator.
   - The "second-directory rebuild byte-identical" claim has no artefact in the repo.
   - The IDLE baseline is now an IRAM spin (RA4E1 spins from flash), so the incremental values are not comparable across platforms.
6. **`live_sham.py`:**
   - At j = 0 and j = 19 it does not use the registered span. j = 19 includes 5 s of gaps and calibration, which biases the mean by −0.034 mA toward ABORT.
   - It uses z = 1.96 instead of t₁₉ = 2.093, which makes the CI 6.8 % narrower.
   - A wrong ABORT would need a per-pulse sd below about 0.077 mA (diag_esp_01 had 0.139), so the risk is theoretical.
   - ABORT and CONTINUE both exit 0.
   - The docstring still says "marker pin is clearly loaded".

## Verified correct

- **Firmware (build_04).**
  - `derive_em01.py --check` passes. Each substitution is asserted to apply exactly once.
  - `rm01.c` is unchanged: daaf2bd6… in the working tree, at c582400 and at 0564ee8.
  - The sim defines `EM_WAIT_ATTR` as `noinline`; `test_em01.py` passes 5/5 (temp directory, `-B`).
- **Busy-wait disassembly.**
  - Exactly one CCOUNT busy loop exists: `wait_cycles` at 0x40377c70. It is in IRAM, aligned (mod 16 = 0) and 28 B long.
  - Its body is `entry`, 3 × `rsr.ccount`, `sub`, `bgeu`/`bltu`, `nop.n`, `retw.n`: no `l32r`, no load, no call.
  - It has 19 `l32r`+`callx8` sites: pulses 2, tel_word 2, hal_entry 15.
  - These cover settle, gaps, IDLE, schedule pulses, sham HIGH/LOW and telemetry.
  - No other application function has a CCOUNT loop.
- **Runtime safety.**
  - The maximum wait is a 2 s gap, 480e6 cycles, which is below 2³²; the unsigned difference is correct.
  - The windowed ABI and IRAM use (about 51 of 350 KiB) are sane.
- **Objects.**
  - Only `em01.c.obj` differs. The other main objects and the 610 library objects are identical, and sdkconfig is identical.
  - `infer_row`, `window_begin` and `hex_prefix` are instruction-identical.
- **Pins.**
  - The `esp_ops.BUILDS['build_04']` pins equal the file hashes.
  - `DEFAULT_BUILD` is build_04.
  - The `flash_em01_build04/` record is consistent: 3 × verified, MAC ok.
- **Driver.**
  - **wait_done equivalence.** `wait_done_esp` and `rs.wait_done` give identical results on the replayed diag_esp_01 (done at 440 s, 12.67 s HIGH, 143 rises).
  - **Fault paths.** Stale status, missing `utc`, unreadable status, and OFF without a guard all give `instrument_fault`. A USB-guard OFF and a current-guard trip do not.
  - **Timestamp parsing.** The `utc` field parses with `+00:00` and `Z`; a naive timestamp gives inf (fail-safe).
  - **`safe_command`.** It returns False on ENXIO and ENOENT.
  - **No analysis after recorder death.** A failed `stop` or `off` forces `done=False`, so nothing is analysed or pooled.
- **Fresh-recorder check.**
  - No false positive on any genuinely fresh recorder: `ppk_esp2`, `ppk_esp6`–`ppk_esp9` and the self-test all read 0xFF in every pre-ON bin.
  - It correctly refuses `ppk_esp1`, 3, 4 and 5, which were USB-powered during setup.
  - Partial CSV rows are filtered by `summary_rows`.
- **Latch-check numbers.**
  - The "980 s / 2468 s constant" claim holds: `ppk_esp2` stayed at (1,1) for 979 s from OFF + 1 s; `ppk_esp8` stayed at (0,0) until OFF + 2871.8 s.
  - The byte was constant from the OFF instant, so the 1 s skip is conservative.
- **Wiring counter-gap gate.**
  - `analyze_pulses` does return `counter_gaps` for the wiring slice.
  - The appended problem makes `rd.eligible` false.
- **Guard and build gates.** `GUARD_MA` and the `BUILD_MARKER_GPIO` refusal work.
- **`live_sham.py`.**
  - Width checks, NaN handling and the partial-data cases (WAIT) behave correctly.
  - The abort rule is correct in both signs.
  - diag_esp_01 → ABORT (live −0.690 mA against registered −0.657 mA).
- **Protocol hashes.**
  - Lines 1–145 hash to cca7ecb8, lines 1–207 to e73f3cfb, and the whole file to 81436b20.
  - c582400 is an ancestor of 0564ee8, which is on `origin/wip/esp32s3-em01-20260930` with commit time 22:20:37 Z, equal to the external timestamp.
- **Amendment 2 numbers.** These match review 1: 64.49/67.81, 65.13/67.91, −0.604 [−0.674, −0.533], −0.053 [−0.105, −0.0005], 63–71.5 mA, 0.14 s, −1.63 mA, and 05:37:21/05:38:48 +08.
- **Deferred items.** The RA4E1 sham re-examination is explicitly deferred to the RA results, and the headline is unaffected. `analyze_diag_esp.py` is superseded, because diag_esp_02 runs through the driver.
