set(DEPLOY "/home/thc1006/dev/SpikeIDS-MCU/tools/board_deployment")
idf_component_register(SRCS "app.c"
    "${DEPLOY}/shared_v5/wire.c"
    "${DEPLOY}/portable_qdq/portable_qdq.c"
    "/home/thc1006/dev/SpikeIDS-MCU/results/portable_qdq_native_20260925_01/model_sources/model.c"
    INCLUDE_DIRS "${DEPLOY}/shared_v5" "${DEPLOY}/portable_qdq"
    REQUIRES esp_driver_usb_serial_jtag freertos)
target_compile_options(${COMPONENT_LIB} PRIVATE -O2 -fno-fast-math
    -ffp-contract=off -fexcess-precision=standard)
# SDK-facing app needs GNU asm keywords in Xtensa/FreeRTOS headers. Preserve
# strict C11 for the three portable arithmetic/protocol/generated units.
set_source_files_properties("${DEPLOY}/shared_v5/wire.c"
    "${DEPLOY}/portable_qdq/portable_qdq.c"
    "/home/thc1006/dev/SpikeIDS-MCU/results/portable_qdq_native_20260925_01/model_sources/model.c"
    PROPERTIES COMPILE_OPTIONS "-std=c11")
