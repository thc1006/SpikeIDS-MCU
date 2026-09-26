# SRAM callback-trace diagnostic variant (not built or deployed yet)

This additive variant replaces, rather than co-resides with, `firmware_sram`.
All original S6 source/artifacts and generated ST3.0 code remain unchanged.
The builder literally pins the seven original S6 implementation/ABI files and
the three reviewed `npu_trace` files. New sources, layout, ABI and documentation
are included in its original input pins before compilation. Startup and no-I/O
syscalls are byte-identical copies of S6. Fixed model, weights, headers, tools,
runtime and generation-history checks remain the original S6 build contract.

Model is the NSL-KDD primary seed-0 QCFS quantized ANN, not a spiking runtime:
`22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d`.
The unchanged 145,457-byte SRAM weights have SHA-256
`cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec`.
No compiler/model/runtime regeneration or source patch is performed.

## Exact memory and protocol changes

The MCU image remains at `0x34064000`, stack `[0x340f0000,0x340f8000)`,
and mailbox `[0x340f8000,0x340f8200)`. The added NOLOAD trace occupies exactly
`[0x340f8200,0x340f9b9c)` (6,556 bytes). All five PT_LOAD segments are checked;
the complete reserved weights `[0x34200000,0x34240000)` and activations
`[0x34240000,0x34244000)` remain excluded. The linker asserts the new boundary
and trace size. No trace bytes are embedded in the BIN. The existing separate
platform-stage region starts at `0x34180400` and is disjoint.

New mailbox magic `0x54364e36` and deployment tag `0x54523031` prevent an old S6
host from silently consuming this variant. Existing offsets through both full
65-byte hash strings (bytes 0..481) remain unchanged. The former 30-byte tail
becomes two padding bytes and seven aligned words at offsets 484..508: trace
address, trace bytes, actual log run ID, begin/finish return status, exact STAI
callback-registration return, trace complete, trace error. `ABI.json` gives the
fixed values. Six original API statuses, all 41 input words and all five output
words remain available; there is no tolerance or argmax-only substitution.

## Runtime evidence contract

After successful network initialization, `npu_trace_bind` registers the frozen
callback on the exact generated descriptor table. Each immutable request calls
`begin(sequence)` before STAI synchronous run, and always calls `finish(actual
run return)` immediately after that call returns, before any error park. The
runtime's normal synchronous reset produces DeInit(NULL), then Init(NULL):
complete means exactly 160 epoch callbacks (40 executable entries: 8 pure-HW,
1 hybrid, 31 pure-SW), followed by those two lifecycle callbacks. The 41st table
entry is a nonexecuted sentinel. Raw flags/wait masks, payload addresses and
ordering are retained and fail-latched by the unchanged helper. A void callback
cannot abort hardware; a hung runtime may leave a partial active log and requires
a separately bounded host/target policy.

On any returned run, exact run/get-error codes and all five raw output words are
preserved before parking on runtime or trace error. Such error-path outputs are
not accepted logits even if finite. Trace failure prevents DONE. Initialization
or pre-begin failure can have no trace for the requested run; never relabel the
old/zero run ID as new evidence. FAULTs are not normal trace completion either.

This log is not a live seqlock buffer. A new host must recognize the new ABI,
observe stable matching DONE plus response sequence (or ERROR with immutable
request and matching log run ID), halt the CPU, then save the complete 6,556-byte
log and full mailbox before another request. On ERROR, response_sequence retains
the last successful sequence and must not be fabricated as a completion commit.
Early errors without a matching run ID remain diagnostic failures, not traces
of a completed run. The next `begin` clears the previous log, so **retention
before the next request is a mandatory host obligation**, not an on-target ACK
protocol. A malicious or mistaken host can violate this obligation. No such
trace-aware host integration or board upload is included here.

The read-only DWT callback counter has not been qualified for counting, rate or
multi-wrap duration. It measures perturbed MCU callback windows, including
software/polling work, not independent NPU hardware cycles. Callback completion
is evidence that this instrumented runtime traversed the expected descriptor
classes, not independent hardware proof, numerical parity, performance or
energy acceptance. Hybrid classification alone does not prove NPU execution.

## Offline build interface and remaining gates

`build.py --output-dir <fresh absolute direct child of this directory>` is an
executable fixed ARM compile/link chain using GNU 13.2.Rel1. There are no model,
flags, address, runtime, hardware or retry overrides. Results use names
`n6_sram_trace.elf`, `.map` and `.bin`; raw per-command logs and failures remain.
External scope/time/resource bounds and actual process-exit evidence are still
the invoking owner's responsibility. Source/byte/stat bookends are finite checks,
not atomic filesystem/OS attestation; the unchanged inherited writer is not a
general hostile-filesystem framework.

This preflight uses synthetic ELF objects and static source controls, not an ARM
compile or execution of the new C integration. The frozen callback helper had
its own 38 C controls and two ARM object checks; those do not prove this complete
variant links. Separate parent review/authorization, actual ARM build and saved
artifact review are required next. Existing secure privileged entry, platform
initialization/ack, CPU D-cache-off, polling runtime and watchdog requirements
remain. This image does not initialize clock/RIF/power/flash/XSPI/OTP or access
USB/GPIO. No device was accessed by this work, and no hardware or energy result
is accepted.
