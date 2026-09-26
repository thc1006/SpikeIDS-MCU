# SpikeIDS v5 export acceptance protocol

The numerical policy below is fixed in the export runner. A formal matrix must
write and fsync a sealed `export_plan.json` before attempt 1 and register that
exact file once in the accepted neural run's `export_registration.json`. The
plan records known prior exposure; a local seal is not an externally timestamped
preregistration or proof that nobody previously inspected related outputs. The
policy is subordinate to the accepted frozen neural-training plan.

- Source run: the accepted, independently verified corrected-data formal run.
  `results/v5_run_20260920_r1` is ineligible engineering evidence.
- Deployment checkpoint: seed 0 from each verified primary neural arm
- Coverage: all 11 declared dataset/model arms
- BatchNorm: fold where applicable, then compare the folded/frozen model with
  the original evaluation graph
- Validation vectors: 1,024 rows sampled deterministically from the validation
  partition
- QDQ calibration: 1,000 rows sampled deterministically from the fit partition
- FP32 freeze/ONNX numerical gate: `atol=1e-6`, `rtol=1e-5`, and zero
  prediction disagreement
- QDQ prediction gate: disagreement fraction at most 0.01 against the verified
  FP32 ONNX graph
- ONNX opset: 17
- QDQ: signed QInt8 activations and weights; per-channel weights; MinMax
  calibration; only Gemm/MatMul/Conv operator classes; no explicit node subsets,
  no reduced range, no external data, no extra options; CPU calibration provider.
  Remaining implementation behavior is bound to the recorded runtime version
  and executable source. QDQ is not an all-integer execution claim.

The plan binds the ordered 22-attempt matrix, all policy values, exact validation
and fit-calibration indices/row IDs/input hashes, the four prepared-cache
inventories, selected seed-0 checkpoint bytes, neural fit/evaluation and independent
verification reports, exact local source/protocol bytes, runtime provenance, and
Python executable. All bound source and input identities are checked before and
after each attempt. An observed failure cannot authorize another registered
matrix for the same neural run. Interrupted or infrastructure-failed matrices
remain incomplete; they are not silently resumed or reclassified as parity
failures.

Before registration, the neural run must contain a sealed
`export_prior_exposure.json` with this schema (the strings shown are illustrative,
not a ready-to-use formal declaration):

```json
{
  "schema": 1,
  "kind": "spikeids_v5_export_prior_exposure",
  "source_plan_sha256": "actual neural plan content_sha256",
  "known_exposures": [
    {
      "description": "Describe an actual previous related inspection",
      "evidence_path": "/absolute/path/to/existing/evidence",
      "evidence_sha256": "actual SHA-256 of that evidence"
    }
  ],
  "declaration": "Describe the known exposure and limits of the history search",
  "complete_history_independently_verified": false,
  "local_freeze_is_external_preregistration": false,
  "content_sha256": "seal of all preceding fields"
}
```

An empty known-exposure list does not establish no prior exposure. The explicit
declaration remains necessary and must accurately describe the history known to
the researchers. Every listed evidence file is hashed and remains bound to the
export plan.

Each FP32 and QDQ attempt uses a fresh per-dataset, per-model output directory.
A separate runner acceptance record reconstructs the declared validation and
calibration row selections, verifies every payload hash, and evaluates the
FP32 and QDQ graphs in new single-threaded CPU ONNX Runtime sessions. The QDQ
gate is computed directly as FP32-ONNX versus QDQ-ONNX prediction disagreement;
the low-level exporter's `quantization_check` must match, but is not the sole
acceptance computation. Each accepted attempt has a sealed
`runner_validation.json`, and the 22-attempt summary binds that evidence and
its log by SHA-256. The summary, every attempt's evidence, generated paper-macro
provenance, and final consumers additionally bind the frozen export-plan seal.

For a numerical failure, the exporter persists the stage, scientific identity,
exact error, preceding numerical checks, failed gate's numerical values, and all
partial payload hashes in sealed `FAILED.json`. The runner repeats that same
attempt in a temporary directory under the identical plan and requires exact
identity, diagnostics, return code, and payload bytes. A replay that passes or
fails differently rejects the outcome. OOM, signals, disk errors, graph-generation
errors, missing diagnostics, or independent-validation inconsistencies remain
infrastructure/unclassified failures and cannot enter manuscript parity counts.

A failed gate remains a failed artifact and is not repaired by changing the
tolerance, calibration rows, validation rows, checkpoint, or model after
inspection. QDQ success establishes sampled ONNX Runtime parity only; it does
not establish an all-integer graph, vendor-NPU placement, board parity,
latency, or energy.
