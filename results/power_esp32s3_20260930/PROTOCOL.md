# EM01 board-level energy measurement on ESP32-S3 N16R8 — pre-registered protocol

Written 2026-09-30 03:25 +08, **before any PPK2-powered ESP32-S3 run**. The only earlier ESP32-S3 activity was:
- read-only identification;
- a full flash backup;
- flashing EM01 build_02;
- one USB-powered bring-up boot, during which the PPK2 output was OFF and only the logic port recorded D0.

Changes after data collection must be listed in dated amendments, never silently.

The template is the FPB-RA4E1 protocol (`results/power_ra4e1_20260929/PROTOCOL.md`, amendments 1–3). Everything not stated here is identical to it: definitions, validity rules, DONE rule and statistics.

## Question

What is the board-input energy per inference of the v5 NSL-KDD QCFS primary seed-0 model on one ESP32-S3 N16R8 board? The model is 41→256→256→128→5 INT8 QDQ with strict FP32 portable arithmetic, the same C implementation that is bit-exact on RA4E1 and N6.

## Board (identified 2026-09-30)

**esptool** (`identify_01/identity.json`):

| Item | Value |
|---|---|
| Chip | ESP32-S3 (QFN56), revision v0.2, 2 cores |
| Crystal | 40 MHz |
| MAC | e8:f6:0a:8b:40:80 |
| PSRAM | embedded 8 MB, AP_3v3 |
| Flash | 16 MB, manufacturer 0x68, device 0x4018; eFuse flash type quad, 3.3 V |

**Operator:**
- Vendor code "IC22071"; no public documentation was found under that code.
- USB-UART bridge **CH343P** (1a86:55d3), dual USB-C (native USB-Serial/JTAG 303a:1001, and CH343P).
- ESP32-S3-DevKitC-1 J1 pin order: 3V3, 3V3, RST, 4, … , 5V, GND.
- The back-side **USB-OTG solder jumper is OPEN**.

**Unknown, and documented as a limitation:** the exact schematic, the LDO part number, and whether the CH343P is powered from the 5 V pin when its USB is absent. All of these are inside the board-level scope.

## Fixed setup

**Power.** PPK2 F4728E9B55E0 in Source Meter mode at 5000 mV (Nordic sequence re-sent on every open).
- VOUT goes to the **5V** pin (J1-21) and PPK2 GND to a **GND** pin.
- **Both USB cables are physically removed before VOUT is attached.** They stay removed during the diagnostic run and all sessions.
  - The recorder runs with `--absent-guard vid:303a,vid:1a86`. It refuses output ON, and switches it OFF, while a native-USB or CH343P device is on the bus.
  - EM01 disables the native USB at every power-on (see B1), so a native cable carrying only power cannot be detected. For that port the rule is enforced physically, and the operator confirms it before each run.
- Guard: 300 mA mean over 100 ms.

**Marker.** GPIO4 (J1-4) → D0. Logic VCC ← 3V3 (J1-1/2); logic GND ← GND. The board has male pins.

**Firmware.** EM01 **build_02**, flashed on 2026-09-30 01:53 with `write_flash --flash_mode keep --flash_size keep --flash_freq keep`. All three regions reported "Hash of data verified", and the flash record MAC matches. The flashed files are retained in `flash_em01_build02/firmware/`.

| Artifact | sha256 prefix |
|---|---|
| `em01.bin` | 46a95057… |
| `em01.elf` | 1b296f55… |
| bootloader | d5bb0adc… |
| partition table | 7f00b6c0… |

- **Reproducible build.** `CONFIG_APP_REPRODUCIBLE_BUILD=y`; a rebuild in a second directory gave byte-identical files.
- **Toolchain.** ESP-IDF commit 7da14d49 (release/v5.4, "v5.4.4"), GCC esp-14.2.0_20260121, esptool 4.11.0.
- **Pinned inputs.** portable_qdq.c e389a691…, portable_qdq.h e8abd58b…, model.c bba723cc…, and validation archive cb5b3415…. These are the same as RM01 build_03.
- **Provenance.** `em01.c = derive_em01(rm01.c)`. Only platform plumbing differs, and 16 measurement functions are byte-identical (`test_em01.py`).
- **Previous board firmware.** It was backed up in full (`flash_backup_before_em01/`, 16 MiB, sha256 5a84996a…).

