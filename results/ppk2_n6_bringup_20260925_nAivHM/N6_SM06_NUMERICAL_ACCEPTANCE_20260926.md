# SM06 numerical phase accepted — not power/performance acceptance

Two actual STM32N6570-DK RAM-load runs, `n6_sram_validation_20260926_08`
and `_09`, each completed the original 1024 validation rows. Each produced
5120/5120 FP32 words bitwise equal to the original QDQ reference, zero
out-of-tolerance values and zero classification disagreements. The two runs
also agree with one another on every original row ID, input word and output
word. Unchanged tolerance: `np.isclose(reference_fp32, actual_fp32,
atol=1e-6, rtol=1e-5)`, with actual as the relative-tolerance anchor.

This is acceptance of **this fixed model, firmware and 1024-row validation
phase only**. It does not prove arbitrary-input equivalence, physical power-
cycle repeatability, all models, all three boards, optimized performance,
calibrated frequency, latency, energy or the whole research. No paper energy
table is updated. Neither run is a formal power measurement.

## Model and actual hardware implementation

Original GPU-trained NSL-KDD QCFS primary seed0, final epoch80,
41→256→256→128→5 quantized ANN, not temporal SNN. No retraining, new export,
best-seed selection, calibration/test-row substitution or tolerance relaxation.

| Fixed input/artifact | SHA-256 |
| --- | --- |
| Original checkpoint | `1e1033cd394283d7a82c6f6d8713eb1beeec9ff4b9d43cd247076833920b837e` |
| Original QDQ ONNX | `22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d` |
| Original validation vectors | `cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb` |
| Original ST raw weights | `cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec` |
| SM06 actual build report | `582163fddcd5e08836588fd4d89f7f6c45540ce0bc017c76fc9ae999d4dc73c6` |
| SM06 actual ELF | `aa31c20c3f3d3078c5b5e356efaee9fae0a46dfbdf42e6262624033fdaafaec4` |
| SM06 actual 85740-byte BIN | `656c04d59f1ad1cc009d1240ca29110714d2f292b0c7640f35a241373bf6c689` |

The later three dense integer dot products run on the NPU. The adapter
retains signed24 accumulator outputs, then uses original graph scales/bias
and strict CPU requantization. The first dense, QCFS and other software
operators run on CPU. Current schedule: 42 executable entries, 7 HW + 35 SW,
zero hybrid, followed by one nonexecuted sentinel. It is **not all-NPU or
all-integer inference**. The adapter does not look up reference logits.

Original export reports remain unchanged: QDQ-versus-original-FP32 errors
and its separate quantization acceptance policy are not erased by perfect
board-versus-QDQ agreement. The previous `board_validated:false` in the old
export report describes its original phase; this external record supplies
new, narrowly scoped board evidence without rewriting that report.

## Issue-level adversarial review and negative evidence

1. Runtime/FP entry and signed16 interpretation failures remain recorded in
   SM01–SM03; SM04 fixed first-dense Conv/Cast semantics but run05 still failed
   297/5120 values across 81 rows. Zero class differences did not qualify it.
2. Actual row2656 captures located a later NPU rounding difference crossing
   a QCFS threshold. Wider signed24 output preserves exact integer sums for
   original requantization; no final-output tolerance was changed.
3. **Our first SM05 adapter had a routing bug**: epoch31 selected disabled
   CONVACC1 rather than the original CONVACC3 producer. An assumption was also
   duplicated in its structural test. The real bounded diagnostic timed out;
   it was not accepted or blamed on the model/vendor. Original SM05 code,
   build and raw failure remain intact.
4. SM06 changes that route's two start/end source fields and deployment tag.
   New tests derive the required producer from the original routing topology,
   reject SM05 and wrong unit IDs. Actual ELF review checked 314 build-input
   pins, 240 artifact pins, four segments, ELF/BIN byte agreement, entry/
   provider binding and absence of unresolved symbols/relocations. Build
   timestamp text differs too: no bitwise-identical rebuild claim is made.
