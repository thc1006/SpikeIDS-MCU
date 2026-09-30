# Actual ARM build — author review and handoff

2026-09-25. Offline engineering only. The author implemented this adapter and
build tool; this note does not substitute for an independent code/ABI review.
No device, USB, serial, programmer, GPIO, power control, model inference or
vendor model regeneration was used. All existing firmware/model/result files
remain untouched; only this new `firmware_v5/` directory was written.

## Actual result

Fresh `build_actual_03` completed with observed tool session **66775**,
completion **c9e7aa**, exit **0**; systemd scope invocation
`463a5c045c7443aa8c843a9ce91eef8a`, requested 4 GiB memory, no swap, CPU 400%,
128 tasks. Every one of 62 recorded commands exited 0, including **23 real ARM
compilations and link**. Compile/link logs contain no warning/error matches.
The linked ELF's `nm -u` output is empty.

| Artifact | Whole SHA-256 |
|---|---|
| `build_actual_03/RESULT.json` | `3d4495b676421e56d4b30dd4e47c1fe9f9d052348a2b124102fa3e30b373021e` |
| `build_actual_03/n6_v5.elf` | `caa57e5b8749acfe2a65ff269cb49084a5832af2c863b3320b3cbb7526851ec2` |
| `build_actual_03/n6_v5.bin` | `8778d45209bf67f15411ad4492b14ef1a4f91c2cbfaff57b256bfbd46fbfbd12` |
| `build_actual_03/n6_v5.map` | `f472d70c0f1b2bafbb88a61107f303fa275b8b40345a2ba956e7d409ae984a01` |

Result seal: `8d67cf498fc77b1af189a757ce4f0e910b5056e15b38f8ecb269c05f3ac72bb5`.
ELF is 3,917,252 bytes including debug data; the code/data binary is 78,260 bytes.
ELF32 little-endian ARM, EABI5 hard-float, Cortex-M55/v8.1-M, integer/FP MVE;
Thumb entry `0x34064061`. RX code and RW data/stack/mailbox are separate segments.

Linker reports 97,824 bytes in the 560 KiB program RAM region (including the
16 KiB bounded heap), separately reserves 32 KiB stack, and places the 512-byte
mailbox at `0x340F8000`. Static assertions fixed input offset 128/output offset
320 and the 512-byte ABI. NPU RAM remains `0x342E0000..0x342E0800`; separate
weights remain in the original vendor raw file for `0x71000000`. Weights are
not silently embedded into the RAM binary or copied/flashed by this build.

The symbols include `ll_sw_forward_conv`, `ll_sw_forward_activ`,
`ll_sw_forward_arith`, `ll_sw_forward_quantizelinear` and
`ll_sw_forward_dequantizelinear`, supporting the previously observed mixed graph.
This proves linkage, not execution or numerical equivalence of these routines.

## Issues discovered and preserved

- `build_actual_01`: wrapper exit 1 at version gate because its initial expected
  text used `Rel1`, while the actual banner contains `rel1`; compiler version
  command itself exited 0. Updated to the exact observed full version line.
- `build_actual_02`: all 22 then-present sources compiled, but link exited
  nonzero. `LL_ATON_SW_FALLBACK` defaults to zero, so merely compiling
  `ll_sw_float.c` did not define the required functions. Installed ST
  `NPU_Validation/armgcc/Makefile` explicitly enables this option. The new build
  now sets it to 1; no generated/model source was changed.
- The same link caught nosys stub warnings under `--fatal-warnings`. Added
  explicit no-I/O newlib stubs, bounded heap and terminal fault handling rather
  than suppressing linker warnings or adding UART/semihosting.
- Root review identified the initial FP/MVE startup-order risk. Naked startup
  now sets CPACR before any C/library call. Actual objdump check **b6a64f / 0**
  shows CPACR OR `0x00F00000`, DSB/ISB, then branch to `reset_c`.

Both earlier failure directories/logs remain intact. No success is inferred
from them. Current source files and successful build03 are now HOLD.

## Source and retention binding

- `build.py`: `8b83c0f3242dec08014d5b8034100fb81bcb874fca8582041b668bc3427d1f1e`
- `main.c`: `3b30416251faa6e330ddc2e7c1d6c1b4df43eef594c78bc12ec8b7834d281040`
- `startup.c`: `912f0e5c864f805c2460508d54d520b41a060e5af472a5c1ccb5884bb1e2629d`
- `mailbox.h`: `240f02e13b8320725b7ade5dbda1b768347120c3ac800cf8a3db024811b802df`
- `linker.ld`: `7bb333c935a7da04f3758d6df381385c5c4cd994e7b60d427c362c888706532d`
- `syscalls.c`: `ce10a311ceee59cf4493cf43ef2f1d4b854a9c2a9570b60c7007256862fb3c3d`
- `README.md`: `4ab7f7ee4548c50019d26362b1bc1547f7ce2adb3c4c7a16e240290ed0b39500`

The builder held 220 direct/discovered source/header/tool/library inputs before
object compilation, plus objects before linking, and hash-checked them at its
endpoint. Separate read-only postcheck **9a45c6 / exit 0** confirmed all 220 input
stats, 237 artifact stats, seven authored source hashes, ELF/BIN/map hashes and
the exact 238-file successful output namespace. These are finite bookends, not
an atomic filesystem snapshot or complete transitive host-library attestation.

## Not yet proved / required before device use

The adapter deliberately waits for an explicit platform acknowledgement before
touching STAI/NPU initialization. That token is not evidence that clocks, secure
execution, RIF/RISAF, XSPI2 mapping, physical weights, NPU state or watchdogs are
correct. No FSBL, loader, flash plan or initialization of those domains is
provided. IRQs remain masked; polling mode is enforced at compile time. CPU
D-cache must already be disabled; otherwise initialization is rejected.

Runtime code obtains the exact preallocated I/O pointers, copies 41 FP32 words,
preserves all five output words and per-API status, and fails on observed layout,
finite-value, request-change or API errors. This protocol has not been exercised
on a device or by a simulated runtime; real compilation/static checks are not
behavioral test coverage. Later independent review must cover row handoff/error
paths, host timeout, numerical parity against all 1,024 held QDQ references,
physical memory ownership and cache policy. DWT cycles are diagnostic modulo
32 bits around the entire mixed run, with no measured clock/energy claim.

No next hardware action is authorized by this note. `board_ready`,
`board_validated`, `compiler_semantic_parity_verified`, `deployment_accepted`
and `energy_measured` are all false.
