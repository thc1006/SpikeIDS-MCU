# SM02 actual full run and first divergent tensor — 2026-09-26

## Decision

Runtime initialization repair is implemented and actually exercised. **Board
numerical validation still FAILS.** No accepted board inference, latency,
NPU profile, power result or publication claim is produced. GPU checkpoint,
original QDQ graph, weights, all 1024 ordered vectors and original tolerance
are unchanged. Previous firmware/builds and failed runs01/02 remain intact.

Current topology: PPK removed, user-reported JP2 3/4 connected, CN18 external
5V/3A supply, CN6 workstation ST-LINK. Exact probe serial
`004000183234510E37333934`. Fresh pre-run Vref estimates 3.2733–3.2765V are
not calibrated/sustained-supply certification. No new wiring change requested.

## Implemented runtime repair and actual run03

New `tools/n6_deployment/firmware_sram_runtime` variant SM02 initializes the
global runtime exactly once before model init, retains API status, and has a
separately checked host ABI. Original sources are included, not overwritten.
Actual cross-build 63 commands succeeded, 82716-byte BIN. See
[preflight](../../tools/n6_deployment/host_sram_runtime/PHASE_PREFLIGHT_REVIEW.md).

- Build RESULT SHA256: `2f7571ef7f878da5d710c949dd590593b1308321c0a83934f62c4930dc50e5fd`
- ELF SHA256: `bf2671fbf5c63ceec5e2b154be6b718dd24e74673bf7dc61a0bf0e0423539556`
- Actual run: `results/n6_sram_validation_20260926_03`, launch `0c8a83`,
  completion `87d284 / exit1`. All **1024** requests completed; final comparison
  rejected the result, not a transport timeout. CPU halted in cleanup.
- **5103/5120** logits exceed original FP32 `isclose(reference, actual,
  atol=1e-6, rtol=1e-5)`; **1024** rows have at least one failed value;
  **497** argmax disagreements. Only17 values bitwise equal, max absolute
  error16.272749423980713. Outputs have only3 distinct vectors, class4 throughout.
- Independent-method saved NumPy recomputation `c8a7e1 / exit0` reproduced all
  mismatch coordinates and metrics. No tolerance change or skipped rows.
- `PARITY.json` SHA256 `f63e6b297b620e4eac12f075bc94c8cc3fd4a7e45c16a8f044a5f6c939630d0a`;
  `FAILED.json` `b413bdc4c6b9c724181c893deaa1a11614d3f078e15448d4785ce3f42fccee0c`;
  `final_mailbox.bin` `c870ecc0479f45f50334cd4bedfff3bf718d2b8884dfc6007dfb8f4775e2445e`.

Live pre-inference NPU CTRL9, clock gates15/15, BUSIF0/1 both1, PRIMASK1.
Later halted read-only checks observed strict FP modes and zero sampled RISAF
fault-status registers. These are not proof of full hardware correctness.
The full-run failure branch does not execute successful-run postvalidation
gates; later diagnostic observations are separate evidence, not a fake pass.

## Actual five-stop diagnostic, not acceptance

Added explicit one-row hardware-breakpoint diagnostic, not software
breakpoints or an ambiguous request retry. It verifies the exact previous
negative response plus all live executable/weights bytes before commit.
No Flash, reset, PPK or firmware rebuild. All41 original input values retained.
Combined tests `e3ef15 → d58523 / exit0`: **181 tests,47 subtests**. Eleven
diagnostic controls include unsupported/existing breakpoints, short writes,
bad PC, timeout, source payload mismatch and retention failure. An initially
incorrect mock success fixture was fixed; production checks were not relaxed.

Actual `results/n6_epoch_diagnostic_20260926_01`: `e0c8a2 → 9f0fc8 / exit0`.
Original rowID20, diagnostic sequence1025, five16KiB activation captures at
ELF-verified symbol entries. Cleanup retained no errors; CPU halted, owned
hardware breakpoints removed. Diagnostic output equals original run03 row0.

| Capture | Independent check | Result |
|---|---|---|
| Before input quantization | Original41 FP32 input bytes | Exact |
| After CPU quantization | Original scale0.2813074588775635, zero-point−119; signed8 saturation/nearest-even | All41 exact |
| After first NPU arithmetic epoch3 | Signed16 `(quantized − zero_point)` | All41 exact |
| After CPU dequantization epoch4 | Signed16 input, zero-point0, original FP32 scale | **24/41 wrong** |
| After first CPU dense operation | Multiplication using the already-wrong input and fixed generated weights | Max absolute difference5.960464477539063e-08 in exploratory NumPy check; not full-model acceptance |

Crucially, interpreting the signed16 buffer as its first41 signed8 bytes and
multiplying by the scale reproduces **all41 board output words bit-for-bit**.
Separate saved-only `struct`/scalar arithmetic review `4ef41b / exit0`
(no NumPy, no board) reproduced input/quant/sub agreement and the24 dequant
failures, checked all five raw mailbox/context/FP records, model/source pins,
completion and unchanged original row0 output. Zero-based bad indices:
`2,3,4,6,7,11,22,23,24,25,26,27,28,30,31,32,33,34,35,36,37,38,39,40`.

Exact local source confirms an interface mismatch: generated epoch4 supplies
signed16 input (`stride.c=2`), but installed ST Edge AI3.0
`ll_aton/ll_sw_integer.c:340` dequant wrapper unconditionally selects S8/U8
array format at lines345–346. The metadata schema has signedness but no
explicit element-width field. Fresh ELF disassembly `78fee5 / exit0` shows
this actual linked wrapper at0x3406a06c calling node_convert. This is concrete
evidence for the first divergent operation, not proof it is the only defect
or that every release of ST software has the same issue.

Diagnostic RESULT SHA256 `0830280f8fbed3a179db2bc693cd644b3a16ed1b640c2dbcdc401b3ce353797a`;
final mailbox `35236b827ad271f7537ec38da00e59e8f5f11909535222370328754fa5a276ca`;
after-dequant capture `aeb1f50df44e8ec231c0324b662ee09de8d0a5b74c86c6ef72a3da8a2150bfb4`.

The input reference follows the [ONNX QuantizeLinear specification](https://onnx.ai/onnx/operators/onnx__QuantizeLinear.html).
Online search did not establish an authoritative fix for this exact installed
wrapper mismatch. Do not substitute unrelated forum reports for measured evidence.

## Next phase, not already completed

Build a separate, source-pinned compatibility repair for the verified generated
dequant call sites. Audit every call's width, signedness, zero point, strides,
scale and overlap; do not globally assume all inputs are16-bit or infer arbitrary
dtype solely from stride. Cover negative, positive, boundary and malformed
metadata controls. Review fresh actual ELF and host bundle before another full
1024-row run. Any later mismatch remains negative and requires localization.
Do not modify frozen ST installation or prior evidence in place.

RA4E1 and ESP32-S3 artifacts remain built but not target-validated. Formal
three-board power experiment is still pending. This is root adversarial review
with independent calculation methods, not independent-agent signoff, author
approval, or proof of absence of all undiscovered defects. No background retry
or power acquisition is armed.
