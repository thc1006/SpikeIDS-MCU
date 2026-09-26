# Three-board experiment status — 2026-09-26

This is the current hardware-work entry point. It does **not** certify the
whole research, complete the paper, or replace negative export results.
All three boards are in scope; none has yet produced an accepted board-model
inference or formal power result in this deployment sequence.

## Latest actual N6 run — supersedes electrical history below

**Current superseding result:SM04 run05 completed1024rows,297/5120 outputs
failed on81rows,0classification disagreements. Still NO numerical acceptance.**
Signed16 repair and first Conv/Cast repair are implemented in separate
frozen variants. New SM04 mapping7HW+32SW,no hybrid;later3dense ops use NPU.
Actual46-stop diagnostic of first failing row2656 locates first remaining
divergence at second NPU dense output:2 values each off by1;one crosses QCFS
threshold and propagates. All first-layer and first-QCFS outputs are exact.
CPU halted,PPK absent,no power run or retry armed. Next:wider NPU accumulator
path with original requantization,subject to new review/testing.
[Run04/05 evidence and adversarial review](../../results/ppk2_n6_bringup_20260925_nAivHM/N6_SRAM_ATTEMPT_20260926_05_REVIEW.md).

The following run03 account is historical,superseded by the above:

Global runtime-init repair is now built/deployed as additive SM02 firmware.
Actual run03 completed all1024 rows, but **5103/5120 logits** failed original
tolerance and **497 classifications** disagreed. No accepted inference,
power, latency or NPU profile. Failed raw evidence is preserved; CPU halted.

Five hardware-breakpoint captures of original row20 localized the first
divergence: input41/41, quantization41/41 and first NPU arithmetic41/41 agree;
CPU dequantization then misreads signed16 as signed8, producing24/41 wrong
values. All41 wrong-read output words reproduce bit-for-bit in separate
NumPy and scalar saved-only reviews. Installed ST3.0 wrapper selects only
S8/U8 despite the generated signed16 input. Compatibility repair is next,
not yet implemented; this is not proof no later defects exist.

Combined preflight181 tests/47 subtests passed. PPK remains removed, JP2 3/4
and standalone CN18 supply connected per user; fresh Vref3.273–3.277V estimates,
not calibrated certification. No additional wiring change or background retry.
[Actual execution, adversarial review and next phase](../../results/ppk2_n6_bringup_20260925_nAivHM/N6_SRAM_ATTEMPT_20260926_03_REVIEW.md).

## Exact common model

The first engineering candidate is the original GPU-trained **NSL-KDD QCFS,
primary seed 0, final epoch 80**, 41→256→256→128→5. It is a quantized ANN,
not a temporal SNN and not a newly chosen best seed.

- Checkpoint: `results/v5_run_20260921_r6_recovery1/results/nslkdd_qcfs/runs/qcfs_seed_0.pt`,
  SHA `1e1033cd394283d7a82c6f6d8713eb1beeec9ff4b9d43cd247076833920b837e`.
- QDQ graph SHA `22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d`.
- Original 1024-row validation vectors SHA
  `cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb`.

No legacy CAN weights or arbitrary latest checkpoint is selected. See
[original model lineage](../../results/ppk2_n6_bringup_20260925_nAivHM/SELECTED_MODEL_IDENTITY.md).
All five logits, exact row IDs/order and all 41 inputs are required. Board
numerical validation retains FP32 `np.allclose(reference, actual, atol=1e-6,
rtol=1e-5)` and zero argmax disagreements. The original QDQ-versus-FP32
quantization allowance is not a second allowance for board-versus-QDQ errors.

## Builds and remaining work

| Board | Selected implementation / actual artifact | What is still unproven |
|---|---|---|
| STM32N6570-DK | [SM04 first-layer semantic repair](../n6_deployment/firmware_sram_firstfloat/README.md), [platform initializer](../n6_deployment/platform_stage/ACTUAL_BUILD_03.md); actual1024-row run05 still fails numerically | Remaining NPU accumulator/requantization divergence,full board parity,qualified NPU activity/clocks and measured power path/energy |
| FPB-RA4E1 | [RA01 firmware](../../results/ra4e1_v5_build_20260925_01/RESULT.json), actual ELF/BIN/HEX, 123120-byte BIN, 37 successful commands | Concrete programming/debug transport, exact connected board, target FP environment and 1024-row parity, measurement marker and energy |
| ESP32-S3 | [ESP03 firmware](ESP32S3_BUILD_ACTUAL_03_REVIEW.md), app/bootloader/partition images, 269472-byte app, 9 successful commands | Physical SKU/flash size/USB identity, controlled programming, boot, target FP environment and 1024-row parity, measurement marker and energy |

