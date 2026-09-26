# User observation after fourth capture: LD3 steady red

The user replied to the explicit follow-up about `fixed_am_observation_01`
(the three-second capture) that **LD3 is steady red**, not LD2. This is a
user-reported current observation, not a camera inspection or a timestamped
LED transition during the acquisition. No cable, jumper or switch movement
was reported in this reply. No new ON or target execution was performed.

## Verified interpretation

ST UM3300 Rev 1, table 8 on page 20, identifies LD3 as the STLINK-V3EC power
status LED and steady red as detected overcurrent. TN1235 Rev 7, section 7
on page 15, further states that this indication corresponds to automatic
target-power shutdown by the ST-LINK power path.

- [UM3300, table 8](https://www.st.com/resource/en/user_manual/um3300-discovery-kit-with-stm32n657x0-mcu-stmicroelectronics.pdf)
- [TN1235, section 7](https://www.st.com/resource/en/technical_note/tn1235-overview-of-stlink-derivatives-stmicroelectronics.pdf)

This adds independent operator-observed status to the retained current trace:
brief higher ranges, then a near-zero tail, despite the collector keeping its
ON interval for approximately three seconds. **Protection shutdown on the
ST-LINK supply path is now supported by the reported LED state**, rather than
inferred solely from current. The precise trip time and initiating mechanism
are not established: source budget, startup transient, wiring/short or a load
fault are not distinguished by this LED alone. Do not call this proven board
damage, a software/model failure, a measured 1 A overload, or a PPK failure.

UM3300 section 6.1 notes an approximately 550 mA limit for the CN6 USB-A-to-C
power configuration, close to this board's consumption. This is a relevant
candidate explanation, not proof of the unique cause in this setup. The
workstation port's USB 3.0 label does not change the documented board-path
limit. The official alternate source selection is USB1/CN18 via JP2 USB_SNK;
an extra CN18 cable alone is not evidence that this route was selected.

The later ST-LINK F7 refresh was taken after the last commanded PPK OFF.
Those low readings remain OFF-state observations; this new LED report does
not retroactively turn them into during-ON voltage measurements.

## Disposition

No unchanged power-cycle retry or formal energy acquisition is accepted on
the present failed supply path. Software build/host work remains separate.
Any recovery wiring change must first disconnect both STM32 USB sources and
account for the existing PPK VIN/VOUT series leads; do not simply add a charger
or shunt a selected pair while leaving an unreviewed parallel supply route.
No new recovery wiring has been recorded as performed. Original raw files,
FAILED reports, model identities and numerical tolerances remain untouched.
