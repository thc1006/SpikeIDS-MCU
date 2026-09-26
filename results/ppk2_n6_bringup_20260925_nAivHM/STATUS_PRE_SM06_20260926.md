# Current bring-up status — 2026-09-26

## Current:SM04 run05 still fails;remaining NPU divergence localized

All1024rows completed;297/5120 logits fail on81rows,0argmax disagreements.
No acceptance/power result. Signed16 and first Conv/Cast repairs are now
implemented;actual mapping7HW+32SW,three later dense NPU ops retained.
46-stop diagnostic of first failing row2656 shows first layer/QCFS exact,
then second NPU dense2values off by1;one crosses QCFS threshold. Independent
saved review and11 tamper controls agree. Next:wider NPU accumulator path
and original requantization require new implementation/review/hardware proof.
CPU halted,PPK absent,no automatic power capture/retry armed.
[Latest full evidence/review](N6_SRAM_ATTEMPT_20260926_05_REVIEW.md).
All sections below are historical and do not supersede this result.

## Latest: runtime repaired; full run fails; signed16 dequant defect localized

SM02 additive runtime repair is built/deployed; actual run03 completed all1024
rows but failed5103/5120 logits and497 classifications under unchanged policy.
Original failure records preserved, no accepted power/latency/inference result.
Five actual hardware-breakpoint observations of original row20 show input,
quantization and first NPU arithmetic correct, followed by24/41 wrong CPU
dequant values. Signed16 bytes misread as signed8 reproduce every output word;
installed ST3.0 wrapper source corroborates the mismatch. Separate saved NumPy
and scalar checks agree. Full combined preflight181 tests/47 subtests passed.

CPU halted, PPK removed, standalone CN18 supply and JP2 3/4 remain the reported
setup. Next is an additive reviewed width/zero-point compatibility repair,
then full original-vector validation; no background retry/power run is armed.
[Actual evidence and adversarial phase review](N6_SRAM_ATTEMPT_20260926_03_REVIEW.md).

## Earlier: reconnect works; actual model load, open runtime-init defect

Exact ST-LINK detected; three Vref estimates 3.270–3.275 V (`e74777 / 0`).
Two actual SRAM load/readback attempts now exist. First failed before ACK
on FP mode; separately reviewed explicit RMode correction succeeded on the
second. Second passed model init and committed row ID20 once, but no reply
within five seconds (`69ac91 / 1`). No accepted row or energy result; CPU halted.

Halted diagnosis found the first hardware epoch waiting with global NPU
clock and bus-interface controls disabled. Both S6 and trace firmware omit
the separate global `stai_runtime_init()` call. Repair/rebuild/new host binding
is the next phase; it has not yet been implemented or deployed. No extra
wiring action or third attempt is currently requested/armed. PPK remains out.
[Full negative evidence, adversarial review and next phase](N6_SRAM_ATTEMPT_20260926_02_REVIEW.md).

The following sections are retained history, not the present USB/Vref state.

## Latest update — 2026-09-26: PPK removed, JP2 open

Later reconnect report: user says the instructed JP2 3/4 and USB setup is
complete, but ST-LINK no longer enumerates. Twenty read-only serial checks
and whole USB enumeration show no probe; kernel last disconnect 08:37:50
+08:00, no later connection through the inspected 08:40 interval. No new
voltage measurement or target write. Asked which board port the workstation
cable occupies; do not reuse the earlier 0.18 V as a current reading.
[Reconnect observation](STANDALONE_RECONNECT_20260926_02.md).

The following describes the preceding open-JP2 observation:

User connected standalone external supply and workstation with PPK2 removed.
ST-LINK enumerates, but three actual probe Vref estimates were only
0.18167–0.18327 V (`9c05b1 / 0`). User then confirmed **all JP2 pairs open**.
Connecting only JP2 3–4 / USB_SNK while fully unpowered is the next physical
correction; completion is NOT yet reported. No target debug or RAM load.
Frozen model/stage bundles and 1024 rows passed offline checks; host suite
passed 76 tests and 47 subtests. See
[standalone preflight and exact next wiring](STANDALONE_PREFLIGHT_20260926_01.md).
The open JP2 after meter removal is a new topology issue, not proof of the
cause of the earlier PPK-connected overcurrent events.