RA/ESP share the portable QDQ CPU implementation: INT8 stored constants with
strict sequential FP32 arithmetic. They are **not** advertised as all-integer
or optimized final-performance kernels. The genuine native C experiment
produced 5120/5120 reference output words bit-for-bit; this is host evidence,
not proof that either target behaves identically. See the
[independent saved native review](portable_qdq/ROOT_SAVED_REVIEW.md).

RA saved root review `7a2127 / 0` checked ELF/BIN/HEX bytes and source/artifact
pins. ESP03 actual build `69b94f / 0` and independent saved root review
`0b4392 / 0` checked 28 input pins, 843 artifact pins, 48 archives, exact
SDK-forced undefined symbols, no relocations, precise RTC reservation and
strict numerical compile flags. See the [external root receipt](ESP32S3_BUILD_ACTUAL_03_ROOT_REVIEW.json).
Failed ESP01/02 records and the original builder remain unchanged.

## STM32N6 NPU distinction

The original ST Neural-ART generated program contains **8 pure hardware,
1 hybrid and 31 software executable epochs**, plus a nonexecuted sentinel.
This is mixed CPU/NPU inference, not an all-NPU graph. In this model the
hybrid Cast takes a CPU conversion branch; do not count it as another proven
accelerator run. Merely linking NPU symbols proves no hardware execution.
Current SM04 explicitly changes the schedule to7hardware+32software;
historical160-callback trace expectations cannot be reused unchanged.

The [trace module](../n6_deployment/npu_trace/README.md) passed 38 host C
controls and two actual ARM object compilations. It handles all 160 epoch
callbacks plus the actual synchronous runtime's DeInit/Init reset callbacks.
A separate [instrumented SRAM firmware variant](../n6_deployment/firmware_sram_trace/BUILD_ACTUAL_01_REVIEW.md)
has now actually compiled/linked (`ec39e3 / 0`, 67 successful commands,
80268-byte BIN). Preflight passed 34 tests and 23 subtests: 21 author controls
and 13 independent controls, including 12 host-C tests of the unchanged new
`main.c` with explicit CMSIS/STAI/helper substitutes. This is not board execution.
Root [independent saved review](../n6_deployment/firmware_sram_trace/ROOT_SAVED_REVIEW_EXECUTION.json)
`38a001 / 0` checked 291 input pins, 256 retained artifact pins, exact ELF/BIN
bytes, all five PT_LOAD segments, the separate 6556-byte trace NOLOAD region,
no undefined symbols/relocations, and fresh disassembly showing the actual
init→bind→begin→run→finish→get-error call sequence in `main`.

The original S6 firmware remains frozen. The trace variant has a distinct
mailbox magic and deployment tag; **do not supply it to the old S6 host**.
A trace-aware host that preserves each log before the next request remains
to be integrated. Its future callback trace is diagnostic, adds overhead and
is not an accepted NPU-cycle or energy measurement. The original uninstrumented
S6 path remains available for its separately implemented numerical validation;
diagnostic tracing and final performance/power runs must remain distinct.

## Host automation already implemented

- [N6 controller](../n6_deployment/host_sram/README.md): fixed model/stage
  bundles, backup before RAM writes, full readback, runtime/platform/FP checks,
  all original vectors and full responses. Three hardware attempts now exist;
  run03 completed1024 rows but failed numerical validation. Additive FP-entry
  and SM02 runtime wrappers fix the two preceding startup defects; signed16
  dequant mismatch remains open. Separate bounded epoch diagnostic completed.
- [RA/ESP host contracts and transports](host_v5/README.md): fixed HELLO,
  model/vector identity, no ambiguous retries, full-row raw retention, poison
  on transport or retention failure. Combined 59 tests plus 28 subtests passed
  (`691f85 / 0`). These are offline/fake-transport tests, not board results.
- No daemon is silently flashing boards or accepting later phases. RA still
  needs a concrete programmer/debugger backend; ESP validation is not itself
  a flash tool. Trace-aware N6 host integration is also not yet complete.

## Actual electrical observation and experiment boundary

The entries below are historical and superseded by the latest N6 section.

2026-09-26 reconnect update: user reports the requested JP2/USB correction
complete, but the workstation has no ST-LINK enumeration across 20 checks.
No new Vref, RAM load or inference. Asked whether the PC cable is at CN6;
do not interpret this as another measured supply collapse. Fixed offline
model/stage bundle validation remains passing.
[Reconnect evidence](../../results/ppk2_n6_bringup_20260925_nAivHM/STANDALONE_RECONNECT_20260926_02.md).

