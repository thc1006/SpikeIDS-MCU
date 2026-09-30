# USB2 sockets, unchanged pins: actual observation and adversarial review

## Outcome

The requested new observation actually ran once at 2026-09-25 15:16:27 +08:00.
The collector exited 0 (`7b3c93`, session 70798, completion `3a3986`), with
300032 frames / 1200128 bytes. This is acquisition completion, **not** board,
model, power-path or energy acceptance. Original GPU models/builds unchanged.

User explicitly retained JP2 1/2 wiring and moved USB cables to USB2 sockets.
The proposed JP2 3/4 / charger move was NOT performed according to this update.
No physical continuity or socket power capability was remotely verified.
The next requested LED observation has not yet been received at publication.

| Saved evidence | Previous fixed observation | New USB2-port observation |
|---|---:|---:|
| Raw frames | 300032 | 300032 |
| Host ON-attempt to OFF-attempt | 3.000641709 s | 3.000658645 s |
| Nonzero current-range sample indices, inclusive | 244–345 | 265–366 |
| Nonzero current-range duration at nominal 100 kHz | 1.02 ms | 1.02 ms |
| Highest-range frames | 57 | 58 |
| ADC-top frames (ALL range0) | 7099 | 7507 |
| Last ADC-top frame | 62786 | 66322 |
| Tail from sample 100000 | range0, no ADC tops, near zero | range0, no ADC tops, near zero |
| Visible modulo-64 counter discontinuities | 0 | 0 |
| Digital input bytes | all 255 | all 255 |

With explicit **assumed** 5 V correction and exact metadata coefficients,
the new tail of 200032 samples has mean -0.05736 uA, min -0.47078 uA and
max 0.32185 uA. Negative values are retained, not clamped or interpreted as
useful reverse supply current. Using assumed 0.8 V changes the mean to
-0.06156 uA. These assumptions are not measured voltage or confidence bounds.
Both policies support the descriptive near-zero tail, not powered inference.

The new unfiltered decoded maximum is 951.803–963.398 mA over those voltage
assumptions; the Nordic-filtered maximum is 786.419–798.014 mA. The unfiltered
maximum is at the first range4 sample. **Neither is a certified physical peak,
a trip-current measurement, proof of 1 A overload, or a guarantee below 1 A.**
Range0 ADC-top is not a highest-range 1 A saturation indication.

## Adversarial checks and limits

- Before execution: frozen collector/helper hashes matched; 48 tests and
  4 subtests passed (`a86600 / 0`). No source edits or relaxed limits.
- Saved-only review `75dbd5 / 0` recomputed framing, range runs, ADC tops,
  counters, command order, source bookends and both capture hashes. Its
  reproducible script is [review_usb2_saved_01.py](review_usb2_saved_01.py).
  Current conversion reused the pinned decoder, not an independent instrument.
- Decoder controls passed 52 tests and 80 subtests (`208262 / 0`).
- Separate root NumPy unpacking and vectorized unfiltered tail formula
  reproduced both tails/range counts (`8be91a / 0`), within FP roundoff.
  Filtered peak arithmetic was not independently reimplemented this turn.
- ON was not software-aborted early; OFF and STOP writes completed. Host
  command completion is not electrical acknowledgement or physical OFF proof.
- ST-LINK F7 before ON was about 0.18008 V and after OFF about 0.003187 V.
  These are target-reference estimates, NOT PPK VIN or during-ON readings.
- Sample times use the nominal device rate, not a synchronized electrical ON
  edge. Modulo-64 continuity cannot exclude losses in multiples of 64.
- No inference-marker window, no model run, no energy computation/acceptance.

## USB reconnect chronology

Read-only kernel review (`208262 / 0`, short-monotonic):

```
618288.538009  PPK device55 disconnect (after initial metadata query)
618289.465025  PPK device57 enumerates with the same serial
618338.109039  PPK device57 disconnect (after capture cleanup)
618339.035032  PPK device58 enumerates with the same serial
```

Collector ON attempt was 618335.062599045, OFF attempt 618338.063257690,
STOP completed 618338.063466405, and post-OFF F7 started 618338.104450980.
Thus the logged second disconnect follows the OFF/STOP/drain sequence,
not the early current event or the near-zero tail during the commanded ON
interval. It does not explain the early disappearance by itself. It is
consistent in timing with serial-session closure, but its cause (DTR/firmware,
USB handling, physical reconnect or otherwise) is not established. No
ModemManager log entries were returned in the inspected interval.
No kernel disconnect was recorded between ON and OFF. No claim of globally
perfect USB transport is made. Do not introduce an untested DTR change or
repeat ON merely to explain a post-cleanup reconnect.

## Conclusion and next discriminator

Changing reported host sockets did not remove the transient-then-near-zero
observation in this one test. It does not prove all USB2/USB3 sources equivalent
or uniquely identify the failing component. Ask only for **fresh LD3** after
this test; earlier red predates the user's latest reconnect. Do not load the
model on the basis of collector exit 0 or silently issue a second ON.

ST documents approximately 550 mA for A-to-C board supply and CN6 switch
current limiting in [UM3300 sections 6.1/7.4.2](https://www.st.com/resource/en/user_manual/um3300-discovery-kit-with-stm32n657x0-mcu-stmicroelectronics.pdf).
That known path limitation remains relevant, not a uniquely proven cause.
The same manual's table 8 defines steady-red LD3 as overcurrent detected;
do not confuse LD2/LD4 or infer a numeric trip level from its color.

[Execution receipt](USB2_FIXED_AM_OBSERVATION_01_EXIT.json),
[original report](usb2_fixed_am_observation_01/report.json),
[pre-execution scope](USB2_FIXED_AM_PLAN_01.md).