**Configuration** (measured state = ESP-IDF defaults for this app unless stated):

| Item | Setting |
|---|---|
| CPU | 240 MHz from PLL 480 MHz and a 40 MHz crystal |
| Radios | none started |
| Power management | no PM/DFS/light sleep |
| Watchdogs | task watchdog off; interrupt watchdog on |
| Panic | halts; no silent reboot |
| FreeRTOS | 100 Hz tick on both cores; this ISR time falls into every window, unlike RA4E1 |
| Cores | measurement task on core 0 at the highest priority; core 1 idles in WAITI |
| Console | none |
| PSRAM | powered but not initialised |
| Flash | DIO 80 MHz, code and rodata executed in place through the 32 KB data cache |

- **M1 — weights.** The model's ~116 KB of INT8 weights stay in external flash and are streamed through the cache on each inference. Measured cost at bring-up: 5 964 475 cycles, i.e. **24.85 ms per inference**. This is the default placement, and the result is conditional on it. DRAM-resident weights, QIO flash and optimized kernels are not measured.
- **B1 — native USB.** The ESP-IDF USB-Serial/JTAG driver is not built. `clk.c` therefore disables the native-USB pad and clock at every power-on, which is IDF's default for an application that does not use USB.
  - Confirmed at bring-up: the host saw 4 aborted enumerations, then nothing.
  - Consequences: there is no JTAG readback, and bring-up and all checks use the marker telemetry.
- **Time base.** Xtensa CCOUNT, which wraps after 17.9 s; the longest window is 6.4 s. Bring-up gave 240.0048 MHz against the PPK2 time base, i.e. +20 ppm, with ±10 ppm across windows.

**Rows.** The first 16 validation rows are cycled. BENCH = 4 reps × 16 rows = 64 inferences, 1.59 s (×2 and ×4 in the dose schedules). OVERHEAD = 32 346 reps.

## Bring-up result (USB-powered, PPK2 output OFF; not a measurement)

Capture `ppk_esp1/seg_000_bringup_esp_01`; telemetry decoded with the registered decoder:
- stage TELEMETRY, error 0;
- **pq_env = 1**: the FP gate passes, so Contingency C1 of the draft is **not needed** and is withdrawn;
- 1024-row parity with **0 mismatched words**, output FNV **0xccc5eb8b**, identical to RA4E1, N6 and the host;
- all 100 BENCH/OVERHEAD checksums correct; telemetry CRC ok (1292 words); 245 windows.

Snapshot:
- reset reason 1 (POWERON), core 0;
- `SYSTEM_CPU_PER_CONF` 0x6 (CPUPERIOD_SEL = 2, PLL_FREQ_SEL = 1);
- `SYSTEM_SYSCLK_CONF` 0xa8400 (SOC_CLK_SEL = 1, PLL);
- APB 80 MHz, XTAL 40 MHz, 16 MiB physical flash.

**Power-on artifact.** At power-on, D0 read HIGH for **3.79 ms** (logic port and GPIO4 not yet driven). The registered ESP mask of power-on + **1.5 s** removes it, giving 140 D0 runs against 140 firmware HIGH windows. Without the mask there are 141.

## Validity, eligibility and quantities

As in the RA4E1 protocol with Amendment 3:
- **Eligibility.** No boot-level problem; wiring and sham valid; ≥ 2 of 3 repeat schedules valid. Dose schedules are reported only.
- **Headline.** Gross board-level energy per inference.
- **Incremental.** Only from range-consistent windows, and "not estimable" if none are.
- **Marker band.** Sham-based.
- **Type-B.** PPK2 gain ±20 %; VOUT band −3 %/+2 % (an assumption); S-term in the dominant range.

**ESP-specific boot-level gates** (`rm01_decode.PLATFORMS`, review M3). Any failure makes the session ineligible:
- telemetry magic EM01/EM1T; time base 'CCNT';
- snapshot APB 80 / XTAL 40 / CPU 240 MHz, marker GPIO4, 16 MiB physical flash;
- `SYSTEM_CPU_PER_CONF` CPUPERIOD_SEL = 2 and PLL_FREQ_SEL = 1; `SYSTEM_SYSCLK_CONF` SOC_CLK_SEL = 1;
- reset reason POWERON; core 0; parity FNV 0xccc5eb8b;
- per schedule, the PPK2-time-base CPU clock within ±0.5 % of 240 MHz, otherwise that schedule is invalid.

