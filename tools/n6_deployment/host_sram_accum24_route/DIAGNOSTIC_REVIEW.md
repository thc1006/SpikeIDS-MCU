# SM06 same-row raw-dot diagnostic preflight

Actual init-only `8b42b7 -> 5574cb / exit0`:fresh READY SM06,0inferences.
Previous mailbox90ee5c07fe1b02920b08aacdb654d5c9fdd93d8161d9393b6450f258673dbd4e.
Same original row2656 and7actual ELF breakpoint sites. Frozen SM05 observer
is reused under private SM06 decoder;no change to one-commit/timeout/retention/
live-code+weights checks or cleanup. Nothing is resumed as a formal pass.

Actual BIN comparison (`3be06e`,`bcbd58 / 0`) has6byte differences from SM05:
two route source bytes,tag35->36 and associated compiler constant arithmetic,
two vendor build-time string digits. No arithmetic parameter/code change.
Timestamp strings mean independently rebuilt BINs are not claimed bitwise
reproducible;exact loaded artifact hashes are fixed and retained.

Topology now derives producer from original incoming ARITH route,not copied
hardcoded IDs. The previous review blind spot is explicitly covered by new
SM05-negative/wrong-ID tests. Allow a fresh bounded90s diagnostic only after
updated39host tests pass. No Flash/PPK/full-run acceptance.
