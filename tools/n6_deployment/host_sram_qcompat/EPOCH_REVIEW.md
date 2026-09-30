# Run04 negative and 48-boundary diagnostic preflight

Actual run04 `b567ef -> 9259f8 / exit1` completed1024 rows but again failed
5103/5120 logits and497 classifications, max abs16.272749423980713. Independent
saved review `0b7928 / exit0` reproduced these numbers. Same total failure
counts do not prove the two defects were not repaired, nor identify the next
cause. Do not mark this numerical phase accepted.

Next bounded diagnostic is one explicit row20/sequence1025, not acceptance.
Fresh output `results/n6_epoch_diagnostic_20260926_02`. Source-pinned original
observer, fixed SM03 ELF/sources, exact previous final mailbox
767781ae0855c264f5d98c409150b5a31582e681ba5b5abe3eaa1ca9ff37ecfb.
48 unique boundaries are derived from the pinned generated schedule and
linked ELF symbols, not guessed addresses. Code/weights readback and full
live prior-mailbox match are mandatory before staging/commit. Only hardware
breakpoints; one at a time, five-second per-stop deadline, cleanup halt and
owned-breakpoint removal. Outer timeout120s/interrupt,10s kill fallback.

Root adversarial review of import isolation, fixed artifact identity, ordering,
raw capture retention, failure no-retry and cleanup: six actual fake-transport
tests passed (`7f9087 / exit0`), including full48 sequence, timeout/bad PC/
short write and middle-capture disk failure. Original eleven observer controls
also remain passing. Hardware evidence still required. More stops alter
timing; no energy/latency value can be accepted from this diagnostic.
