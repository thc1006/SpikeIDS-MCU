# Bounded epoch diagnostic preflight, 2026-09-26

Actual run 03 completed 1024 requests but failed numerical comparison. This
separate one-row replay is NOT a continuation toward acceptance or a retry of
an ambiguous transaction. Original run evidence and strict tolerance remain.

`diagnose_epochs.py` defaults to offline checks. Explicit execution requires
the exact retained negative final mailbox, halted secure privileged M55 state,
masked IRQs, strict FP state, and live code/weights matching the fixed SM02
build. It reuses original row ID20, assigns diagnostic sequence1025 once,
and retains all inputs/outputs and 16KiB activations at five fixed ELF symbols.
Only explicit hardware breakpoints are requested; no code-byte patch, Flash,
reset, model rebuild or PPK operation. CPU must halt and owned breakpoints
must be removed on every exit. Hardware-breakpoint perturbation makes any
timing/power observation unsuitable for research measurement.

Root adversarial review inspected staging, commit ambiguity, stale response,
live model mismatch, existing breakpoint ownership, timeout, retention failure
and cleanup. Eleven fake-debug controls passed (`6e0c92`, exit0). The initial
success fixture failed because it retained pending API sentinel words; only
the fixture was corrected to represent a successful response. Production
API-status checking was not relaxed. This is not independent-agent signoff.

Remaining scope limits: debugger API breakpoint confirmation is not an
independent electrical trace. CPU halt alone is not proof of NPU quiescence.
The five observations localize a discrepancy, not by themselves its unique
cause. Diagnostic completion never sets research acceptance true.
