# PPK2 + STM32N6 progress — 2026-09-25

> Historical pre-pulse/pre-ARM-build snapshot. See [CURRENT_STATUS.md](CURRENT_STATUS.md)
> for the two failed physical diagnostics, user-reported LD3 steady red,
> completed offline ARM build and independent reviews. The "no ON/no ARM
> binary" statements and blanket voltage-check prerequisite below are
> superseded, not current gate decisions. Original snapshot retained for history.

## Completed in this execution

1. **Live identification, not board power acceptance.** Both reported devices
   were observed. PPK2 read back Ampere mode. ST-LINK target-reference estimate
   was 0.196 V; this is not a VIN measurement or proof of board damage. No
   output-ON, voltage change, flash, reset, halt or board inference was requested.
   See [live record](LIVE_CHECK.md) and [supply clarification](SUPPLY_FOLLOWUP.md).

2. **Offline PPK2 analyzer implemented and reviewed.** 19 author + 33 independent
   controls passed. An additional direct fixed-official-JS comparison passed
   50 cases / 25,600 synthetic samples with zero binary64 mismatches. This is
   algorithm verification, not physical calibration certification. The original
   bad baseline assumption produced exit1 and remains retained; its reviewed
   no-baseline followup decoded all 303104 old samples but remained exit2 with
   zero complete GPIO windows and research acceptance false. See
   [phase review](PPK2_PHASE_REVIEW.md) and [official oracle review](ORACLE_CROSSCHECK_REVIEW.md).

3. **Actual fixed-v5-model vendor generation completed and reviewed.** The
   NSL-KDD QCFS primary-seed0 QDQ graph was hash-checked and supplied to installed
   ST Edge AI Core3.0 in a fresh directory. Actual version/analyze/generate and
   the outer service exited0; service34.242s, memory peak828.8M, swap0B. This
   produced C/STAI code and145457 bytes of weights; it is NOT a linked ARM
   firmware or a flashed board. Thirty-three synthetic subprocess tests passed
   before this run. Independent saved-only postcheck950c01/exit0 confirmed
   102 unique files, 23 original held pins, 9 analyze additions, 77 generated
   output files/8 directories, exact hashes/stats and return codes.
   See [pre-review](N6_VENDOR_PRE_REVIEW.md),
   [actual execution](vendor_actual_01_execution.json),
   [interpretation](N6_VENDOR_INTERPRETATION.md), and
   [post-review](N6_VENDOR_POST_REVIEW.md).

## Important real findings, not conclusions to hide

- The old N6 harness used an 11-input CAN model. The chosen v5 model has
  41 FP32 inputs and five FP32 outputs. Old firmware/weights were not executed.
- Actual vendor mapping: **8 HW + 1 hybrid + 31 SW = 40 epochs**. The first
  affine also has a float software convolution, not only QCFS/Floor fallback.
  There are15 not-quantized warnings per analyze/generate phase. These are
  recorded compiler/code observations, not measured runtime proportions.
- Input is preallocated and cannot simply be replaced by the old application's
  separate input array. The next adapter must obtain runtime input/output
  pointers, copy164 input bytes and preserve all20 output bytes for every row.
- The existing raw PPK2 diagnostic has all digital bytes255 and no complete
  inference markers. It does not measure N6 current or per-inference energy.
- The original formal matrix remains FP32 4/11, QDQ 1/11; all17 negatives stay
  negative. The chosen QDQ passed its existing classification-disagreement gate,
  not bit-exact FP32 logits or board parity. No retraining or threshold change.

## Next scope — still unfinished

The user has already requested continuation of the hardware workflow; ordinary
in-scope software preparation does not need repeated user permission. Each
new technical phase still needs its own bounded pre/post review.

1. New fail-closed N6 firmware adapter/build, using this exact generated model
   and its float+NPU runtime; full per-row inputs/outputs/status, checked buffer
   ownership, linker/memory/stack/cache layout, and actual firmware artifact
   hashes. First cross-compile/link offline; do not reuse the legacy build or
   flash scripts. No ARM firmware binary has been built in this phase.
2. Review the real board boot/clock/flash path and GPIO output pin/I/O domain;
   define counted inference batches, warm-up and matched idle acquisition.
3. **Physical supply qualification is unresolved.** The user has no multimeter
   or adjustable bench supply. USB-A current limiting does not verify the
   actual VIN voltage. Output not enabled does not mean VIN is isolated.
   Do not claim the present energized VIN connection is verified safe or use
   software metadata as physical voltage. A suitable on-site voltage check or
   verified in-spec supply is required to close this boundary.
4. Only then collect full fixed validation outputs, measured clock/timing and
   GPIO-tagged PPK2 data. No µJ/inference or three-board result exists from this
   phase, and no unattended target-power/flash task is armed.

Original training/checkpoint/export/paper files were not changed or deleted.
New sources are under `tools/ppk2_energy/` and `tools/n6_deployment/`; raw
evidence, failures, generated weights and reviews are retained in this folder.
Review coverage is finite and does not claim an absence of all possible bugs.
