#!/usr/bin/env bash
# Fetch the pinned third-party sources for firmware/n6 (not vendored).
set -euo pipefail
TP="$(cd "$(dirname "$0")/.." && pwd)/firmware/n6/third_party"
mkdir -p "$TP"; cd "$TP"
clone() { local url=$1 dir=$2 ref=$3; if [ ! -d "$dir" ]; then git clone -q --depth 1 --branch "$ref" "$url" "$dir"; fi; echo "$dir: $(git -C "$dir" describe --tags --always)"; }
clone https://github.com/ARM-software/CMSIS-NN.git            CMSIS-NN            v7.0.0
clone https://github.com/ARM-software/CMSIS_6.git             CMSIS_6             v6.1.0
clone https://github.com/STMicroelectronics/cmsis-device-n6.git      cmsis-device-n6      v1.4.0
clone https://github.com/STMicroelectronics/stm32n6xx-hal-driver.git stm32n6xx-hal-driver v1.4.0
