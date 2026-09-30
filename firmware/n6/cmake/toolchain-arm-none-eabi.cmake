set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
set(CMAKE_C_COMPILER arm-none-eabi-gcc)
set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)
set(CMAKE_OBJCOPY arm-none-eabi-objcopy)
set(CMAKE_SIZE arm-none-eabi-size)
# Cortex-M55 with FP + MVE (Helium). Hard float ABI.
# -mcmse: we run in the Secure state (like the OOB app) and must use the secure peripheral
# aliases; the device header selects them via __ARM_FEATURE_CMSE == 3 -> CPU_IN_SECURE_STATE.
set(CPU_FLAGS "-mcpu=cortex-m55 -mthumb -mfloat-abi=hard -mfpu=auto -mcmse")
set(CMAKE_C_FLAGS_INIT "${CPU_FLAGS} -ffunction-sections -fdata-sections -fno-common -Wall -Wextra")
set(CMAKE_ASM_FLAGS_INIT "${CPU_FLAGS}")
set(CMAKE_EXE_LINKER_FLAGS_INIT "${CPU_FLAGS} --specs=nano.specs --specs=nosys.specs -nostartfiles -Wl,--gc-sections")
