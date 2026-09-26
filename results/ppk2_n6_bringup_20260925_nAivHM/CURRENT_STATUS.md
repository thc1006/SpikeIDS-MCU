# Current N6 bring-up status — 2026-09-26

SM06 numerical phase passed **two actual complete1024-row board runs**.
Each has5120/5120 FP32 words bitwise equal to the original QDQ reference,
zero tolerance failures and zero classification disagreements. Two runs
also agree with each other on every row/input/output word.

Selected model remains original GPU-trained NSL-KDD QCFS primary seed0,
final epoch80,41→256→256→128→5 quantized ANN. Three later dense integer
dot products execute on NPU, with original signed24 accumulator values and
CPU requantization. First dense and QCFS remain CPU;7HW+35SW,not all-NPU.

[Actual acceptance, hashes, adversarial review and execution receipts](N6_SM06_NUMERICAL_ACCEPTANCE_20260926.md).
[Current three-board entry point](../../tools/board_deployment/STATUS.md).
[Exact selection gate](../../tools/board_deployment/N6_SM06_SELECTION.json).

## Boundaries

- Runs08/09 each retain1060 artifacts; original1024row order,all41inputs and
  all5outputs checked. Related combined suite127passed.
- CPU halted after run09;no claim that NPU is electrically quiescent.
- Latest USB observation has ST-LINK,not PPK2,RA4E1 or ESP32-S3.
- Standalone CN18 supply and JP2 3/4 connection are user-reported topology.
  No software operation in this phase changes wiring or supply.
- No formal power capture, qualified latency/frequency or optimized
  performance. No background capture/retry/flash daemon.
- Next software work is a separately reviewed SM06 measurement/marker
  variant;old40-epoch trace cannot be used for the new42-epoch schedule.
  Its acceptance must be earned separately,not inherited from SM06 parity.

[Historical status snapshot](STATUS_PRE_SM06_20260926.md) retains failed
SM01–SM05 and prior electrical observations. Those failures were not deleted,
converted into successes or silently repaired. Original pins/paths remain
intact;[historical index](../../archive/hardware/SM06_REJECTED_VARIANTS_20260926.md).
