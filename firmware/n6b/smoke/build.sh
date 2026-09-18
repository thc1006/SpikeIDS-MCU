#!/usr/bin/env bash
set -uo pipefail
export PATH="/home/thc1006/opt/arm-gnu-toolchain-13.2.Rel1-x86_64-arm-none-eabi/bin:$PATH"
ST=/home/thc1006/opt/stedgeai/3.0/Middlewares/ST/AI
TP=/home/thc1006/dev/SpikeIDS-MCU/firmware/n6/third_party
MODEL=/home/thc1006/dev/SpikeIDS-MCU/firmware/n6b/model
HERE=/home/thc1006/dev/SpikeIDS-MCU/firmware/n6b/smoke
B=/tmp/claude-1000/-home-thc1006-dev-SpikeIDS-MCU/e287e8df-b593-44ae-b9b0-05620b77d9a7/scratchpad/n6b_smoke
mkdir -p "$B"; rm -f "$B"/*.o
CPU="-mcpu=cortex-m55 -mthumb -mfloat-abi=hard -mfpu=auto"
DEFS="-DSTM32N657xx -DUSE_HAL_DRIVER -DUSE_FULL_LL_DRIVER -DLL_ATON_PLATFORM=LL_ATON_PLAT_STM32N6 -DLL_ATON_OSAL=LL_ATON_OSAL_BARE_METAL -DLL_ATON_RT_MODE=LL_ATON_RT_ASYNC -DLL_ATON_SW_FALLBACK -DLL_ATON_DBG_BUFFER_INFO_EXCLUDED=1"
INCPRE="-include stm32n6xx_hal.h"
INC="-I$MODEL -I$ST/Inc -I$ST/Npu/ll_aton -I$ST/Npu/Devices/STM32N6xx -I$TP/CMSIS_6/CMSIS/Core/Include -I$TP/cmsis-device-n6/Include -I$TP/stm32n6xx-hal-driver/Inc -I/home/thc1006/dev/SpikeIDS-MCU/firmware/n6/hal_conf"
ATON_SRC="ll_aton.c ll_aton_cipher.c ll_aton_debug.c ll_aton_dbgtrc.c ll_aton_lib.c ll_aton_lib_sw_operators.c ll_aton_runtime.c ll_aton_util.c ll_sw_float.c ll_sw_integer.c ll_aton_stai_internal.c ll_aton_rt_main.c"
DEV_SRC="mcu_cache.c npu_cache.c"
fail=0
echo "== compile =="
for f in "$MODEL/stai_ids.c" "$MODEL/ids.c" "$HERE/main_smoke.c"; do
  arm-none-eabi-gcc $CPU $DEFS $INC $INCPRE -O2 -ffunction-sections -fdata-sections -c "$f" -o "$B/$(basename "$f" .c).o" 2>"$B/$(basename "$f" .c).cc.log" || { echo "  FAIL $(basename $f)"; fail=1; }
done
for s in $ATON_SRC; do
  arm-none-eabi-gcc $CPU $DEFS $INC $INCPRE -O2 -ffunction-sections -fdata-sections -c "$ST/Npu/ll_aton/$s" -o "$B/${s%.c}.o" 2>"$B/${s%.c}.cc.log" || { echo "  FAIL $s"; fail=1; }
done
for s in $DEV_SRC; do
  arm-none-eabi-gcc $CPU $DEFS $INC $INCPRE -O2 -ffunction-sections -fdata-sections -c "$ST/Npu/Devices/STM32N6xx/$s" -o "$B/${s%.c}.o" 2>"$B/${s%.c}.cc.log" || { echo "  FAIL $s"; fail=1; }
done
echo "compile failures: $fail ; objs: $(ls "$B"/*.o 2>/dev/null | wc -l)"
echo "== link =="
arm-none-eabi-gcc $CPU -nostartfiles -Wl,--gc-sections -e _start -Ttext=0x34200000 \
  "$B"/*.o -L"$ST/Lib/GCC/ARMCortexM55" -l:NetworkRuntime1100_CM55_GCC.a \
  --specs=nano.specs --specs=nosys.specs -lm -o "$B/smoke.elf" -Wl,-Map="$B/smoke.map" 2>"$B/link.log"
echo "link exit=$?"
