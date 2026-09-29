#ifndef RM01_H
#define RM01_H
#include <stddef.h>
#include <stdint.h>

/* RM01: autonomous FPB-RA4E1 power-measurement firmware (no host link needed).
 * Every power-on runs: settle -> 1024-row self-parity (bitwise vs embedded
 * QDQ reference) -> WIRING pulses -> SHAM null control -> calibration ->
 * 5 schedules (3 repeat + dose x2, x4) -> telemetry of this block on the
 * marker pin -> marker held HIGH (DONE). Any error skips to telemetry.
 * The block also stays in RAM for optional J-Link readback (J9 replugged). */
#define RM_MAGIC UINT32_C(0x31304D52)         /* "RM01" */
#define RM_VERSION 1u
#define RM_TEL_MAGIC UINT32_C(0x54314D52)     /* "RM1T" */
#define RM_RESULT_ADDRESS UINT32_C(0x2001C000)
#define RM_MAX_WINDOWS 256u
#define RM_ROWS 1024u
#define RM_BENCH_ROWS 16u
#define RM_HEADER_WORDS 64u                   /* header telemetered verbatim */
#define RM_WINDOW_TEL_WORDS 5u
#define RM_MARKER_PORT_PIN UINT32_C(0x0107)   /* P107 = J5-5 (Arduino D4) */
#ifndef RM_OFS1_SEC_PTR
#define RM_OFS1_SEC_PTR ((const volatile uint32_t *)0x0100A200u)
#endif

enum { RM_S_BOOT=1, RM_S_PARITY=2, RM_S_WIRING=3, RM_S_SHAM=4, RM_S_CALIB=5,
       RM_S_SCHEDULE=6, RM_S_TELEMETRY=7, RM_S_DONE=8, RM_S_ERROR=9 };
enum { RM_W_IDLE=1, RM_W_BENCH=2, RM_W_OVERHEAD=3, RM_W_PULSE=4 };   /* = SM07M kinds */
enum { RM_E_ENV=-201, RM_E_INFER=-202, RM_E_PARITY=-203, RM_E_WINDOWS=-204,
       RM_E_TIMER=-205, RM_E_PARAM=-206 };
#define RM_TIMER_ID UINT32_C(0x31545047)      /* "GPT1": GPT321 at PCLKD/1 */

typedef struct {
    uint32_t kind, start_cycle, end_cycle, iterations;
    uint32_t checksum, marker_high, phase, reserved;
} rm_window_t;

typedef struct {
    uint32_t magic, version, struct_bytes, stage;                        /* 0x00 */
    int32_t error; uint32_t error_detail, system_core_clock, fcachee;    /* 0x10 */
    uint32_t pq_env, cpuid, timer_ctrl, schedules_done;                  /* 0x20 */
    uint32_t parity_mismatched_words, parity_first_bad_row,              /* 0x30 */
             parity_outputs_fnv, parity_rows;
    uint32_t parity_cycles_total_lo, parity_cycles_total_hi,             /* 0x40 */
             parity_cycles_min, parity_cycles_max;
    uint32_t cal_bench_cycles, cal_overhead_cycles, n_rows, bench_reps;  /* 0x50 */
    uint32_t overhead_reps, cycles, idle_cycles, pulse_cycles;           /* 0x60 */
    uint32_t pulse_count, wiring_cycles, wiring_pulses, sham_cycles;     /* 0x70 */
    uint32_t sham_pulses, gap_cycles, n_schedules, windows_used;         /* 0x80 */
    uint32_t multiplier[8];                                              /* 0x90 */
    uint32_t telemetry_words, settle_cycles, timer_id, cal_checksum;     /* 0xB0 */
    uint32_t model_sha_prefix[2], vectors_sha_prefix[2];                 /* 0xC0 */
    uint32_t sckdivcr, sckscr, pllccr, pllcr;                            /* 0xD0 clock snapshot */
    uint32_t hococr, mococr, opccr, flwt;                                /* 0xE0 */
    uint32_t ofs1_sec, reserved_f4, reserved_f8, reserved_fc;            /* 0xF0 */
    rm_window_t window[RM_MAX_WINDOWS];                                  /* 0x100 */
} rm_result_t;

_Static_assert(offsetof(rm_result_t, parity_mismatched_words) == 0x30, "parity offset");
_Static_assert(offsetof(rm_result_t, cal_bench_cycles) == 0x50, "calibration offset");
_Static_assert(offsetof(rm_result_t, multiplier) == 0x90, "multiplier offset");
_Static_assert(offsetof(rm_result_t, model_sha_prefix) == 0xC0, "identity offset");
_Static_assert(offsetof(rm_result_t, sckdivcr) == 0xD0, "clock snapshot offset");
_Static_assert(offsetof(rm_result_t, window) == RM_HEADER_WORDS * 4, "window table offset");
_Static_assert(sizeof(rm_window_t) == 32, "window record size");
_Static_assert(sizeof(rm_result_t) == 0x100 + 32 * RM_MAX_WINDOWS, "result block size");

extern volatile rm_result_t g_rm;
extern const uint32_t rm_inputs[RM_ROWS * 41];
extern const uint32_t rm_expected[RM_ROWS * 5];
extern const char rm_vectors_sha256[65];
#endif
