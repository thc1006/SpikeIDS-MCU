# Fixed-model STM32N6 offline preparation

This directory is new engineering work, not part of the frozen v5 research
sources. `prepare_vendor.py` only prepares the existing **NSL-KDD QCFS seed0 QDQ**
artifact with installed **ST Edge AI Core 3.0.0-20426 123672867**. It cannot select
another model or add arbitrary vendor arguments. It never calls `validate`,
serial/USB discovery, a programmer, a board driver, or an inference API.

## Approval boundary

The wrapper and synthetic tests must be reviewed before the first real compiler
invocation. Running the command below **does execute the vendor compiler**; it is
not a dry run. The parent directory must already exist and must be a new,
unprotected engineering results directory. The output itself must not exist.
Use an externally owned systemd scope/service with memory/CPU/task limits and
control-group cleanup. No board may be connected by this workflow.

```sh
uv run --no-project --offline --python .venv/bin/python \
  tools/n6_deployment/prepare_vendor.py \
  --output-dir /absolute/repository/results/NEW_PHASE/vendor_actual_01
```

No real analyze/generate invocation was used in author tests. The tests substitute
fixed path/hash constants and use a tiny actual subprocess that writes synthetic
reports. They do not invoke ST, Torch, ONNX Runtime, a model, or hardware.

## Fixed contract

- Input QDQ graph SHA:
  `22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d`.
- Original artifact directory:
  `results/v5_exports_20260922_r6_1_remaining19/nslkdd/qcfs/qdq`.
- Original seven artifacts, wrapper source, Python executable, and fourteen
  explicitly listed vendor binaries/front-end/configuration files are held with
  SHA-256 plus original file identity/size/mode/link/time metadata. The compiler
  receives a byte-identical new graph copy, not the original path.
- Invocation order: `--version`, `analyze`, `generate`; STM32N6, ONNX, STAI,
  `default@` the installed profile, lossless/balanced, FP32 input/output and
  `--binary` on generate. No recalibration, custom operator, graph cut, manually
  changed epsilon, simplifier flag, or alternate checkpoint is supplied.
  Vendor default ONNX optimizer remains enabled and its products are retained.
- Original 1,024-vector QDQ agreement was 1/1024 argmax disagreement against
  FP32 under the fixed 1% policy; FP32 logit allclose was **false**. This does not
  authorize another 1% degradation in vendor or board validation.
- `validation_vectors.npz/reference_logits` contains QDQ CPU reference logits;
  the wrapper hashes but does not decode or execute the vectors.

Each phase has raw `.stdout`, `.stderr`, and `.json` command receipts, including
actual child return code. Timeout kills the child process group, waits for the
observed exit and retains partial streams. The externally owned control group
is still required: parent exit alone does not prove every descendant exited.
There is no automatic retry, overwrite, cleanup, or resume.

Success requires nonempty analyze artifacts, required generated C/STAI metadata,
nonempty named binary weight files, and an unambiguous generation-report epoch
summary. HW/SW/hybrid counts are observations of that report, **not independently
proved kernel placement**. All workspace artifacts and exact directory names
are retained, hashed, and checked again at publication. `RESULT.json` must be
combined with a separately observed successful outer execution; it cannot
self-attest its eventual process exit.

Failures return nonzero, retain logs/partial artifacts, and attempt `FAILED.json`
only inside the original owned directory. A failure after a tentative result can
leave both files; **FAILED or any nonzero outer exit always invalidates success**.
Before a safe directory identity is acquired, or after a rebind, a failure marker
is not guaranteed. Never accept an existing directory as a fresh run.

## Scientific and lifecycle limits

`board_validated`, `energy_measured`, `npu_placement_verified`,
`deployment_accepted`, and `publication_accepted` are always false. All seventeen
historical export negatives remain negative. This is diagnostic preparation,
not firmware build/link success, on-target parity, throughput, latency or energy.

The installed 3.0 operator-support document lists ONNX `Floor` as `SW_FLOAT`; the
QCFS graph contains Floor. Mixed CPU/NPU execution must be read from this actual
compilation's mapping report. Never reuse the old CAN H64 report or firmware
weights. The default memory pool is diagnostic, not an approved linker/flash map.

This wrapper is not an OS filesystem/device/network sandbox. It suppresses
inherited credentials and injection-related environment variables, but trusts
the installed vendor executable to perform its requested offline commands.
The fourteen pinned vendor files do **not** form a complete transitive package,
dynamic-library or portable runtime closure. File checks are finite before/after
observations, not atomic snapshots or continuous attestation. Original model
bytes remain unchanged; graph semantics after vendor optimization require a
separate saved-artifact and validation review before any board preparation.

Local references read during development:
`stedgeai --help`, `stedgeai analyze --help`, `stedgeai generate --help`,
`stedgeai --version`, and installed 3.0 `Documentation/stneuralart_operator_support.html`.
Help/version commands alone do not compile a model.
