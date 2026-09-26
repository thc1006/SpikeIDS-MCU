# Actual 01: compiler completed, original wrapper rejected

The sole ST generation ran in session **38764**, launch `16b769`, completion
`3592be`: outer wrapper exit **1**, retained ST child exit **0** in 17.089 s.
The external receipt is [ACTUAL_01_EXECUTION.json](ACTUAL_01_EXECUTION.json),
SHA `306855057d1eb069a7a0dd60293cdd13c57685b3505e2328f19508092ff3b2b1`.
The 4 GiB / zero-swap / 128-task / 400%-CPU scope invocation was
`5362cd56ffe8442dbd1560a0c6899f92`. No hardware was contacted.

`FAILED.json` remains present, SHA
`e0f185738bef0ee8a48a12371a9cf8ea097cba8937318e3655da0787a75210d5`;
there is **no RESULT.json**. The reason was the original validator's requirement
that generated C explicitly include zero cache designators. Actual generated C
instead omits both fields from its static const streaming-engine aggregates.
This is a validator dialect mismatch, not observed nonzero cache configuration.
No generator, profile, original model or generated output was changed and no
second compiler invocation was made. Source/profile bookends were identical.

Saved metadata inspection (`b342c9`, exit 0) observed weights 145,457 bytes at
`0x34200000` in the 256 KiB weights pool, and activations 2,048 bytes at
`0x34240000` in the 16 KiB activation pool. Both pools are CACHEABLE_OFF.
The RAW SHA is `cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec`,
matching the prior compiler's RAW bytes; that is not proof of numerical parity.
Reported mapping remains 31 software / 1 hybrid / 8 hardware epochs.

## Exact local basis for a separate saved-only review

ST 3.0 `Middlewares/ST/AI/Npu/ll_aton/ll_aton.h`, SHA
`d8a70bceaa40d016a11680fe65e3adec6ad0bff87987d54a8d3018fb555ccbc2`,
lines 446–447 declares the two unsigned bitfields unconditionally. Its C runtime,
SHA `9cdd88f5ac450c65a48e164608b59ca215df3dd3afe74fd4572ebbe5b7b7f7e2`,
lines 716–722 consumes those fields when the corresponding hardware macros exist.
Omitted scalar members in a valid aggregate initializer are zero-initialized;
this is C initialization semantics, not a guessed compiler default. See
[WG14 initialization issue 0413, quoting C11 6.7.9](https://open-std.org/JTC1/SC22/WG14/issues/c11c17/issue0413.html).

The saved C contains 21 static const descriptors and 21 calls. A replacement
review must positively bind every declaration/use, reject nonconstant or alias
mutations, and validate both raw-cast and physical-address-macro base forms.
It must not simply accept any absent cache field. The old result stays failed.

The header documents offset_limit as a prefetch boundary; runtime lines 702–710
program `base + limit - 1`. One saved activation limit is **2,112**, 64 bytes
beyond the reported 2,048-byte used footprint, but within the reserved 16 KiB.
Data intervals and reserved prefetch limits therefore require separate checks.
Any future linker/loader must exclude the whole reserved pool, not just 2 KiB.
This review does not simulate every hardware traversal or prove live register
state, cache policy, SRAM accessibility, RIF, clocks, target execution or parity.

`review_saved.py` is a separate visible validator revision, not a compiler retry
or rewrite of FAILED. Its author 23 synthetic controls passed `b965a5`, exit 0;
independent pre-review is required before its actual saved-output invocation.
It pins the independent retained-file snapshot and preserves its integer stats.

Precision correction to the older author preflight note: the author 22 include
spill/overrun/membership negatives; the explicit bad-alignment negative belongs
to the independent 25-control suite, not a separately executed author case.
