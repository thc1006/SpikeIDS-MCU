# Saved-only validator author preflight

Final source `review_saved.py`:
`909b77937c806510443f848240ee2e0d33eabbdbe35ed6acc06c1cda509f0445`.
Final author test `test_review_saved.py`:
`d61d5c22f4991b1e46fcc7a81ab8a74f499a1bcca603e425ec002d0877e78e3f`.

**25 synthetic controls passed**, actual `aaa3e4`, exit 0, 0.004 s; five source,
fixture and original-snapshot SHA bookends were identical. This invocation did
not open actual generated artifacts or invoke any compiler/device.

The new validator visibly copies the old placement function. Its body differs
only by removing the explicit-cache-designator loop, replacing that check with
a separate strict static-const aggregate/parser and exact call binding. No
runtime AST rewriting remains. The frozen generator is still literal-pinned,
and its model/tool/snapshot helpers are reused without invoking generation.

Controls cover omitted versus explicit zero cache fields; enabled fields;
both raw-cast and physical-address macro bases; positive padding beyond used
but within reserved capacity; wrong data/prefetch bounds; weights writes;
nonconstant/positional/duplicate/unknown members; extra references and aliases;
mutations; unknown or duplicate calls and counts; type macros; uint32 limits;
and full tiny placement integration retaining external-address rejection.

Root identified an actual new-parser defect: C `0100` means octal 64, but the
draft interpreted it as decimal 100. With start=77, end=0100, limit=0100 the
draft wrongly passed. The preserved execution `415d03`, exit 1, had 24 passing
controls and that one expected rejection failure. Final grammar accepts only
decimal `0` or nonzero-leading digits, or explicit hex, and rejects octal-like
notation. This defect concerns the reviewer dialect, not the saved compiler C.

The actual failure stays bound by the original external exit receipt, FAILED
and compiler-call hashes. Independent snapshot SHA
`ddf5338a4724bb5ec25487fd1a1f28426d49689dd538419304d6d02d23513d75`
binds all retained files/empty directories. Its eight original stat/hash fields
are converted by explicit key mapping, preserving integer values, not freshly
adopted or resealed. The exact pinned ST header/runtime sources establish the
descriptor ABI. No full DMA traversal, board state, numerical equivalence,
deployment acceptance, or original-wrapper success is claimed.

Independent pre-review is required before the one actual saved-only invocation.
There is no second compiler call in this validator.
