# Limited phase acceptance: offline analyzer / rejected old trace

Accepted scope: engineering implementation of current conversion, nominal
sample-time GPIO integration, and explicit rejection of unsupported old-data
measurement claims. **No physical power-up, calibration accuracy, board-model
parity, NPU execution, inference energy, or three-board comparison is accepted.**

## Implementation and independent checks

- `tools/ppk2_energy/analyze.py` SHA
  `7eae8347391b11e747be73a7368f55587a9f154e7749f622844e5fae8a9869a9`.
- 19 author plus 33 independently written tests: all 52 pass; root actual
  `d17fc7 / exit 0`. `ppk2_tests_execution.json` preserves the complete tool
  receipt and matching source/test pre/post hashes.
- Independent test author did not read the author tests, used rational
  arithmetic and hand-packed frames, and independently ran its 33 controls:
  `af1a4b / exit 0`, source/test bookends unchanged.
- Separate static reviewer found a real 1-ULP vendor-filter discrepancy:
  decimal `.82` was not bit-identical to the official operation `1.0-.18`.
  It was fixed without loosening comparison tolerances and has a dedicated
  independent regression. This difference was software arithmetic, not a
  claim that the instrument can physically resolve a 1-ULP current difference.
- Explicit metadata-exact vs GUI-zero-substitution policy; separate current
  correction and energy voltages; no implicit metadata VDD as physical VIN;
  unknown energy remains null; stateful filter spans the whole stream;
  negative current/energy not silently clipped; captured report pin, raw
  payload SHA/count, metadata text, source bookends and output separation.

## Actual old trace: assumption failure retained, not converted to success

Input: existing `transport-fyhlcuoi`, recorded when the STM32 USB was disconnected.
Report SHA `4b38c0f13e6bbee937f836383f15de93e129cc7c196ed0eba6bbf40d73b58309`;
raw SHA `ac2f0336f3257fa46a3171547298c70685021fc648dddd67ff0c1f96060772f9`.

1. First diagnostic incorrectly assumed samples [0,30000) were a LOW idle
   baseline. The analyzer refused at GPIO HIGH: actual `45181b / exit 1`.
   `old_transport_decode/analysis.json` and its external receipt are retained.
   This is a failed analysis attempt, not the expected no-window exit 2.
2. Independent Node raw inspection, `20004b / exit 0`, examined every frame:
   303104 samples, all digital bytes 255, all range0, zero digital transitions.
   This disproves that LOW-baseline assumption. It does not establish why the
   inputs read HIGH, prove a wiring fault, or by itself prove floating inputs.
3. After separate review, a new diagnostic removed only the unsupported
   baseline and used a new output directory. Channel0, correction4V explicitly
   GUI-setting replay, metadata-exact coefficients, Nordic filter, minimum
   length and declared counts were unchanged; energy voltage remained omitted.
4. `10c96c / exit 2`: all 303104 samples decoded, raw identity matched,
   `analysis_completed=true`, **`analysis_checks_passed=false`**, windows=[],
   baseline=null, research=false. There is no valid window charge or energy.
   Current statistics describe only those old bytes under the disclosed
   correction-voltage assumption, not an STM32 idle/inference measurement.
5. Root post-readback `aa46d0 / exit 0` verified original analyzer/report/raw
   hashes. Separate saved-only reviewer `cd15a5 / exit 0` matched both analysis
   reports and actual exits, independent logic inspection, small source/report
   bindings and scope interpretation. It did not rerun decoding or read raw.

Supplementary analysis report SHA:
`3b108e29db189b14f90775c320885b7a2dc6fd4847810b765c4a2c4036e0ffbf`.

## Remaining boundaries

The decoder tests establish finite algorithm/control coverage, not absence of
all bugs. Sample-clock error, analog bandwidth, range-dependent accuracy,
current/GPIO alignment, real supply voltage, true baseline workload, firmware
inference count and deployed model outputs are not verified by these tests.
PPK2 data-transfer success and GPIO bits cannot replace those measurements.

Physical status and the unresolved supply boundary are in `LIVE_CHECK.md`.
Model selection and old firmware incompatibility are in `V5_MODEL_BINDING.md`.
The next independent engineering phase is offline vendor compilation of the
fixed v5 graph. Do not enable target power based on this phase acceptance.
