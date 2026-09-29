/* Host simulation of one RM01 power-on (test only).
 * Time model: 1 GPT321 access = 1000 cycles (one PPK2 sample at 100 MHz / 100 kS/s),
 * one model inference = SIM_INFER_CYCLES, one DSB = 400 cycles (row copies).
 * Output: argv[1] = transitions "cycle marker activity" per line (activity =
 * inside a model inference), argv[2] = final g_rm bytes.
 * SIM_CORRUPT_CALL=<n>: flips one bit of the n-th inference output (0-based). */
#include "hal_data.h"
#include "portable_qdq.h"
#include "rm01.h"
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TICK 1000u
#define DSB_CYCLES 400u
#define SIM_INFER_CYCLES 2500000u        /* 25 ms at 100 MHz */

uint32_t SystemCoreClock = 100000000u;
sim_dcb_t sim_dcb;
sim_scb_t sim_scb = { 0x410FD214u };
sim_fcache_t sim_fcache = { 1u, 2u };
sim_system_t sim_system = { 0x21022121u, 5u, 0x2711u, 0u, 0u, 0u, 0u };   /* ICK=PCKD=/2, PLL x20 from HOCO/2 */
uint32_t sim_ofs1_sec = 0xFFFFFDFFu;
sim_port_t sim_port1;
static sim_dwt_t dwt;
static sim_gpt_t gpt = { 0, 0, 1, 0xFFFFFFFFu };
static int gpt_started = 0;
static uint64_t now;
static int level = 0, activity = 0;
static uint64_t last_change;
static FILE *trace;
static jmp_buf finished;
static long corrupt_call = -1, calls = 0;

void hal_entry(void);

static void advance(uint32_t c) { now += c; dwt.CYCCNT += c; if (gpt_started && (gpt.GTCR & 1u)) gpt.GTCNT += c; }
static void emit(void) { fprintf(trace, "%llu %d %d\n", (unsigned long long)now, level, activity); }

sim_dwt_t *sim_dwt(void) { fprintf(stderr, "DWT used\n"); exit(5); }
sim_gpt_t *sim_gpt(void) { advance(TICK); return &gpt; }
void sim_module_start(int channel) { if (channel != 1) exit(6); gpt_started = 1; }

void sim_dsb(void)
{
    const uint32_t v = sim_port1.PCNTR3;
    sim_port1.PCNTR3 = 0;
    int next = level;
    if (v & (1u << 7)) next = 1;
    if (v & (1u << 23)) next = 0;
    if (next != level) { level = next; last_change = now; emit(); }
    advance(DSB_CYCLES);
}

void sim_nop(void)
{
    advance(10);
    if (level && g_rm.telemetry_words && (g_rm.stage == RM_S_DONE || g_rm.stage == RM_S_ERROR) &&
        now - last_change > 50000000ull)
        longjmp(finished, 1);
}

void sim_pincfg(uint32_t pin, uint32_t cfg)
{
    if (pin != BSP_IO_PORT_01_PIN_07 || cfg != BSP_IO_PFS_PDR_OUTPUT) { fprintf(stderr, "bad pincfg\n"); exit(3); }
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
    emit();
    fclose(trace);
    FILE *f = fopen(argv[2], "wb");
    if (!f || fwrite((const void *)&g_rm, sizeof g_rm, 1, f) != 1) return 2;
    fclose(f);
    return 0;
}
