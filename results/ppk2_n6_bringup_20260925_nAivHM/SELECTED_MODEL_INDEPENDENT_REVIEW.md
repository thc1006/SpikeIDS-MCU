# Selected-model identity and CPU replay — bounded independent review

Date: 2026-09-25. This is a selected-artifact audit, not renewed research,
vendor-runtime, board, power, or energy acceptance. The reviewer previously
authored `prepare_vendor.py`; this check independently follows original
checkpoint/export metadata and executes the already-exported QDQ graph.
No checkpoint deserialization, training, export, quantization, compiler,
USB/SWD, power command, or original-file modification occurred.

## Exact selected identity

The original checkpoint is:

`/home/thc1006/dev/SpikeIDS-MCU/results/v5_run_20260921_r6_recovery1/results/nslkdd_qcfs/runs/qcfs_seed_0.pt`

- Actual whole-file SHA-256: `1e1033cd394283d7a82c6f6d8713eb1beeec9ff4b9d43cd247076833920b837e`.
- Original export-plan stat also matches: 1,856,863 bytes; device 66306;
  inode 21938483; mtime_ns 1789957791003802951;
  ctime_ns 1789957791004961504; current mode 33152, nlink 1.
- The sealed original result identifies `formal.execution=primary`,
  `job_id=nslkdd_qcfs`, CUDA/GPU placement, seed 0, fixed final epoch 80.
  Its best and final state digests both equal
  `8507ea64223a063a25b7016786de5cfcab52e66d2819b8c680ce58e31db620dd`.
  The selected export-plan attempt and export policy record that same digest.
  This semantic tensor-state digest was **not recomputed** here: the checkpoint
  was hashed as bytes, not loaded. It is not its `.pt` file SHA.
- Neural-plan content seal:
  `e229b7fe1790ed837f17c90a117bd035ad65342574f544b6ce16d15d6fff8b74`.
  Export-plan content seal:
  `1ef01de3bdbb415e8fa194d87a15347cf4d7b50f1ae55b0faad2be4a3872d812`.
- Data fingerprint:
  `3e1582990fcf07703bf1562bbd17b904cfc817808fd14cd7b0833199764a931c`.
  This is NSL-KDD QCFS, a quantized ANN, not a validated temporal SNN.

The actual seven-file bundle is under
`results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq/`:

| File | Verified whole-file SHA-256 |
| --- | --- |
| model_qdq_int8.onnx | 22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d |
| model_fp32.onnx | 3b14adf8179a5df0fd4215a7b6000e7edf22c8a0d462a11e10c21731b3d12038 |
| validation_vectors.npz | cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb |
| preprocessing.json | c296ddcd0cc89eac605a3277f9077a9f3b76d34a737496328a915763e3f02aec |
| calibration_rows.json | af48ddf5d8d218b4975385b7819ef8e30d1db495650488062a22cd0860f74cbe |
| export_policy.json | 2ca6fda8b6bbca50784a48318544f55634b48e6dddd8af04d0d8dc5109639d0f |
| export_report.json | 46a0f963aa7401320a017a2506cfca0f704b81d50270f4dda76d4fca34e4e881 |

## Registry and provenance

The absence of the neural-run `export_registration.json` is intentional:
`tools/export_v5_runtime.py::_no_legacy_registration` requires it. The exact
external registry is
`results/v5_export_registry/6713117facfabca510161f1b0ec362efc091a86e121a3bd991befacf4978e943/`.
Its two-file namespace, seals, canonical key, claim binding, and selected-plan
references matched. Nothing was registered or restored.

Actual whole-file hashes (paths relative to the repository):

| Path | SHA-256 |
| --- | --- |
| results/v5_run_20260921_r6_recovery1/plan.json | dfddcf388ecca8f5f00f051e9625ad0f374639e638a3d203247a5847945ea786 |
| results/v5_run_20260921_r6_recovery1/results/nslkdd_qcfs.json | 754eec60bd0661fbb4e49921659e44e735860ccec58706edbb06523de0459eb0 |
| results/v5_run_20260921_r6_recovery1/verification_fit.json | 98fad0318d67290bb33ffc7ef7762e5e6070c83f7d4d455f7700daebc4b17724 |
| results/v5_exports_20260922_r6_1/export_plan.json | 6a5a748a2a68c05225dd4c72efe92ffdf30b7f38dbf20636292d64cb2ff832f7 |
| results/v5_export_continuation_20260922_r6_1/plan.json | 2a94bddcc676e7ff4d7e7453bdd6196aa8725a7032e0989feb17010f5cd658d3 |
| registry claim.json, under the directory above | abc210f4efa07dc6aaade1a3fa3ebcd4ed3f6f46aa864417cce924cfb8b896f8 |
| registry registration.json, under the directory above | cb249d5f19f63f4b551f508f91ec95b39795bf890195e3e81654a1a082d44f0f |
| results/v5_export_continuation_20260922_r6_1_recovery1/summary.json | 3aa57c88486df262336f5a013654a6e0b67b698c0776743478a71b5965a76c27 |
| results/v5_export_continuation_20260922_r6_1_recovery1/adjudications/attempt_04.json | cdb4e242f616367d4bca55aa21dd677e786d412ebcdff5f8ae2528eb8512a313 |

