# Standalone N6 preflight — 2026-09-26

## User-reported topology and actual observation

The user reports PPK2 disconnected from STM32, with STM32 connected to external
power and the workstation. Enumeration `50b977 / 0` showed ST-LINK device61
and no PPK2. No collector/programmer process was found apart from the query.
This does not establish where the external cable is plugged or JP2 continuity.

Exact-probe low-level voltage query `9c05b1 / 0` completed under a 10 s outer
timeout / 2 s kill grace. Serial: `004000183234510E37333934`.
No target debug, reset, memory write, power command or PPK command was sent.
Source hash bookends passed; USB interface open and close completed.

| Raw F7 reply | ADC reference | ADC target | Probe estimate (V) |
|---|---:|---:|---:|
| e205000073000000 | 1506 | 115 | 0.18326693227091634 |
| e205000072000000 | 1506 | 114 | 0.18167330677290836 |
| e205000073000000 | 1506 | 115 | 0.18326693227091634 |

These are three back-to-back target-reference indications, not a calibrated
VIN measurement, long-duration stability test, or proof of every rail.
No RAM deployment was attempted at this indication.

The user then explicitly confirmed **no pair of JP2 pins is connected**.
Unlike the former PPK series topology, removing the meter leaves the selected
5 V supply path open unless a JP2 pair is connected. This is a concrete missing
connection consistent with the present low target-reference indication.
It does not retroactively explain the previous PPK-connected overcurrent
events or prove this is the only possible issue after reconnection.

## Actual offline preparation completed

- Fixed controller CLI `00632a / 0`: both frozen payload bundles and all
  1024 original vector rows checked; hardware_accessed false.
- Full host_sram test suite: launch `4d03d9`, session98548, completion
  `14c9c1 / 0`, **76 tests and 47 subtests passed** in 1.84 s.
- Controller SHA-256:
  `2d2328bc8d46c762910d628a8d1c65d0c7b8e296c332ec4eccc6b07f538e1f93`.
- Backend SHA-256:
  `ccea760c695766a23c9b9d8180f7d53b4ab33d0de266ba6817613b02fe004a5d`.
- Probe-query SHA-256:
  `d8ade05ee62c638d256124058bda316883c8e2a570eb725c054509075e19dd2d`.
- No source/model/tolerance changes. Selected model remains original NSL-KDD
  QCFS primaryseed0 QDQ; SRAM S6 numerical path, not the incompatible trace ABI.

Offline passes are not on-board inference, NPU activity or power results.

## Reviewed physical correction, NOT yet reported completed

1. Disconnect both STM32 USB cables before touching JP2. Wait for board LEDs
   to extinguish; do not move a conductor on the powered header.
2. Fit only the **JP2 3–4 / USB_SNK** pair, using the matching shunt or one
   short suitable female-to-female jumper lead. No 1–2 or 5–6 bridge; do not
   attach loose meter leads to this pair or leave PPK connected in parallel.
   Identify by printed function/pin numbering, not a guessed left/right view.
3. Keep developer boot at SW1/BOOT1=H, SW2/BOOT0=L as previously selected.
4. External source with the reported 5 V / 3 A profile and C-to-C cable goes
   to **CN18 / USB1**. The workstation data cable goes to **CN6 / ST-LINK**.
   No external PD-trigger accessory or intentional >5 V setting.
5. Report completed physical change; then refresh exact-serial target voltage
   and assess readiness before any RAM write. Do not automatically launch a
   model on a timer or equate a lit ST-LINK LED with target power.

Primary sources checked this turn:
[UM3300 §7.4.1–7.4.3](https://www.st.com/resource/en/user_manual/um3300-discovery-kit-with-stm32n657x0-mcu-stmicroelectronics.pdf)
and [ST employee confirmation of USB1 with JP2 3–4](https://community.st.com/stm32-mcus-boards-and-hardware-tools-26/stm32n6570-dk-ai-demo-not-working-144566).
Full C02 schematic fetch failed this turn; no newly viewed schematic image
is claimed. No higher-power PPK path is being authorized by this correction.
