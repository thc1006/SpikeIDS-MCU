#!/usr/bin/env bash
set -uo pipefail
export PATH="/home/thc1006/opt/arm-gnu-toolchain-13.2.Rel1-x86_64-arm-none-eabi/bin:$PATH"
ROOT=/home/thc1006/dev/SpikeIDS-MCU; ST=/home/thc1006/opt/stedgeai/3.0/Middlewares/ST/AI
TP=$ROOT/firmware/n6/third_party; HAL=$TP/stm32n6xx-hal-driver
MODEL=$ROOT/firmware/n6b/model; SRC=$ROOT/firmware/n6b/src
B=/tmp/claude-1000/-home-thc1006-dev-SpikeIDS-MCU/e287e8df-b593-44ae-b9b0-05620b77d9a7/scratchpad/n6b_fw; mkdir -p "$B"; rm -f "$B"/*.o
CPU="-mcpu=cortex-m55 -mthumb -mfloat-abi=hard -mfpu=auto -mcmse"
DEFS="-DSTM32N657xx -DUSE_HAL_DRIVER -DCORE_CM55 -DLL_ATON_PLATFORM=LL_ATON_PLAT_STM32N6 -DLL_ATON_OSAL=LL_ATON_OSAL_BARE_METAL -DLL_ATON_RT_MODE=LL_ATON_RT_POLLING -DUSE_NPU_CACHE"
INC="-I$SRC -I$MODEL -I$ST/Inc -I$ST/Npu/ll_aton -I$ST/Npu/Devices/STM32N6xx -I$TP/CMSIS_6/CMSIS/Core/Include -I$TP/cmsis-device-n6/Include -I$HAL/Inc -I$ROOT/firmware/n6b/hal_conf"
OPT="-O2 -ffunction-sections -fdata-sections"
cc(){ arm-none-eabi-gcc $CPU $DEFS $INC $OPT "$@"; }
fail=0
# app + init (npu_init/main include hal.h themselves; startup is bare)
for f in $SRC/startup.c $SRC/main_npu.c $SRC/npu_init.c; do cc -c "$f" -o "$B/$(basename ${f%.c}).o" 2>"$B/$(basename ${f%.c}).log" || { echo "FAIL $(basename $f)"; fail=1; }; done
# model
for f in $MODEL/stai_ids.c $MODEL/ids.c; do cc -c "$f" -o "$B/$(basename ${f%.c}).o" 2>"$B/$(basename ${f%.c}).log" || { echo "FAIL $(basename $f)"; fail=1; }; done
# ATON runtime (no -include)
for s in ll_aton ll_aton_cipher ll_aton_debug ll_aton_dbgtrc ll_aton_lib ll_aton_lib_sw_operators ll_aton_runtime ll_aton_util ll_sw_float ll_sw_integer ll_aton_stai_internal ll_aton_rt_main; do cc -c "$ST/Npu/ll_aton/$s.c" -o "$B/$s.o" 2>"$B/$s.log" || { echo "FAIL $s"; fail=1; }; done
# Devices (need -include)
for s in mcu_cache npu_cache; do cc -include stm32n6xx_hal.h -c "$ST/Npu/Devices/STM32N6xx/$s.c" -o "$B/$s.o" 2>"$B/$s.log" || { echo "FAIL $s"; fail=1; }; done
# HAL drivers (need -include for the def-ordering)
for s in stm32n6xx_hal stm32n6xx_hal_rif stm32n6xx_hal_cacheaxi stm32n6xx_hal_cortex stm32n6xx_hal_rcc stm32n6xx_hal_rcc_ex; do cc -include stm32n6xx_hal.h -c "$HAL/Src/$s.c" -o "$B/$s.o" 2>"$B/$s.log" || { echo "FAIL $s"; fail=1; }; done
echo "compile fails=$fail objs=$(ls "$B"/*.o 2>/dev/null|wc -l)"
echo "== link =="
arm-none-eabi-gcc $CPU -T$ROOT/firmware/n6b/linker/n6b.ld -nostartfiles -Wl,--gc-sections \
  "$B"/*.o -L"$ST/Lib/GCC/ARMCortexM55" -l:NetworkRuntime1100_CM55_GCC.a \
  --specs=nano.specs --specs=nosys.specs -lm -o "$B/n6b.elf" -Wl,-Map="$B/n6b.map" 2>"$B/link.log"
echo "link exit=$?"
