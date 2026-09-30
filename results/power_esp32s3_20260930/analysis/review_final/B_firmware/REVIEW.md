# Review B: firmware, platform facts and measurement validity (EM01 build_04)

Reviewer: independent, adversarial. Read-only apart from this file. Sources: the local ESP-IDF checkout at `/home/thc1006/esp/esp-idf` (commit 7da14d49), `build_04/sdkconfig`, `build_04/build/em01.elf` (objdump/nm), and the analysis JSONs of diag_esp_01 (build_02), diag_esp_02 and esp_session_01–03.

**VERDICT: CLEAN.** No BLOCKER or MAJOR findings; 5 MINOR.

## Verified (no action needed)
- **USB-Serial/JTAG off.** `clk.c:290-297` turns off the USJ pad and bus clock in the non-CPU-reset branch when `!CONFIG_USJ_ENABLE_USB_SERIAL_JTAG && !CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG_ENABLED`. `esp_driver_usb_serial_jtag` is not in build_components, so B1 holds.
- **Clock registers.**
  - `CPU_PER_CONF` 0x6 decodes to CPUPERIOD_SEL=2 and PLL_FREQ_SEL=1 (240 MHz). WAIT_MODE_FORCE_ON=0, so WAITI clock gating is on, which fits core 1 sitting in WAITI.
  - `SYSCLK_CONF` 0xa8400 decodes to SOC_CLK_SEL=1 (PLL) and CLK_XTAL_FREQ=40.
  - The CCOUNT wrap is 17.895 s. The longest window is 6.36 s.
- **Configuration matches the build.**
  - Tick: one SYSTIMER alarm per core at 100 Hz, IRAM ISR (`port_systick.c:93-116`).
  - Watchdogs: interrupt watchdog tick hook runs on both cores; task watchdog is off.
  - Flash DIO 80m; esp_psram is not built; main task pinned to CPU0.
  - Core 1: `prvIdleTask` → `esp_vApplicationIdleHook` (flash, 0x42001ea0; no hooks registered) → `waiti 0`.
- **BENCH window contents** (disassembly).
  - `window_begin` stores W1TS 8 instructions after `rsr.ccount`.
  - The loop at 0x42006aa4–0x42006b07 runs `infer_row`, an inline fnv1a and 2 volatile read-modify-writes. It contains no wait.
  - The end is W1TC, then `memw`, then `rsr.ccount`.
  - Non-inference work is 120–150 cycles per inference: BENCH is 5 964 594–620 cycles per inference against the parity mean of 5 964 473, i.e. 0.002 %.
- **Boundary bias.**
  - The CCOUNT span exceeds the marker span by about 0.1 µs.
  - Per-window PPK2 sample count minus the CCOUNT prediction: mean −0.13…+0.12 samples, |max| 1.4 samples.
  - gross vs dwt-gross differ by ≤ 7e-6 per window and ≤ 4.5e-7 on average.
  - The window-placement bias on gross is therefore ≪ 1e-5. That includes the 10 µs sampling, the logic input delay and the step overshoot.
- **Determinism.** CCOUNT per inference is identical to 0.1 cycle across all four build_04 power-ons. Rodata (weights l0–l3, rm_inputs) sits at byte-identical addresses in builds 02, 03 and 04.

## MINOR
1. **Wrong cache named** (PROTOCOL configuration table). It says "code and rodata … through the 32 KB data cache". Code actually goes through the **16 KB ICache** (`CONFIG_ESP32S3_INSTRUCTION_CACHE_16KB=y`, 8-way, 32 B lines) and rodata through the 32 KB DCache (8-way, 32 B). The line-crossing argument in Amendment 2 is about ICache lines, which are 32 B, so it still holds. *Fix:* add an erratum.
2. **Snapshot clock "gates" are software values.**
   - `esp_clk_apb_freq()` on S3 is `MIN(cpu_sw_freq, 80 MHz)` (`esp_clk.c:96-103`), so the APB gate cannot fail independently.
   - `cpu_hz_clk` is the ROM ticks-per-µs variable; XTAL is a value stored in RTC memory.
   - The independent evidence is the two SYSTEM registers plus the PPK2 clock (+21 ppm). *Fix:* reword.
3. **Reset reason 1 is not uniquely a power-on.** ESP32-S3 `RESET_REASON_CHIP_BROWN_OUT = 0x01` equals `CHIP_POWER_ON` (`soc/esp32s3/.../reset_reasons.h:38-39`), and an EN reset also reports 0x01.
   - Session 2 had a 1.025 A inrush peak, so "POWERON" alone does not rule out a brown-out restart just after ON.
   - The headline is unaffected: a restart inside the mask only shifts the timeline, and the telemetry/window matching would catch a mid-run reset.
   - *Fix:* state this, and check that the ON→first-wiring-edge delay is equal across sessions.
4. **The "conditional on build_04" caveat is adequate but gives no evidence.** Evidence that the layout dependence is weak:
   - (a) The weights are placed identically in builds 02/03/04.
   - (b) The hot MAC loop is a 76 B zero-overhead `loop` body (0x420073c9–0x42007414; 109 440 iterations per inference). It fits the core's 256 B loop buffer (`core-isa.h` `XCHAL_LOOP_BUFFER_SIZE 256`; loop-buffer purpose: https://www.bdti.com/InsideDSP/2013/12/11/Cadence), so its fetches do not depend on where it sits in flash. The 3.1 mA effect came from a *branch* loop that is fetched through the ICache on every iteration.
   - (c) Cycles per inference differ by ≤ 10 between build_02 and build_04.
   - (d) BENCH−OVERHEAD, which cancels the power-on offset: build_02 −7.334 mA against build_04 −7.286/−7.340/−7.310/−7.311 mA. The build effect is ≤ ~0.05 mA (0.08 %), within the power-on spread. Absolute BENCH in build_02 is 0–0.25 mA below build_04, less than the 0.65 mA cold/warm difference.
   - Limits: a shift common to both BENCH and OVERHEAD is not excluded, and the loop-buffer mechanism is inferred, not measured.
   - *Fix:* add one sentence with (a)–(d).
5. **Scope: back-to-back inference with a hot ICache.**
   - The first inference in each window is warm: the per-window spread is ≤ 54 cycles per inference, because IDLE runs from IRAM and OVERHEAD uses ROM memcpy.
   - The weights (115 KiB) exceed the DCache, so they are streamed every inference.
   - A cold-cache inference costs up to +0.8 % cycles (parity max 6 007 9xx against min 5 960 855).
   - *Fix:* write "back-to-back (hot I-cache)" in the scope.

## NOT DONE
- The ON→first-wiring-edge comparison for MINOR 3. Wiring slices agree to within ±20 ms of segment start, but the ON samples were not extracted.
- The tick-ISR cycle cost was not measured (it is present in every window alike).
- The share of cycles in the inner loop (estimated ~95 %) was not modelled, and loop-buffer engagement was not measured.
