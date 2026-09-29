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
