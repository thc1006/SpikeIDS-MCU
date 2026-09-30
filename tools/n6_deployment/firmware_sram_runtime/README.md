# S6 global-runtime initialization repair

Separate variant; original generated model, weights, firmware and failures are
preserved. The old model-init call is replaced by a checked wrapper that calls
`stai_runtime_init()` once after platform ACK, before model initialization.
The wrapper records call count, exact runtime status and a distinct stage.
New deployment tag SM02 and three receipt words occupy former input padding.
Old host must reject this variant. No model, math or tolerance change.

Build uses the source-pinned old build engine in a separate module namespace,
with only variant directory/includes and additional frozen inputs selected.
All compiler/runtime identities, full dependency pinning, layout checks and
no-overwrite behavior remain. Include wrappers reuse original C/linker files;
these exact originals are pinned before compilation. No USB or target access
occurs in building. The inherited build report's platform-initialization
limitation does not mean the new global runtime call is missing.

Installed ST 3.0 sources confirm runtime initialization enables the global
NPU clock and bus interfaces. Default pre-init hook is empty. Bare-metal
polling OSAL must remain selected. Runtime initialization DOES configure NPU
interrupt masks and NVIC enable/disable bits, even in polling mode; PRIMASK=1
must remain asserted and be checked while halted before inference. It does
not request PWR/OTP/Flash initialization. Actual machine code and compiled
call graph must be reviewed before deploying. The 16-entry exception vector
table is not an external-IRQ handler table, so unmasking IRQs is not allowed.

Acceptance requires actual cross-build, saved artifact review, fixed new host
binding, explicit FP entry, and full original 1024-row all-logit parity.
Host controls alone are not hardware acceptance. NPU profiling and energy
remain separate later phases; PPK is currently removed.
