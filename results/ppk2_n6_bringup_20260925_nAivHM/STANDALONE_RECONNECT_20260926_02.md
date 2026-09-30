# Standalone reconnect 02: ST-LINK not enumerated

User replied `接好了` after instructions to connect only JP2 3/4/USB_SNK
while unpowered, then connect CN18 to the external source and CN6 to the
workstation. Treat this as reported completion, not visually verified wiring.
PPK remains outside this proposed standalone board topology.

## Actual checks

- Initial `lsusb` (`fd1b6d`) showed root hubs and the unrelated HID device,
  no ST-LINK or PPK2. Probe voltage helper raised
  `ValueError: Expected unique exact ST-LINK serial` **before opening USB**.
  No fresh voltage reply, target debug or write occurred. This was a compound
  shell call whose final exit was 0 due to subsequent source reads; that exit
  must NOT be described as a successful voltage query. The helper's subprocess
  return code was not separately retained.
- Read-only serial enumeration: 20 checks (indices 0–19, about 19 s), all
  `ports: []`; launch `087185`, session55159, completion `8e0e28 / 0`.
  Exit 0 here means the observation loop completed, not a connected board.
- Independent whole USB enumeration and absent `/dev/serial/by-id` in
  `039bfb` agree. Last enumeration `6029bf / 0` still showed no ST-LINK.
- Kernel log records ST-LINK device61 disconnect at 2026-09-26 08:37:50 +08:00
  and no later ST-LINK connection in the inspected interval ending around
  08:40:06 +08:00. This is not proof of cable reversal or target power loss.
- Fixed model/stage bundle offline CLI passed again (`039bfb / 0`): 1024
  rows, hardware_accessed false. Controller and backend hashes remain
  `2d2328bc8d46c762910d628a8d1c65d0c7b8e296c332ec4eccc6b07f538e1f93`
  and `ccea760c695766a23c9b9d8180f7d53b4ab33d0de266ba6817613b02fe004a5d`.

## Adversarial interpretation and next observation

Do not carry the previous 0.18 V observation across the reported new connection.
There is **no new target-voltage measurement**. USB absence is a distinct
blocker from the earlier supply-protection and open-JP2 findings. It can arise
from the PC/data path, connector/cable/source assignment or other causes;
the exact cause is not established by software enumeration alone.

Asked the user to identify whether the workstation cable is at CN6/ST-LINK
or CN18/USB1, without moving JP2 or energized conductors. As documented by
[ST UM3300 §7.3/§7.4.3](https://www.st.com/resource/en/user_manual/um3300-discovery-kit-with-stm32n657x0-mcu-stmicroelectronics.pdf),
CN6 supplies the embedded debug USB path, and CN18 with USB_SNK is the
proposed external board supply. Do not assume a reported swap occurred.

No power command, reset, SRAM load, flash, model inference or energy
measurement was performed. The finite observation loop has finished;
there is no background job poised to flash or automatically accept a device.
