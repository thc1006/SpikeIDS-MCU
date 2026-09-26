# Actual native portable-QDQ candidate

**One genuine native run completed, exit 0. All 5120 output FP32 words matched
the frozen QDQ reference bit-for-bit** across the original 1024 rows. Reported
maximum absolute error, allclose failures and argmax disagreements are all zero.
This is an x86 native semantic result, not RA4E1/ESP32-S3 board acceptance.

Actual tool `39226f / 0`, synchronous (no session), scope
`spikeids-portable-qdq-native-01.scope`, invocation
`f5b49340e549419c85402838ea5ee0f0`. The scope had 4 GiB memory, zero swap,
200% CPU quota, TasksMax 128 and outer timeout 360 seconds. There was exactly
one source generation, native compile and full native inference process, no retry.
The compiler and native child both returned 0. Source bookends `7fd3bb` and
`47f9a4` matched all five held implementation files.

- [Observed external execution receipt](NATIVE_ACTUAL_01_EXECUTION.json), with
  the original report's eight-field integer/hash pin. The producer's own
  `actual_process_exit` remains null; it does not assert its own outer exit.
- [Result](../../../results/portable_qdq_native_20260925_01/RESULT.json), SHA
  `cb3536b760e40ad2fe6ce942e677ab2472837e2a73ffb86edd15700c3a171a93`.
- [Generated C](../../../results/portable_qdq_native_20260925_01/model_sources/model.c), SHA
  `bba723cc7b031815c2aaf848f6893eb87dd91cb05f5580f93df611be489bb1e9`.
- [Native executable](../../../results/portable_qdq_native_20260925_01/candidate), SHA
  `903b6def744ca1f77559e8f92628adb267991828999dd7a4b182745952efc251`.
- [Raw ordinal/status/five-word records](../../../results/portable_qdq_native_20260925_01/native.stdout),
  28672 bytes, SHA `b7d8f354ef425c3355a7d4effffbadc4dd5fd452314a5472ecb2cd4c1c7cce7f`.
- [Saved logits and row IDs](../../../results/portable_qdq_native_20260925_01/logits.npz), SHA
  `7c8eccf55a52b0b01f4677f23dfee339c42771b2d1aa2581ab7a71fd82c93055`.

The result retains nine selected source/tool/input pins and 14 output pins before
RESULT. The graph is exactly SHA `22dc7979…`, the original validation archive
`cb5b3415…`; complete hashes and raw records are in the result, not inferred from
filenames. Inputs were not reselected, sorted or requantized externally. All
1024 statuses were zero and all five logits per row were retained. The tolerance
comparison reproduces `np.allclose(reference, actual)` with FP32 inputs; here
exact equality makes tolerance orientation immaterial to the observed outcome.

The implementation stores 109440 INT8 weight elements but performs per-channel
FP32 dequantization and sequential non-FMA FP32 Gemm plus the complete QDQ/QCFS
chain. It is neither all-integer nor a fastest-backend benchmark. Host compiler
success and native numerical parity do not prove either MCU linker fit,
cross-compiler arithmetic, board execution, clock/memory placement, latency,
power, or NPU behavior. No new ONNX export, checkpoint/model training, ORT/Torch
forward, device/USB, programming, supply or OTP action occurred. Parent's
independent saved-output review is separate; this is the author's observed result.
