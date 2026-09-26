# Saved-only interpretation: NSL-KDD QCFS seed0 on STM32N6

2026-09-25. This reviewer authored the offline wrapper; this is a separate
saved-report/code interpretation, **not an independent numerical equivalence
oracle or hardware acceptance**. No compiler, inference, board, serial, flash or
PPK2 operation was performed for this review. No held output was edited.

## Bound execution and evidence

Root's preserved external execution is session **90435**, completion **5fc850**,
actual exit **0**, service invocation `f11e42e216334053a9c6742c0b762713`.
Its reported service runtime is 34.242 s, CPU consumption 17.734 s, peak memory
828.8 M and swap 0 B. These are **host compilation resources**, not N6 inference
latency or energy. Version/analyze/generate each exited 0.

- `vendor_actual_01_execution.json` whole SHA:
  `7f58b7067ef3f630a557f50071fc87b4916384084178193c0754e3b95fad921a`.
- `vendor_actual_01/RESULT.json` approved whole SHA verified:
  `220e16ebadb171e1bfecbcfc1a94d5e92a5c098ae2cbcf631289d163bff0e4e4`.
  Its canonical seal also verified:
  `f40e5ff80a29b7935d1c31ccdac22c4e13e15dafd6f940333576812cd1082f05`.
- Wrapper source `tools/n6_deployment/prepare_vendor.py` remains
  `cd1bb490fa913d0ffde3c5c59ff8108134537228ded9ec130e5ac17939f7a94f`.
- Original QDQ model remains bound to
  `22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d`.
- Generation report:
  `14132d4ff8ae56fe2f4825ea3e8df9f3ea25f4cf8f887b1f0cbf4855904cc64e`.
- Generation `c_info.json`:
  `55ecfcad62f6b896afda317c48749699f21dc3378392079037365b2a1341f1a8`.
- Generated network C:
  `c4dd9a92116a041cdd50f6c9a4579f071933fc8c42b5816eb3162b4b66efc72f`.
- Generated STAI C/header:
  `29051185d691463c0743dbbb2ef41630bf8144ad08a0f4edb4be8e752185f0e6` /
  `b26a68f0de308bae21b8620f568d3f86fcfe5525af4556351fd1160eef829eab`.

The report, c_info, network C, STAI header and both stdout files were checked
against the original RESULT file hashes and original seven-field file stats in
actual read-only check **a3b9d3 / exit 0**. This does not substitute for the
wrapper's entire input/tool/output retention check or numerical validation.

## What the actual compiler produced

ST Edge AI Core **3.0.0-20426 123672867**, Neural-ART compiler **1.1.3-8**,
default installed memory/optimization profile, FP32 external I/O. The import
report matches the intended **41→256→256→128→5** QCFS structure, retaining the
three Div/Clip/Mul/Add/Floor/Div/Mul chains. The source report lists 126,269 MACC;
this is a compiler metric, not measured cycles. The vendor optimized graph is
447,529 bytes, SHA
`7ae5c0f4ea8988957907704ccab6d67a2ddfe4356d81bafb185ea9175ce97aef`:
it is a new transformation product, not byte-identical to the original QDQ.
No semantic equality of that transformation has yet been demonstrated.

Observed mapping: **40 epochs = 8 HW + 1 hybrid + 31 SW**; zero epoch-controller
blobs/meta epochs reported. The SW breakdown in the actual table is:

- 21 float QCFS stages: seven per block, including all three Floor operations;
- four QuantizeLinear and five DequantizeLinear stages;
- **one Conv(float)** implementing `Gemm_15_conv_4`.

The last item is not just a generic warning: generated network C around lines
455–509 declares all 41 inputs, 256 outputs, 10,496 FP32 weights (41,984 bytes),
and invokes `ll_sw_forward_conv` for the first affine's convolution lowering.
Thus eight HW epochs must not be paraphrased as “all four Gemms execute on NPU”.
The hybrid epoch is a Cast. These are compiler/code observations, not live
kernel traces; epoch proportions cannot be converted into runtime or energy
fractions, nor can this review establish why the compiler selected that mapping.

Each analyze/generate stdout contains **15 “is not quantized” warnings**: Clip,
Mul, Add, Floor and the second Div in each of the three QCFS blocks. Both stderr
files are empty. These warnings are consistent with the retained mixed mapping;
successful exit is not a claim that they disappeared, that all operators are
integer, or that on-board numerical parity will pass.

## Exact I/O and memory handoff

Generated `stai_nsl_qcfs_seed0.h` specifies:

| Item | Actual contract |
|---|---|
| Input | one FP32 `[1,41]`, 164 bytes, name `Input_12_out_0` |
| Output | one FP32 `[1,5]`, 20 bytes, name `Dequantize_53_out_0` |
| Quantization metadata for external I/O | no scale/offset entries |
| Declared I/O alignment | 32 bytes; generated API also requires cache-line padding for user allocations |
| Activation allocation | 2,048 bytes, `0x342E0000`–`0x342E0800` |
| Binary weights | 145,457 bytes in `nsl_qcfs_seed0_atonbuf.xSPI2.raw`, base `0x71000000` |

Binary whole SHA:
`cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec`.
The report's rounded weight address span ends at `0x71023840` (145,472 bytes),
whereas the raw file ends exclusively at `0x71023831`. Do not mistake the
15-byte alignment gap for missing file data or silently modify the held binary.
This remains a proposed default map, not permission to flash that address.

The input is **PREALLOCATED, not override-enabled**. Generated STAI setter code
around lines 243–247 rejects a pointer differing from the generated buffer's
physical address. Merely replacing the old int8 array with a separate float
array and calling `set_inputs` is therefore not a valid integration. The c_info
lists original input and output at RAM5 offset zero with different lifetimes:
obtain the generated pointers, copy each row before run, and copy all output
words before loading the next row. Check every API return code.

The c_info also contains a composite virtual memory pool with a 1,968,128-byte
used address span across its subpools; do not add it again to the physical
2,048-byte activation allocation. Kernel/toolchain flash/RAM fields are null:
these results are **not a complete linked-firmware size or board-fit proof**.
Its `power_estimates`/memory-cycle attributes are compiler estimates, not PPK2
samples, rail energy, or measured device cycles.

## Narrow next firmware step — separate approval, no execution here

Create a new, source-pinned firmware adapter/build stage using these exact
generated C/header/raw files and the matching STAI/ATON **including float SW
operator runtime**. Preserve the existing `firmware/n6b` and old weights. First
review and cross-compile/link offline with actual nonzero failure propagation,
full linker map, section/stack/mailbox/activation range checks, and final binary
hashes. Do not reuse the old build script's stale path/exit handling.

Use init/get-info/get-inputs/get-outputs, confirm FP32 shapes/bytes and pointers,
then a bounded row transaction: fixed model identity + row ID + 41 original
FP32 feature words → checked synchronous inference → five complete FP32 output
words + per-row status. For later explicitly approved device validation compare
against the held NPZ's **QDQ `reference_logits`**, not only argmax or the original
FP32 logits. Preserve the already fixed preprocessing and all 1,024 validation
rows. The prior 1/1024 QDQ-vs-FP32 disagreement does not authorize another 1%
degradation after vendor conversion, and no tolerance/model change is proposed.

Only after firmware/memory/boot/weights and numerical-validation review should
an explicitly approved board/PPK2 phase establish clock, trigger, supply path,
idle/warm-up policy and raw samples. A trigger around full `stai_run` measures
this mixed CPU/NPU execution interval, **not isolated NPU energy**. All current
board/energy/deployment/publication flags remain false; all seventeen original
export negatives remain negative.