## Earlier update: USB2 sockets with original JP2 pins retained

Subsequent user update: both STM32 USB cables were unplugged. Enumeration
showed no ST-LINK (`41561d / 0`); fresh exact-serial PPK metadata verified
Ampere mode and OFF-only write/flush completed (`7da67c / 0`). No sixth ON.
Pin wiring remains unchanged. Standalone CN18-powered board diagnosis with
PPK temporarily isolated is proposed, **not executed or yet agreed**; it
requires a JP2 selection change, so the user's prior unchanged-pin constraint
must first be resolved. [Unplug/OFF receipt and next-phase review](USB2_POST_FAILURE_UNPLUG_01.md).

The user explicitly did not change the pin wiring, moved USB cables to USB2
sockets, and requested a new test. One fifth actual ON observation completed
(`usb2_fixed_am_observation_01`, `3a3986 / 0`): 300032 raw frames, host interval
3.000658645 s. Nonzero current ranges still lasted only nominal 1.02 ms and
the final two seconds decoded near zero. OFF/STOP host writes completed;
no model load, inference or accepted energy. Saved-only adversarial review
and a separate vectorized cross-check reproduced the waveform conclusion.
The logged PPK reconnect occurred after capture cleanup, not during the early
current event. The user has now explicitly confirmed **fresh steady-red LD3**
after this USB2 test. This supports ST-LINK supply protection shutdown, not a
unique cause, exact trip current or board damage. See the
[new LED follow-up and limits](USB2_LD3_RED_FOLLOWUP_01.md).
See [USB2 outcome and review](USB2_FIXED_AM_REVIEW_01.md).

The proposed JP2 3/4/charger rewiring below remains **unperformed**. Original
JP2 1/2 is the current user-reported topology; no automatic sixth ON is armed.

## Previous update: actual fourth ON observation and three-platform deployment

This section is historical where superseded by the USB2 update above.

- **Later user update: both STM32 USB cables have been unplugged.** ST-LINK
  no longer enumerated; PPK2 remained identifiable by serial. Fresh metadata
  verified Ampere Meter and an OFF-only command completed (`75317b / 0`).
  The proposed next wiring moves PPK VIN/VOUT from JP2 1/2 to 3/4 for CN18
  USB_SNK power, retaining the series meter and no JP2 shunt. This move and
  charger connection are **not yet reported complete**. See the
  [rewiring preparation and limits](USB_SNK_REWIRE_PREPARATION_01.md).
- **New user follow-up: LD3 is steady red after the fourth capture.** Official
  ST definitions identify detected overcurrent and automatic target-power
  shutdown on the ST-LINK supply path. This supports protection activation,
  but not its unique initiating cause, exact trip time, board damage or a
  measured 1 A overload. [Observation and source review](LD3_RED_FOURTH_CAPTURE_FOLLOWUP.md).
  No recovery rewiring or fifth ON has been reported/performed by this update.
- A fourth ON diagnostic actually completed: `fixed_am_observation_01`,
  external completion `c59d4e / 0`, 300032 raw samples across a nominal three
  seconds. OFF and STOP host writes completed; not electrical readback.
  [External execution receipt](FIXED_AM_OBSERVATION_01_EXIT.json).
  Initial independent saved decoding observed higher current ranges for about
  1.02 ms, followed by range0; the last two seconds were near zero. This is not
  evidence of sustained model operation. During-ON voltage was not recorded;
  the subsequent user-reported red LD3 now supports protection shutdown, but
  the exact initiating cause is not established.
