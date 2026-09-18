cmake_minimum_required(VERSION 3.22)
project(spikeids_n6_bench C ASM)

set(TP ${CMAKE_CURRENT_SOURCE_DIR}/third_party)
set(CMSIS_CORE ${TP}/CMSIS_6/CMSIS/Core/Include)
set(DEV        ${TP}/cmsis-device-n6/Include)
set(HAL        ${TP}/stm32n6xx-hal-driver)
set(NN         ${TP}/CMSIS-NN)

# CMSIS-NN as a static library, MVE enabled by the -mcpu/-mfpu flags (ARM_MATH_MVEI is set
# automatically from __ARM_FEATURE_MVE in arm_nn_math_types.h).
file(GLOB_RECURSE NN_SRC ${NN}/Source/FullyConnectedFunctions/*.c ${NN}/Source/NNSupportFunctions/*.c
                          ${NN}/Source/ActivationFunctions/*.c ${NN}/Source/BasicMathFunctions/*.c)
add_library(cmsis_nn STATIC ${NN_SRC})
target_include_directories(cmsis_nn PUBLIC ${NN}/Include ${CMSIS_CORE})
target_compile_options(cmsis_nn PRIVATE -O2 -Wno-unused-parameter)

# HAL: only RCC (clock decode) — everything else is deliberately not compiled.
add_library(hal_rcc STATIC ${HAL}/Src/stm32n6xx_hal_rcc.c ${HAL}/Src/stm32n6xx_hal_rcc_ex.c)
target_include_directories(hal_rcc PUBLIC ${HAL}/Inc ${DEV} ${CMSIS_CORE} ${CMAKE_CURRENT_SOURCE_DIR}/hal_conf)
target_compile_definitions(hal_rcc PUBLIC STM32N657xx USE_HAL_DRIVER)
target_compile_options(hal_rcc PRIVATE -O2 -Wno-unused-parameter -Wno-unused-variable)

if(NOT DEFINED BUILD_ID)
  execute_process(COMMAND git rev-parse --short=8 HEAD OUTPUT_VARIABLE GIT_SHA OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
  if(GIT_SHA)
    set(BUILD_ID 0x${GIT_SHA})
  else()
    set(BUILD_ID 0)
  endif()
endif()

add_executable(n6_bench.elf src/startup.c src/bench.c src/kernels_read.c src/kernels_mlp.c)
target_include_directories(n6_bench.elf PRIVATE src ${DEV} ${CMSIS_CORE} ${HAL}/Inc ${CMAKE_CURRENT_SOURCE_DIR}/hal_conf)
target_compile_definitions(n6_bench.elf PRIVATE STM32N657xx USE_HAL_DRIVER BUILD_ID=${BUILD_ID})
target_compile_options(n6_bench.elf PRIVATE -O2 -g)
target_link_libraries(n6_bench.elf PRIVATE cmsis_nn hal_rcc)
target_link_options(n6_bench.elf PRIVATE -T${CMAKE_CURRENT_SOURCE_DIR}/linker/n6_sram3.ld
                    -Wl,-Map=${CMAKE_BINARY_DIR}/n6_bench.map -Wl,--print-memory-usage)
add_custom_command(TARGET n6_bench.elf POST_BUILD
  COMMAND ${CMAKE_SIZE} $<TARGET_FILE:n6_bench.elf>
  COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:n6_bench.elf> ${CMAKE_BINARY_DIR}/n6_bench.bin)
