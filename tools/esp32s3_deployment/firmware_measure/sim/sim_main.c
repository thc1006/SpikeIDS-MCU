/* Host simulation of one EM01 power-on (test only). Time model at 240 MHz:
 * 1 timer read = 2400 cycles (one PPK2 sample), 1 inference = SIM_INFER_CYCLES,
 * 1 DSB = 960 cycles. argv[1] = transitions "cycle marker activity",
 * argv[2] = final g_rm bytes. SIM_CORRUPT_CALL=<n> flips a bit of inference n. */
#include "em01.h"
#include "portable_qdq.h"
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define TICK 2400u
#define DSB_CYCLES 960u
#define SIM_INFER_CYCLES 1200000u          /* 5 ms at 240 MHz */
uint32_t sim_cpu_hz = 240000000u;
static uint32_t ccount;
static uint64_t now;
static int level = 0, activity = 0;
static uint64_t last_change;
static FILE *trace;
static jmp_buf finished;
static long corrupt_call = -1, calls = 0;
void hal_entry(void);
static void advance(uint32_t c) { now += c; ccount += c; }
static void emit(void) { fprintf(trace, "%llu %d %d\n", (unsigned long long)now, level, activity); }
uint32_t sim_cycles(void) { advance(TICK); return ccount; }
void sim_marker(int high) { if (high != level) { level = high; last_change = now; emit(); } }
void sim_dsb(void) { advance(DSB_CYCLES); }
void sim_nop(void)
{
    advance(10);
    if (level && g_rm.telemetry_words && (g_rm.stage == RM_S_DONE || g_rm.stage == RM_S_ERROR) &&
        now - last_change > 120000000ull)
        longjmp(finished, 1);
}
void sim_snapshot(volatile rm_result_t *r)
{
    r->psram_enabled = 0; r->chip_info = 9u | (2u << 8) | (2u << 16);
    r->apb_hz = 80000000u; r->xtal_hz = 40000000u; r->cpu_hz_clk = 240000000u; r->reset_reason = 1u;
    r->marker_gpio = EM_MARKER_GPIO; r->tick_hz = 100u; r->core_id = 0u; r->flash_bytes = 16u * 1024u * 1024u;
    r->idf_version = (5u << 16) | (4u << 8) | 4u;
    r->cpu_per_conf = 2u | (1u << 2); r->sysclk_conf = 1u << 10;
}
int sim_pq_infer(const pq_model *m, const float *in, size_t ni, float *out, size_t no)
{
    const int rc = pq_infer(m, in, ni, out, no);
    activity = 1; emit();
    advance(SIM_INFER_CYCLES);
    if (calls++ == corrupt_call) { uint32_t w; memcpy(&w, out, 4); w ^= 1u; memcpy(out, &w, 4); }
    activity = 0; emit();
    return rc;
}
int main(int argc, char **argv)
{
    if (argc != 3) return 2;
    const char *c = getenv("SIM_CORRUPT_CALL");
    if (c) corrupt_call = atol(c);
    trace = fopen(argv[1], "w");
    if (!trace) return 2;
    emit();
    if (!setjmp(finished)) { hal_entry(); return 4; }
    emit(); fclose(trace);
    FILE *f = fopen(argv[2], "wb");
    if (!f || fwrite((const void *)&g_rm, sizeof g_rm, 1, f) != 1) return 2;
    fclose(f);
    return 0;
}