The selected continuation entry is `new_suffix`, passed, return code 0,
negative_stage null, and names the exact QDQ directory above. This does not
promote the other 17 negatives: the existing matrix remains four FP32 passes,
one QDQ pass, six freeze negatives, eight FP32-parity negatives, and three
QDQ-parity negatives (metadata read `026e4f / 0`).

## Actual one-time numerical replay receipt

The real numerical execution completed in tool chunk **`3d6f4e`, exit 0**.
It used the original QDQ graph bytes and `np.load(..., allow_pickle=False)`;
no saved outputs were rewritten. Scope:
`spikeids-selected-qdq-replay-20260925-03.scope`, actual cgroup memory.max
4,294,967,296 bytes, memory.swap.max 0, peak 73,248,768 bytes;
CPUQuota 100%, TasksMax 64, external timeout 120 s.

- ONNX Runtime 1.24.3, NumPy 2.4.2, CPUExecutionProvider only,
  ORT_SEQUENTIAL, ORT_ENABLE_BASIC, intra/inter-op threads 1, batch 1.
  Profiling disabled; no optimized graph output path.
- Exact named FP32 `[1,41] input` to `[1,5] logits`; all 1,024 frozen rows.
- All **5,120 FP32 logits matched both NumPy equality and bytewise equality**:
  zero changed words, max absolute error 0, zero argmax disagreements.
- Original row order/IDs matched the fixed export-plan selection exactly.
  Shape-and-dtype-prefixed array digests:
  x `6b9161a32aac5fe5418ea7ab3009aa703c915cb6bd6854e8d0593355cf5959e5`;
  IDs `4c04aeed28d98928f98f4d4133923efb3c356278571079bd0339d2f5aad9e045`;
  reference and replay logits both
  `8af91c522b614695b122202c768713c7ccea850f31a92201d0a0370ca0f200d8`.
- Twenty-one selected artifact/metadata/source files had equal full SHA and
  non-atime stat bookends. The four checked source hashes were:
  `contracts.py` 575672391a0c849d9ad38142b4370d80d53e676f4bff89f2dd132825febef6b0;
  `experiment_all.py` 86f2cbd6c288cce36f811587ee2050286d5b647b15693aff5ea2cb2dfaa0c8c2;
  `export_verified.py` 624ed021b1b7f98c7a2a6b0d04302ea7c95c5db86c775c41fc2fdc4d03aae5ae;
  `tools/export_v5_runtime.py` c080be013e36aeb906e763ae025d22d3677796a2231be456cad5e96d258ec65e.
  No whole-repository or full installed-runtime integrity claim is made.

Two earlier failed launches are retained in the tool transcript, not hidden:
`8057c5 / 2` was a `uv run` syntax error before Python; `53f965 / 1` was this
one-off check mistakenly comparing an adjudication whole-file digest against
its content seal. Both stopped **before ORT import/session/inference**.
The corrected comparison uses whole SHA cdb4e242...; the distinct valid seal
is bba9d3770344b2e63866d0655221ae5790e2af7871958c6649878321faf7bd02.
There was one actual numerical replay, not three inference attempts.

## Substitution risks and parent-note review

`firmware/n6b/model/ids_generate_report.txt` is explicitly `can_h64_int8`,
11 inputs, hidden widths 64/64/32, five outputs. Its hash is
`d40920d2a996817690444151f807b86d0b780b849cfa24b0a746f275dfcd9700`.
Matching five output classes or a generic `ids` symbol is not model identity.
Those old CAN C/RAW/HEX files must not substitute for this NSL 41-input bundle;
neither may partial failed exports or negative-replay artifacts.

Reviewed parent `SELECTED_MODEL_IDENTITY.md` at whole SHA
`9edb7fbd3fba638e04ac5daed7f8b800a6484c3fc3b74caf90b5e9ac98322615`.
Its primary/seed/epoch, recorded semantic digest, seven payload commitments,
ANN-versus-SNN distinction, external-registry explanation, original 1/1024
QDQ disagreement, and nonacceptance limitations agree with this bounded
check. Suggested wording precision only: describe Cortex-M55/NPU as **vendor
mapping/placement**, not observed execution. No selected-model blocker found.
The new SRAM placement versus old external `0x71000000` warning is appropriate;
this review does not reaccept either compiler/build artifact or a loader.

An exact CPU replay does not erase the original QDQ-versus-FP32 allclose
failure/one argmax disagreement, prove vendor numerical equivalence, qualify
USB/PPK power, or establish board or energy acceptance. All remain separate.
