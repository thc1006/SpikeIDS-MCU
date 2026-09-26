# Portable fixed-QDQ candidate (not accepted inference)

The subsequent [single actual native probe](NATIVE_ACTUAL_01_REVIEW.md) completed
with all 5120 saved QDQ-reference FP32 words matching. This is native semantic
evidence only; MCU builds and board parity are not accepted by that result.

This additive candidate targets the same selected NSL-KDD QCFS primary-seed-0
ONNX model, not the old CAN network. It provides a portable C11 arithmetic core,
strict graph-to-constant translator, a bounded native replay runner, and synthetic author tests. No device I/O,
training, model export, firmware modification or board execution is included.

The only production generator argument is `--output-dir` (fresh directory).
The original model and validation archive must match the two literal SHA-256
commitments in `generate.py`. Parsing the ONNX protobuf is not inference. The
generator verifies the full connected 66-node graph, all consumed initializers,
exact attributes, fixed dimensions and complete QCFS/QDQ stages. It rejects
external tensors, extra/unsupported nodes, altered axes, unknown attributes,
nonfinite values, missing scales, nonzero INT32 bias zero-points, and partial
conversion. Tiny structurally identical graphs use a separate direct test seam.

INT8 weights stay `static const int8_t`; no full FP32 weight matrix or N6 packed
RAW initializer is stored in RAM. Each dot product dequantizes each weight using
its original per-output-channel FP32 scale/INT8 zero point; biases retain INT32
storage and per-channel scales. Two 256-float activation arrays use 2048 bytes
before stack/ABI overhead. Flash/RAM fitness still requires each board's actual
linker map; generated-C text size is not firmware storage size.

## Explicit arithmetic candidate

- IEEE binary32, nearest-even environment, gradual underflow required. No fast
  math; compile with `-fno-fast-math -ffp-contract=off
  -fexcess-precision=standard`. Intermediate volatile FP32 stores also prevent
  accidental contracted multiply/add or retained excess precision.
- Quantization rounds `x / scale` ties-to-even **before** adding the integer
  zero point, then saturates INT8. It does not use `roundf` (ties away from zero).
  The fixed graph uses per-tensor activation QDQ and per-axis-0 weight/bias DQ.
  See the [ONNX QuantizeLinear specification](https://onnx.ai/onnx/operators/onnx__QuantizeLinear.html#quantizelinear-13)
  and [DequantizeLinear specification](https://onnx.ai/onnx/operators/onnx__DequantizeLinear.html#dequantizelinear-13).
- Four Gemms use original `alpha=beta=1`, `transB=1`, a sequential left-to-right
  FP32 product/sum with bias added last. This is a disclosed implementation
  choice, **not** a claim that ORT uses the same accumulation order/kernel.
  See the [Gemm operator contract](https://onnx.ai/onnx/operators/onnx__Gemm.html#gemm-13).
- All three Div → Clip → Mul → Add → Floor → Div → Mul chains execute separately,
  including surrounding QDQ pairs. No ReLU substitute, fused arithmetic,
  threshold adjustment or new quantization is used.
- `pq_infer` checks dimensions/environment/nonfinite values, permits caller
  input/output alias through local staging, and publishes all outputs only on
  success. The generic tiny-fixture API is not a model-selection override.

The first 1024-row native replay must wait for root's source/test review. It must
retain raw five-logit FP32 outputs per original row, nonzero process/model status,
the exact input/output/model hashes and unfavorable metrics. Match the held
`export_verified.compare_logits(reference, actual)` call: NumPy FP32
`allclose(reference, actual, atol=1e-6, rtol=1e-5)` (relative anchor **actual**),
and zero argmax disagreements. Do not use an extra 1% board/native allowance or
change accumulation/scales until a preserved failure has been reviewed.

`run_native.py --output-dir <fresh-directory>` performs one source generation,
one fixed native compilation and one native subprocess consuming all 1024 rows.
Its only input paths are the original literal-hash bundle; no model, compiler,
flags, row count or tolerance overrides are exposed. The executable reads exactly
1024×41 little-endian FP32 words and returns ordinal/status/five words for every
row. It rejects truncated or trailing input. The host retains raw stdin hash,
stdout/stderr, return codes, original row IDs, logits, selected source/tool pins,
flags and metrics. Numerical disagreement is a valid negative result; nonzero
subprocess/protocol failures retain FAILED. There is no automatic retry.
Child environments are an explicit small allowlist (PATH, locale/timezone,
thread limits and task-owned TMPDIR), not inherited compiler/preload settings.
Selected tool/module pins do not claim the whole compiler or NumPy dependency
closure. Source generation and replay publish only into fresh owned output roots.

The preflight author tests compile a two-wide
synthetic model and one full-width synthetic 1024-row fixture; neither reads the
original graph/validation payload. RA/ESP
SDK wrappers, transport and physical board identification are subsequent work;
successful native parity would still not qualify board latency or energy.
