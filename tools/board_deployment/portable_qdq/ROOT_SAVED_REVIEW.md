# Root independent review — native candidate, 2026-09-25

Actual saved-only review `651dd6 / exit 0` checked all nine original input/source
pins and 14 output pins before/after, the fixed external execution receipt and
original RESULT stat/hash. It independently decoded all 1024 raw records,
required sequential ordinals and zero statuses, bound the native stdin digest
to the original full 1024 x 41 input tensor, and compared all 5120 output words
to the original QDQ archive. Every word matched bit-for-bit. All five NPZ fields
were also checked against the raw stream/original archive.

Reviewer: `review_native_saved.py`, SHA-256
`f3f0ed75d8b56a5781f4b0e77a5f69cc3a06db1dda860d7b69311bc0fc5be61f`.
No native executable rerun, ORT/Torch forward, compilation or hardware access.
This clears the native numerical step for additive RA4E1/ESP32-S3 cross-builds;
it does not accept either board or any energy/performance result.

The first reader attempt in tool `2f84f7` mistakenly expected two NPZ fields;
the actual producer stores five. The resulting `ValueError: Native NPZ schema`
was a reviewer assumption error. The reader was corrected to validate all five,
not to weaken the numerical gate. That multi-command shell returned 0 because
its last, separate stage-bundle unittest succeeded; its overall exit must NOT
be cited as proof the first reader passed. The passing review above was run
as a standalone command. Original producer sources and outputs were unchanged.
