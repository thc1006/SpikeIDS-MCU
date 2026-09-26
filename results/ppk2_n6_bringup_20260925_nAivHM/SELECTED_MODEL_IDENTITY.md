# Selected model identity — not a hardware acceptance

The first N6 candidate is **NSL-KDD / QCFS / primary seed 0**, from the
registered v5 GPU experiment. It is the recorded **quantized ANN**, not a
validated temporal spiking network. For the 41 → 256 → 256 → 128 → 5 model,
the vendor mapping reports mixed Cortex-M55 floating-point / NPU placement. Do not
describe it as an all-INT8, all-NPU, or SNN power result.

## Original artifacts, independently of filenames

Repository-relative checkpoint:
`results/v5_run_20260921_r6_recovery1/results/nslkdd_qcfs/runs/qcfs_seed_0.pt`

- Actual whole-file SHA-256:
  `1e1033cd394283d7a82c6f6d8713eb1beeec9ff4b9d43cd247076833920b837e`.
- Recorded best/final tensor-state semantic digest:
  `8507ea64223a063a25b7016786de5cfcab52e66d2819b8c680ce58e31db620dd`.
- The original result records `formal.execution=primary`, `device=cuda`,
  fixed final epoch 80, and seed 0. This is not a smoke-test checkpoint,
  replica, selected best-performing seed, or the old CAN model.
- Source plan semantic digest:
  `e229b7fe1790ed837f17c90a117bd035ad65342574f544b6ce16d15d6fff8b74`.
- Registered export plan semantic digest:
  `1ef01de3bdbb415e8fa194d87a15347cf4d7b50f1ae55b0faad2be4a3872d812`.

Root then actually loaded this same hash-checked checkpoint on CPU with
`torch.load(..., weights_only=True)` and independently recomputed the semantic
digest of all 29 `best_model` tensors. It exactly matched `8507ea...`; dense
weight shapes were `[256,41]`, `[256,256]`, `[128,256]`, `[5,128]`. File bytes and
stat observations were unchanged before/after. No forward pass, GPU, or board
was used; the full checkpoint semantic payload digest was not revalidated
(the whole-file SHA-256 was rechecked). Observed
actual exit 0: `99be91` launch / `3c1e2a` completion, session 21931. See
[execution receipt](CHECKPOINT_IDENTITY_EXECUTION.json).

Root actual byte-hash check: tool `e1764a` printed the matching checkpoint,
source-plan, result, verification, and export-plan digests. Its attempted old
neural-side `export_registration.json` lookup was absent. That is **not** a
missing registration: the frozen external-runtime design explicitly requires
that old path to be absent. The actual claim/registration reside under
`results/v5_export_registry/6713117facfabca510161f1b0ec362efc091a86e121a3bd991befacf4978e943/`.
Do not restore or fabricate a neural-side registration.

The original QDQ bundle remains at
`results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq/`.
Root actual full-byte recheck `da9439 / 0` observed:

| File | SHA-256 |
| --- | --- |
| model_qdq_int8.onnx | 22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d |
| model_fp32.onnx | 3b14adf8179a5df0fd4215a7b6000e7edf22c8a0d462a11e10c21731b3d12038 |
| validation_vectors.npz | cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb |
| preprocessing.json | c296ddcd0cc89eac605a3277f9077a9f3b76d34a737496328a915763e3f02aec |
| calibration_rows.json | af48ddf5d8d218b4975385b7819ef8e30d1db495650488062a22cd0860f74cbe |
| export_policy.json | 2ca6fda8b6bbca50784a48318544f55634b48e6dddd8af04d0d8dc5109639d0f |
| export_report.json | 46a0f963aa7401320a017a2506cfca0f704b81d50270f4dda76d4fca34e4e881 |

Both the original vendor-preparation wrapper and the new internal-SRAM
candidate use literal commitments to these seven files, reject a mismatch,
and provide no model/checkpoint selection override. They are offline compiler
tools, **not an implemented end-to-end hardware interlock**. Any future loader
must bind its own exact ELF, initialized data, weights, readback, and vector
order to the accepted build, rather than relying on this note or an embedded
hash string.

## Numerical acceptance must not be relabeled

- The independent CPU-only replay actually completed (`3d6f4e / 0`): all
  1,024 frozen inputs in original row order produced all 5,120 reference logits
  bit-for-bit, with zero changed FP32 words or argmax disagreements. ORT 1.24.3,
  CPU provider, sequential BASIC optimization and one intra/inter-op thread
  match the original export policy. The seven payload files, checkpoint and
  selected provenance files retained their original hash/stat observations.
  See [independent identity and replay review](SELECTED_MODEL_INDEPENDENT_REVIEW.md).
- Original QDQ versus FP32 had **one argmax disagreement in 1,024 rows** under
  the frozen 1% quantization policy. Full logit allclose was false. Preserve it.
- The board must compare all 5,120 logits against the frozen **QDQ reference**
  in original row order: `atol=1e-6`, `rtol=1e-5`, zero argmax disagreements.
  There is no additional 1% board-error allowance and no post-hoc threshold
  tuning to make an implementation pass.
- CPU replay of the original graph cannot prove vendor or board numerical
  equivalence. Compilation cannot prove inference, clock, or power acceptance.

## Current engineering candidate and exclusions

The first internal-SRAM ST generate child actually returned 0, but its wrapper
returned **1** because a checker assumed explicit generated cache fields that
were absent. `internal_sram_actual_01/FAILED.json` is retained, with no RESULT.
Do not treat compiler exit 0 as acceptance or edit away this negative record.
A separate saved-artifact review subsequently passed (`30d3fe / 0`) using
reviewer SHA `909b77937c806510443f848240ee2e0d33eabbdbe35ed6acc06c1cda509f0445`.
It checked 21 static streaming descriptors, 35 source/input/runtime pins and
the unchanged 34-file / 5-directory original namespace. Root's combined author
and independent regression run passed **51 tests** (`58e192 / 0`). The earlier
unittest-only command (`4db038 / 0`) collected only the 25 author tests; it was
not the combined suite. There has been no second compiler invocation or board
execution for this candidate. See the
[saved-only review](../../tools/n6_deployment/internal_sram/SAVED_REVIEW_ACTUAL_01.md).

Its raw weight SHA, independently read by root (`2ea853 / 0`), is
`cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec`,
identical to the old vendor candidate's 145,457-byte weight initializer. This
weight-file digest is **not** the checkpoint digest or the ONNX graph digest.
The new address is SRAM `0x34200000`, not old external-memory `0x71000000`;
the old `firmware_v5/build_actual_03` is therefore not a loader-ready image for
this new placement. Do not mix those two candidates.

The new activation data footprint is 2,048 bytes, but one hardware prefetch
stop reaches offset 2,112. The future linker/loader must reserve the entire
configured 16 KiB activation pool and 256 KiB weight pool. A matching new RAM
adapter build, explicit platform initialization, verified device load/readback,
1,024-row board parity and measurement-window validation remain separate
unfinished steps. The descriptor review does not qualify physical power.

Explicitly excluded from research results: old CAN weights/HEX, synthetic or
zero-input kernel benchmarks, RAM heartbeat probes, startup-current captures,
failed exports, and fabricated/reconstructed board logits. No trained-model
board inference or formal model-energy measurement is claimed here. Other
datasets, the RA4E1/ESP32-S3 deployment, and the original three-board matrix
are not replaced by this first N6 engineering candidate.
