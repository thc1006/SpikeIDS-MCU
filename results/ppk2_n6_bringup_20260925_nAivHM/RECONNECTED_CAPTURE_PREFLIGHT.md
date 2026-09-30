# Reconnected-pair raw observation preflight, 2026-09-25

Scope: one bounded raw-current diagnostic, not model inference or formal power.
This is a different acquisition policy from the retained failed pulses 01-03.
The old 700 mA/any-range ADC cutoff is not reused or reinterpreted as a Nordic
overload specification. No manufacturer current/voltage rating is increased.

## New physical state reported by the user

The user unplugged and reconnected the two boards' computer USB cables, stated
that no JP2 shunt was added, and reported reconnecting the cables after discussing
an additional computer connection to CN18. Retain the original user-reported
PPK series wires (VIN/JP2-1, VOUT/JP2-2, GND/CN8-6), SW1 H/SW2 L. Treat CN18 as
an additional reported connection, not an enumerated/verified USB device.
JP2 3-4 remains unbridged by the last report. There is no post-reconnect LED
observation. The previous LD3 red report precedes this reconnect and must not
be silently called either cleared or still present.

Host `55eaa1 / 0`: STLINK 004000183234510E37333934 on physical USB 1-1, bus001
device047, /dev/ttyACM0; PPK F4728E9B55E0 on 1-2, device048, /dev/ttyACM1.
TTY numbering has swapped; serial identity, not tty name, selects each device.
No active acquisition/debugger was observed in the bounded process check.

Metadata-only `994213 / 0`, 2026-09-25T01:26:27.409818+00:00: mode='1' (Ampere),
VDD='4000'. VDD is not a measurement of VIN or an AM voltage regulator setting.
Only command 0x19 was issued. The actual output switch state was not queried.

Reference-only `69f2ab / 0`, 2026-09-25T01:26:27.823613+00:00: command f7,
raw e305000077000000, ratio estimate 0.1895155938951559 V. No debug entry,
reset, PPK power change or VIN measurement. This pre-ON target-reference
observation is not a powered-load failure or a wiring/boot acceptance result.

## Frozen collector and finite review

- observe_fixed.py: 7ed8fcd668f939665e638e55bb8c486ba727e90687ddf35e91a0b88acf030334
- test_observe_fixed.py: ee22da0ce63730a9cc4425e33fa85d7c4de87e627f97eb437440d9b9879efd98
- test_observe_fixed_independent.py: 4fe76c805433036df3b1e6baad156234012341d53231d309994e50bd33ea3968
- Author 41 synthetic tests: df3f97 / 0; root independent seven controls:
  b29312 / 0. The root's earlier whole-directory run was 109 tests, 09343c / 0;
  the subsequent combined run actually passed 116 tests (2902a5 / 0).

Root read the full collector and checked deadline-from-ON-attempt, delayed and
failed writes, OFF then STOP despite errors, preservation of received raw bytes,
frame/counter validation, before/after-only f7, no source-mode/voltage change,
one exact serial pair, no ON retry, and fresh-output refusal. The deadline fix
was demonstrated against delayed-write negative controls; physical timing is
not guaranteed by Python or serial write completion.

Execution proposal: a single three-second host deadline, six-second acquisition
watchdog, external timeout20s/TERM then KILL5s, fresh output directory, no SWD,
reset, model load or firmware write. This note alone does not execute or attest
electrical success. Record actual completion and post-review separately.

### Independent preflight outcome: hardware ON not approved

The independent reviewer accepted the bounded collector software but did not
approve a new ON on the current unmeasured external AM supply. Nordic specifies
external VIN no higher than 5.0 V and explicitly does not support exceeding it;
the ST 5 V input range permits up to 5.25 V. This is an unresolved compatibility
bound, **not a measurement that the present USB supply exceeds 5.0 V**, evidence
of damage, or a claim that every nominal-5 V diagnostic needs a multimeter.
Neither metadata VDD nor ST-LINK target-reference f7 measures PPK VIN.

No fourth ON was executed. The proposal above remains unexecuted. The available
software cannot certify this input voltage, move source-selection wiring, or
infer a model-specific energy window from the old startup pulses. Source Meter
4.8 V was researched only as a candidate: it would require physically isolating
VIN, qualifying its 600 mA rating and the board's low-end voltage margin; no mode
or wiring change was made. Offline exact-model compiler/probe work continues
independently of this hardware gate.

Primary clarification: [Nordic support, external supply above 5 V](https://devzone.nordicsemi.com/f/nordic-q-a/122292/ppk2-current-meter-testing-methods).

## Electrical and interpretation limits

The original CN6 source is the reported computer USB-A-to-C path. ST documents
around 550 mA for this path, with board overcurrent protection. This is a source
design constraint, not a measured exact trip current or proof of normal load.
PPK AM's continuous rating remains 1 A; USB5V is nominal and unmeasured. Added
CN18 does not select a second main-board source without changing JP2, according
to the selection architecture; incidental paths/interface current are not
characterized. PPK samples describe only its series branch.

A returned three-second raw capture is not a boot pass, calibrated current,
zero-loss proof, model-specific inference window, measured V(t), whole-board
total, NPU-only power, or paper result. No GPIO marker is connected/verified.
Do not turn near-zero samples into an efficiency claim, or after-OFF reference
into evidence that the board was unpowered throughout the ON interval.

Primary sources: [ST UM3300 sections 6.1, 7.4, 7.9](https://www.st.com/resource/en/user_manual/um3300-discovery-kit-with-stm32n657x0-mcu-stmicroelectronics.pdf),
[Nordic AM supply](https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_power_supply.html),
[Nordic maximum current](https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_max_dut_current.html).
