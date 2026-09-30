/* RM01: autonomous FPB-RA4E1 power-measurement firmware. See rm01.h.
 *
 * Model path = Codex's RA01 candidate unchanged: portable_qdq.c + the generated
 * model.c of results/portable_qdq_native_20260925_01, same compiler flags.
 * Only the application layer differs: RA01's host mailbox is replaced by a
 * fixed, self-running schedule that mirrors the SM07M protocol used on the N6
 * (same window kinds, marker semantics, checksums and timing targets), so the
 * same offline analysis applies. The marker is P107 (J5-5, Arduino D4), which
 * has no LED or other load on the FPB-RA4E1 (UM r20ut4958eg0100 Table 7).
 *
 * Time base: GPT321 (R_GPT1, 32-bit; GPT320 is 16-bit on RA4E1, FSP
 * BSP_FEATURE_GPT_32BIT_CHANNEL_MASK=0x06) counting PCLKD/1. PCLKD and ICLK are
 * both PLL(200 MHz)/2, so one count = one CPU cycle. The DWT is NOT used: on RA
 * it stops counting while SYOCDCR.DBGEN=0 (observed 2026-09-29 on this board,
 * CYCCNT frozen with DBGEN=0), and enabling on-chip debug would put the board
 * in a non-deployment power state. Field names keep "cycle" for the SM07M
 * analysis; they are GPT321 counts. */
#include "hal_data.h"
#include "portable_qdq.h"
#include "rm01.h"
#include <string.h>

volatile rm_result_t g_rm __attribute__((section(".rm01_result"), aligned(32), used));

/* Generated FSP vectors keep the CAN ISR slot; CAN is never opened here. */
void can_callback(can_callback_args_t *args) { (void)args; }

/* Protocol constants (seconds at the nominal SystemCoreClock). Identical to the
 * N6 driver defaults: 3 repeat + dose 2x/4x schedules, 10 cycles, 16 rows,
 * 1.5 s BENCH, 1.0 s OVERHEAD, 1.0 s IDLE, 3 x 20 ms preamble, 5 x 100 ms
 * wiring pulses, 20 x 1 s sham. */
#define RM_SETTLE_MS 2000u
#define RM_GAP_MS 2000u
static const uint32_t k_multiplier[] = {1u, 1u, 1u, 2u, 4u};
#define RM_SCHEDULES (sizeof k_multiplier / sizeof k_multiplier[0])

static float g_in[41], g_out[5];

static inline uint32_t cycles_now(void)
{
    return R_GPT1->GTCNT;
}

static inline void marker(int high)
{
    R_PORT1->PCNTR3 = high ? (UINT32_C(1) << 7) : (UINT32_C(1) << (7 + 16));
    __DSB();
}

static void marker_init(void)
{
    R_BSP_PinAccessEnable();
    R_BSP_PinCfg(BSP_IO_PORT_01_PIN_07, BSP_IO_PFS_PDR_OUTPUT);   /* output, PODR=0 (LOW) */
    R_BSP_PinAccessDisable();
    marker(0);
}

static void wait_cycles(uint32_t cycles)
{
    const uint32_t start = cycles_now();
    while ((uint32_t)(cycles_now() - start) < cycles) __NOP();
}

static uint32_t ms_cycles(uint32_t ms)
{
    return (uint32_t)(((uint64_t)SystemCoreClock * ms) / 1000u);
}

static uint32_t fnv1a(uint32_t h, const uint32_t *words, unsigned n)
{
    for (unsigned i = 0; i < n; ++i)
        for (unsigned b = 0; b < 4; ++b) {
            h ^= (words[i] >> (8 * b)) & 0xFFu;
            h *= UINT32_C(16777619);
        }
    return h;
}

