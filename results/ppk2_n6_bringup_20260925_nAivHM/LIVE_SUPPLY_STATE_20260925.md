# Latest physical-state clarification, 2026-09-25

This is a conversation/host-observation update, not electrical acceptance.
Original raw captures and their reports have not been changed.

## User-reported state

- After pulse03 the user explicitly reported **LD3 steady red**. Earlier notes
  saying that the post-pulse03 LED was unknown are historical, not current.
- The user explicitly **did not perform** the proposed PPK-disconnection,
  JP2 3-4 shunt, and CN18 charger procedure. Do not record that proposal as an
  executed experiment or ask for its result as though it happened.
- Therefore the last reported target wiring remains the original series path:
  PPK VIN to JP2 pin 1, VOUT to pin 2, GND to CN8 pin 6; JP2 1-2 shunt removed;
  workstation USB-A-to-C to CN6. Boot switches were last reported SW1 H/SW2 L.
  This is user-reported wiring, not independently inspected continuity.
- A USB-C PD charger and C-to-C cable are available. The user corrected the
  charger current rating from 2 A to 3 A; no full label photograph or measured
  output voltage was obtained. Charger availability is not a connection record.
- The user's phrase about two micro-USB plugs may refer to both PPK USB ports;
  it must not be silently reinterpreted as a JP2 modification.

## Last command versus physical state

The last actual DUT ON was pulse03. Its cleanup attempted and completed OFF
and STOP writes. No fourth ON, reset, SWD entry, firmware load or inference was
performed in the subsequent clarification turns. Successful OFF writes are
not an independent physical switch-state measurement.

Host check `9973da`, exit 0, listed STLINK-V3 (0483:3754, bus 001 device 042)
and PPK2 (1915:c00a, bus 001 device 044). The matching process listing contained
only the check itself, not a running acquisition/programmer process.

Single read-only target-reference observation `018160`, exit 0, at
2026-09-25T01:08:51.406165+00:00:

```json
{"serial":"004000183234510E37333934","command_hex":"f7","raw_hex":"e205000002000000","reference_estimate_v":0.003187250996015936,"is_vin_measurement":false,"debug_entry":false,"reset_sent":false,"ppk_accessed":false}
```

This approximately 0.003 V target-reference estimate was obtained **after the
last commanded PPK output state was OFF**. It is not a new powered-load test,
not a measurement of the USB 5 V/VIN, and cannot establish a damaged board,
incorrect wiring, or a new supply failure. USB enumeration establishes that
the PPK controller and ST-LINK communicate; it does not establish that the N6
target is currently powered through the PPK-controlled series path.

## Work that can proceed without another electrical retry

The v5 inference adapter has a real offline ARM build but lacks a validated
platform initializer/loader and on-target numerical parity. A separate minimal
RAM heartbeat/readback probe and host-side checks are being prepared offline.
It must not be labeled an NPU initializer, model execution or formal experiment.
The corrected raw collector is also undergoing offline review; it has not been
run against the board. No automatic power retry is armed.

Formal board inference, timing and energy acceptance remain false. In
particular, do not imply that changing USB cables alone closes the remaining
software prerequisites.

ST defines the reported LD3 red state as power-protection shutdown; its cause
and exact trip current/timing remain unestablished. Source:
[UM3300, power selection and LED descriptions](https://www.st.com/resource/en/user_manual/um3300-discovery-kit-with-stm32n657x0-mcu-stmicroelectronics.pdf).
