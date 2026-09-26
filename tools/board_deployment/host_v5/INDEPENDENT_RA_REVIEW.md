# Independent RA mailbox offline review

Result: no remaining blocker within this bounded protocol/test scope. This is not hardware, board-power, firmware-execution, numeric-parity or energy acceptance. No device/backend was opened and no target operation was performed.

Final observed execution: tool chunk `40ec36`, exit **0**; child unittest exit **0**, all **12** controls passed in 0.053 s. Six source/test whole-file SHA-256 values matched before and after; complete stdout/stderr and both hash maps are preserved in `INDEPENDENT_RA_FINAL_02.json`.

Reviewed implementation: `ra_mailbox.py` SHA-256 `08aa77d82d0995a468462a95fdcb7acfd4fb49667ca802d6dde57ee4affbe131`. Independent tests: `test_independent_ra.py` SHA-256 `dd34094fa235cd4aac1698f6b932fa051b3b9fc50bf575155877aa617d2c5c01`. I authored these additional tests, not the production mailbox implementation. They reuse the author's explicitly synthetic RAM provider and frame helper while exercising the real mailbox, protocol codec and Session.

The source-level mapping is consistent with the reviewed target: 512-byte mailbox at `0x2001f000`, board 1, FP-environment flag 1, 160-byte HELLO at offset 352, 232-byte request at offset 32, four-byte request commit at offset 16 written last, 88-byte response at offset 264 and response commit at offset 20. Target source inspected: `../ra4e1_v5/app.c` SHA-256 `e338443db40f39eee6153eeac40143bd4e192ff8dcdc97101a99a18e37496a0b`; this static comparison is not a new ELF or hardware validation.

The complete positive control processes all 1,024 ordered frames, all 41 input values and all 5 outputs, with exactly 2,048 staging/commit writes and no 1,025th inference. Negative controls cover stale HELLO/CRC-valid wrong-sequence reply, partial staging, header/request mutation, sink failure before and after commit, final-read deadline crossing, target non-completion, invalid request/reply types and refusal to retry poisoned sessions. The final-read raw snapshot is retained before a deadline failure is raised.

One concrete fault-injection defect was reproduced on the original `b27b6438...` source: after a finite first clock reading, a later NaN reading bypassed `now >= deadline`. Source-bookended execution `9dfede`, exit 1, recorded 11 passing controls and this one failure in `INDEPENDENT_RA_ATTACK_01.json`. The author's minimal change computes remaining time and rejects nonfinite or nonpositive values; the unchanged independent test now passes. This is clock-API defensive handling, not a claim that a real monotonic clock returned NaN. Earlier development execution `a6f339` is not treated as the source-bookended result because its preceding hash command used the wrong working-directory paths.

Finite limits: deadline checks cannot preempt a blocking read/write/retention callback; a separately bounded transport/outer process remains necessary. Two equal RAM snapshots and sequence checks are protocol consistency checks, not cryptographic hardware attestation. These controls do not prove cache/coherence behavior, target liveness on a real board, model execution, measured timing or safe power. No automatic retry, board/energy promotion, or new hardware authorization follows from this review.

All prior counterexample evidence and these final tests/reports are retained; no production source was edited by this reviewer.