5. Actual row2656 SM06 diagnostic completed all seven stops. Independently
   computed NumPy and scalar original-weight dot products match all 389
   captured NPU integers (256 + 128 + 5). Captured inputs match original
   intermediate quantization; final five words match. Eleven corruption
   controls reject wrong raw inputs, accumulators, outputs, tags, PC, FP state,
   cleanup and false acceptance. This one-row diagnostic is not all-row
   per-layer profiling; full-model evidence is supplied by runs08/09.
6. Saved full-run reviewer independently recomputes all reference comparisons.
   Initial ten controls passed; further review found it did not reject some
   altered acceptance flags/metadata. It was hardened before final acceptance.
   Twenty additional controls reject false energy/frequency/latency/research
   claims, wrong CPU/memory placement, final-mailbox mismatch, unchecked
   payload-readback claims, nonordinary evidence entries and malformed scope.
   Firmware, launcher and raw measurements were not edited for this repair.
7. A new offline selection gate pins checkpoint, export lineage, exact firmware,
   launch/review sources, raw NPU gate and both complete run inventories. It
   rechecks source/artifact bookends and scalar cross-run words. Wrong model,
   seed, firmware, manifest, evidence, source and execution/power CLI requests
   are rejected. No implicit `latest` selection or automatic fallback exists.

Final combined execution: **127 tests passed**, `db6abf -> 6ab12a / exit0`,
covering selection gate, current host, SM05 arithmetic and SM06 route suites.
This is one agent's separate review implementations and adversarial tests,
not a claim of external peer review or absence of every possible defect.

## Actual execution receipts and retained data

| Run | Tool launch → completion / exit | Rows / exact words | Fresh platform nonce |
| --- | --- | --- | --- |
| 08 | `195b2f -> 92ef8d / 0` | 1024 / 5120 | 4082609654 |
| 09 | `3c5b39 -> e09089 / 0` | 1024 / 5120 | 742385446 |

Both use fresh platform/NPU initialization and RAM reload, not physical
power cycling. Each retains 1060 files. Source/model/stage identities hold
before and after. Independent saved NumPy and separate scalar cross-run
review `834e7d / 0` confirmed exact agreement after reviewer hardening.
CPU halt succeeded; no NPU quiescence or electrical shutoff is inferred.
Producer `actual_process_exit:null` fields remain untouched; tool receipts
above supply the observed exits. Hashes detect drift, not fabricated hardware
or cryptographically signed execution receipts.

Canonical [selection manifest](../../tools/board_deployment/N6_SM06_SELECTION.json)
SHA `c70b0200ea022938da5fdd1ab8a46e2b6adb3394eae512de8f6c1e40fbc17403`.
Run the offline gate from the repository root:

```sh
uv run --no-project --offline --python .venv/bin/python python tools/board_deployment/verify_n6_selection.py
```

The command does not connect to a board, execute a model or control power.
Its fresh check `db6abf` passed before the 127-test run. Future changed
firmware/instrumentation must earn separate build review and full parity;
this selection's acceptance must not be inherited by a different ELF.

## Next phase and physical boundary

Latest USB inventory (`f71032 / 0`) contains the expected ST-LINK, not PPK2,
RA4E1 or ESP32-S3. No power capture/retry daemon is armed. The user-reported
standalone N6 supply/JP2 arrangement is not being changed by software.

Next software work is a separately tagged SM06-compatible measurement/
instrumentation variant, with explicit GPIO boundaries and review of clock,
overhead, memory placement and host retention. Old trace code expects 40
epochs/162 records; SM06 requires 42/170 and cannot reuse that contract.
Trace callbacks and mixed CPU cycles alone are not NPU hardware cycles.
The old trace firmware is not selected or permitted as a substitute.

Formal energy additionally needs the actual meter connected to a reviewed
measurement path and synchronized marker input; neither can be manufactured
by software. Other boards still require actual target identification,
programming/readback and the same 1024-row validation. A finite correct-model
gate is now available for automation, but the entire three-board energy
pipeline is not yet complete and this record does not claim otherwise.
