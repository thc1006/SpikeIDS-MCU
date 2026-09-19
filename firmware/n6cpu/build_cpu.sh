#!/usr/bin/env bash
# CPU-int8 baseline firmware for the N6 M55 (Helium/MVE), NOW with the ST 800MHz clock bring-up
# (VDDCORE overdrive + PLL1 + MEMSYSCTL cache-gate). ST AI lite runtime + CM55 CPU runtime lib.
# Weights embedded (cpunet_data.c); image loaded to AXISRAM1 via pyOCD.
set -uo pipefail
export PATH="/home/thc1006/opt/arm-gnu-toolchain-13.2.Rel1-x86_64-arm-none-eabi/bin:$PATH"
ROOT=/home/thc1006/dev/SpikeIDS-MCU; ST=/home/thc1006/opt/stedgeai/3.0/Middlewares/ST/AI
TP=$ROOT/firmware/n6/third_party; HAL=$TP/stm32n6xx-hal-driver
MODEL=$ROOT/firmware/n6cpu/model; SRC=$ROOT/firmware/n6cpu/src
B=/tmp/claude-1000/-home-thc1006-dev-SpikeIDS-MCU/e287e8df-b593-44ae-b9b0-05620b77d9a7/scratchpad/n6cpu_fw
mkdir -p "$B"; rm -f "$B"/*.o
CPU="-mcpu=cortex-m55 -mthumb -mfloat-abi=hard -mfpu=auto"
DEFS="-DSTM32N657xx -DUSE_HAL_DRIVER -DCORE_CM55"
INC="-I$SRC -I$MODEL -I$ST/Inc -I$ROOT/firmware/n6cpu/hal_conf -I$HAL/Inc -I$TP/CMSIS_6/CMSIS/Core/Include -I$TP/cmsis-device-n6/Include"
OPT="-O2 -ffunction-sections -fdata-sections"
cc(){ arm-none-eabi-gcc $CPU $DEFS $INC $OPT "$@"; }
fail=0
# app (startup is bare; main_cpu/clock_n6 include hal.h themselves)
for f in $SRC/startup.c $SRC/main_cpu.c $SRC/clock_n6.c $MODEL/cpunet.c $MODEL/cpunet_data.c; do
  cc -c "$f" -o "$B/$(basename ${f%.c}).o" 2>"$B/$(basename ${f%.c}).log" || { echo "FAIL $(basename $f)"; fail=1; }
done
# HAL drivers (need -include for the def-ordering, as in Path A)
for s in stm32n6xx_hal stm32n6xx_hal_rcc stm32n6xx_hal_rcc_ex stm32n6xx_hal_pwr stm32n6xx_hal_pwr_ex stm32n6xx_hal_cortex stm32n6xx_hal_gpio; do
  cc -include stm32n6xx_hal.h -c "$HAL/Src/$s.c" -o "$B/$s.o" 2>"$B/$s.log" || { echo "FAIL $s"; fail=1; }
done
echo "compile fails=$fail objs=$(ls "$B"/*.o 2>/dev/null|wc -l)"
echo "== link =="
arm-none-eabi-gcc $CPU -T$ROOT/firmware/n6cpu/linker/n6b.ld -nostartfiles -Wl,--gc-sections \
  "$B"/*.o -L"$ST/Lib/GCC/ARMCortexM55" -l:NetworkRuntime1100_CM55_GCC.a \
  --specs=nano.specs --specs=nosys.specs -lm -o "$B/n6cpu.elf" -Wl,-Map="$B/n6cpu.map" 2>"$B/link.log"
echo "link exit=$?"
grep -icE 'undefined|error' "$B/link.log" | sed 's/^/link errors: /'