- The new internal-SRAM model firmware and platform initializer both have real
  ARM ELF/BIN builds and independent saved reviews. Use `firmware_sram` and
  `platform_stage_actual_03`, NOT the old external-memory `firmware_v5` payload.
  The fixed host controller now checks both bundles offline and implements
  backup/load/readback, initialization, FP checks and all 1024 complete rows.
  [Executable controller and limits](../../tools/n6_deployment/host_sram/README.md).
  No real target SRAM load or NPU inference has yet occurred.
- RA4E1 and ESP32-S3 use the same selected QDQ model, not old CAN weights.
  Their portable C candidate completed one actual native 1024-row experiment;
  all 5120 output words matched the frozen reference bit-for-bit. Independent
  root saved review `651dd6 / 0` confirmed it. RA4E1 subsequently cross-built
  successfully (37 commands, 123120-byte BIN); root saved review `7a2127 / 0`
  checked ELF/BIN/HEX and all pins. ESP32-S3 candidate03 now passed the complete
  v2 pipeline (`69b94f / 0`, 9 commands), producing app/bootloader/partition
  images. Independent root saved review `0b4392 / 0` checked 28 source pins,
  843 artifact pins, 48 archives, precise RTC and numerical compile flags.
  Candidate02's wrapper exit 1 remains preserved, not reclassified. Neither
  board ran inference. Current entry: [three-board status](../../tools/board_deployment/STATUS.md).
  [Three-platform plan](../../tools/board_deployment/THREE_PLATFORM_PLAN.md),
  [independent native review](../../tools/board_deployment/portable_qdq/ROOT_SAVED_REVIEW.md).
- N6's generated model has 8 hardware, 1 hybrid and 31 software epochs. Actual
  NPU execution still needs board evidence. No NPU-only latency, calibrated
  clock or model energy number has been accepted. The full research export
  gate remains 1/11 QDQ and 4/11 FP32, not all models validated.
- Additive NPU tracing now compiles into two ARM objects; 38 host controls
  passed. Root found/fixed handling of STAI's post-run reset callbacks. It is
  now linked into a separate new diagnostic SRAM firmware: actual build
  `ec39e3 / 0`, 67 commands, 80268-byte BIN, all five PT_LOAD segments.
  Root independent saved review `38a001 / 0` checked 291 input/256 artifact
  pins, ELF/BIN and actual linked main call ordering. The original frozen S6
  remains unchanged; the new trace ABI is deliberately rejected by the old
  host. Trace-aware host integration and hardware execution remain pending.
- RA/ESP full-vector host logic and transports passed a combined 59 tests plus
  28 subtests (`691f85 / 0`), including failure controls. These are offline/fake
  transports and C wire stubs, not board results. See the
  [host implementation](../../tools/board_deployment/host_v5/README.md) and
  [root artifact review](../../tools/board_deployment/ROOT_ARTIFACT_REVIEW.md).

The new electrical observation must be resolved before a long powered board
validation; firmware work continues independently. No fifth ON, flash or
debug session has been performed by this update.

The later [probe-only Vref refresh](PROBE_VREF_REFRESH_01.json) completed
`6f4721 / 0`: three raw ST-LINK F7 replies indicated approximately
3.19/1.59/1.59 mV after the last commanded PPK OFF. No PPK command, debug
attach, target reset or power toggle occurred. This is not a new powered-load
failure or a during-ON voltage measurement; it does not diagnose the earlier
current collapse. The low-level USB interface was opened and closed normally.

## Earlier updates (superseded where conflicting)

> Latest: after a further user-reported USB reconnect and added CN18 computer
> cable, the serial ports exchanged tty numbers. The pre-ON f7 reference was
> approximately 0.190 V; it does not measure PPK VIN or establish a powered-load
> fault. No new LED state was reported. The updated raw collector passed 116
> offline tests, but independent electrical preflight has **not approved a new
> ON**; see [reconnected preflight and outcome](RECONNECTED_CAPTURE_PREFLIGHT.md).
> No fourth capture or v5 board inference has run. Exact-model internal-SRAM
> generation completed at the ST child level (exit 0) but the wrapper rejected
> a cache-descriptor syntax assumption (exit 1); the retained output is under
> a separate saved-only review that subsequently passed (30d3fe / 0), not
> on-board or energy acceptance. Original FAILED remains; no compiler retry.
> [Selected model identity](SELECTED_MODEL_IDENTITY.md) now records actual
> checkpoint tensor hashing and an independent 1,024-row QDQ CPU replay: all
> 5,120 reference logits bitwise equal, without modifying original artifacts.

