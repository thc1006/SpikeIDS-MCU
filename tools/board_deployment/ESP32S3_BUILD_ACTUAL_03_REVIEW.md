# ESP32-S3 candidate03: successful offline pipeline

Actual session **93560**, launch `c3efd7`, completion **`69b94f / 0`**,
scope invocation **`17b6b6b4493d4572a1ad146a682f7a3b`**.
The dedicated scope used 4 GiB RAM, zero swap, CPU quota 200%, TasksMax 128,
outer timeout 900 s and Ninja `-j2`. See the
[external exit receipt](ESP32S3_BUILD_ACTUAL_03_EXECUTION.json).

All **9 subprocess commands** passed. The original
[RESULT](../../results/esp32s3_v5_build_20260925_03/RESULT.json), SHA
`672d89e8ebdd2c1ecf90cdec38d1215b7d0a3b418b5f9c820aa27a93e7c20622`,
retains 28 original input SHA/stat pins, 843 artifact pins before itself and
329 directories. The author bookends checked inputs and retained outputs;
full SDK/toolchain dependency closure is explicitly not claimed.

The [v2 source](build_candidate_v2.py) SHA is
`4af738272558c3b38143f2780f58a57655ce9697573d576340c5f25353b26071`.
Source and test hashes matched before launch and after completion (`3437a9`).
[Preflight](BUILD_V2_PREFLIGHT_REVIEW.md) records 22 passing pure saved-artifact
and in-memory counterexample tests. Parent independently read the narrow v2
change before the one fresh candidate03 build.

V2 requires exactly the three documented SDK `-u` symbol names, their anchored
CMake directives, no reference to those names from **all 48 build archives**,
and no ELF relocation sections. It does not ignore arbitrary undefined symbols.
All eight PT_LOAD segments passed; the sole additional RTC reservation is
exactly 24-byte RW NOBITS at `0x600fffe8`, not an arbitrary RTC payload allowance.
All three model/protocol/numerical compile commands were checked as complete
`shlex` tokens, including final C11/O2 and unchanged strict floating-point flags.
Primary and secondary consoles are NONE; PSRAM is disabled.

Actual deliverables:

- [App ELF](../../results/esp32s3_v5_build_20260925_03/build/spikeids_v5_qdq.elf):
  SHA `ddf4b31dc4faab544dbbd8a09cb0a2c583477977893588931a7a857e1a0a75a8`.
- [App image](../../results/esp32s3_v5_build_20260925_03/build/spikeids_v5_qdq.bin):
  269,472 B, SHA `a5f27b149d3fde49ad9825a656dd540c5204377b7238952c4e9ba2af9b79edbb`.
- [Bootloader](../../results/esp32s3_v5_build_20260925_03/build/bootloader/bootloader.bin):
  13,760 B. [Partition table](../../results/esp32s3_v5_build_20260925_03/build/partition_table/partition-table.bin): 3,072 B.

This supersedes the broken generic check only for this new successful build.
Original build_candidate.py, successful RA01, and failed ESP01/02 remain intact;
their exits are not rewritten. No model inference, training, graph conversion,
device connection or programming was performed. Physical ESP identity/flash
capacity, boot, target FP-environment gate and full original 1024-row parity
remain technical checks for the board stage. This is a CPU FP32 QDQ candidate
with INT8 constant storage, not an NPU or all-integer backend.
