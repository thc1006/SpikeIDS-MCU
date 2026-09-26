# Live identification / limited supply observation — 2026-09-25

This is an engineering bring-up record, not a hardware or energy acceptance.
No target-power ON, voltage change, mode change, firmware write, reset, halt,
or SWD entry was requested in this phase.

- PPK2 `1915:c00a`, serial `F4728E9B55E0`, `/dev/ttyACM0`.
- ST-LINK `0483:3754`, serial `004000183234510E37333934`, `/dev/ttyACM1`.
- USB enumeration was observed; no other PPK/STM controller was running in the
  process check. Physical lead endpoints were not photographed or measured.
- PPK2: one metadata command `19` only at 2026-09-24 23:12:07 UTC;
  saved `live_ppk2_metadata.json`. It reports `mode=1` (Ampere), `VDD=4000`
  (old source setting), not actual measurement-input voltage. Device-supplied
  coefficients and `Calibrated=0` are preserved without interpreting that flag
  as a calibration pass or failure. Serial close may re-enumerate the PPK2.
- ST-LINK: one low-level `f7` GET_TARGET_VOLTAGE command, using the inspected
  pyOCD USB transport rather than the higher-level debug initialization. Actual
  tool receipt `2490b5 / exit 0`, timestamp 2026-09-24 23:12:21.723977 UTC.
  Raw reply `e20500007b000000`, a0=1506, a1=123;
  `2*a1*1.2/a0 = 0.19601593625498007 V`. This is target-reference estimation,
  NOT a measurement of PPK2 VIN and NOT proof that the N6 board is faulty.
  The earlier malformed `uv run ... -c` invocation failed before executing the
  Python command; the corrected invocation explicitly named `python`.

## Physical boundary that remains unresolved

Reported wiring is the previously instructed JP2 STLK shunt insertion:
PPK2 VIN to JP2-1, VOUT to JP2-2, GND to board GND, two separate USB cables.
STM32 CN6 computer end is USB-A. Board is unmodified MB1939-N6570-C02.
The user already stated there is no multimeter or adjustable bench supply;
do not keep asking the same questions or infer that unplugging was performed
unless the user actually confirms it.

Nordic's specified external VIN is 0.8–5.0 V; the 5.5 V rating is for its own
micro-USB supply, not VIN. ST documents 5 V +/-5% board input and approximately
550 mA supply limit for the reported USB-A cable path. The current-limit fact
does not establish VIN <=5.0 V. We have not found a software-only measurement
of this external VIN. PPK2's old VDD setting and the ST-LINK target-reference
reading cannot supply that missing measurement. Thus target power remains
unqualified; no automatic power-on job has been armed.

Power leads alone also do not supply GPIO window evidence. LOGIC VCC/GND/Dx
must eventually be connected to an independently reviewed N6 I/O pin/domain.
JP2 insertion measures downstream board load, not isolated MCU/NPU power.

Official references:

- https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_power_supply_specs.html
- https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_max_dut_current.html
- https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/logic_port.html
- https://www.st.com/resource/en/user_manual/um3300-discovery-kit-with-stm32n657x0-mcu-stmicroelectronics.pdf

Proceeding offline is possible: decode retained transport bytes with disclosed
correction-voltage assumptions, and compile the correct v5 artifact without
opening hardware. Neither action resolves this physical boundary.