static uint32_t crc32_word(uint32_t c, uint32_t w)
{
    for (unsigned b = 0; b < 4; ++b) {
        c ^= (w >> (8 * b)) & 0xFFu;
        for (unsigned i = 0; i < 8; ++i) c = (c >> 1) ^ ((0u - (c & 1u)) & UINT32_C(0xEDB88320));
    }
    return c;
}

static int fail(int32_t code, uint32_t detail)
{
    marker(0);
    if (g_rm.error == 0) { g_rm.error = code; g_rm.error_detail = detail; }
    g_rm.stage = RM_S_ERROR;
    __DSB();
    return 0;
}

/* One inference: the only model call site (parity and BENCH share it). */
static int infer_row(uint32_t row, uint32_t *dst)
{
    memcpy(g_in, &rm_inputs[row * 41], 164);
    const int rc = pq_infer(&spikeids_qdq_model, g_in, 41, g_out, 5);
    if (rc != PQ_OK) return fail(RM_E_INFER, (uint32_t)rc | (row << 16));
    memcpy(dst, g_out, 20);
    return 1;
}

/* OVERHEAD: the same row copy and checksum as BENCH without the model; the
 * checksum covers the first five input words, as on the N6 (I/O alias there). */
static void overhead_row(uint32_t row, uint32_t *dst)
{
    memcpy(g_in, &rm_inputs[row * 41], 164);
    __DSB();
    memcpy(dst, g_in, 20);
}

static volatile rm_window_t *window_begin(uint32_t kind, int high, uint32_t phase)
{
    const uint32_t w = g_rm.windows_used;
    if (w >= RM_MAX_WINDOWS) { fail(RM_E_WINDOWS, w); return 0; }
    volatile rm_window_t *rec = &g_rm.window[w];
    rec->kind = kind; rec->iterations = 0; rec->checksum = UINT32_C(2166136261);
    rec->marker_high = (uint32_t)high; rec->phase = phase; rec->end_cycle = 0;
    g_rm.windows_used = w + 1;
    __DSB();
    rec->start_cycle = cycles_now();
    marker(high);
    return rec;
}

static void window_end(volatile rm_window_t *rec)
{
    marker(0);
    rec->end_cycle = cycles_now();
}

static int pulses(uint32_t count, uint32_t cycles, uint32_t phase)
{
    for (uint32_t i = 0; i < count; ++i) {
        volatile rm_window_t *rec = window_begin(RM_W_PULSE, 1, phase);
        if (!rec) return 0;
        wait_cycles(cycles);
        window_end(rec);
        wait_cycles(cycles);
    }
    return 1;
}

static int run_parity(void)
{
    g_rm.stage = RM_S_PARITY;
    uint32_t out[5], mismatched = 0, first_bad = UINT32_MAX, h = UINT32_C(2166136261);
    uint64_t total = 0; uint32_t lo = UINT32_MAX, hi = 0;
    for (uint32_t r = 0; r < RM_ROWS; ++r) {
        const uint32_t begin = cycles_now();
        if (!infer_row(r, out)) return 0;
        const uint32_t cycles = cycles_now() - begin;
        total += cycles; if (cycles < lo) lo = cycles; if (cycles > hi) hi = cycles;
        h = fnv1a(h, out, 5);
        for (unsigned k = 0; k < 5; ++k)
            if (out[k] != rm_expected[r * 5 + k]) {
                ++mismatched;
                if (first_bad == UINT32_MAX) first_bad = r;
            }
    }
    g_rm.parity_rows = RM_ROWS;
    g_rm.parity_mismatched_words = mismatched;
    g_rm.parity_first_bad_row = first_bad;
    g_rm.parity_outputs_fnv = h;
    g_rm.parity_cycles_total_lo = (uint32_t)total;
    g_rm.parity_cycles_total_hi = (uint32_t)(total >> 32);
    g_rm.parity_cycles_min = lo; g_rm.parity_cycles_max = hi;
    /* Fail closed: no energy is measured on an image that is not bit-exact. */
    if (mismatched) return fail(RM_E_PARITY, first_bad);
    return 1;
}

