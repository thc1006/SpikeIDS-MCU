# USB_SNK series-measurement rewiring preparation

## Observed / performed in this turn

- The user reported unplugging the two STM32 USB cables, as requested after
  steady-red LD3. No jumper/lead move or charger connection is yet reported.
- Actual `lsusb` in `da1458 / 0` showed PPK2 and no ST-LINK. This corroborates
  probe disconnection, not complete electrical isolation or lead continuity.
- Metadata query `d52741 / 0` retained `PPK_BEFORE_CABLE_MOVE_01.json` for exact
  PPK serial `F4728E9B55E0`, mode `1` (Ampere Meter). Metadata `VDD=4000`
  remains a stored field, not an AM regulation setting or VIN measurement.
- A second fresh exact-serial metadata query plus **OFF only** completed in
  `75317b / 0`: commands `19`, `0c00`; OFF write count 2 and serial flush
  completed. No ON, sample start, mode/voltage change or target debug occurred.
  This is completed host-command evidence, not independent electrical OFF
  acknowledgement. The metadata helper SHA before/after was
  `e35b4697f974c74c04ed97965a9df1d9f18ea19a046d3982f0ec59e625f41b13`.
  The successive queries observed different tty names (`ttyACM1`, `ttyACM0`),
  so subsequent tools must re-enumerate by exact serial, never retain a tty
  assumption. No cause for the tty change is inferred.

## Proposed, NOT recorded as performed

With the two STM32 USB sources disconnected:

| Lead | Original reported endpoint | Proposed endpoint |
|---|---|---|
| PPK VIN | JP2 pin 1, ST-LINK source | JP2 pin 3, USB_SNK source |
| PPK VOUT | JP2 pin 2, board 5 V | JP2 pin 4, board 5 V |
| PPK GND | CN8 pin 6, GND | Unchanged |

Do not fit JP2 shunts on any pair: a 3–4 shunt would bypass the meter and a
1–2 shunt would reconnect the alternate source to the load. Pin numbering is
by board labels/source drawing, not an assumed left/right viewing direction.
Retain the previously selected developer boot mode, SW1/BOOT1=H,
SW2/BOOT0=L. This does not itself recover power or prove boot success.

After the lead move, the intended supply is the user's previously reported
charger with a 5 V / 3 A output option through an ordinary C-to-C cable to
**CN18 / USB1**. CN6 / ST-LINK returns to the workstation A-to-C connection
for ST-LINK power/debug communication; it no longer supplies the selected
JP2 load through pins 1–2. Do not add a PD trigger or request 9/12/20 V.
PPK USB connections remain connected, mode stays Ampere Meter, and the host
does not turn its output ON until the changed wiring has been reported complete.

## Primary-source verification and adversarial wiring review

The official **MB1939-N6570-C02** schematic's indexed POWER sheet (5/21)
explicitly places `5V_STLK` at `PIJP201`, `5V_USB_SNK` at `PIJP203`, and
`5V_VIN` at `PIJP205`, with the 2/4/6 side on the board `5V` bus. This turn
used the indexed primary-source excerpt; full-PDF fetching failed, and no
successful full schematic download/image inspection is claimed.

- [ST C02 schematic, POWER sheet](https://www.st.com/resource/en/schematic_pack/mb1939-n6570-c02-schematic.pdf)
- [ST UM3300, section 7.4.3 and figure 9: CN18/USB1 source selection](https://www.st.com/resource/en/user_manual/um3300-discovery-kit-with-stm32n657x0-mcu-stmicroelectronics.pdf)
- [Nordic PPK2 connectors: VIN external input, VOUT to DUT](https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_user_guide_connectors.html)
- [Nordic Ampere Meter wiring and USB-source example](https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/measure_current_ampere_meter.html)

Review considered reversed VIN/VOUT, the old ST-LINK pair left connected,
parallel shunts bypassing measurement, mistaken Source Meter mode, wrong
CN6/CN18 connector, and interpreting charger capability as actual current.
Charger 3 A capability does not force a 3 A load, **nor** does it upgrade the
PPK's 1 A continuous current or 0.8–5.0 V AM operating limits. The new source
has not yet been exercised with this load. It is not proven safe/accepted by
the previous path's clipped or autoranging startup trace. No voltage accuracy,
transient-current compliance or protective trip threshold is fabricated.

This is a measurement of the selected board 5 V rail **downstream of JP2**,
not isolated NPU/core energy and not the complete sum of both USB-input powers
(ST-LINK/source-side circuitry is outside that boundary). Correct wiring alone
does not establish numerical parity, marker alignment, voltage calibration or
formal energy acceptance. No fifth ON or v5 model execution occurred here.
