# EM01 component: RM01 logic (em01.c, derived) + the same model path as RA01/RM01.
set(FW "${CMAKE_CURRENT_LIST_DIR}/..")
set(REPO "${FW}/../../..")
set(PQ "${REPO}/tools/board_deployment/portable_qdq")
set(MODEL_C "${REPO}/results/portable_qdq_native_20260925_01/model_sources/model.c")
set(VECTORS_C "${CMAKE_CURRENT_LIST_DIR}/generated/rm_vectors.c")
idf_component_register(SRCS "app_main.c" "${FW}/em01.c" "${PQ}/portable_qdq.c" "${MODEL_C}" "${VECTORS_C}"
    INCLUDE_DIRS "${FW}" "${PQ}"
    REQUIRES esp_driver_gpio esp_hw_support spi_flash freertos)
# Same strict floating-point flags as the RA01/RM01 build (no fast math, no FMA contraction).
target_compile_options(${COMPONENT_LIB} PRIVATE -O2 -fno-fast-math -ffp-contract=off -fexcess-precision=standard)
set_source_files_properties("${PQ}/portable_qdq.c" "${MODEL_C}" "${VECTORS_C}"
    PROPERTIES COMPILE_OPTIONS "-std=c11")