/* Window sizing from the firmware's own timing, as the N6 driver did on the
 * host: BENCH 4 rows x 1 rep, OVERHEAD 4 rows x 200 reps, marker LOW. The
 * loops update a volatile scratch record exactly like the schedule loops do
 * (build_02 used a register checksum that the compiler removed, so OVERHEAD
 * windows ran 1.19 s instead of 1.0 s). */
static volatile rm_window_t g_cal_scratch;

static int calibrate(void)
{
    g_rm.stage = RM_S_CALIB;
    uint32_t out[5];
    volatile rm_window_t *rec = &g_cal_scratch;
    rec->checksum = UINT32_C(2166136261); rec->iterations = 0;
    uint32_t t0 = cycles_now();
    for (uint32_t r = 0; r < 4; ++r) {
        if (!infer_row(r, out)) return 0;
        rec->checksum = fnv1a(rec->checksum, out, 5);
        rec->iterations++;
    }
    const uint32_t cb = cycles_now() - t0;
    t0 = cycles_now();
    for (uint32_t rep = 0; rep < 200; ++rep)
        for (uint32_t r = 0; r < 4; ++r) {
            overhead_row(r, out);
            rec->checksum = fnv1a(rec->checksum, out, 5);
            rec->iterations++;
        }
    const uint32_t co = cycles_now() - t0;
    g_rm.cal_checksum = rec->checksum;
    if (cb == 0 || co == 0) return fail(RM_E_TIMER, 0);
    const uint64_t f = SystemCoreClock;
    g_rm.cal_bench_cycles = cb; g_rm.cal_overhead_cycles = co;
    g_rm.n_rows = RM_BENCH_ROWS;
    /* round(1.5 s * f / (16 * cb / 4)) and round(1.0 s * f / (16 * co / 800)) */
    uint64_t br = (3u * f + 4u * (uint64_t)cb) / (8u * (uint64_t)cb);
    uint64_t orp = (50u * f + (uint64_t)co / 2u) / (uint64_t)co;
    g_rm.bench_reps = br ? (uint32_t)br : 1u;
    g_rm.overhead_reps = orp ? (uint32_t)orp : 1u;
    /* BENCH at the largest dose must not wrap the 32-bit counter. */
    if ((uint64_t)g_rm.bench_reps * 4u * RM_BENCH_ROWS * (cb / 4u) >= UINT64_C(0xF0000000))
        return fail(RM_E_PARAM, g_rm.bench_reps);
    return 1;
}

static int run_schedule(uint32_t phase, uint32_t bench_reps)
{
    const uint32_t n = g_rm.n_rows;
    uint32_t out[5];
    volatile rm_window_t *rec;
    if (!pulses(g_rm.pulse_count, g_rm.pulse_cycles, phase)) return 0;
    for (uint32_t c = 0; c < g_rm.cycles; ++c) {
        if (!(rec = window_begin(RM_W_IDLE, 0, phase))) return 0;
        wait_cycles(g_rm.idle_cycles);
        window_end(rec);

        if (!(rec = window_begin(RM_W_BENCH, 1, phase))) return 0;
        for (uint32_t rep = 0; rep < bench_reps; ++rep)
            for (uint32_t r = 0; r < n; ++r) {
                if (!infer_row(r, out)) return 0;
                rec->checksum = fnv1a(rec->checksum, out, 5);
                rec->iterations++;
            }
        window_end(rec);

        if (!(rec = window_begin(RM_W_IDLE, 0, phase))) return 0;
        wait_cycles(g_rm.idle_cycles);
        window_end(rec);

        if (!(rec = window_begin(RM_W_OVERHEAD, 1, phase))) return 0;
        for (uint32_t rep = 0; rep < g_rm.overhead_reps; ++rep)
            for (uint32_t r = 0; r < n; ++r) {
                overhead_row(r, out);
                rec->checksum = fnv1a(rec->checksum, out, 5);
                rec->iterations++;
            }
        window_end(rec);
    }
    if (!(rec = window_begin(RM_W_IDLE, 0, phase))) return 0;
    wait_cycles(g_rm.idle_cycles);
    window_end(rec);
    return 1;
}