**Mask.** Frames before output-ON + **1.5 s** are treated as logic-unpowered (`run_sessions_esp.MASK_S`). RM01 keeps the marker LOW for 2 s after marker_init, and the power-on transient lasts 3.79 ms.

**Range (review M4).** The board current is expected near the PPK2 R3/R4 boundary (~50 mA). Auto-ranging is permitted for gross. Incremental comes only from windows whose BENCH and both IDLE spans share one range with no switch.

## Sequence

1. Wiring for PPK2 power, done stepwise and in this order:
   1. confirm both USB cables are removed;
   2. VOUT → 5V and PPK2 GND → GND, keeping the logic leads from bring-up.
2. **One diagnostic PPK2 power-on**, `diag_esp_01`: full pipeline, **not pooled**. An independent adversarial review follows.
3. **Three formal power-on sessions** with `run_sessions_esp.py`:
   - `--mac e8:f6:0a:8b:40:80`, `--flash-record flash_em01_build02`, `--build build_02`, output OFF ≥ 10 s between sessions;
   - driver sha256 and code hashes are logged at preflight.

## Not claimable

- SoC or core energy.
- Energy with radios on, at another clock, with QIO flash, DRAM-resident weights, PSRAM enabled, or an optimized kernel (ESP-NN).
- Any cross-board ranking beyond "same model, same protocol, different board scope, clock and operating point".
  - The 5 V → 3.3 V linear LDO alone dissipates about a third of the board input power on every board.
- Behaviour of other units, temperatures or supply voltages.

## Board state to document with the results

- Both USB cables removed, confirmed by the operator.
- LED states during a PPK2-powered run (power LED, RGB LED), recorded by the operator.
- PSRAM powered but not initialised; native USB disabled by IDF at power-on; CH343P power state unknown.
- Room temperature not controlled.

## Amendment 1 (2026-09-30 05:40 +08, after diag_esp_01, one attribution power-on and a logic-port repair, before any formal session)

**diag_esp_01** (recorder `ppk_esp2`, segment sha256 81bffe29…, 44 905 760 frames; not pooled):
- Every ESP boot-level gate passed:
  - platform esp32s3, stage TELEMETRY, error 0, pq_env 1;
  - 1024-row parity with 0 mismatched words (FNV 0xccc5eb8b);
  - reset reason POWERON, core 0;
  - `SYSTEM_CPU_PER_CONF` 0x6, `SYSTEM_SYSCLK_CONF` 0xa8400, APB 80 / XTAL 40 / CPU 240 MHz, 16 MiB;
  - telemetry CRC ok.
- Wiring valid (5 × 0.1000 s); all 5 schedules valid; CPU clock against the PPK2 time base 240.005 MHz; no counter or reader gaps. The only ADC upper-rail frame is 8.45 ms after ON (inrush, R0), inside the mask.
- **Sham invalid:** ΔI(marker HIGH − LOW) = **−0.657 mA** (95 % CI −0.732 to −0.581, n = 20), beyond the 0.5 mA gate. The session is ineligible, and every formal session with this setup would be too.
- For the record only:
  - gross 7.917 mJ/inference (3 repeat schedules, CV 0.14 %); 24.852 ms/inference;
  - board current 63–66 mA, in R4 except 0.13 s at power-on;
  - BENCH draws 1.65 mA less than the IDLE spin (incremental −0.20 mJ/inference).

**Attribution power-on `attrib_nod0_01`** (same firmware and wiring with the D0 lead detached from GPIO4; segment sha256 e5442939…; not a measurement, not pooled):
- **Method.** The diag_esp_01 marker edges were mapped onto this capture by the parity-end current step (offset −1 ms; residual at 100 BENCH edges: median +0.75 ms, max 5.3 ms). Scripts: `analysis/sham_nod0.py`, `analysis/full_nod0.py`.
- **Sham slots.** With the identical estimator for both captures, ΔI = **−0.618 mA** (95 % CI ±0.057) with D0 detached, against −0.674 mA (±0.060) with D0 on GPIO4.
  - Quadrature-shifted null: −0.007 / −0.008 mA.
  - The current step completes within ~0.1 ms of each marker edge.
