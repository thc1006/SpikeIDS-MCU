# SM04 first-layer compiler-boundary repair candidate

Not an accepted model or energy run. Original GPU checkpoint, ONNX, weights,
ordered rows and strict output policy stay fixed. Original files and all
negative runs remain frozen. SM04 is a distinct engineering implementation.

Actual SM03 row20 trace proves signed16 dequant repaired, then all256 first
Conv outputs (range -1.352..1.366) become zero in Q18.-3 Cast. Generated
post-conv affine constants correspond to integer accumulator units, not the
real-valued CPU Conv output. Blind rescaling plus old truncation is not exact
ONNX semantics. This variant instead implements original first Gemm with
strict sequential binary32 multiply/add and original dequantized bias, then
original nearest-even signed8 quantization. It uses the existing validated
portable arithmetic helpers; only first Gemm/quantization is replaced.

The broken first post-conv NPU bias/quant epoch7 is explicitly removed from
the scheduling table; epoch6 now performs CPU quantization, not hybrid Cast.
Other callbacks and all three later NPU dense operators remain unchanged.
New actual schedule:7 HW +32 SW, no hybrid,39 executable +sentinel. Historical
8/1/31 counts must NOT be claimed for this variant. This is not all-NPU and
not a final performance-optimized build. No dummy NPU work is substituted.

The schedule adapter includes the frozen generated file under a renamed
provider, checks exact affected entries and original counts, then derives a
separate array. Original generated C, ST installation and SRAM weights are
not patched. New first-bias constants derive solely from original ONNX
int32 bias and FP32 scale, not fitted outputs or validation labels.

Require full first-layer1024-row native control, malformed-contract and
schedule tests, actual ELF/binding review and full board validation before
claiming any numerical result. Remaining NPU fixed-point rounding may still
fail original final-logit policy; do not relax it or return CPU substitute
final logits. NPU profiling and PPK energy are subsequent separate gates.
