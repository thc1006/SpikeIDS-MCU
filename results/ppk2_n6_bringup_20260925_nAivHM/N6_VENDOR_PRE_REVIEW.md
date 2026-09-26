# Pre-execution review: fixed v5 graph → offline vendor preparation

Root read the complete wrapper and author tests, compared the generation-report
grammar with an existing vendor report (grammar only, not old model results),
and requested an additional nonempty binary-weight requirement. The author
implemented it before the final synthetic test run.

Candidate identities:

- prepare_vendor.py `cd1bb490fa913d0ffde3c5c59ff8108134537228ded9ec130e5ac17939f7a94f`
- test_prepare_vendor.py `e8725a226130ebaa643a01caa3f3f3455dbd65a432c6c50554d957c133c62eed`
- README.md `f80b06c5f82b712a65d682092fb7cd6269e8110ff1d9cdd49edc6561447bd767`

Author observed 33 synthetic subprocess/IO tests passing, actual completion
193ed3 / exit0. The preceding test run had two exception-type expectation
failures; actual operations correctly refused the inputs. The test expectations
were corrected, not the fail-closed wrapper. Both test runs are retained.

Reviewed cases: wrong fixed input/tool/source identity, incorrect tool version,
nonzero subprocess, timeout/group kill, partial logs, missing/empty artifacts
and binary weights, ambiguous epoch counts, source/tool/input mutation,
publication replacement, output rebind/symlinks, no overwrite/resume, and
disallowed external CLI/model arguments. Scope is finite engineering coverage,
not proof of compiler correctness or a full package closure.

## Authorized actual operation

One invocation in fresh `vendor_actual_01` under this phase directory:
installed ST Edge AI Core 3.0 --version → analyze → generate, fixed SHA v5
NSL-KDD/QCFS primary seed0 QDQ, STM32N6 default vendor profile, explicit
FP32 I/O, STAI, lossless/balanced and binary output. Do not invoke validate,
serial/USB, firmware load, reset, flash or target power. No training, new
calibration or new formal export. All existing export negatives remain intact.

Outer transient user service: memory ceiling4GiB, swap disabled for this
service, CPU quota400%, tasks128, runtime ceiling600s, control-group kill and
10s stop timeout. This does not clear existing system swap or reconfigure
other jobs. Live workstation observed available RAM about12GiB and disk50GiB;
do not assume the old global inventory's free-space figure.

Subprocess and outer actual exit must both be retained. An exit0 plus generated
files only qualifies offline preparation; a subsequent independent review must
check mapping and artifacts. The default memory profile is not yet the final
board flash/linker layout. Physical supply, firmware, full board logits,
GPIO wiring/clock, latency and energy remain unaccepted.