> Earlier physical-state correction: the user **did not execute** the proposed
> CN18 charger/JP2 3-4/PPK-removal procedure. Original series wiring remains the
> last reported topology, and post-pulse03 LD3 was reported steady red. The
> subsequent approximately 0.003 V reference read followed the last commanded
> PPK OFF; it is **not a new powered-load failure**. See
> [latest physical-state clarification](LIVE_SUPPLY_STATE_20260925.md).
> Offline loader/probe preparation is separate from formal board acceptance.

> Later update: the user selected HL and reconnected CN6. One additional
> diagnostic was software-aborted; there are now three retained negative
> pulses, not three proven hardware failures. See
> [the policy correction and third-pulse findings](POWER_DIAGNOSTIC_POLICY_REVIEW.md)
> and [DEV_BOOT preflight](DEV_BOOT_RECONNECT_PREFLIGHT.md). No fourth ON is
> armed. The earlier next-gate request for a USB-C source is not a mandatory
> requirement; existing A-to-C was retained for the third diagnostic.

## Historical snapshot — after pulse02, before pulse03

The remainder of this file preserves the earlier snapshot, including its
pulse count and proposed next gate. For the current count and next actions,
use the later update above and the linked policy review, not this old section.

Updated after the user's direct report that **LD3 is steady red**, received
after pulse02. This supersedes the earlier `STATUS.md` snapshot. Original
captures, failures, source hashes and execution receipts remain unchanged.

## Hardware: NOT ACCEPTED

Two bounded Ampere-mode diagnostics actually ran. Both returned exit 1;
neither completed the intended three-second test. No third pulse, automatic
retry, flash, reset, SWD entry or v5 inference has been performed in this phase.
OFF and sampling STOP writes completed on both runs. Command completion is
not electrical switch readback or proof that all board rails are isolated.

| Observation | Supported interpretation | Not established |
|---|---|---|
| Pulse01: decoded 1.005119887 A on the first highest-range sample | Software's conservative single-sample 700 mA cutoff fired | True 1 A load, sustained overload, normal startup or damage |
| Pulse02: range0 throughout retained data, approximately zero current; target-reference estimate 0.003187251 V before/during/after | No normal powered target was observed; reference guard stopped the test | Which component or connection caused the loss of power |
| User reports **LD3 steady red** after both tests | ST defines this as detected overcurrent with automatic target-power shutdown | Trip time, exact trip current, fault-free wiring or damaged board |

The LED observation supplies independent physical evidence for the ST-LINK
power-protection state. It was not photographed or sampled synchronously with
either pulse. It supports protective shutdown as an explanation for pulse02,
but cannot identify the trigger: limited USB budget, inrush, load, wiring or
another fault remain to be distinguished. No circuit-level latch mechanism is
claimed; the exact C02 schematic download was unsuccessful.

ST UM3300 section 6.1 explicitly warns that USB-A to USB-C supply is limited
to around 550 mA, close to this board's consumption; adding the camera module
can prevent startup. The user confirmed a computer-end USB-A connector in a
USB 3.0 port. That does not establish the higher USB-C current advertisement.
This known limitation is relevant, but not proof it is the sole fault.

The PPK2 Ampere-mode specification is **1 A continuous**. A different source
with a higher advertised capacity would not increase that instrument rating
and is not authorization to pass its full available current through PPK2.
The program's 700 mA stop remains a conservative software policy, not an
instrument overload flag or hardware current limiter. No cutoff was raised.

