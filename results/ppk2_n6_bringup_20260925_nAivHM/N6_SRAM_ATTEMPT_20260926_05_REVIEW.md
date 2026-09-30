# Actual SM03/SM04 execution and adversarial review — 2026-09-26

No formal inference, latency, NPU profile or energy result is accepted.
All negative runs remain intact. No Flash/unlock/PPK action was performed.
Exact original GPU NSL-KDD QCFS primary seed0 epoch80 checkpoint remains
`1e1033cd394283d7a82c6f6d8713eb1beeec9ff4b9d43cd247076833920b837e`.
Original QDQ graph `22dc7979...`, weights `cb5b6413...`, vectors `cb5b3415...`
are not replaced, retrained or selected from a better seed. This is ANN,
not a temporal SNN. Original all-five-logit tolerance and row order unchanged.

## Run04: signed16 and signed-zero-point repair, still negative

Separate SM03 compatibility firmware and host were built/reviewed; source
details in `tools/n6_deployment/host_sram_qcompat/PREFLIGHT_REVIEW.md`.
Full run04 (`b567ef -> 9259f8 / 1`) completed1024rows but failed5103 values,
497 classifications, maximum error16.272749423980713. Separate saved review
`0b7928 / 0` agreed. Runtime did not hang. The old numerical failure was not
reclassified as success just because execution completed.

Diagnostic02 (`cfa99d -> 237a1a / 0`) used48 hardware-only breakpoint stops
of original rowID20. Signed16 dequant now agrees41/41 bitwise. Original
generated first float Conv outputs range -1.35147..1.36575; generated Q18.-3
Cast truncates all256 to zero. Generated downstream affine parameters use
integer-accumulator units, not the real-valued float Conv units. This is an
inference from source, parameters and actual capture, not vendor confirmation.
Naive rescale/truncate alternative was tested offline on all1024 and rejected:
5367 first-layer quantized differences on1023 rows. No such fix was deployed.

## SM04 first-layer repair and actual run05

Additive `firmware_sram_firstfloat` keeps original float weights and derives
the256 bias constants solely from original ONNX int32 bias/scale. Strict
sequential binary32 first Gemm/bias and nearest-even quantization replace the
bad first Conv/Cast/bias boundary. Original epoch7 is removed; epoch6 is SW.
Actual mapping7HW+32SW,0hybrid (39 executable),not historical8/1/31. Later
three dense operations remain genuine NPU operations,not CPU final-logit
substitution. No performance optimization claim.

Native C control:all262144 first-layer signed8 outputs exactly equal original
ONNX Runtime. All10496 float weights/256bias words checked bitwise. Added
diagnostic graph outputs preserve5120 original reference words.13 firmware
tests including malformed descriptors/nonfinite/schedule/main passed.
Actual ARM build63commands,77876B BIN;302 input pins and240 artifacts verified
with independent ELF/BIN reconstruction and fresh disassembly. Actual NN
interface points at new schedule provider0x34066725. Full details and exact
build hashes in `tools/n6_deployment/host_sram_firstfloat/PREFLIGHT_REVIEW.md`.

Combined regression235tests+47subtests passed (`ea6341 -> 7b352a / 0`).
New host23tests passed separately; new diagnostic expansion29tests passed
(`130a2f / 0`). Importlib-mode combined collection initially failed on old
sibling imports; normal collection passed. No board failure was hidden.

Actual run05 `c2fed4 -> 66721e / exit1`,all1024rows completed:

| Quantity | Actual outcome |
|---|---:|
| Failed output values | 297 /5120 |
| Affected rows | 81 /1024 |
| Argmax disagreement | 0 /1024 |
| Bitwise-equal output values | 4823 /5120 |
| Maximum absolute error | 0.4961204528808594 |

Saved-only NumPy/struct review `e1e33d / 0` reproduces metrics,raw inputs,
IDs,source/model pins and cleanup across1057 retained artifacts. Its11
adversarial controls (`eabc1c / 0`) reject tampered tag/model/input/output/
row/receipt/tolerance/summary/missing row and forged RESULT. Classification
agreement alone DOES NOT pass the original protocol. FAILED remains;no RESULT.

## Diagnostic03: remaining first divergence and propagation

`158f11 -> c6cc43 / exit0`:one diagnostic sequence1025 on FIRST failing
original validation index20,rowID2656;46 hardware-only stops. Live code and
whole weight reservation verified before commit; fixed previous mailbox
`d2f741c967d15f6ac7d7b51594e0c282852661ccbd4b2b199f7c19d35fa498cf`
and PARITY `4442ff73620419d93803f69eee70690ce1da72cb1996aec1e987642e282ea24b`.
Cleanup errors[],CPU halted,owned breakpoints removed. This diagnostic is
neither an additional formal row nor latency/power evidence.

Saved operator comparison `0ef950 / 0`,original ONNX/no optimization/batch1:

- Input dequant,first Gemm quant/dequant,all7 first QCFS float operations and
  first activation quantization agree exactly.
- Second dense NPU output:first divergence,channels61/98 each off by1 int8
  unit:actual[-12,4],reference[-11,3]. Input to this NPU dense is exact.
- Channel98 after next divide:0.397801816 versus0.340972990. QCFS floor
  becomes2 versus1; next activation quantization0 versus-64.
- Third dense output51 differences; final QCFS3 activation differences;
  final dense3 output values off by1 quantized unit. These downstream counts
  do not prove each downstream kernel independently wrong.

Initial exploratory comparison assumed ping-pong offsets for in-place Clip,
Mul/Add and used a wrong final tensor name; it exited1 (`2a0cbe`). Those
intermediate mismatch reports are NOT findings. Corrected comparison derives
actual output offsets from pinned generated descriptors,uses real final
tensor name and exits0;all first QCFS stages are exact as stated above.

## Next engineering hypothesis, not a completed fix

Original second/third/final NPU generated code reduces Conv output precision
before affine requantization. Installed LL headers document accumulator-input
left shift and result-output right shift. ST documents that optimized NPU
accumulator/rounding paths need not be bit-exact with the original framework:
[ST programming model](https://stedgeai-dc.st.com/assets/embedded-docs/stneuralart_programming_model.html).
This explains why differences are plausible;it does not waive our protocol.

Offline exact integer dot -> FP32 input scale -> per-channel weight scale ->
original bias -> original nearest-even quantization was checked against ALL
original1024 intermediate rows for all4dense layers:0 quantized differences
(`0ef950 / 0`). This supports investigating preservation of NPU accumulator
precision and CPU requantization. It is not actual raw-accumulator hardware
validation,not a universal all-input equivalence proof,not permission to
replace NPU output with CPU-computed full dense/logits.

Any next variant needs explicit wider-buffer/stream routing/accumulator
bounds review,native arithmetic controls,real ARM build and raw NPU dot
comparison before another complete run. PPK is physically absent from USB;
power experiment cannot be recorded now. No background retry is armed.
