# Selected N6 engineering artifact — not board acceptance

The original formal export matrix remains 11 arms / 22 attempts, with FP32
4/11 and QDQ 1/11 passing their respective frozen gates. All 17 original
negative attempts remain negative. No training, calibration, re-export or
threshold change is part of this hardware-preparation phase.

The only passing QDQ bundle is:

`results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq/`

- Fixed primary seed0 NSL-KDD QCFS, 41→256→256→128→5, L=4 shifted_v1.
- QDQ graph SHA `22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d`.
- Validation NPZ SHA `cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb`.
- FP32 graph SHA `3b14adf8179a5df0fd4215a7b6000e7edf22c8a0d462a11e10c21731b3d12038`.
- Preprocessing SHA `c296ddcd0cc89eac605a3277f9077a9f3b76d34a737496328a915763e3f02aec`.
- Export policy SHA `2ca6fda8b6bbca50784a48318544f55634b48e6dddd8af04d0d8dc5109639d0f`.
- Export report SHA `46a0f963aa7401320a017a2506cfca0f704b81d50270f4dda76d4fca34e4e881`.

The audit agent re-hashed these small artifacts and checked before/after stat.
The original checkpoint is
`results/v5_run_20260921_r6_recovery1/results/nslkdd_qcfs/runs/qcfs_seed_0.pt`.
Its historical committed SHA is
`1e1033cd394283d7a82c6f6d8713eb1beeec9ff4b9d43cd247076833920b837e`;
this phase's audit checked its stat only, not reloaded or re-hashed its payload.

## Acceptance must not be overstated

This QDQ passed the pre-existing **classification-disagreement gate**:
1/1024 = 0.0009765625, below 0.01. It did not pass FP32-vs-QDQ logit allclose;
the export report records max absolute logit error 8.932059288024902. Do not
call this bit-exact inference, an all-integer network, or all-NPU execution.

The exported vectors have `x` FP32 [1024,41] and QDQ `reference_logits` FP32
[1024,5], with original logits and validation row IDs also retained. Full
on-board outputs must be compared to the **QDQ reference**, not to a fabricated
zero input or only the final argmax. `export_policy.json` freezes board
atol=1e-6, rtol=1e-5; `deployment_gate.py` requires allclose and zero prediction
disagreement against that reference. The export's 1% quantization gate does
not automatically grant another 1% vendor/board-conversion allowance.

`Floor` has software mapping in the installed ST Edge AI Core 3.0 operator
documentation. The actual graph's vendor report, not its filename or a past
network, must establish observed HW/SW epoch mapping. Any generated C/weights
still need firmware linking, fixed input/output layout, full board parity,
clock evidence and GPIO/PPK2 synchronization.

## Existing N6 scripts are not ready-to-run v5 experiments

- `firmware/n6b/model/` is an old 11-input CAN/H64 model, not this v5 artifact.
- `main_npu.c` initializes input to zero, records cycles/final argmax only,
  has no GPIO energy markers, and can overwrite earlier inference errors.
- `build.sh` accumulates compiler failures and ends by echoing link status;
  it can exit successfully after a failed link, and writes an old scratch path.
- `flash_weights.sh` points to old weights; `scripts/n6b_run.py` assumes an
  800 MHz timer unless overridden and does not provide full per-row logits.
- The old default memory profile and OOB/DEV takeover assumptions are not an
  approved v5 flash/linker/boot layout.

These scripts were inspected but not executed or modified. A fresh offline
vendor wrapper is being prepared separately under `tools/n6_deployment/`.
Its output can support the next firmware implementation; it cannot itself
accept an NPU, latency, energy or three-platform research claim.