- **Conclusion.** The marker-state current is not the PPK2 D0 input, whose share is ≤ ~0.06 mA (the order seen on RA4E1 and N6). It is a load on the board side of GPIO4 that draws ~0.62 mA more while GPIO4 is driven LOW.
  - GPIO4 read LOW while undriven at boot, which excludes a resistive pull-up.
  - The load's form is unknown (no schematic; LED observation not reported by the operator).
- **Offset.** The capture ran ~0.25 mA (~0.4 %) below diag_esp_01 in both marker states alike: a power-on-to-power-on offset.

**Change** — the only one to the measurement: the marker moves to **GPIO5** (silkscreen "5", J1-5).
- **Firmware.** EM01 **build_03** differs from build_02 only in `EM_MARKER_GPIO` (em01.h, 5u).
  - `em01.bin` bcf2ca47…, `em01.elf` 2a244cc3…; bootloader d5bb0adc… and partition table 7f00b6c0… unchanged; sdkconfig identical; a rebuild in a second directory was byte-identical.
  - Disassembly: all 768 functions keep their names. The only differences are:
    - the marker constants (1<<4 → 1<<5; snapshot 4 → 5) in `window_begin`, `pulses`, `hal_entry` and the fail-closed path of `infer_row`;
    - a register re-allocation in the telemetry transmitter `tel_word` (one instruction fewer).
  - The inference arithmetic and every timed loop are unchanged.
- **Host code.**
  - The ESP snapshot gate accepts marker GPIO 4 or 5 (`rm01_decode.ESP_MARKER_GPIOS`).
  - `run_sessions_esp.py` requires the flashed build's value (build_03 → 5).
  - `esp_ops.py` pins build_03 and uses it by default.
  - Tests: EM01 sim 5/5, PPK2 recorder 17/17, RA4E1 diag_07 regression 3/3.
  - The three RA4E1 formal sessions re-analysed with the current decoder are identical in every numeric leaf (max relative difference 0; only the new `platform` key).
- **Flash.** `flash_em01_build03/`, 2026-09-30 04:22:29 +08, via the CH343P port (1a86:55d3, serial 5B5E017386), with VOUT detached. All 3 regions verified; MAC e8:f6:0a:8b:40:80.
- **Unchanged.** Everything else, including the sham gate (|ΔI| < 0.5 mA), eligibility, headline and statistics.

**Logic-port incident and repair** (setup only; no measurement):
- **04:26:17.** The PPK2 stream stalled for > 1 s while the operator re-routed D0 (recorder `ppk_esp3`, fail-safe exit, output OFF). The cause was not identified.
- **After the stall.** From then on, the logic port read VCC absent (D1–D7 = 1) through the 10-pin ribbon cable, although the board's 3V3 was live and D0 still followed the marker.
- **Self-test `ppk_selftest_logic_01`.** The PPK2's own VOUT (3300 mV, 20 mA guard, board not involved) was put directly on the logic header VCC pin. The logic port woke 0.01 s after ON with ~0.06 µA static VCC current, so the PPK2 logic port is healthy.
- **Repair.** The ribbon cable is set aside. The logic port is now wired with three female-female jumpers from the PPK2 header (VCC → 3V3, GND → G, D0 → GPIO5); VOUT → 5V and PPK2 GND → G are as registered.
- **Wiring check `wiringcheck_esp_01`** (recorder `ppk_esp8`, 36 s, not a measurement):
  - a fresh connection read logic 0xFF before ON;
  - the logic port was powered 0.01 s after ON (3602/3603 bins);
  - board current 63.4–63.9 mA;
  - 5 wiring pulses from 29.59 s after ON (diag_esp_01: 29.60 s), then 1.01 s sham pulses on D0.
- **Other events.**
  - Between 04:07 and 05:23 the operator plugged the board's native USB port several times: 4 aborted enumerations each, the EM01 signature. These were setup steps with the PPK2 output OFF throughout.
  - Whether VOUT was attached to 5V during those USB connections was not reported.
  - Recorders `ppk_esp3`–`ppk_esp7` were idle diagnostics only.

**Next:** diag_esp_02 with build_03 (not pooled), an early sham check at ~80 s (`analysis/live_sham.py`, non-registered, abort only), the full registered analysis and an independent review, then three formal sessions with `--build build_03 --flash-record flash_em01_build03`.
- If diag_esp_02 fails the sham gate, no formal session is run on that pin.

