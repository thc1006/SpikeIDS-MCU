# SM05 first inference diagnostic, pre-execution review

INIT-ONLY actual `dab8bd -> d95109 / exit0` is independently checked by
`74a879 / 0`:READY SM05,0requests/responses,no row/PARITY/RESULT files,clean
CPU halt. Fresh F7 indicated3.2717–3.2749V;uncalibrated,no PPK/Flash/reset.
This is initialization,NOT a successful inference result.

Fixed prior mailbox:c9bc7032b456ed87dff2e088819bebf34b882715187bbc723111dc3b53f128c9.
New observer derives from frozen earlier hardware-only observer;intentional
state changes limited to requiring fresh READY sequence0 and issuing1 once.
It verifies exact live prior/code/weights,uses fixed original validation
index20/row2656,and7unique breakpoint sites in actual fixed RX ELF.

Capture before NPU dense19/31/43 and before CPU requantization after each,
plus final dequant entry. Each includes full16KiB activation memory and raw
mailbox/registers/FP. Saved analysis must compare raw signed24 data at8192
with independent integer dot using actual captured unsigned input and
original ONNX weights. Final5outputs must be checked too;no subset pass
becomes whole-model acceptance. No CPU dot exists in device candidate.

38 host tests (`76cfac / 0`) pass,including9new controls for complete7stops,
deadline,badPC,shortwrite,diskfailure,live-code drift,wrong prior mailbox,
existing and unavailable HWbreakpoint. Existing breakpoints are preserved;
owned breakpoints removed andCPU halted,with no retry after ambiguous commit.
These tests are fake transport controls,not NPU arithmetic evidence.

Allow one explicit fresh diagnostic with90s outer bound,not full1024/power.
Raw data packing correctness is the experiment's question,not an assumption
being accepted. Original model/weights and error policy unchanged.
