# Full-vector RA4E1 / ESP32-S3 host validation

The only selectable model is the original NSL-KDD QCFS primary seed 0 QDQ
`22dc7979...75e2d`, with the original `cb5b3415...1edb` validation archive.
No retraining, model substitution, test-label access or tolerance change.

`protocol.py` matches `../shared_v5/WIRE_ABI.json`: HELLO checks the full model
and vector digests, platform, CPU backend, FP environment and 41/5 shape.
Every request contains all 41 raw binary32 words, original 64-bit row ID,
ordinal, sequence and CRC; each reply must return five finite raw words.
Bad identity/CRC/sequence, ambiguous writes and timeouts poison the session.

`validate.py` retains each complete row before requesting the next and checks
all 1024 rows under the unchanged FP32 `isclose(reference, actual)` tolerance
(atol=1e-6, rtol=1e-5), plus zero argmax disagreements. The relative anchor is
actual, not reference. Persistence failures also poison the session. Results
do not certify firmware programming/readback, clock, latency or energy.

## ESP32-S3

Offline CLI (does not open USB):

```sh
uv run --no-project --offline --python .venv/bin/python python tools/board_deployment/host_v5/run_esp.py
```

Live operation requires an explicitly supplied `--execute-esp-validation`,
`--port`, `--expected-usb-serial`, and fresh absolute `--output` under results.
The selected physical board must already have the correct reviewed firmware;
this collector neither selects nor programs an image. The USB serial and
native ESP VID/PID are checked before/after opening. No automatic port fallback
or deliberate bootloader/reset action is performed. An outer timeout is needed.

DTR/RTS are requested false before opening. OS/driver open/close transients are
still possible. pySerial POSIX open discards pre-open input internally; only
post-open HELLO prefix noise and all returned request/reply chunks are retained.
The fresh HELLO query is sent after opening. Inference replies do not allow
resynchronization, noise discard, or a second request attempt.

## RA4E1

`ra_mailbox.MailboxExchange` provides the same callable transport for
`Session(exchange, 1)` through explicit read/write callbacks. It validates a
fresh 512-byte mailbox at 0x2001f000, requires complete request readback, commits
the request last, and requires stable completed response/sequence/HELLO before
returning logits. Its constructor does not access hardware. A concrete reviewed
RA debug/programming backend is still required; this is not a ready-to-flash CLI.

## Executed checks and limits

Combined final root run `691f85 / exit 0`: **59 tests and 28 subtests passed**.
This includes 1024-row synthetic serial and RA flows, compiled C/Python wire
round trips with an explicit fake inference function, failure controls and
offline loading of the actual fixed validation archive. None executed a board.
Native full-model numerical evidence is separate in `../portable_qdq/`.

Independent reviews found and closed the HELLO environment boolean inversion,
two CLI source-bookend gaps, and a nonfinite-clock fault-injection gap in the RA
transport. The latter does not imply the OS monotonic clock actually returned
NaN. Source mutation on final publication produces failure/nonzero even if a
provisional RESULT file remains: do not accept RESULT existence without the
separate successful process exit and absence of FAILED. Finite bookends do not
promise immutable files or protection against arbitrary privileged interference.

See `PEER_LOGIC_REVIEW.md`, `SERIAL_TRANSPORT_REVIEW.md` and the separate RA
review. Existing failing tests and build captures are retained, not relabeled.
