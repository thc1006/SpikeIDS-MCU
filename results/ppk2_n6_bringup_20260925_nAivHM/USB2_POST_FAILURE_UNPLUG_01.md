# After USB2 failure: user unplugged STM32, OFF-only preparation

The user answered `拔了` to the request to unplug both STM32 USB connections
without changing JP2/Dupont leads. Read-only enumeration `41561d / 0` showed
PPK2 device58 and no ST-LINK. This corroborates USB disconnection, not measured
electrical isolation of every rail. No pin move is reported or assumed.

## Actual action, independently observed external completion

OFF-only command execution `7da67c / 0` used a 10-second external timeout
with 2-second TERM-to-KILL grace. It verified the metadata helper before and
after against SHA-256
`e35b4697f974c74c04ed97965a9df1d9f18ea19a046d3982f0ec59e625f41b13`, checked no
ST-LINK VID/PID serial interface enumerated, and selected only PPK serial
`F4728E9B55E0` (at `/dev/ttyACM0`, not assumed in advance).

On one exclusive serial session with TIOCEXCL, fresh GetMetadata (`19`)
reported mode `1` (Ampere Meter). After checking no unexpected tail/stream,
output OFF (`0c00`) wrote both bytes and flush completed. No ON, sampling,
mode/voltage change, debug access, reset or flash occurred. Host-write success
is not independent electrical OFF readback. Metadata `VDD:4000` is not an
AM voltage measurement or a new voltage-setting instruction.

This is not a sixth capture; the fifth raw/report/exit receipt remain unchanged.

## Next-phase review and user-choice boundary

The original JP2 1/2 path has twice shown a brief current event followed by
near-zero current in fixed-duration captures, with fresh red LD3 reported
after each. This establishes a persistent observed problem, not its unique
cause. Blind repetition or disabling protection is not a repair.

A proposed next diagnostic is **standalone board supply via CN18/USB1**, using
the user's reported 5 V / 3 A C-to-C source, with the meter temporarily out of
the load path. CN6 would remain the separate workstation debugger connection.
This requires changing the JP2 selection to USB_SNK 3/4 and isolating the
PPK VIN/VOUT leads; it is NOT authorized merely by the user's unplug report.
The user previously required unchanged pins. Ask before giving an instruction
to perform that change; no connection or new ON is recorded here.

Reason to separate this from the earlier proposal to move the meter directly
to JP2 3/4: a stronger upstream source does not qualify the PPK2 for a larger
load or prove acceptable startup current. Nordic specifies **1 A continuous
in Ampere mode**; the preceding transition/clipped traces cannot certify the
full board within that limit. Standalone board startup and model validation
would not be power-measurement acceptance or license to reinsert the meter.
Actual load/measurement suitability would still need qualification afterward.

Review constraints before a future accepted wiring change:

- No energized lead movement; both STM32 USB sources remain disconnected
  during changes and measurement leads must not become loose live inputs.
- Do not leave the STLK 1/2 path bridged while selecting USB_SNK 3/4.
- Do not wire PPK VOUT in parallel with the new source or bypass it while
  pretending to record board current.
- No Source Meter mode, PD trigger, or request for higher than the board's
  nominal 5 V source; no assumption charger capability forces 3 A into the load.
- CN18 supply must not be confused with CN6 debugger USB. A charger alone
  at CN6 is not a complete host-debug solution.
- Preserve developer boot configuration and frozen model artifacts; numerical
  validation still precedes formal timing/energy claims.
- Do not claim the stronger source fixes an unverified short or hardware fault.

Primary sources freshly checked:

- [ST UM3300 sections 7.4.2/7.4.3](https://www.st.com/resource/en/user_manual/um3300-discovery-kit-with-stm32n657x0-mcu-stmicroelectronics.pdf)
- [ST employee on USB1/CN18 and JP2 3/4](https://community.st.com/stm32-mcus-boards-and-hardware-tools-26/stm32n6570-dk-ai-demo-not-working-144566)
- [Nordic maximum admissible current](https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_max_dut_current.html)
- [Nordic AM voltage/power requirements](https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_power_supply.html)

This is a bounded engineering review, not certification of unseen wiring.