2026-09-26 latest: user reports PPK removed, standalone external supply and
workstation attached. ST-LINK enumerates; actual Vref indication 0.18167–0.18327 V.
User confirmed all JP2 pairs open. Unpowered connection of only 3–4/USB_SNK
is the pending correction, not yet done. No RAM deployment attempted.
Fixed bundle CLI checked 1024 rows and host suite passed 76 tests/47 subtests.
[Standalone preflight](../../results/ppk2_n6_bringup_20260925_nAivHM/STANDALONE_PREFLIGHT_20260926_01.md).
The earlier electrical paragraphs below are historical, not current topology.

Post-failure update: the user unplugged both STM32 USBs; no ST-LINK enumerated
and PPK fresh Ampere metadata plus OFF-only command completed (`7da67c / 0`).
No new ON or model deployment. A standalone CN18 supply diagnostic with PPK
isolated is proposed, not connected; changing JP2 requires resolving the
user's unchanged-pin constraint. [Current unplug state and proposal](../../results/ppk2_n6_bringup_20260925_nAivHM/USB2_POST_FAILURE_UNPLUG_01.md).

Latest: the user retained original JP2 1/2 wiring and moved USB cables to
USB2 sockets. One new fifth ON diagnostic ran (`3a3986 / 0`, 300032 frames):
nonzero current ranges still appeared only for nominal 1.02 ms; the final
two seconds were near zero. No sustained model operation established.
OFF/STOP writes completed; no firmware or model changed. Saved-only review
plus a separate NumPy cross-check confirmed these observations. The PPK USB
reconnect was after cleanup. The user subsequently confirmed fresh steady-red
LD3, supporting ST-LINK supply protection shutdown; no exact trip current or
unique cause is established. [Post-test LED follow-up](../../results/ppk2_n6_bringup_20260925_nAivHM/USB2_LD3_RED_FOLLOWUP_01.md).
[USB2-port experiment and adversarial review](../../results/ppk2_n6_bringup_20260925_nAivHM/USB2_FIXED_AM_REVIEW_01.md).
The proposed JP2 3/4 and charger connection did not occur according to the
latest user instruction. The following fourth-capture section is historical.

The fourth actual three-second Ampere-Meter diagnostic completed, with
300032 raw samples. Higher current ranges appeared only for approximately
1.02 ms; the final two seconds were near zero. The collector did not end the
ON interval early. This does **not** establish sustained operation of the
measured N6 path. No during-ON voltage was recorded. In a subsequent explicit
follow-up, the user reported **LD3 steady red**. ST defines this as detected
overcurrent with automatic shutdown of the ST-LINK target supply; it supports
protection activation but does not establish the initiating cause or a 1 A
overload. See the [new LED observation and primary-source review](../../results/ppk2_n6_bringup_20260925_nAivHM/LD3_RED_FOURTH_CAPTURE_FOLLOWUP.md).
USB enumeration of ST-LINK alone is not target-power or model-execution proof.

See [current hardware evidence](../../results/ppk2_n6_bringup_20260925_nAivHM/CURRENT_STATUS.md)
and [independent raw analysis](../../results/ppk2_n6_bringup_20260925_nAivHM/FIXED_AM_OBSERVATION_01_INDEPENDENT_REVIEW.md).
The fifth ON is only the new short diagnostic described above; no target RAM
load, flash or model inference occurred. Latest enumeration observed ST-LINK
and PPK2, not RA/ESP.

A later probe-only refresh (`6f4721 / 0`) read three ST-LINK F7 replies,
approximately 3.19/1.59/1.59 mV, without target attach/reset or PPK commands.
This followed the last commanded PPK OFF; it is **not** a new powered-load
failure, not VIN and not the missing during-ON measurement. Raw replies,
source identities, seven decoder controls and four independent fake-USB
controls are recorded in the [refresh receipt](../../results/ppk2_n6_bringup_20260925_nAivHM/PROBE_VREF_REFRESH_01.json).

Before accepting formal energy: preserve exact firmware/model identity;
validate each board numerically; demonstrate its execution backend; establish
the measured rail and its voltage/time basis; align inference windows with
verified marker acquisition; reject clipping/drops/partial captures; record
idle and active conditions separately. Do not substitute nominal USB 5 V
for an unmeasured downstream rail or report current alone as energy.

## Preservation and research limits

Do not move/delete pinned historical build or result paths: that would break
their provenance. Correct candidates are selected by the explicit links
above; failed/stale evidence stays labeled, not silently promoted or erased.
The broader retained research remains 440 neural fits, 84 tree fits and 22
original exports, with **4/11 FP32 and 1/11 QDQ accepted**. Negative exports,
additional candidates and board preparation are separate denominators.
There is no new accepted three-platform latency/power table or paper result.
