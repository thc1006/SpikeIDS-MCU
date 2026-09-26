# Offline two-board firmware candidates

Both architectures now have actual crosscompiled ELF and binary artifacts using
the exact native-passed QDQ constants and unchanged portable numerical core.
Neither firmware has executed on a physical board in this work.

## RA4E1: wrapper and tool commands passed

Actual session `8731`, launch `32ad84`, completion `324b14`, exit **0**;
37 subprocess commands returned zero. See
[external receipt](RA4E1_BUILD_ACTUAL_01_EXECUTION.json) and
[original RESULT](../../results/ra4e1_v5_build_20260925_01/RESULT.json).
The author hash/stat bookends cover 578 explicit input files, and the RESULT
records 172 artifacts before itself. This is not full compiler dependency closure.

The [ELF](../../results/ra4e1_v5_build_20260925_01/firmware.elf)
SHA is `fbe5bdd0f4cf5138d37336a01ba2a5bdf4c1923060db32d9c9c9356c947066fe`.
[BIN](../../results/ra4e1_v5_build_20260925_01/firmware.bin) is 123,120 bytes,
SHA `d9a49cb9a2728a6bd3779b9c91ad33c288b180ae77d5be32503311985f7e8cf2`.
Five PT_LOAD segments cover ordinary flash and SRAM only; no option/protection
programming range is present. Unresolved-symbol output is empty. Main stack is
8,192 bytes, ordinary static SRAM sections total 8,340 bytes, and the 512-byte
mailbox is at `0x2001f000` inside the reserved final 4 KiB. Dynamic maximum stack
and target runtime behavior have not been measured.

## ESP32-S3: compiler succeeded; original wrapper rejection retained

Candidate01 failed compilation because strict C11 on the SDK-facing app rejected
GNU `asm` in SDK headers. Original streams and FAILED remain, with exact old
configuration copies in `esp32s3_v5_candidate_history`. Candidate02 only lets
the SDK app use the SDK GNU dialect; the numerical/protocol/model units still
use C11 and all strict floating-point flags. Both consoles are explicitly NONE.

Actual session `84766`, completion `3f3d04`: compiler/link/image subprocess **0**,
outer wrapper **1**. Its generic empty-`nm -u` condition rejected three names:
`__cxx_fatal_exception`, `start_app`, `start_app_other_cores`. No RESULT was
created and [FAILED](../../results/esp32s3_v5_build_20260925_02/FAILED.json) is
unchanged. No third compilation or relink was used to obtain acceptance.

Separate saved-only observation `111ab8 / 0`, source
[review_esp_saved.py](review_esp_saved.py) SHA
`f27cf58a392100f3814f665e5dbc58305f246b73346656d17c0e5623cb473f97`, verifies
25 original input pins and unchanged 832 saved files/329 directories. Local IDF
`esp_system/CMakeLists.txt` and `cxx/CMakeLists.txt` explicitly add these three
`-u` names. None is referenced by the 34 inspected component archives; actual
startup functions `esp_startup_start_app` and its other-core variant are linked.
The final ELF has no relocations. This is bounded explanation of the rejection,
not a claim that every SDK/runtime dependency has been independently proven.

Eight PT_LOAD segments fit the SDK's mapped flash/internal SRAM/RTC ranges.
The extra RTC reservation is `[0x600fffe8,0x60100000)`, justified by the SDK's
`esp_system/ld/esp32s3/memory.ld.in`; the generic wrapper did not include this
range. `.ext_ram.dummy` is a zero-file-byte address-reservation section, not
evidence of an installed or enabled PSRAM device. CONFIG_SPIRAM is disabled.
Retained configuration uses a candidate 4 MB flash map, **not** confirmed module
capacity. The missing ESP_ROM_ELF_DIR warning concerns debugger symbol-script
generation; configure and compile exited zero in candidate02.

See [external build/review receipt](ESP32S3_BUILD_ACTUAL_02_EXECUTION.json).
[App ELF](../../results/esp32s3_v5_build_20260925_02/build/spikeids_v5_qdq.elf)
SHA `6f07e705dff6548a780fcd338f040f607e6838482b8aa1d5ac2b0a8000a9f9a9`;
[app image](../../results/esp32s3_v5_build_20260925_02/build/spikeids_v5_qdq.bin)
269,472 bytes, SHA `fc0ac37783d99faddfe1c82966632ad244a92556b9b1e016b338be9e32146fab`.
Bootloader is 13,760 bytes; partition table is 3,072 bytes. These are deliverables,
not a statement that programming or boot was performed.

## Wire identity and remaining technical checks

[WIRE_ABI.json](shared_v5/WIRE_ABI.json) is the common full-41-input/full-five-output
raw binary32 contract. HELLO supplies complete graph and validation hashes,
platform/backend identity and the actual FP environment result. Parent-owned
C/Python cross tests passed `b78a65 / 0` on wire SHA `fc811b0b…`; their inference
implementation was explicitly a test double, not a rerun of the real model.
The earlier HELLO boolean inversion was corrected before any crossbuild.
Seven bounded build-helper controls passed `5febed / 0`.

The backend is CPU FP32 arithmetic with INT8 stored constants, not an NPU or
all-integer kernel. Target FE_TONEAREST/gradual-underflow checks can still refuse
HELLO or inference; crosscompilation does not prove a passing FP environment.
Remaining board stage must establish physical ESP identity/connector/flash map,
review the fixed image programming paths, then preserve all original 1,024 row
IDs and all 5,120 output words. Acceptance uses the original FP32
`isclose(reference, actual)` gate (actual is the relative-tolerance anchor) and
zero argmax disagreements. No relaxed tolerance, calibration, labels, training,
CAN-model substitution, hardware, PPK or supply operation occurred here.
