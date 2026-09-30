# SM02 runtime repair: pre-execution review, 2026-09-26

Scope: repair the missing global NPU runtime initialization observed in actual
attempt 02. No claim of numerical, latency, NPU profiling or energy acceptance.
Original S6/trace sources, failed attempts 01/02, generated model, GPU checkpoint,
weights, ordered vectors and original FP32 comparison are preserved.

## Implemented change

`firmware_sram_runtime/main.c` reuses the frozen original main and replaces
only model init with a guarded runtime-then-model wrapper. The real global
runtime is called once, after ACK, before network init; any non-success
returns to the existing fail-closed error path. Exact status is retained in
three formerly reserved mailbox words; deployment tag is SM02. Original
hosts reject this identity. Runtime configuration includes NPU NVIC changes,
but PRIMASK remains masked; no external-IRQ vector table is supplied.

The new decoder validates tag and receipt before projecting ONLY those new
fields to original S6 values for inherited ABI validation. It returns and
retains the original SM02 bytes, including all inputs and outputs. Other
reserved bytes must still be zero. Original Mailbox transaction logic and
original numerical evaluator are reused unchanged. New controller halts at
READY, retains and checks PRIMASK=1 plus global NPU clock/BUSIF enable, strict
FP state and unchanged platform observations before any request. These
checks repeat after validation. Failed MMIO observations are retained before
rejection; final raw mailbox is retained even on header/init failures.

## Actual controls and independent-method saved inspection

- Host C compiles the real variant and original main against explicit CMSIS/
  STAI substitutes: success, runtime failure, model-init failure, no ACK,
  cache-on, info failure, repeated init. This is not hardware execution.
- Wire controls reject old identity, pending/failed/missing/repeated runtime
  receipt and nonzero remaining reserved fields. Full fake 1024-row flow,
  missing receipt, IRQ unmask, disabled BUSIF, retention failure, and final
  MMIO corruption are covered; no failure submits a forbidden next request.
- Actual combined execution **e5462d / exit 0**: **170 tests, 47 subtests**,
  comprising 46 new plus 124 existing tests. Default CLI checks 1024 rows
  without USB (`98df17` then `e5462d`).
- Actual ARM build **3e7242 → f659d6 / exit 0**, 63 successful commands,
  82716-byte BIN. Saved-only root review **e42542 / exit 0** independently
  parsed ELF with pyelftools, checked 287 input pins and 240 retained artifacts,
  all four load segments, exact BIN equality to ELF bytes/gap padding, no
  undefined symbols/relocations, and freshly regenerated disassembly.
- Machine code shows `main` call at `0x340642b0` to `stai_runtime_init`, a
  return-code conditional with failure branch, then model init at `0x340642cc`.
  `stai_runtime_init → LL_ATON_RT_RuntimeInit → LL_ATON_Init` is actually linked.
  No `cpsie` instruction exists in the reviewed disassembly. That alone is not
  proof of IRQ state; the new live gate is also required.
- This is root adversarial review using distinct checks, NOT an independent
  subagent signoff or a guarantee that no undiscovered issue remains.

Fixed new artifact SHA-256:

- RESULT.json: `2f7571ef7f878da5d710c949dd590593b1308321c0a83934f62c4930dc50e5fd`
- n6_sram.elf: `bf2671fbf5c63ceec5e2b154be6b718dd24e74673bf7dc61a0bf0e0423539556`
- variant main.c: `b8e611b07cf32afde463eddee179877b760d6de7319a5d0874d5fd7445cf9451`
- controller.py: `15f546cbc8e74c729ec5c66458b631317db393885d02b42dcf3a17ecc5908759`
- runtime_protocol.py: `b6c5c33565caad1a4e91f32137ef1debecc76d8197d782dcc12e78ac268955c7`
- run.py: `190ff04a743bb1508269ef4a52f1524b272c7ed4761b424a4e0e57cd91810f30`

Fresh exact-probe F7 query **267b8a / exit 0** observed 3.273306772908366,
3.276494023904382, 3.273306772908366 V, no target debug/reset/power or PPK.
Not calibrated/sustained-supply certification. User topology remains standalone
CN18 external supply, CN6 workstation, JP2 3/4 connected, PPK removed.

## Planned bounded attempt 03

Fresh output `results/n6_sram_validation_20260926_03`; outer timeout 180 seconds
with interrupt cleanup and 10-second kill fallback. The stage explicitly
resets NPU before reconfiguration/payload loading; original CPU-only halt
is not used as proof that previous NPU transactions are quiescent. No model
retry, skipped row, timeout relaxation, flash, unlock or PPK operation. Failed
results remain negative. A successful full-logit comparison would establish
only this candidate's fixed-subset board parity, not final research acceptance.
