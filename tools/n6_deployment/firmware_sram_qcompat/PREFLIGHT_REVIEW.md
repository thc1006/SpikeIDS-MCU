# SM03 implementation adversarial review, 2026-09-26

Root review, no independent-agent claim. Original model graph, weights, runtime
installation, SM01/SM02 artifacts and failed board evidence are not edited.

The first actual divergence was signed16 epoch4 dequant read as signed8.
Full nine-site source/constant audit also found incorrectly unsigned zero-point
metadata at inserted quant nodes12/21/30 (actual signed8 -128) and dequant
nodes13/22 (-3/-15). Installed ll_sw_integer.c uses os/is signedness, while
these generated scale flags differ from the ozp/izp signedness. Correcting a
local descriptor copy preserves original eight-bit vendor arithmetic. First
signed16 dequant uses explicit fixed-site scalar FP32 multiplication. Its
zero point is0, scale bits3e900788, disjoint input[176,258)/output[0,164).

Actual C controls `a70d64 / exit0`: 13 tests. Installed real ll_sw headers,
all9 descriptors extracted from source hash8b7a8703... without retyping, exact
145457-byte weights. Every descriptor agrees with the strict adapter. Full
65536 signed16 domain is checked against a double-intermediate independently
rounded reference.405 individual malformed semantic-field cases,18 corrupt
constant cases and2 null cases reject without vendor calls or activation writes.
Eight-bit call substitutes verify local-copy signedness correction and that
no other descriptor bytes change; substitutes are not real ARM kernel tests.
Seven tests compile the actual new main and original inference loop, checking
runtime order, failures, no-ACK, cache-on and repeated-init rejection.

Rejected alternatives: global stride-based dtype guessing; replacing all
operators or retraining; in-place vendor patch; loosening parity tolerance;
setting a successful research status from compilation. Exact Q/DQ site
validation constrains this adapter to the frozen model only.

Primary semantics checked against ONNX DequantizeLinear:
https://onnx.ai/onnx/operators/onnx__DequantizeLinear.html
ST4.0.1 release notes do not establish a fix for this exact local3.0 mismatch.
Do not claim a vendor-confirmed diagnosis from unrelated forum reports.

Next gate: actual cross-build and independent saved ELF/source/binary review,
new SM03-only host identity, then bounded original1024-row board run. Unknown
later mismatches remain negative. CPU/NPU clocks are still unoptimized; no
timing or power acceptance is part of this numerical-debug phase.
