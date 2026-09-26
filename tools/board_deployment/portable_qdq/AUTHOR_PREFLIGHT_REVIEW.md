# Portable QDQ author preflight — synthetic scope only

Final synthetic suite: **40 passed, 8 subtests passed**, 0.63 seconds. Actual
tool `f0da34` exited 0; dedicated scope
`spikeids-portable-qdq-author-03.scope`, invocation
`9320ee804b2c44329bd9ab850b94c409`, MemoryMax 4 GiB, MemorySwapMax 0,
TasksMax 128, CPU quota 200%, outer timeout 120 seconds. Python optimization 0,
bytecode off, hash seed 0 and NumPy/BLAS threads 1 were explicit launch settings.
JUnit: [author_03.xml](author_03.xml).

The suite exercises real native C compilation/inference for tiny inputs and a
full-width **synthetic** four-layer model, source generation and one complete
1024-row synthetic streaming subprocess. It checks INT8 constant preservation,
nonuniform per-channel DQ, signed ties-even and round-before-zero-point order,
saturation including finite division overflow, all output words, safe aliasing,
nonfinite rejection and no partial output on failure. Parser negatives include
wrong operator, transpose/axis/attributes, missing/unused/duplicate content,
external tensors, scalar bindings, dtype/shape/scales and INT32 bias zero point.
Runner tests cover ordering/status/length/last output, signed-zero diagnostics,
actual-anchor FP32 allclose orientation, failed fixed input identity, stale root,
foreign-parent rebinding, late generated-file edits and poisoned inherited
compiler/preload environment.

Earlier 26-test pass (`e34e74 / 0`) covered the initial C/parser, and the first
complete suite was 39 pass (`cedc2a / 0`, [author_02.xml](author_02.xml)). Root then
found a pre-run configuration gap: inherited CPATH/GCC_EXEC_PREFIX/LD_PRELOAD and
unrelated environment variables could affect a child. The final runner uses a
small explicit environment allowlist and records it in every command receipt;
the new adversarial control brings the final count to 40. This was a reviewed
implementation issue before any true-model invocation, not a failed board result.

Final source SHA-256 commitments:

| File | SHA-256 |
| --- | --- |
| generate.py | df7792e04ab5763971b0b3a0045df94e901ce78131eec24d422805c7e59cacdd |
| portable_qdq.c | e389a691656fd8dfbb75771c205e51ab16f491adfad65213b6e0ec951e0e4851 |
| portable_qdq.h | e8abd58b44e15806eff54df5245757c23aa491bd044f579dd59d0efc7c5be406 |
| native_main.c | e06cf0d6e33298ba75f5cdc91f6ad58f8843464c4e446a2082450b0ce88ede50 |
| run_native.py | b2057e38b99608ae9cabe9c57de4c11dd6c7d74abafd8a71971d6dde12ba5fba |
| test_portable_qdq.py | 1110d6542e0f507e1ee35f92dbf5248c71d4bd0f3480a0a1fe51555e49d557d7 |
| test_native_runner.py | 297c5c8b541a2af89b8fd3cf0bd450c37d5d40502517574283a7248862703b8a |

All seven final files are HOLD. The two changed files had matching SHA bookends
inside `f0da34`; the other five remained unchanged from the prior complete run's
matching `cedc2a`/`f66282` bookends and were rehashed after the final run.

Original ONNX static inspection `f17145 / 0` was separately limited to the
hash-checked protobuf, its 66 operators and tensor metadata. It performed no
forward pass. Neither the production generator nor the original 1024-row native
probe has run at this preflight point. There is no board, compiler-placement,
full-toolchain closure, all-integer, fastest-backend, parity or energy acceptance.
Sequential FP32 Gemm may differ from ORT; the forthcoming fixed probe must retain
any negative result and cannot relax the held numerical policy.
