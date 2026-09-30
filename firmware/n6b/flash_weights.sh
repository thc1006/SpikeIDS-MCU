#!/usr/bin/env bash
# Flash the NPU weights to external XSPI2 flash @0x71000000. REQUIRES BOOT1 in DEV mode (pos 1-3).
set -euo pipefail
CP=/home/thc1006/opt/STMicroelectronics/STM32CubeProgrammer/bin/STM32_Programmer_CLI
EL=/home/thc1006/opt/STMicroelectronics/STM32CubeProgrammer/bin/ExternalLoader/MX66UW1G45G_STM32N6570-DK.stldr
HEX="$(dirname "$0")/model/ids_weights_0x71000000.hex"
"$CP" -c port=SWD mode=HOTPLUG ap=1 -el "$EL" --download "$HEX" --verify
