# SM07M measurement firmware (over frozen SM06)

Adds autonomous measurement commands to the accepted SM06 image so that no
SWD traffic is needed inside a measured window. The SM06 translation unit is
included unchanged (only its `main` is renamed); `main()` here repeats SM06
`main()` statement for statement plus a poll of `g_measure` (`test_measure.py`
checks this against the SM06 source).

- `PARITY`: runs preloaded rows through the same run/copy statements as INFER.
  The host requires bitwise equality with the accepted SM06 run08 outputs and
  the original `validation.evaluate` policy before any measurement.
- `PULSES`: marker-only pulses for PPK2 D0 wiring verification.
- `SCHEDULE`: preamble pulses, then `cycles` x [IDLE, BENCH, IDLE, OVERHEAD],
  final IDLE. Marker HIGH during BENCH/OVERHEAD. DWT start/end cycles, iteration
  counts and an FNV-1a output checksum are recorded per window.

Marker: PH8 (Arduino D12, CN12-5) push-pull, set up like ST
x-cube-n6-ai-power-measurement `trace_gpio.c` TRACE_PIN_1 (VDDIO4 valid + GPIO
clock). Not PE15/D13: UM3300 wires it to LED LD6 (active HIGH). Set up on
the first measurement command only, after the host's post-READY register checks.
Clock/platform: unchanged SM06 platform stage (nominal HSI 64 MHz, caches off).
