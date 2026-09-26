# Additive RA4E1 / ESP32-S3 v5 candidates

Native saved-output review passed independently (`651dd6 / 0`); that does not
establish MCU arithmetic or hardware acceptance. Compile the exact generated
`model.c` SHA `bba723cc7b031815c2aaf848f6893eb87dd91cb05f5580f93df611be489bb1e9`
and unchanged portable core/header SHAs `e389a691…` / `e8abd58b…`. No model
conversion, CAN weights, regeneration, quantization change or trained-model
selection is part of these projects. The shared backend is CPU FP32 arithmetic
over compact INT8 constants, not an NPU or all-integer implementation.

## RA4E1

Use read-only adjacent FSP 6.5.0 startup/system/BSP and generated configuration,
GNU Arm 13.2.Rel1, Cortex-M33 hard FPv5-SP-D16. A new `bsp_cfg.h` wrapper changes
only main-stack allocation from 1 KiB to **8 KiB**; two 256-float core temporaries
alone need 2 KiB. No µT-Kernel/CAN application or old model is linked. Existing
generated CAN vectors/driver remain SDK dependencies, but CAN is never opened.

The existing FSP linker remains read-only. The additive wrapper reserves the last
4 KiB of the 128 KiB SRAM from general allocation; a fixed 512-byte mailbox starts
at `0x2001f000`. Ordinary flash remains `[0,0x80000)`. Drop option-setting
sections and verify no allocated image payload at option/protection addresses;
never blindly program old FSP option records. Model weights stay in flash. The
SDK's ordinary startup initializes the MCU; this is not the N6 no-init stub.
No code is executed on the target during this stage.

RA mailbox 32-bit fields at offsets 0..28 are magic `0x41353556`, version 1,
state (READY=1/BUSY=2/DONE=3/ERROR=4), FP environment check, request commit,
response commit, next sequence, SDK SystemCoreClock metadata. Request frame is
at offset 32 (232 bytes), response at 264 (88 bytes), then the 160-byte HELLO
identity at offset 352, published before READY.
Host writes the entire request before request_commit; must not write it while
busy. Firmware copies and rechecks every request byte/commit. Response body then
DMB → state → DMB → response_commit; host requires stable terminal state and
matching commit/sequence/CRC, not a commit value alone. No measured clock or
timing claim follows from SystemCoreClock.

## ESP32-S3

New ESP-IDF 5.4.4 project and fresh build/configuration; no inherited CAN project,
ESP-NN kernels, Wi-Fi or PSRAM. Fixed CPU0 worker, 8 KiB internal task stack,
same portable arithmetic flags. Use built-in USB Serial/JTAG binary driver,
not guessed UART GPIOs or console text. Application/bootloader logging is disabled;
host still uses framing/CRC to reject startup noise. Exact module/PCB/connector
remains unconfirmed: compile-time 4 MB flash layout is a candidate bound, **not**
proof of populated flash or permission to assume PSRAM. Readback/physical identity
must confirm the image layout before later programming. The user has authorized
ordinary three-board work; this technical prerequisite is not a new permission gate.

## Shared raw protocol

All multi-byte integers and binary32 words are little-endian. CRC-32/IEEE uses
polynomial `0xedb88320`, initial/final XOR `0xffffffff`.

Request: magic `V5RQ` at 0, u32 version=1 at 4, sequence at 8, ordinal at 12,
original 64-bit row-ID word at 16, input count=41 at 24, payload bytes=164 at 28,
raw 32-byte original QDQ SHA at 32, 41 input words at 64, CRC over bytes 0..227
at 228. Device requires sequences 1..1024 once per boot and ordinal=sequence−1.
It echoes row-ID bits, not a fabricated row index; host independently matches
the original frozen row-ID/order archive. No device label/test access.

HELLO query is 12 bytes: `V5HQ` u32 magic, version 1, CRC over the first 8 bytes.
It does not consume/reset sequence or invoke inference. HELLO response is 160
bytes: `V5HI`, version 1, board ID (RA=1/ESP=2), backend ID 1 (portable CPU FP32),
flags (bit0 means FP environment passed; all other bits zero), input count 41,
output count 5 at offsets 0/4/8/12/16/20/24. Full lowercase ASCII graph SHA
occupies bytes 28..91; original vectors SHA occupies 92..155; CRC is at 156.
There is no nonce or authentication claim. ESP recognizes query/request magic
in a rolling byte window; malformed complete frames are rejected and incomplete
frames discarded, while host transport bounds and retains any prefix noise.

Response: `V5RS`, version, sequence, ordinal, row-ID occupy the same first 24 bytes;
status at 24, output count at 28, compiled graph SHA at 32, all five FP32 logits
at 64, CRC over bytes 0..83 at 84. Nonzero status means count=0 and invalid output
words. No argmax-only shortcut. Valid framed requests are consumed once even on
arithmetic failure; no silent re-inference retry. Malformed requests never invoke
the model. A reboot/new session is required after the fixed 1024-request run.

Builds retain exact source/model/tool identities, commands/exits/streams, ELF/map
and section/address observations. Flags include `-fno-fast-math`,
`-ffp-contract=off`, `-fexcess-precision=standard`; runtime refuses non-nearest-even
or nongradual-underflow FP environments. Actual full 41/5 board parity remains
separate after build review. This task performs no USB, device, flash, OTP, PPK
or supply operation.
