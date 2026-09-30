# Offline SRAM-weight ARM adapter candidate

This is a new executable build for the exact NSL-KDD seed-0 QCFS QDQ graph
`22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d`.
It is a quantized ANN deployment, not a spiking runtime. The unchanged RAW
weights are 145,457 bytes, SHA
`cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec`.

Generated code is read only from the retained `internal_sram_actual_01`; there
is no re-export, regeneration or manually patched generated address. The saved
review `e024e446e6c1dca394c61081e9ba1251e0483dce80d5d7d7a303538b6bc7528d`,
its external exit `30cb08b2498e9d246dee46e0b713f6981f75129ae60b60c137cafaa73cd297c3`,
and original retained snapshot `ddf5338a4724bb5ec25487fd1a1f28426d49689dd538419304d6d02d23513d75`
bind this candidate. Original generation wrapper exit 1 / compiler exit 0 and
FAILED/no RESULT remain unchanged. The separate saved review exit 0 is not a
rewrite of the original result.

## Memory and startup contract

MCU image starts at `0x34064000`, stack is `[0x340f0000,0x340f8000)`,
mailbox is at `0x340f8000`. This is a mutually exclusive replacement for v5,
not simultaneous resident execution. The separate minimal probe region remains
disjoint. Weights reserve **all** `[0x34200000,0x34240000)` (256 KiB);
activations reserve **all** `[0x34240000,0x34244000)` (16 KiB), although used
activation bytes are 2,048 and one prefetch stop reaches 2,112. No PT_LOAD
segment may overlap either reserved pool. The ELF does not embed the RAW weights.
A separately reviewed loader must establish RAM access, load image PT_LOADs and
BSS correctly, then load/read back the exact RAW in its weight range.

The reviewed v5 adapter semantics are reused in new sources. Naked startup masks
interrupts, establishes MSP/CONTROL, enables CP10/CP11 before optimized C, sets
VTOR and clears BSS. This presumes privileged secure Thread entry from a reviewed
loader; it does not discover or establish board security, clock or power state.
Polling runtime and Cortex-M55 software fallback are retained. USE_NPU_CACHE is
not defined. Runtime cache-maintenance routines are not cache initialization.

The 512-byte mailbox has a distinct S6 magic/deployment tag. It initially stays
in **WAIT_PLATFORM**. No board initializer is provided and no code writes a fake
acknowledgement. The host prerequisite token is not hardware attestation: SRAM
clock/shutdown state, NPU clock/reset, precise RIF/security, cache policy, secure
entry and watchdog policy remain separate requirements. CPU D-cache must be off.
There are no adapter calls to power/clock/RIF/XSPI/flash/OTP or USB/GPIO setup.
Post-ack API initialization/inference necessarily invokes the ST runtime.

One outstanding request carries all 41 finite FP32 input words; the runtime-owned
input/output addresses must both be `0x34240000`. The deliberate lifetime alias
is handled by copying all five output words before the next request. Full logits,
row IDs, request/response sequences, six exact API statuses, model/weight hashes
and deployment pool IDs are exposed. Cycle counts surround the whole mixed
CPU/NPU call, not NPU-only time. No argmax-only or tolerance-based result is used.
Before and after the vendor run, finite checks compare sequence, row, command,
input count, platform token and all 41 request words against the stable copy.
This does not make arbitrary concurrent host mutation safe: the host must still
honor one outstanding immutable request. DONE precedes the final DMB-ordered
response_sequence commit; a host consumes only a stable matching DONE+sequence.

## Offline build only

`build.py --output-dir <fresh direct child>` has a fixed compiler/source graph
and no model/compiler-flag overrides. The ARM compiler is the existing GNU
13.2.Rel1 toolchain; headers, selected libraries and generated artifacts are
pinned. Synthetic/source review precedes exactly one root-approved build.
Failures and raw command exits are retained without automatic retries.

There is no target execution, USB/SWD access, RAM upload, voltage change, flash
or OTP operation in this phase. A successful ELF is not proof of initialized
hardware, safe loading, on-board inference, numerical equivalence, performance
or energy. Old firmware, probe and SRAM-generation files remain unchanged.