/* Telemetry: pulse-width bits on the marker, LSB first, 1 ms period,
 * HIGH 0.25 ms = 0 and 0.75 ms = 1. Frame = 300 ms sync HIGH, 100 ms LOW,
 * RM_TEL_MAGIC, word count, header words, 5 words per window, CRC-32 over
 * all preceding frame words (little-endian bytes). */
static void tel_word(uint32_t w, uint32_t *crc)
{
    const uint32_t period = ms_cycles(1), h0 = period / 4u, h1 = 3u * period / 4u;
    *crc = crc32_word(*crc, w);
    for (unsigned b = 0; b < 32; ++b) {
        const uint32_t high = ((w >> b) & 1u) ? h1 : h0;
        marker(1); wait_cycles(high);
        marker(0); wait_cycles(period - high);
    }
}

static void telemetry(void)
{
    g_rm.stage = (g_rm.stage == RM_S_ERROR) ? RM_S_ERROR : RM_S_TELEMETRY;
    const uint32_t nw = g_rm.windows_used;
    g_rm.telemetry_words = RM_HEADER_WORDS + RM_WINDOW_TEL_WORDS * nw;
    __DSB();
    uint32_t crc = UINT32_C(0xFFFFFFFF);
    marker(0); wait_cycles(ms_cycles(RM_GAP_MS));
    marker(1); wait_cycles(ms_cycles(300));
    marker(0); wait_cycles(ms_cycles(100));
    tel_word(RM_TEL_MAGIC, &crc);
    tel_word(g_rm.telemetry_words, &crc);
    const volatile uint32_t *hdr = (const volatile uint32_t *)&g_rm;
    for (unsigned i = 0; i < RM_HEADER_WORDS; ++i) tel_word(hdr[i], &crc);
    for (uint32_t i = 0; i < nw; ++i) {
        const volatile rm_window_t *w = &g_rm.window[i];
        tel_word(w->kind | (w->marker_high << 8) | (w->phase << 16), &crc);
        tel_word(w->start_cycle, &crc);
        tel_word(w->end_cycle, &crc);
        tel_word(w->iterations, &crc);
        tel_word(w->checksum, &crc);
    }
    uint32_t final_crc = ~crc, dummy = 0;
    tel_word(final_crc, &dummy);
    marker(0); wait_cycles(ms_cycles(100));
}

static uint32_t hex_prefix(const char *s)
{
    uint32_t v = 0;
    for (unsigned i = 0; i < 8; ++i) {
        const char c = s[i];
        v = (v << 4) | (uint32_t)(c >= '0' && c <= '9' ? c - '0' : c - 'a' + 10);
    }
    return v;
}

