#ifndef N6_SRAM_PLATFORM_INIT_H
#define N6_SRAM_PLATFORM_INIT_H
#include <stdint.h>
#include <stddef.h>

/* Portable sequence; MMIO callbacks are the only side-effect seam.
 * Secure privileged entry, exclusive ownership and powered rails are external
 * preconditions, NOT established by a caller flag or by this routine. */
#define PLATFORM_POLL_LIMIT UINT32_C(65536)
#define PLATFORM_OBSERVATIONS 192u
#define PLATFORM_SOURCE_PROFILE UINT32_C(0x00010400)
enum platform_error {
    PLATFORM_OK=0, PLATFORM_BAD_API=1, PLATFORM_ENTRY=2,
    PLATFORM_CACHE=3, PLATFORM_MEMORY_POLICY=4, PLATFORM_HSI_PROFILE=5,
    PLATFORM_RISAF_PROFILE=6, PLATFORM_LOCKED=7, PLATFORM_READBACK=8,
    PLATFORM_TIMEOUT=9, PLATFORM_OVERFLOW=10, PLATFORM_RIF_ERROR=11
};
enum platform_step {
    STEP_ENTRY=1, STEP_CONTROL_CLOCKS=2, STEP_NPU_RESET=3, STEP_RIF=4,
    STEP_HSI=5, STEP_CPU_CLOCK=6, STEP_SYS_CLOCK=7, STEP_DIVIDERS=8,
    STEP_RAM=9, STEP_CACHE_RESET=10, STEP_NPU_RELEASE=11, STEP_FINAL=12
};
typedef struct {
    uint32_t address, before, after;
} platform_observation_t;
typedef struct {
    uint32_t error, step, failed_address, failed_mask, expected, observed;
    uint32_t writes, reads, poll_reads, hsi_divider, nominal_hz, observation_count;
    uint32_t source_profile, ready_for_payload, reserved[2];
    platform_observation_t observations[PLATFORM_OBSERVATIONS];
} platform_report_t;
typedef struct {
    void *context;
    uint32_t (*read32)(void *, uint32_t);
    void (*write32)(void *, uint32_t, uint32_t);
    void (*barrier)(void *); /* target implementation MUST execute DSB + ISB */
} platform_io_t;
typedef struct { uint32_t control, ipsr, primask; } platform_entry_t;
_Static_assert(sizeof(platform_report_t)==2368, "platform report ABI");
int platform_init(const platform_io_t *, const platform_entry_t *, volatile platform_report_t *);
#endif
