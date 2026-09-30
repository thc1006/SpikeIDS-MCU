# Independent offline firmware build review

Reviewed `build_actual_03` and the final adapter sources on 2026-09-25. No
additional concrete blocker was found within this bounded offline scope. This
is not board, numerical, power, or deployment acceptance.

## Observed checks

The independent read-only artifact check completed as tool chunk `5582b2`,
actual exit **0**. It did not import or run `build.py`, invoke the compiler, or
access hardware.

- Recomputed the RESULT seal using its original sorted, indented JSON encoding;
  checked its schema, kind, build-success flag, and all five false acceptance
  flags.
- Checked **237 retained artifacts with current full SHA-256 and original
  seven-field filesystem metadata**, before/after reading. Checked the exact
  build-directory namespace, including RESULT and excluding unknown entries.
- Checked **220 input paths against their original seven-field stat metadata**.
  This was **not** a current full-hash verification of all 220 inputs. Separately
  full-hashed the seven direct adapter/build/documentation sources listed below.
- Verified all 62 retained command records had typed integer return code zero
  and `timed_out=False`, and matched their individual command JSON records.
  All 23 compile commands specified Cortex-M55 hard-float, polling mode, and
  software fallback.
- Confirmed the retained undefined-symbol output was empty, and independently
  ran the installed ARM `nm -u` against the ELF: exit zero, empty output.
- Parsed the actual ELF header and four PT_LOAD segments: ARM ELF32
  little-endian, hard-float ABI, permissions RX/RW/RW/RW, non-overlapping VMAs,
  initialized data loaded at VMA, entry `0x34064061`, and initial stack pointer
  `0x340F8000`. Reconstructed the **78,260-byte** binary from the initialized
  PT_LOAD bytes and compared it byte-for-byte with `n6_v5.bin`.
- Rechecked artifact/input metadata, RESULT identity/hash, and exact namespace
  at the end. These finite bookends do not claim atomic filesystem attestation.

Independent disassembly command `8855b7` exited **0**. The actual Reset_Handler
enables CP10/CP11 access with DSB/ISB before branching to the first C routine;
startup masks IRQs. The actual main code retains all 41 raw input words and five
raw output words, count/layout checks, finite-word checks, sequence/row checks,
and the barrier before publishing response sequence and DONE. The host contract
requires both matching response sequence **and DONE**, with one outstanding
request and no request mutation in flight.

The source/API reads confirmed that the generated input and output are
non-user-allocated, FP32, respectively 164 and 20 bytes, at the same address
`0x342E0000`, with input epoch 0 and output epoch 44. The adapter obtains those
runtime-owned pointers and copies outputs out before writing another input; it
does not replace them with a separate `set_inputs` buffer.

Polling follow-up source reads (`9e1e19`, exit **0**) confirmed the selected
runtime path waits through `LL_Streng_Wait`/`LL_EpochCtrl_Wait` and returns
`LL_ATON_RT_NO_WFE`. The full-disassembly search (`725917`, exit **0**) found
`cpsid` and no `cpsie`. A generic STAI wrapper **does retain a WFE instruction**
at `0x34069BE0`, reached on a `LL_ATON_RT_WFE` return; this review does not claim
the ELF contains no WFE instruction. Several exploratory source reads used
incorrect vendor paths and returned exit 2; the relevant paths were then
resolved from RESULT's input list. Those path-lookup errors were not build or
adapter failures.

The build author separately reported build session `66775`, launch chunk
`e75239`, completion `c9e7aa`, exit **0**, scope
`spikeids-n6-v5-arm-build-20260925-03.scope`, invocation
`463a5c045c7443aa8c843a9ce91eef8a`. This review independently checked its retained
artifacts and command records; it did not itself observe that build process.

## Exact reviewed bindings

| File | SHA-256 |
| --- | --- |
| `build_actual_03/RESULT.json` | `3d4495b676421e56d4b30dd4e47c1fe9f9d052348a2b124102fa3e30b373021e` |
| RESULT content seal | `8d67cf498fc77b1af189a757ce4f0e910b5056e15b38f8ecb269c05f3ac72bb5` |
| `build_actual_03/n6_v5.elf` | `caa57e5b8749acfe2a65ff269cb49084a5832af2c863b3320b3cbb7526851ec2` |
| `build_actual_03/n6_v5.bin` | `8778d45209bf67f15411ad4492b14ef1a4f91c2cbfaff57b256bfbd46fbfbd12` |
| `build_actual_03/n6_v5.map` | `f472d70c0f1b2bafbb88a61107f303fa275b8b40345a2ba956e7d409ae984a01` |
| `main.c` | `3b30416251faa6e330ddc2e7c1d6c1b4df43eef594c78bc12ec8b7834d281040` |
| `startup.c` | `912f0e5c864f805c2460508d54d520b41a060e5af472a5c1ccb5884bb1e2629d` |
| `mailbox.h` | `240f02e13b8320725b7ade5dbda1b768347120c3ac800cf8a3db024811b802df` |
| `linker.ld` | `7bb333c935a7da04f3758d6df381385c5c4cd994e7b60d427c362c888706532d` |
| `build.py` | `8b83c0f3242dec08014d5b8034100fb81bcb874fca8582041b668bc3427d1f1e` |
| `syscalls.c` | `ce10a311ceee59cf4493cf43ef2f1d4b854a9c2a9570b60c7007256862fb3c3d` |
| `README.md` | `4ab7f7ee4548c50019d26362b1bc1547f7ce2adb3c4c7a16e240290ed0b39500` |

## Unverified boundaries

No source or build artifact was edited, no compiler was rerun, no inference was
performed, and no USB, programmer, serial, GPIO, PPK2, flashing, or power action
was taken. No synthetic execution is presented as on-target evidence.

This is a RAM-load adapter, not a BootROM/FSBL or flashable boot image. Actual
secure execution, loader behavior, memory availability/permissions, clock tree,
NPU/cache setup, XSPI mapping and physical weight bytes remain unverified.
The platform acknowledgement is a host prerequisite token, not attestation.
CPU D-cache is required to be disabled; the firmware rejects enabled D-cache
at initialization. Watchdog behavior and recovery from a stuck polling loop
require separate integration review.

The linker layout does not prove real boot firmware leaves these regions free.
FP/MVE access and hard-float ABI do not establish model parity or all inherited
floating-point state. All-five-logit on-target parity, stack high-water use,
clock/cycle interpretation, sustained power, timing and energy remain untested.
`run_cycles` covers the whole mixed CPU/NPU synchronous call, not NPU-only time
or energy. The review does not establish complete transitive toolchain identity,
compiler semantic equivalence, hardware readiness, or deployment acceptance;
the existing scientific/export outcomes are not relabelled.