**Reporting:** diag_esp_01 and attrib_nod0_01 are reported as a documented finding (a marker-pin load on this board) and are never pooled.

## Amendment 2 (2026-09-30 06:19 +08, after an independent max-rigor review of Amendment 1, before diag_esp_02 and any formal session)

**Withdrawn: the GPIO4 attribution of Amendment 1.** The review is in `analysis/review_amendment1/REVIEW.md` and was confirmed here by disassembly and one spot check.
- **Two different wait loops.** `wait_cycles` was inlined 19 times in build_02 and build_03. The sham's two halves therefore ran different machine code:
  - HIGH half: loop at 0x420061d4, inside one 32-byte cache line;
  - LOW half: loop at 0x420061fd, which crosses a line boundary.
- **Code placement changes the current.** Inlined waits at different addresses drew different currents. Per the review, in diag_esp_01:
  - two adjacent marker-LOW waits read 64.49 and 67.81 mA;
  - IDLE read 65.13 mA against 67.91 mA for final-IDLE.
- **Moving the marker did not help.** attrib_nod0_01 (D0 detached) reproduces the effect. wiringcheck_esp_01 (GPIO5, build_03) shows the same sham offset: −0.526 and −0.648 mA in its two sham windows, recomputed here.
- **Conclusion.** The diag_esp_01 sham offset is a code-placement effect of the busy-wait. It is not a GPIO4 load and not the PPK2 D0 input.
  - The "marker-pin load on this board" finding of Amendment 1 is withdrawn; no load on GPIO4 is known.
  - The same inlining exists in RM01. The RA4E1 sham ΔI (−0.137 mA, passed) and its attribution to the D0 input network are to be re-examined and reported with the RA4E1 results. The registered RA4E1 eligibility and headline are unaffected.

**Change: build_04.** Every wait runs **one** copy of the busy-wait.
- **Source.** `derive_em01.py` adds exactly one substitution: `static void EM_WAIT_ATTR wait_cycles(uint32_t cycles)`. `em01_port.h` defines `EM_WAIT_ATTR` as `__attribute__((noinline, aligned(16))) IRAM_ATTR`. The body is identical to RM01, and `test_em01.py` checks both facts.
- **Binaries.** `em01.bin` 1dea01ce…, `em01.elf` 5a8c2233…. Bootloader and partition table are unchanged. A rebuild in a second directory was byte-identical.
- **Disassembly.**
  - `wait_cycles` sits at 0x40377c70 (IRAM, 16-byte aligned), with the CCOUNT read inlined and no flash access.
  - The 19 former inline sites load its address and call it: `pulses` 2, `tel_word` 2, `hal_entry` 15.
  - No other CCOUNT polling loop remains in the application (only FreeRTOS `xPortEnterCriticalTimeout`).
- **Objects.** Only `em01.c.obj` differs from build_03. `portable_qdq.c.obj`, `model.c.obj`, `rm_vectors.c.obj` and `app_main.c.obj` are byte-identical, and `infer_row` and `window_begin` are instruction-identical.
- **Marker.** The marker stays on GPIO5 (wired and validated). Nothing now favours GPIO4.
- **Consequences.** IDLE, sham and gap levels change, because the loop now runs from IRAM. The BENCH code is unchanged, but its current and timing can shift slightly with the flash layout, so results are conditional on build_04.

**Procedure changes (review M2, M3; `run_sessions_esp.py`):**
- **Preflight.** It requires:
  - the registered guard (300 mA) and a registered build;
  - a live recorder (status < 5 s old);
  - a **fresh recorder whose logic port read unpowered (0xFF) in every bin since it started** (≥ 3 s). This is the instrumented check that the board has no other supply.
- **Between sessions.** The latched logic byte must stay constant while the output is OFF (from OFF + 1 s to the next ON); otherwise the session is ineligible. Verified: the byte stayed constant for 980 s (ppk_esp2) and 2468 s (ppk_esp8) after OFF, including while leads were moved.
- **Dead recorder.** An unreadable or stale status, or a failed control command, ends the run with an abort record as an instrument fault, instead of waiting or crashing.
- **Wiring phase.** A PPK2 counter discontinuity in the wiring phase makes the session ineligible.
- **Instrument-fault replacement rule (pre-registered).**
  - A formal session that ends with an instrument fault is reported, never pooled, and replaced by one additional formal session, with at most two replacements. Instrument faults are: recorder exit, PPK2 disconnect or stall, or output OFF without a guard.
  - Sessions failing a registered gate are not replaced.
  - The headline aggregate uses all eligible formal sessions.
