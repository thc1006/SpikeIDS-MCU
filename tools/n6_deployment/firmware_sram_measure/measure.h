#ifndef S7_MEASURE_H
#define S7_MEASURE_H
#include <stddef.h>
#include <stdint.h>

/* SM07M measurement control block. Separate from the frozen 512-byte SM06
 * mailbox ABI; the host finds it by ELF symbol and cross-checks the header.
 * Host writes parameters first and request_sequence last, then must not touch
 * the block until state==DONE/ERROR and response_sequence matches. */
#define S7_MAGIC UINT32_C(0x4D374D53)          /* "SM7M" */
#define S7_VERSION 1u
#define S7_MAX_ROWS 1024u
#define S7_MAX_WINDOWS 128u
#define S7_MARKER_PORT_PIN UINT32_C(0x00480008) /* 'H', pin 8 = Arduino D12 */

enum { S7_IDLE=1, S7_BUSY=2, S7_DONE=3, S7_ERROR=4 };
enum { S7_CMD_PARITY=1, S7_CMD_SCHEDULE=2, S7_CMD_PULSES=3 };
enum { S7_W_IDLE=1, S7_W_BENCH=2, S7_W_OVERHEAD=3, S7_W_PULSE=4 };
enum { S7_E_COMMAND=-101, S7_E_PARAM=-102, S7_E_INPUT=-103, S7_E_OUTPUT=-104,
       S7_E_SEQUENCE=-105 };

typedef struct {
    uint32_t kind, start_cycle, end_cycle, iterations;
    uint32_t checksum, marker_high, reserved0, reserved1;
} s7_window_t;

typedef struct {
    uint32_t magic, version, struct_bytes, state;                  /* 0x00 */
    uint32_t request_sequence, response_sequence, command;         /* 0x10 */
    int32_t error;
    uint32_t rows_in_address, rows_out_address, max_rows, marker;  /* 0x20 */
    uint32_t n_rows, bench_reps, overhead_reps, cycles;            /* 0x30 params */
    uint32_t idle_cycles, pulse_cycles, pulse_count, max_windows;  /* 0x40 params */
    uint32_t parity_cycles_total_lo, parity_cycles_total_hi,       /* 0x50 results */
             parity_cycles_min, parity_cycles_max;
    uint32_t windows_used, first_bad_row, marker_initialized, reserved; /* 0x60 */
    s7_window_t window[S7_MAX_WINDOWS];                            /* 0x70 */
} s7_measure_t;

_Static_assert(offsetof(s7_measure_t, n_rows) == 0x30, "Param offset changed");
_Static_assert(offsetof(s7_measure_t, window) == 0x70, "Window table offset changed");
_Static_assert(sizeof(s7_window_t) == 32, "Window record size changed");
_Static_assert(sizeof(s7_measure_t) == 0x70 + 32 * S7_MAX_WINDOWS, "Measure block size changed");

extern volatile s7_measure_t g_measure;
extern uint32_t g_rows_in[S7_MAX_ROWS * 41];
extern uint32_t g_rows_out[S7_MAX_ROWS * 5];
#endif
