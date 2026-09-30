# Independent saved-only review of internal SRAM generation 01

2026-09-25. **Original wrapper remains failed (exit 1); ST generate child exited
0. No RESULT was published, no retry or hardware action was performed.**

Author-observed execution receipt `ACTUAL_01_EXECUTION.json`, SHA256
`306855057d1eb069a7a0dd60293cdd13c57685b3505e2328f19508092ff3b2b1`, binds
session 38764 / completion 3592be, the child exit 0, wrapper exit 1 and failure
`Generated cache field enabled/missing`. I read this as an external operator
record, not a signature or independent observation of its original live process.

My saved-only verification actually completed **f5ae04 / exit 0**. It checked
all 30 original INTENT input/tool/source pins by full SHA256 and original stat;
the copied QDQ is still `22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d`.
All 34 saved files and five subdirectories matched the initial full-hash/stat
snapshot captured by `235a9d / exit 0` and retained in
`ACTUAL_01_REVIEW_SNAPSHOT.json` (SHA256
`ddf5338a4724bb5ec25487fd1a1f28426d49689dd538419304d6d02d23513d75`).
FAILED and generate.json match the external receipt. No source, failed candidate,
old reference/archive or original evidence was modified or regenerated.

## Concrete cache-dialect finding

The cache guard was over-specific for these saved bytes. There are **21 static
const `LL_Streng_TensorInitTypeDef` aggregate initializers**, each used solely
by its declaration and one exact `LL_Streng_TensorInit(id, &object, 1)` call.
All omit `cacheable` and `cache_allocate`; none explicitly enables them.
Unsigned aggregate members omitted from an initializer are initialized to zero
under [C11 N1570, 6.7.9 paragraphs 19 and 21](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf).
This is a positive property of the matched initializer forms, not a general
rule that any absent cache text proves cache is disabled.

The installed official 3.0 `ll_aton.h` defines these as one-bit fields at lines
446–447; `ll_aton.c` reads those fields into stream-engine bus attributes at
lines 718–719. Their full hashes and stats, plus `ll_aton_caches_interface.h`
and `ll_aton_version.h`, match the original four pins in the frozen firmware
build 03 RESULT. There are zero generated NPU-cache maintenance calls and
32 MCU-clean plus nine MCU-invalidate calls. MCU cache maintenance is not a
statement that any cache was enabled on a board.

Both observed pools are CACHEABLE_OFF with the declared absolute addresses,
capacities and read/write roles. All 98 buffer records, including 49 parameters,
have compatible membership, alignment and extents; allocated I/O is FP32 41/5.
Weights RAW is 145,457 bytes, SHA256
`cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec`;
activation used extent is 2,048 bytes. All 21 stream start/end ranges fit their
used pool; prefetch-limit offsets fit the reserved pool capacities. Maximum
limits are 2,112 bytes for activations and 143,096 for weights. A limit is not
the same as a tensor's used extent: requiring activation limit <= 2,048 would
incorrectly reject this bounded 16 KiB pool. Official runtime writes limit-1
as its last-address guard. This is a finite syntax/range observation, not a
proof of every dynamic transfer performed by compiled code.

Observed mapping is 31 SW, one hybrid and eight HW epochs, plus six no-execution
nodes. Equality of these counts to the older build is coincidental evidence,
not a required gate or numerical equivalence proof. The generated preamble's
activation-size comment says 16,376 while JSON reports 16,384; the independent
range checks use the pinned descriptor/JSON capacities and actual extents, not
that comment. My first throwaway inspection (`a6258d`, exit 1) also exposed my
overly narrow raw-cast matcher: two of the 21 bases use the physical-to-virtual
macro. The corrected saved-only check included both explicit forms.

## Outcome and limits

An additive saved-only validator can address this false rejection by proving
the exact static-const forms, unique uses, known runtime fields, no later
mutation, explicit nonzero rejection and both transfer/prefetch bounds. Merely
deleting the missing-field check is insufficient. This review does not change
the wrapper's recorded exit, manufacture a RESULT, or accept the candidate.

No ST tool, model inference, actual reference-array decode, board loader or
USB operation was invoked by this reviewer. SRAM initialization/access,
clock/security/cache setup, numerical parity, deployment, power and publication
remain unverified. The historical failed namespace and all old gates remain HOLD.