- **`analysis/live_sham.py`** (non-registered early check): width checks on the 5 wiring and 20 sham runs. It aborts a diagnostic only when the whole early 95 % CI lies beyond 0.5 mA.

**Corrections to Amendment 1** (review minors):
- diag_esp_01: board current 63–71.5 mA (OVERHEAD windows ~71 mA); non-R4 time 0.14 s; BENCH−IDLE −1.63 mA.
- With the registered estimator, the attrib_nod0_01 sham ΔI is −0.604 mA (95 % CI −0.674 to −0.533). The D0-attachment share is −0.053 mA (95 % CI −0.105 to −0.0005).
- The quadrature-shifted null tests drift only.
- The current step overshoots ~40 % and settles in 5–8 ms.
- The offset between captures is phase-dependent (0.24–0.47 mA).
- The self-test's ~0.06 µA is within the PPK2 zero offset and is not a measured VCC current.
- The Amendment 1 heading time "05:40" is approximate. Its registration time is 05:37:21 +08, external timestamp 05:38:48 +08 (`PROTOCOL.sha256`).

**Next:**
1. Flash build_04 (VOUT detached, CH343P port), keeping the Amendment 1 wiring (jumpers).
2. Start a fresh recorder.
3. Run diag_esp_02 with `run_sessions_esp.py --build build_04 --sessions 1` (not pooled).
4. Full analysis and an independent review.
5. Three formal sessions with `--build build_04 --flash-record flash_em01_build04`.

If diag_esp_02 fails the sham gate, no formal session is run.

## Amendment 3 (2026-09-30 06:36 +08, after an independent re-review of Amendment 2 — verdict CLEAN with one MAJOR — before diag_esp_02 and any formal session)

**Pre-registered code-placement check** (re-review A2-M1; script `analysis/lowspan_check.py`, applied to every diagnostic and formal session). All busy-wait spans with the marker LOW must agree with their neighbours, which cancels slow thermal drift:
- **C1:** in each schedule, |mean(IDLE before BENCH) − mean(IDLE after BENCH)| ≤ 0.25 mA. The two are interleaved; the per-schedule noise is ~0.08 mA.
- **C2:** pooled over the 5 schedules, |mean(final IDLE) − mean(all IDLE)| ≤ 0.5 mA.
- **C3:** |mean(sham LOW halves) − mean(2 s gap before the sham)| ≤ 0.5 mA, and likewise for the 2 s gap after the sham.
- **Spans.** The spans are the marker-LOW intervals between D0 runs, with 50 ms excluded at every edge.
- **Calibration on diag_esp_01 (build_02), which fails as expected:**
  - C1: −0.67, −0.56, −0.59, −0.49, −0.44 mA;
  - C2: +2.50 mA;
  - C3: −0.39 / +0.93 mA.
- **Decision rules:**
  - **diag_esp_02** must pass C1–C3 in addition to every registered gate, otherwise no formal session is run.
  - **In a formal session**, a C1–C3 failure makes that session's incremental "not interpretable". Its gross headline and eligibility are unaffected, because BENCH windows contain no wait.
- **diag_esp_01 incremental.** The diag_esp_01 incremental (−0.20 mJ/inference) is not interpretable: its IDLE baseline mixed wait copies whose currents differ by up to 3.1 mA.

**Driver fixes** (re-review minors; `run_sessions_esp.py`, tests in `test_run_sessions_esp.py`, 5/5):
- Any instrument fault (stale or unreadable status, a failed command) ends the run.
- Every aborted session is listed in the aggregate's `instrument_faults`.
- Board-state evidence before each ON uses whole 10 ms bins before the ON sample:
  - session 1: only 0xFF from the recorder start;
  - later sessions: the latched byte over the OFF gap must be constant and equal to (1, 1) after a DONE session (verified: 97 898 bins after diag_esp_01).
- The USB-guard OFF classification compares against its count at session start.
- `live_sham.py` uses a Student-t CI (19 dof) and exits 10 on ABORT. It still ends its first and last sham LOW spans differently from the pipeline, a ~−0.03 mA bias towards ABORT that is harmless under the CI rule.