void hal_entry(void)
{
    volatile uint8_t *all = (volatile uint8_t *)&g_rm;
    for (size_t i = 0; i < sizeof g_rm; i++) all[i] = 0;
    g_rm.version = RM_VERSION;
    g_rm.struct_bytes = sizeof g_rm;
    g_rm.stage = RM_S_BOOT;
    g_rm.system_core_clock = SystemCoreClock;
    g_rm.fcachee = R_FCACHE->FCACHEE;
    g_rm.flwt = R_FCACHE->FLWT;
    g_rm.sckdivcr = R_SYSTEM->SCKDIVCR; g_rm.sckscr = R_SYSTEM->SCKSCR;
    g_rm.pllccr = R_SYSTEM->PLLCCR; g_rm.pllcr = R_SYSTEM->PLLCR;
    g_rm.hococr = R_SYSTEM->HOCOCR; g_rm.mococr = R_SYSTEM->MOCOCR; g_rm.opccr = R_SYSTEM->OPCCR;
    g_rm.ofs1_sec = *RM_OFS1_SEC_PTR;        /* option setting OFS1_SEC: HOCOFRQ lives here */
    g_rm.cpuid = SCB->CPUID;
    g_rm.model_sha_prefix[0] = hex_prefix(spikeids_qdq_sha256);
    g_rm.model_sha_prefix[1] = hex_prefix(spikeids_qdq_sha256 + 8);
    g_rm.vectors_sha_prefix[0] = hex_prefix(rm_vectors_sha256);
    g_rm.vectors_sha_prefix[1] = hex_prefix(rm_vectors_sha256 + 8);
    g_rm.n_schedules = RM_SCHEDULES;
    for (unsigned i = 0; i < RM_SCHEDULES; ++i) g_rm.multiplier[i] = k_multiplier[i];
    __DMB(); g_rm.magic = RM_MAGIC; __DSB();

    marker_init();
    R_BSP_MODULE_START(FSP_IP_GPT, 1);
    R_GPT1->GTCR = 0;                        /* stopped, saw-wave mode, PCLKD/1 */
    R_GPT1->GTUDDTYC = 1;                    /* count up */
    R_GPT1->GTPR = UINT32_C(0xFFFFFFFF);     /* full 32-bit period: natural wrap */
    R_GPT1->GTCNT = 0;
    R_GPT1->GTCR = 1;                        /* CST: start */
    __DSB();
    g_rm.timer_ctrl = R_GPT1->GTCR;
    g_rm.timer_id = RM_TIMER_ID;

    g_rm.settle_cycles = ms_cycles(RM_SETTLE_MS);
    g_rm.gap_cycles = ms_cycles(RM_GAP_MS);
    g_rm.idle_cycles = ms_cycles(1000);
    g_rm.pulse_cycles = ms_cycles(20); g_rm.pulse_count = 3; g_rm.cycles = 10;
    g_rm.wiring_cycles = ms_cycles(100); g_rm.wiring_pulses = 5;
    g_rm.sham_cycles = ms_cycles(1000); g_rm.sham_pulses = 20;

    const uint32_t c0 = cycles_now();
    wait_cycles(g_rm.settle_cycles / 2u);
    int ok = 1;
    if (cycles_now() == c0 || R_GPT1->GTPR != UINT32_C(0xFFFFFFFF)) ok = fail(RM_E_TIMER, g_rm.timer_ctrl);
    g_rm.pq_env = (uint32_t)pq_environment();
    if (ok && !g_rm.pq_env) ok = fail(RM_E_ENV, 0);
    if (ok) wait_cycles(g_rm.settle_cycles / 2u);

    if (ok) ok = run_parity();
    if (ok) { wait_cycles(g_rm.gap_cycles); g_rm.stage = RM_S_WIRING; ok = pulses(g_rm.wiring_pulses, g_rm.wiring_cycles, 0); }
    if (ok) { wait_cycles(g_rm.gap_cycles); g_rm.stage = RM_S_SHAM; ok = pulses(g_rm.sham_pulses, g_rm.sham_cycles, 1); }
    if (ok) { wait_cycles(g_rm.gap_cycles); ok = calibrate(); }
    for (uint32_t s = 0; ok && s < RM_SCHEDULES; ++s) {
        g_rm.stage = RM_S_SCHEDULE;
        wait_cycles(g_rm.gap_cycles);
        ok = run_schedule(2u + s, g_rm.bench_reps * k_multiplier[s]);
        if (ok) g_rm.schedules_done = s + 1u;
    }
    telemetry();
    if (g_rm.stage != RM_S_ERROR) g_rm.stage = RM_S_DONE;
    __DSB();
    marker(1);                     /* DONE (or ERROR after telemetry): HIGH forever */
    for (;;) __NOP();              /* no WFI: keep the core debuggable for readback */
}
