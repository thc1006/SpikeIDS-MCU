# Saved-only internal-SRAM candidate review

The one authorized saved-only invocation passed: actual tool **30d3fe**, exit
**0**, 0.157 s. See [raw report](SAVED_REVIEW_ACTUAL_01.json) (SHA
`e024e446e6c1dca394c61081e9ba1251e0483dce80d5d7d7a303538b6bc7528d`)
and [external exit receipt](SAVED_REVIEW_ACTUAL_01_EXIT.json).
Raw stdout was retained without JavaScript numeric parsing. Source
`909b77937c806510443f848240ee2e0d33eabbdbe35ed6acc06c1cda509f0445`
and author/independent tests plus the retained snapshot had unchanged SHA
bookends (`3828a4` before, `d062a6` after).

This separately reviewed **35 held source/input/runtime pins**, the unchanged
**34 original files / 5 directories**, and **21 exact streaming descriptors**.
All effective cacheable/cache-allocate bits are zero, by validated static-const
aggregate initialization and exact descriptor-use binding, not by accepting an
arbitrary missing field. Both original placement checks and actual allocated
41-input/5-output FP32 buffer roles passed. The RAW weights are 145,457 bytes
at `0x34200000`; activations use 2,048 bytes at `0x34240000`. The configured
reserved ranges remain 256 KiB and 16 KiB respectively. Epoch observation is
31 software / 1 hybrid / 8 hardware, not a numerical or board measurement.

One prefetch stop reaches offset **2,112**, 64 bytes above the 2,048-byte used
activation footprint. It is within the reserved 16 KiB pool; data intervals and
prefetch reservation were checked separately. A future firmware linker/loader
must reserve the whole stated pools. Full DMA traversal was not simulated.

The original generator invocation remains **wrapper exit 1 / ST child exit 0**.
Its FAILED marker remains unchanged and RESULT is absent. This report does not
rewrite that history. The cause and exact C/runtime basis are in
[the failure review](ACTUAL_01_FAILURE_REVIEW.md).

No second compiler, inference, model scoring, device access, RAM upload, power,
clock/security setup, flash, XSPI or OTP operation occurred. Successful saved
descriptor review establishes an offline placement candidate only. Numerical
equivalence, accessible/initialized RAM, live cache/register state, NPU execution,
hardware readiness and deployment acceptance remain unverified/false. Root is
responsible for integration; no new scientific experiment denominator is created.