**Wording corrections to Amendment 2:**
- **"BENCH code unchanged."** `portable_qdq.c.obj`, `model.c.obj` and `rm_vectors.c.obj` are byte-identical and `infer_row` is instruction-identical. The BENCH repetition loop inside `hal_entry` has permuted registers and moved (0x42006ade → 0x42006aaa), and the `pq_*` code moved by −164 B.
- **"Inlined 19 times."** build_04 has 19 call sites of the single `wait_cycles`; build_03 had 16–18 distinct CCOUNT wait loops, depending on how outer loops are counted.
- **The −0.526 / −0.648 mA of the GPIO5 wiring check** use a two-sided LOW estimator (mean of the LOW spans before and after each HIGH). The pipeline-style estimator gives −0.327 mA for the first window.
- **The second-directory rebuild of build_04** was compared file by file (4 identical sha256) and then deleted. No artefact is kept, and a rebuild with `build.py` reproduces it.
- **The IDLE baseline** of build_04 is an IRAM spin, so incrementals are not comparable with RA4E1 (as registered, never across boards).
- **Wiring-check figures in Amendment 1:**
  - "1.01 s" is the 10 ms-bin width; the raw sham pulses are 1.000 s.
  - "3602/3603" counts bins, with the first bin containing the power-up.
  - "63.4–63.9 mA" are the 0.5 s value at 2 s and the 36 s mean.
- **em01.h.** The `em01.h` comment on `EM_MARKER_GPIO` still states the withdrawn GPIO4 cause. It is left unedited, because the build source is hash-pinned.

**Instrument handling:**
- 5 of 9 recorders in this setup phase ended with a PPK2 `SerialException`, because the PPK2 USB cable was moved between host ports (kernel log: ports 1-6, 1-5, 1-1).
- From diag_esp_02 on, the PPK2 stays on one host port, and nobody touches the PPK2, its cables or the board during a run.
- The self-test's 2 counter gaps fell 5 ms after its output OFF, outside the ON period.

## Observation 1 (2026-09-30 07:03 +08, after the CLEAN independent review of diag_esp_02; written while formal session esp_session_01 was running, before any formal analysis output existed)

**diag_esp_02** (build_04; recorder `ppk_esp9`; not pooled). Independent review: `analysis/review_diag02/REVIEW.md`, verdict CLEAN.
- **Gates.** Every registered gate and the Amendment 3 checks C1–C3 passed; eligible.
  - sham ΔI −0.062 mA (95 % CI −0.140 to +0.015);
  - C1 −0.10…+0.11 mA; C2 +0.13 mA; C3 −0.09 / −0.06 mA.
- **Results (for the record only).**
  - Gross 7.937 mJ/inference (3 repeat schedules, CV 0.22 %); 24.852 ms/inference; 240.005 MHz.
  - Incremental +0.113 mJ/inference (sham-corrected +0.121 mJ). BENCH−IDLE is +0.91 mA, stable across schedules.
  - The independent re-decode matched the pipeline to ≤ 7e-16 relative on all 30 repeat BENCH windows.

**Reporting rules**, fixed now, before any formal result:
- **Warm-up drift.** Gross and IDLE drift upward within a power-on: +0.43 % across the 3 repeat schedules in diag_esp_02 and +0.26 % in diag_esp_01, with BENCH−IDLE constant.
  - The between-schedule CI of a session describes this warm-up trend plus noise and is reported as such.
  - The per-schedule values are reported alongside it.
- **Dose-response intercept.** It is confounded by this drift, because the dose schedules run last, so it is not interpreted as a fixed per-window cost.
- **Logic-port fraction.** The logic-port-powered fraction is reported after the mask (100 % in diag_esp_02). The pipeline's `logic_powered_fraction` includes the masked frames.

**Errata and observations:**
- Under PPK2 power the D0 power-on artifact lasts 6.96 ms (3.79 ms at the USB bring-up), still well inside the 1.5 s mask.
- The OVERHEAD repetition count is calibrated at every power-on: 32 287 in diag_esp_02, against the 32 346 quoted from the bring-up.
- An `em01.c` comment attributes 1.19 s OVERHEAD windows to build_02; that refers to build_01. The source is hash-pinned and left unedited.
