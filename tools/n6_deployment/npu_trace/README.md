# Fixed ST 3.0 NPU-runtime callback trace

Additive offline preparation only. Neither this module nor its checks accesses a device. No frozen SRAM firmware, generated model, runtime source, weights or build result is modified. The module is not yet linked into an instrumented firmware variant or executed on hardware.

## Actual API and schedule

`npu_trace_bind(network, ctx, log, read_cpu_counter, cookie)` uses the actual generated `stai_nsl_qcfs_seed0_set_callback` API. Its ST 3.0 bridge forwards the `LL_ATON_RT_Callbacktype_t` value and original `EpochBlock_ItemTypeDef *`. This is **not** the generic `STAI_EVENT_NODE_START/STOP` numbering: PRE_START, POST_START, PRE_END and POST_END are 0, 1, 2 and 3 respectively.

The fixed generated SRAM model has 41 descriptor entries: 40 executable entries (8 pure-HW, 1 hybrid, 31 pure-SW) and one `last_eb` sentinel. The runtime checks the sentinel before start/end execution; it has no four-event callback sequence. The fixed model projection is saved in `check_actual_05/MODEL_DESCRIPTOR_PROJECTION.json` with the original generated-C hash. Compiler epoch IDs are not contiguous array indices.

The selected **STAI_MODE_SYNC** path automatically resets the network before returning: after 160 epoch callbacks it emits `NN_DeInit` (5, NULL payload), then `NN_Init` (4, NULL payload). The log therefore has **162 records**, while the matched-epoch-event count remains 160. Missing, reversed, early, non-NULL, extra or out-of-order events fail the completion gate. Other runtime modes are outside this contract.

The hybrid entry is compiler epoch 6, a FLOAT-to-FXP Cast. In this fixed ST 3.0 source it takes the CPU conversion branch of `LL_ATON_LIB_Cast`, not its same-type DMA-copy branch. Therefore a hybrid label alone is not an additional hardware-execution count. Unexpected internal-library callbacks are retained as a failure, not silently folded into the expected 40 entries.

## Future integration (not a hardware instruction)

In a **new** instrumented adapter after successful network initialization:

1. Allocate `npu_trace_context_t` and the fixed-width 6,556-byte `npu_trace_log_t` in a separately reviewed memory region. Bind once and require success; use the same runtime compile configuration, including `LL_ATON_EB_DBG_INFO`, for every translation unit.
2. Call `npu_trace_begin(ctx, fresh_nonzero_increasing_run_id)` immediately before the existing synchronous run. Call no init/deinit inside this interval beyond the reset that STAI already performs.
3. Run the unchanged generated model through `stai_nsl_qcfs_seed0_run(..., STAI_MODE_SYNC)`. Always call `npu_trace_finish(ctx, actual_return_code)` after the call returns. Preserve raw trace and full outputs/status even on failure.
4. Require successful finish and normal output validation before labeling the trace complete. Persist this run's log before a later explicit begin overwrites the one-run buffer. Detach the callback before separately deinitializing the network. Reading the buffer live requires a separate publication protocol; this struct is not a seqlock mailbox.

The original table pointer, function pointers, flags, wait masks, blob fields and (when enabled) debug metadata are checked against the preparation snapshot during events and at completion. Foreign/NULL epoch payloads are rejected before dereference. Error state latches, existing rows are retained, and overflow never writes past the fixed buffer. These C callbacks return void: failure of the trace gate **does not stop hardware or abort the runtime**. A stalled model may leave a useful partial trace but will not reach finish; an independent owner timeout/abort policy is still necessary.

An optional read-only CPU counter provider supplies raw 32-bit values and modulo-32 deltas. No DWT, GPIO, clock or NPU register is touched by this module. `counter_present` is not proof the clock was enabled, calibrated, monotonic across resets, or free of multiple wraps. PRE/POST intervals include runtime setup, polling, software and callback overhead. They are not NPU hardware cycles, exclusive accelerator latency, or accepted performance figures. Omitting the provider still permits callback-sequence completion with counter_present=0.

Completion establishes only that the instrumented runtime callback path was traversed in the expected order, stronger than merely finding NPU symbols in an ELF. It is not independent hardware-completion proof, compiler semantic parity, electrical readiness or formal energy/performance acceptance. Hardware proof would need separately reviewed hardware-counter/status evidence plus correct outputs; this phase does not implement or authorize it.

## Evidence and limits

`check.py` pins six original ST/generated semantic sources, verifies the literal descriptor projection, runs host C synthetic controls and compiles two Cortex-M55 relocatable objects against actual installed ST/generated declarations. It never compiles or runs the generated model. The host registration function/table are explicit synthetic seams; only that host path replaces the generated header's ARM-specific declaration dependency. ARM compilation uses the real generated header. Third-party include paths are system headers; new module sources remain under `-Wall -Wextra -Werror`.

Final author execution `abcd9a`, exit 0, invocation `5bcf5157159448c5bda35feac8a92b7f`: **38 host controls passed**, both ARM object compilations passed, with full recorded input hash/stat bookends. This is not a full firmware link or live STAI runtime test. The finite build record does not attest every compiler subprocess/library or the whole installed OS environment.

Earlier results remain: 01/02 host preprocessing failed on ARM-only include dependencies; 03 passed the original 32 host controls but failed on unused-parameter warnings in ST's ATON header. Root then identified the missing synchronous reset events; 04 (`923f02`, exit 1) reproduced that real contract defect with 160+DeInit+Init before finish. Original pre-fix C/header/tests are retained as `pre_sync_*`. The final 38 controls include realistic reset completion and missing/reversed/early/extra lifecycle failures.

Primary source anchors: installed ST3 `ll_aton_stai_internal.c` sync/reset around lines 382–438; `ll_aton_runtime.c` callback brackets 101–268, network reset 475–522 and polling/sentinel logic 686–770; fixed model `nsl_qcfs_seed0.c` descriptor table 3960–4524 and Cast at 504. Their exact hashes are in `check.py` and the RESULT. [ST's profiling documentation](https://stedgeai-dc.st.com/assets/embedded-docs/stneuralart_profiler.html) distinguishes callback-phase MCU timings from hardware-counter NPU measurements; that current page is for 4.0.0 and is conceptual corroboration, not a substitute for the installed 3.0 API source checked here.
