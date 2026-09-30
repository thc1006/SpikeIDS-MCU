# EM01 board-level energy measurement on ESP32-S3 N16R8 — protocol DRAFT (not registered)

Status: **DRAFT, 2026-09-30.** Nothing in this file is registered yet.
- It becomes the pre-registered protocol only when all of the following hold:
  1. the physical board is identified (section *Board identification*, all TBD items filled in);
  2. the independent review findings are resolved;
  3. the file is copied to `results/power_esp32s3_<date>/PROTOCOL.md`, hash-logged and pushed to GitHub.
- All three happen before any formal ESP32-S3 session.
- The RA4E1 protocol (`results/power_ra4e1_20260929/PROTOCOL.md`, amendments 1–3) is the template. Everything not listed here is identical to it.

## Question

What is the board-input energy per inference of the v5 NSL-KDD QCFS primary seed-0 model on an ESP32-S3 N16R8 board, using the same strict FP32 portable-QDQ C implementation that is bit-exact on RA4E1 and N6?

## Board identification (must be completed with the operator before registration)

Operator answers (2026-09-30):
- Vendor item code "IC22071"; no public datasheet found under that code.
- USB-UART bridge **CH343P** (marking 3FF29, USB 1a86:55d3). **Dual USB-C**: native USB-Serial/JTAG (303a) plus the CH343P port.
- Pin row read by the operator: 3V3, 3V3, RST, **4**, … This is the ESP32-S3-DevKitC-1 J1 order (J1-1/2 3V3, J1-3 RST, J1-4 GPIO4, …, J1-21 5V, J1-22 GND). Pins labelled **5V** and **3V3** are present.
  - Conclusion: a DevKitC-1-compatible clone. Its exact schematic is still unavailable, which is a documented limitation.
- A **USB-OTG** solder jumper is on the back and is **OPEN** (factory default), per the operator on 2026-09-30.
  - On DevKitC-1-style designs this keeps the native-USB VBUS behind its diode.
  - The rule "USB unplugged whenever VOUT is attached" applies regardless.


- [ ] Board model and revision (silkscreen or photo): TBD. Examples: ESP32-S3-DevKitC-1 v1.0/v1.1, VCC-GND YD-ESP32-S3, or another clone.
- [ ] USB ports: native USB (GPIO19/20, USB-Serial/JTAG) and/or a USB-UART bridge (CH343/CP2102N/…): TBD.
- [ ] 5 V entry pin label and position (5V / 5Vin / VIN): TBD. Schematic check of what lies between USB VBUS and that pin (diode or direct) decides the back-feed rule.
- [ ] 3V3 pin, GND pins, and the position of **GPIO4**: TBD.
- [ ] On-board LEDs: power LED, and the RGB LED on GPIO48 (DevKitC-1 v1.0) or GPIO38 (v1.1). Neither is driven by EM01.
- [ ] esptool identity (`esp_ops.py identify`): chip revision, MAC, 16 MB flash, embedded 8 MB PSRAM.

## Fixed setup

**Power path.** PPK2 serial F4728E9B55E0 in Source Meter mode at **5000 mV** (Nordic sequence, re-sent on every open).
- VOUT goes to the board 5 V pin; PPK2 GND goes to the board GND.
- **All board USB cables are unplugged whenever VOUT is attached.** The recorder's `--absent-guard` holds the board's USB serial, and the driver refuses to start if any Espressif (303a) or bridge (1a86/10c4/0403) device is on the bus.
- Guard current: **300 mA** mean over 100 ms. Expected board current is 50–120 mA at 240 MHz with radios off, and depends on the board. A steady current above 250 mA means stop.

**Marker.** GPIO4 → PPK2 D0.
- Logic VCC ← board 3V3; logic GND ← board GND.
- The board side uses male pins.
- Stepwise bring-up exactly as on RA4E1:
  1. PPK2-only self-test;
  2. power only, expecting the settle→parity current step at 2 s;
  3. add logic VCC/GND, expecting the logic port powered within ms of ON;
  4. add D0, expecting 5 wiring pulses about 30–40 s after ON (exact time TBD from bring-up).

