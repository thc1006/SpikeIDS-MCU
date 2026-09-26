# Three-board experiment status — 2026-09-26

Current entry point. Numerical correctness is not power/performance acceptance.

## STM32N6: fixed-model numerical phase passed twice

Actual SM06 runs08 and09 each completed the original 1024 validation rows.
Each has 5120/5120 FP32 output words bitwise equal to the original QDQ model,
zero tolerance failures and zero class differences. Cross-run inputs, row
order and output words also agree exactly. Fresh platform/NPU initialization
and RAM reload were repeated; physical power cycling was not.

Original GPU-trained NSL-KDD QCFS primary seed0, final epoch80,
41→256→256→128→5 quantized ANN, not temporal SNN. No retraining, new export,
seed selection or tolerance change. Later three dense integer dot products
run on actual NPU; first dense, QCFS and requantization run on CPU.
SM06 has 7 HW + 35 SW executable epochs, not an all-NPU graph.

[Full acceptance, original hashes, failures, actual receipts and limits](../../results/ppk2_n6_bringup_20260925_nAivHM/N6_SM06_NUMERICAL_ACCEPTANCE_20260926.md).
Final related combined suite: **127 passed**. This is not independent external
peer review or a claim that every possible defect is excluded.

## Correct-model entry point

[Fixed selection manifest](N6_SM06_SELECTION.json) binds the original
checkpoint/export lineage, exact SM06 ELF/BIN, launch/review code, raw NPU
diagnostic and both full evidence inventories. The offline gate rechecks
314 build inputs, 240 build artifacts, both 1060-file run inventories and
all original outputs. No wildcard, arbitrary latest build or fallback model.

```sh
uv run --no-project --offline --python .venv/bin/python python tools/board_deployment/verify_n6_selection.py
```

This command is read-only. It neither runs the model nor controls power.
It refuses changed evidence; its success accepts only this numerical phase.
New instrumentation ELF must undergo new review and original-vector parity.

## What remains, by platform

| Board | Actual completed work | Remaining before formal energy |
| --- | --- | --- |
| STM32N6570-DK | SM06 actual SRAM deployment, raw later3 NPU accumulator diagnostic, two full1024-row parity passes | SM06-compatible measurement/marker firmware, clock/timing/overhead qualification, actual reviewed PPK path and synchronized acquisition |
| FPB-RA4E1 | [RA01 ELF/BIN/HEX cross-build](../../results/ra4e1_v5_build_20260925_01/RESULT.json), 123120-byte BIN; shared native C reference parity | Connected exact target, concrete programmer/debugger, programming/readback, target FP and1024-row parity, marker/energy |
| ESP32-S3 | [ESP03 app/bootloader/partitions](ESP32S3_BUILD_ACTUAL_03_REVIEW.md), 269472-byte app; shared native C reference parity | Exact physical module/flash/USB identity, programming/readback, target FP and1024-row parity, marker/energy |

RA/ESP portable kernels store INT8 constants but use strict FP32 arithmetic;
they are not advertised as all-integer optimized kernels. Their host native
5120-word parity does not certify either physical board.

Latest observed USB inventory has ST-LINK, no PPK2/RA4E1/ESP32-S3. CPU halt
succeeded after run09. This does not certify NPU quiescence or power removal.
No background power-capture, retry or flashing daemon is armed.

## Next phase, without inheriting invalid assumptions

1. Keep SM06 numerical selection frozen. Create separately tagged measurement
   instrumentation and a matching host contract; do not reuse the old trace
   image. Old trace expects40 epochs/162 records; SM06 needs42/170.
2. Review/test memory placement, callbacks, GPIO boundaries and timing scope;
   rebuild and validate the instrumented image against all original vectors.
   Mixed CPU cycles/callback intervals must not be called NPU-only latency.
3. Review the physical meter/marker path, record raw synchronized samples,
   check saturation/dropout/timebase and retain all attempts. Do not report
   nominal64MHz or earlier transient current as qualified final performance.
4. Apply target-specific programming, full numerical checks and measurement
   to RA/ESP when physically available. Do not substitute old CAN firmware.

**Formal power results, optimized latency and the entire three-board pipeline
remain unfinished.** No corresponding paper result is published by this phase.

## Retained history — not current experiment selection

[Rejected/historical variant index](../../archive/hardware/SM06_REJECTED_VARIANTS_20260926.md).
[Previous status snapshot](STATUS_PRE_SM06_20260926.md) retains the old failed
runs and electrical history. Pinned source/build/raw paths are preserved,
not moved or silently repaired; their old README acceptance status is
historical and superseded only by the specific evidence above.
