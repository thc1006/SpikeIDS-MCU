# v5 NSL-KDD QCFS RAM firmware adapter — offline build only

Uses the exact generated STAI/Neural-ART source and weights from
`results/ppk2_n6_bringup_20260925_nAivHM/vendor_actual_01/generate` without editing,
copying over, or regenerating them. This is the 41→256→256→128→5 seed0 model;
it includes Cortex-M55 float software as well as NPU epochs. Nothing in this
directory accesses a USB device, programmer, serial port, GPIO or PPK2.

## Build

Run from the repository root, in an externally resource-limited scope:

```sh
uv run --no-project --offline --python .venv/bin/python \
  tools/n6_deployment/firmware_v5/build.py \
  --output-dir /absolute/repo/tools/n6_deployment/firmware_v5/build_actual_01
```

Only a fresh direct child directory is accepted. Errors stop immediately and
retain command/stdout/stderr/return-code records and a failure marker when safe.
Actual source/header/library/tool hashes are held before object compilation and
checked after link. Hardlinked installed compiler binaries are permitted but
their original identity/link count is retained. No toolchain package is changed.
The generated vendor files are checked against the fixed RESULT's original pins.
`LL_ATON_SW_FALLBACK=1` is required by this mixed graph and matches the installed
ST NPU_Validation build configuration. Newlib uses explicit no-I/O stubs and a
bounded 16 KiB heap; no UART/semihosting is introduced. FP/MVE access is enabled
in naked startup before any C/library operation. Global IRQs stay masked and
the source enforces `LL_ATON_RT_POLLING` at compile time.

`n6_v5.elf`, `.bin`, `.map`, readelf/size/symbol logs and RESULT are offline build
artifacts, **not a flashable boot image or proof of board readiness**. The binary
contains code/data only; the separate 145,457-byte raw weights stay at their
original vendor path with required base `0x71000000`. Do not use the old CAN HEX.

## Runtime ABI for later separately reviewed integration

`mailbox.h` is authoritative: one 512-byte, 32-byte-aligned mailbox at
`0x340F8000`, protocol version 1 and new magic `0x56354E36` (not the legacy ABI).
The ELF embeds the expected model and raw-weight SHA strings; strings alone do
not verify installed physical flash contents.

At boot the image parks in WAIT_PLATFORM. A future host must establish and
explicitly acknowledge all platform requirements with `platform_ack=0x504C4154`.
The acknowledgement is not attestation. No uploader is included. The image then
initializes STAI, checks its I/O descriptors, obtains the generated runtime-owned
input/output pointers, and requires the exact fixed address `0x342E0000`.
It never supplies a separate input buffer to `set_inputs`.

The reviewed host protocol must issue one request at a time: fill `command=1`,
`row_id`, `input_count=41`, and all 41 little-endian IEEE FP32 words; write the
strictly increasing nonzero `request_sequence` last. Wait for matching
`response_sequence` **and DONE**, while also monitoring ERROR/FAULT and timeout.
Do not modify a request in flight. All five raw FP32 output words, vendor API
statuses and the completed row ID are preserved. No argmax-only substitution or
implicit quantization occurs. Nonfinite inputs/outputs and observed concurrent
request changes fail closed. Input and output share the generated address with
different lifetimes; output is copied before another input may overwrite it.

`run_cycles` is a 32-bit DWT delta around the whole synchronous mixed CPU/NPU
call, not NPU-only time, nanoseconds or energy. Counter wrap/clock/frequency,
warm-up, interrupt and trigger policies require separate measurement review.
No PPK2 trigger or model self-test is automatically performed.

## Explicit unresolved platform prerequisites

- A reviewed loader must load all initialized ELF segments at VMA and establish
  the appropriate secure Cortex-M55 context. There is no BootROM/FSBL integration.
- Clock tree, NPU clocks/reset/cache, RIF/RISAF permissions, XSPI2 memory mapping,
  verified weight bytes, SRAM access and watchdog behavior are inherited and
  **not initialized or proved by this adapter**. We do not reuse legacy blanket
  security-region changes, watchdog defanging or fault recovery.
- CPU D-cache must be disabled before platform acknowledgement; otherwise the
  adapter rejects initialization. This is a reproducibility prerequisite for
  debugger/mailbox coherence, not a recommended production cache policy.
- Program RAM is `0x34064000..0x340F0000`; reserved stack is 32 KiB through
  `0x340F8000`; mailbox follows. Linker assertions prevent overlap with the fixed
  NPU activation range `0x342E0000..0x342E0800` and preserve weight range constants.
  These assertions do not prove the real boot firmware leaves these regions free.
- Faults park without continuing inference. A stuck vendor polling loop needs
  external timeout/recovery; the adapter does not implement a new watchdog policy.
- Full 1,024-vector QDQ-reference parity, physical mapping, board timing/energy,
  firmware stack high-water use and sustained power behavior remain untested.

All old v5 results, seventeen export negatives, source trees and papers remain
unchanged. Compiler/link success is not numerical, hardware or deployment acceptance.