**Firmware.** EM01 `tools/esp32s3_deployment/firmware_measure/build_01`.
- `em01.bin` sha256 5d28723d…; bootloader 17fbdd9d…; partition table 7f00b6c0….
- ESP-IDF v5.4.4 and GCC esp-14.2.0.
- **em01.c = derive_em01(rm01.c).** Only platform plumbing differs; 16 measurement functions are byte-identical, and `test_em01.py` checks this.
- Model sources and vectors are identical to RA01/RM01 and pinned.
- **Configuration:**

  | Item | Setting |
  |---|---|
  | CPU | 240 MHz from the 40 MHz crystal |
  | Radios | no Wi-Fi/BT started |
  | Power management | off (no DFS or light sleep) |
  | Task watchdog | off |
  | FreeRTOS tick | 100 Hz on both cores |
  | Core usage | measurement on core 0 at the highest priority; core 1 idles (WAITI) |
  | Console | none |
  | PSRAM | powered but not initialised (SPIRAM component not built) |
  | Flash | DIO 80 MHz (ESP-IDF default), code/rodata executed from flash through the cache |

- **Time base.** Xtensa CCOUNT at the CPU clock; 32-bit, wraps every 17.9 s. The longest window is below 7 s. The dose-4 wrap guard is in the RM01 logic.

**Rows.** The first 16 validation rows are cycled, as on RA4E1.

## Floating-point environment gate (pre-registered policy)

`portable_qdq.c` requires round-to-nearest and gradual underflow (FLT_MIN·0.5 > 0).
- The ESP32-S3 FPU's subnormal behaviour is not documented in any source we could obtain. QEMU's Xtensa FPU model applies no flush-to-zero; the Cadence ISA summary was not retrievable (HTTP 403).
- **If EM01 reports pq_env = 0** (error −201 at boot), the session is ineligible and fails closed, as designed. The finding is reported.
- **Contingency C1** (registered now, used only in that case): a variant EM01-C1 build whose sole change is removing the subnormal clause from the gate. It is justified by `FP_CENSUS.json`:
  - All 1024 rows were instrumented: **345 082 439** add/mul/div/QCFS-floor operations.
  - There were **0 subnormal operands**, **0 subnormal results** and 0 subnormal input features, with 0 mismatched output words.
  - A flush-to-zero FPU therefore cannot change any result on these rows.
  - Bitwise parity on all 1024 rows on-device remains mandatory.
- **Bitwise parity** against the QDQ reference is required on every boot. It fails closed, as on RA4E1 and N6.

## Sequence, quantities, validity, eligibility, statistics

These are identical to the RA4E1 protocol including Amendment 3:
- DONE rule and masking of the latched logic byte;
- eligibility = no boot-level problem, wiring valid, sham valid, and ≥ 2 of 3 repeat schedules valid; dose schedules are reported only;
- 3 power-on sessions;
- headline = gross board-level energy per inference;
- incremental energy only from range-consistent windows;
- a sham-based marker band;
- Type-B: PPK2 gain ±20 % and a VOUT band of −3 %/+2 % (assumed), with the S-term in the dominant range. R4 is likely at 50–120 mA, where the S-term matters more.
- Platform-specific checks: telemetry magic EM01/EM1T, time base 'CCNT', and snapshot APB 80 MHz / XTAL 40 MHz / CPU 240 MHz / GPIO4 / 16 MiB flash. The reset reason is reported; POWERON is expected for each PPK2 power-on.

## Not claimable

- SoC or core energy.
- Energy with radios on, at another clock, with QIO flash or PSRAM enabled, or with an optimized kernel (ESP-NN/ESP-DSP). This is portable FP32 QDQ.
- Any cross-board ranking beyond "same model, same protocol, different board scope, clock and operating point".

## Board state to document with the results

- USB unplugged.
- LED states.
- PSRAM powered but not initialised.
- Which bridge chip is present and whether it is powered from the 5 V pin (from the schematic).
- Room temperature not controlled.
