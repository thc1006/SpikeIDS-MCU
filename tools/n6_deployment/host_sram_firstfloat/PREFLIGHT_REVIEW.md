# SM04 pre-execution adversarial review — 2026-09-26

Original checkpoint, ONNX, SRAM weights, original ordered 1024 vectors and
all-five-logit policy unchanged. No accepted inference/power claim.
This is root independent-method review, not independent-agent certification.

Issue controls: actual C first boundary, mechanically extracted original
descriptors and installed vendor headers; all 262144 first-layer signed8
values exactly match original ONNX Runtime (unoptimized graph, batch1).
Added diagnostic outputs retain all original 5120 final-reference bits.
All 10496 generated float weights and 256 added FP32 bias words exactly
match the original quantized graph's dequantized constants. Nothing is
fitted to validation outputs, labels or another model. All original files
remain unchanged. First-only CPU fallback retains later three NPU dense ops.

13 tests passed (`bf4daa / 0`): malformed Conv/Cast semantic fields,
nonfinite inputs, shape/DMA errors, scheduling counts/early sentinel/wrong
callbacks, original main's 7 init/protocol/error controls, immutable builder
reuse and correct original weight-path reporting. The harness first failed
on missing host config macros then a header regex; both were test setup
defects corrected before these results, not hidden board retries.

Actual ARM build `386bd6 -> 336079 / 0`:63 successful commands,77876-byte
BIN. Independent pyelftools/fresh objdump review `2f670a / 0` checked302
input pins,240 artifacts,content digest,exact ELF/BIN reconstruction,
four disjoint RX/RW/stack/mailbox load regions, no relocations/cpsie.
Undefined-symbol command succeeded with empty output. Frozen SM03 sources
and older evidence were not edited.

- RESULT:6ba56223fbd8ee055d02cf149df9cb0ff53039789b44a4c224eb1b6d94ce9a1b
- ELF:dbd51b7de4a1a09b5507e9876d72c12dba0c55e67672749f5f68a353e9ee4dc7
- BIN:b4e612b3a0637124612ea6b7518192bef97cbde48eda7f47dcb4517e9dfaf5a0

Actual generated Conv and Cast calls bind to wrappers at0x340649c0 and
0x34064c54. NN interface epoch-provider pointer is0x34066725 (Thumb),
the new SM04 provider, not merely an unused symbol (`7796b6 / 0`). Actual
ELF original table41x20B and affected callbacks/flags match; adapter's
800B array is in RAM. Reviewed derived schedule:7 HW+32 SW,0hybrid.
Actual main runtime initialization precedes model initialization.

23 host tests passed; all old tags including SM03 are rejected, raw mailbox
unchanged, private import identity restored, all original FP/IRQ/bus/receipt
and full-flow controls retained. Offline CLI checked1024rows with tagSM04,
no USB (`eee2b7`). Read-only exact ST-LINK Vref estimates3.2701–3.2717V
(`a3935f / 0`) are not calibrated/sustained-supply certification. PPK absent.

Next allowed execution: single fresh RAM validation05 with bounded180s
outer interrupt deadline/10s kill fallback. Same unchanged strict policy,
no retries/skips, no Flash/unlock or PPK access. CPU cleanup halt is not a
formal NPU-quiescence/power result. Remaining NPU arithmetic may still fail;
the first-layer native result is not whole-model acceptance.

Semantic references consulted: ONNX [Gemm](https://onnx.ai/onnx/operators/onnx__Gemm.html)
and [QuantizeLinear](https://onnx.ai/onnx/operators/onnx__QuantizeLinear.html).
FP32 accumulation order equivalence is empirically checked, not promised by
the Gemm specification; quantization uses nearest-even before zero addition.