USB nominal 5 V is an unmeasured correction assumption; metadata `VDD: 4000`
is not the measured Ampere-mode input voltage. A multimeter is not imposed as
a universal prerequisite to every USB-powered diagnostic, but voltage and
current uncertainty must remain explicit for any later quantitative result.

## Retained measurement evidence and reviews

- [Pulse01 findings](POWER_PULSE_01_FINDINGS.md): raw 20,480 B, 5,120 frames;
  tool `3b18b9`, exit 1. Only a short startup fragment was retained.
- [Official-decoder crosscheck](ACTUAL_PULSE_ORACLE_REVIEW.md): all 20,480
  compared binary64 values agree across two coefficient and two filter
  policies. Full filtered maximum is approximately **0.84561 A**, not the
  0.01495 A replacement value of the first range4 sample. This verifies
  arithmetic, not physical current accuracy.
- [Pulse02 report](power_pulse_02/report.json) and
  [observed execution](power_pulse_02_execution.json): tool `85a957`, exit 1;
  149,504 B / 37,376 retained frames including stopped-stream drain.
  Raw SHA-256 `ed084a0e12abc0b566965d17e466a980cb57bf247430a7940bd452c1e8c73ada`;
  report SHA-256 `3e0413c17c5706fd8396906577dcde8609b5f6a67dfa6ed84d2b29ea0c3f1762`.
- Independent saved-only pulse02 check `1d9957`, exit 0: all range0, no
  visible modulo-counter gap, independently reproduced near-zero current,
  three raw target-reference replies, and exact source/raw/receipt binding.
  A passing evidence check does **not** turn the diagnostic into a pass.

## Firmware: actual offline build and independent review completed

The new v5 adapter has a real linked ARM ELF; the old statement that no ARM
binary exists is superseded. Build03 completed with tool `c9e7aa`, exit 0:
62 recorded commands, including 23 ARM C compilations, all returned 0.

- [Author review](../../tools/n6_deployment/firmware_v5/BUILD_REVIEW.md).
- [Independent review](../../tools/n6_deployment/firmware_v5/INDEPENDENT_BUILD_REVIEW.md):
  full hashes of 237 artifacts, original stat checks for 220 inputs, full
  hashes of seven direct sources; empty undefined-symbol output; ELF/BIN
  consistency; startup FP/MVE ordering; memory layout and mailbox inspection.
- ELF SHA-256 `caa57e5b8749acfe2a65ff269cb49084a5832af2c863b3320b3cbb7526851ec2`.

This is a **RAM adapter artifact, not a ready-to-flash boot image**. Platform
initialization/loader, physical weights, cache/permissions, board numerical
parity, clock validation and GPIO-tagged energy remain unproved. Generated
execution is mixed CPU/NPU (8 HW + 1 hybrid + 31 SW epochs), not all-NPU.
No paper energy result or hardware acceptance follows from successful linking.

## Next gate

1. Record available USB-C source/cable or another suitable power arrangement
   before proposing an exact recovery sequence. Do not blindly reset and retry
   the same protected path; do not bypass protection or raise the PPK limit.
2. Continue offline platform/boot-path preparation in parallel. Keep its
   engineering review separate from physical power acceptance.
3. After a reviewed power recovery and stable target observation, qualify
   board boot and all fixed numerical references before timing/energy work.

All review conclusions have finite scope. Research acceptance remains false.

## Primary sources

- [ST UM3300, sections 6.1, 7.4 and Table 8](https://www.st.com/resource/en/user_manual/um3300-discovery-kit-with-stm32n657x0-mcu-stmicroelectronics.pdf).
- [ST TN1235 Rev 7, section 7: PWR_STATUS](https://www.st.com/resource/en/technical_note/tn1235-overview-of-stlink-derivatives-stmicroelectronics.pdf).
- [Nordic PPK2 maximum DUT current](https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_max_dut_current.html).
- [Nordic explanation of range-switch peaks](https://devzone.nordicsemi.com/f/nordic-q-a/109264/ppk2-52840-measure-the-current-in-rush-current).
