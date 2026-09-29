/* SM07M: frozen SM06 model/runtime/hooks + autonomous measurement commands.
 *
 * The whole SM06 translation unit is included unchanged; only its main() is
 * renamed. main() below repeats SM06 main() statement for statement (checked
 * by test_measure.py), with stai init spelled as the runtime-init wrapper that
 * the qcompat layer substitutes by macro. The INFER loop is unchanged; the only
 * addition is a poll of g_measure. The PH8 marker (Arduino D12, CN12-5) is set up
 * on the first measurement command, after the host's post-READY register checks.
 * Not PE15/D13: UM3300 wires that pin to LED LD6 (active HIGH), which would add
 * LED current to every marked window. PH8 has no LED and is ST's TRACE_PIN_1. */
#include "mailbox.h"
#define main s6_sm06_main_replaced
#include "../firmware_sram_accum24_route/main.c"
#undef main
#include "measure.h"

volatile s7_measure_t g_measure __attribute__((aligned(32)));
uint32_t g_rows_in[S7_MAX_ROWS * 41] __attribute__((aligned(32)));
uint32_t g_rows_out[S7_MAX_ROWS * 5] __attribute__((aligned(32)));

static void marker_init(void)
{
    /* Same steps ST x-cube-n6-ai-power-measurement trace_gpio.c uses for PH8
     * (HAL_PWREx_EnableVddIO4 + GPIO clock + push-pull output), register level. */
    RCC->AHB4ENSR = RCC_AHB4ENSR_PWRENS | RCC_AHB4ENSR_GPIOHENS;
    (void)RCC->AHB4ENR; __DSB();
    PWR->SVMCR1 |= PWR_SVMCR1_VDDIO4SV; __DSB();
    GPIOH->BSRR = UINT32_C(1) << (8 + 16);
    GPIOH->OTYPER &= ~(UINT32_C(1) << 8);
    GPIOH->PUPDR &= ~(UINT32_C(3) << 16);
    GPIOH->OSPEEDR = (GPIOH->OSPEEDR & ~(UINT32_C(3) << 16)) | (UINT32_C(1) << 16);
    GPIOH->MODER = (GPIOH->MODER & ~(UINT32_C(3) << 16)) | (UINT32_C(1) << 16);
    __DSB();
    g_measure.marker_initialized = 1;
}

static inline void marker(int high)
{
    GPIOH->BSRR = high ? (UINT32_C(1) << 8) : (UINT32_C(1) << 24);
    __DSB();
}

static void wait_cycles(uint32_t cycles)
{
    const uint32_t start = DWT->CYCCNT;
    while ((uint32_t)(DWT->CYCCNT - start) < cycles) __NOP();
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

static void measure_fail(int32_t code)
{
    if (g_measure.marker_initialized) marker(0);
    g_measure.error = code;
    __DMB(); g_measure.state = S7_ERROR; __DSB();
}

/* One inference on a preloaded row: the same statements as the SM06 INFER path
 * between the input copy and the output copy (input/output buffers alias). */
static void infer_row(stai_network *network, stai_ptr in0, stai_ptr out0,
                      uint32_t row, uint32_t *dst)
{
    memcpy(in0, &g_rows_in[row * 41], 164);
    __DSB();
    stai_return_code rc = stai_nsl_qcfs_seed0_run(network, STAI_MODE_SYNC);
    __DSB();
    checked(4, rc);
    checked(5, stai_nsl_qcfs_seed0_get_error(network));
    memcpy(dst, out0, 20);
}

static int rows_finite(uint32_t n)
{
    for (uint32_t i = 0; i < n * 41; ++i)
        if (!finite_word(g_rows_in[i])) { g_measure.first_bad_row = i / 41; return 0; }
    return 1;
}

/* Parameters are read once when a command starts; later host writes cannot
 * change a running command. */
typedef struct { uint32_t n, bench_reps, overhead_reps, cycles, idle, pulse, pulses; } s7_params_t;

static s7_params_t params_snapshot(void)
{
    s7_params_t p = { g_measure.n_rows, g_measure.bench_reps, g_measure.overhead_reps,
                      g_measure.cycles, g_measure.idle_cycles, g_measure.pulse_cycles,
                      g_measure.pulse_count };
    return p;
}

static volatile s7_window_t *window_begin(uint32_t kind, int high)
{
    const uint32_t w = g_measure.windows_used;
    if (w >= S7_MAX_WINDOWS) return 0;
    volatile s7_window_t *rec = &g_measure.window[w];
    rec->kind = kind; rec->iterations = 0; rec->checksum = UINT32_C(2166136261);
    rec->marker_high = (uint32_t)high; rec->end_cycle = 0;
    g_measure.windows_used = w + 1;
    __DSB();
    rec->start_cycle = DWT->CYCCNT;
    marker(high);
    return rec;
}

static void window_end(volatile s7_window_t *rec)
{
    marker(0);
    rec->end_cycle = DWT->CYCCNT;
}

static void run_parity(stai_network *network, stai_ptr in0, stai_ptr out0, const s7_params_t *p)
{
    const uint32_t n = p->n;
    if (n == 0 || n > S7_MAX_ROWS) { measure_fail(S7_E_PARAM); return; }
    if (!rows_finite(n)) { measure_fail(S7_E_INPUT); return; }
    uint64_t total = 0; uint32_t lo = UINT32_MAX, hi = 0;
    for (uint32_t r = 0; r < n; ++r) {
        const uint32_t begin = DWT->CYCCNT;
        infer_row(network, in0, out0, r, &g_rows_out[r * 5]);
        const uint32_t cycles = DWT->CYCCNT - begin;
        total += cycles; if (cycles < lo) lo = cycles; if (cycles > hi) hi = cycles;
        for (unsigned k = 0; k < 5; ++k)
            if (!finite_word(g_rows_out[r * 5 + k])) { g_measure.first_bad_row = r; measure_fail(S7_E_OUTPUT); return; }
    }
    g_measure.parity_cycles_total_lo = (uint32_t)total;
    g_measure.parity_cycles_total_hi = (uint32_t)(total >> 32);
    g_measure.parity_cycles_min = lo; g_measure.parity_cycles_max = hi;
    __DMB(); g_measure.state = S7_DONE;
}

static void run_pulses(const s7_params_t *p)
{
    if (p->pulses == 0 || p->pulses > 64 || p->pulse == 0) { measure_fail(S7_E_PARAM); return; }
    for (uint32_t i = 0; i < p->pulses; ++i) {
        volatile s7_window_t *rec = window_begin(S7_W_PULSE, 1);
        if (!rec) { measure_fail(S7_E_PARAM); return; }
        wait_cycles(p->pulse);
        window_end(rec);
        wait_cycles(p->pulse);
    }
    __DMB(); g_measure.state = S7_DONE;
}

static void run_schedule(stai_network *network, stai_ptr in0, stai_ptr out0, const s7_params_t *p)
{
    const uint32_t n = p->n;
    if (n == 0 || n > S7_MAX_ROWS || p->cycles == 0 || p->bench_reps == 0 ||
        p->overhead_reps == 0 || p->idle == 0 || p->pulses == 0 || p->pulses > 16 || p->pulse == 0 ||
        (uint64_t)p->pulses + 4u * (uint64_t)p->cycles + 1u > S7_MAX_WINDOWS) { measure_fail(S7_E_PARAM); return; }
    if (!rows_finite(n)) { measure_fail(S7_E_INPUT); return; }
    uint32_t out[5];
    volatile s7_window_t *rec;
    /* Preamble: known number of short HIGH pulses anchors the capture. */
    for (uint32_t i = 0; i < p->pulses; ++i) {
        if (!(rec = window_begin(S7_W_PULSE, 1))) { measure_fail(S7_E_PARAM); return; }
        wait_cycles(p->pulse);
        window_end(rec);
        wait_cycles(p->pulse);
    }
    for (uint32_t c = 0; c < p->cycles; ++c) {
        if (!(rec = window_begin(S7_W_IDLE, 0))) { measure_fail(S7_E_PARAM); return; }
        wait_cycles(p->idle);
        window_end(rec);

        if (!(rec = window_begin(S7_W_BENCH, 1))) { measure_fail(S7_E_PARAM); return; }
        for (uint32_t rep = 0; rep < p->bench_reps; ++rep)
            for (uint32_t r = 0; r < n; ++r) {
                infer_row(network, in0, out0, r, out);
                rec->checksum = fnv1a(rec->checksum, out, 5);
                rec->iterations++;
            }
        window_end(rec);

        if (!(rec = window_begin(S7_W_IDLE, 0))) { measure_fail(S7_E_PARAM); return; }
        wait_cycles(p->idle);
        window_end(rec);

        /* Same row copies and checksum as BENCH, without the model run. */
        if (!(rec = window_begin(S7_W_OVERHEAD, 1))) { measure_fail(S7_E_PARAM); return; }
        for (uint32_t rep = 0; rep < p->overhead_reps; ++rep)
            for (uint32_t r = 0; r < n; ++r) {
                memcpy(in0, &g_rows_in[r * 41], 164);
                __DSB();
                memcpy(out, out0, 20);
                rec->checksum = fnv1a(rec->checksum, out, 5);
                rec->iterations++;
            }
        window_end(rec);
    }
    if (!(rec = window_begin(S7_W_IDLE, 0))) { measure_fail(S7_E_PARAM); return; }
    wait_cycles(p->idle);
    window_end(rec);
    __DMB(); g_measure.state = S7_DONE;
}

static void measure_poll(stai_network *network, stai_ptr in0, stai_ptr out0, uint32_t *seen)
{
    const uint32_t seq = g_measure.request_sequence;
    if (seq == *seen) return;
    if (seq != *seen + 1) { measure_fail(S7_E_SEQUENCE); *seen = seq; g_measure.response_sequence = seq; return; }
    *seen = seq;
    const uint32_t command = g_measure.command;
    const s7_params_t p = params_snapshot();
    if (!g_measure.marker_initialized) marker_init();
    g_measure.error = 0; g_measure.windows_used = 0; g_measure.first_bad_row = UINT32_MAX;
    g_measure.state = S7_BUSY; __DMB();
    switch (command) {
    case S7_CMD_PARITY: run_parity(network, in0, out0, &p); break;
    case S7_CMD_SCHEDULE: run_schedule(network, in0, out0, &p); break;
    case S7_CMD_PULSES: run_pulses(&p); break;
    default: measure_fail(S7_E_COMMAND); break;
    }
    marker(0);
    __DMB(); g_measure.response_sequence = seq; __DSB();
}

static void measure_publish(void)
{
    memset((void *)&g_measure, 0, sizeof g_measure);
    g_measure.version = S7_VERSION;
    g_measure.struct_bytes = sizeof g_measure;
    g_measure.rows_in_address = (uint32_t)(uintptr_t)g_rows_in;
    g_measure.rows_out_address = (uint32_t)(uintptr_t)g_rows_out;
    g_measure.max_rows = S7_MAX_ROWS;
    g_measure.max_windows = S7_MAX_WINDOWS;
    g_measure.marker = S7_MARKER_PORT_PIN;
    g_measure.state = S7_IDLE;
    __DMB(); g_measure.magic = S7_MAGIC; __DSB();
}

int main(void)
{
    memset((void *)&g_mailbox, 0, sizeof g_mailbox);
    g_mailbox.version = S6_PROTOCOL;
    g_mailbox.struct_bytes = sizeof g_mailbox;
    g_mailbox.cpuid = SCB->CPUID;
    memcpy((void *)g_mailbox.model_sha256,
           "22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d", 65);
    memcpy((void *)g_mailbox.weights_sha256,
           "cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec", 65);
    for (unsigned i=0; i<6; ++i) g_mailbox.api_status[i] = INT32_MIN;
    g_mailbox.weights_address=S6_WEIGHTS_ADDRESS;
    g_mailbox.weights_reserved_bytes=S6_WEIGHTS_RESERVED_BYTES;
    g_mailbox.activation_address=S6_RUNTIME_IO_ADDRESS;
    g_mailbox.activation_reserved_bytes=S6_ACTIVATION_RESERVED_BYTES;
    g_mailbox.weights_bytes=145457;
    g_mailbox.deployment_tag=S6_DEPLOYMENT_TAG;
    g_mailbox.state = S6_WAIT_PLATFORM;
    __DMB(); g_mailbox.magic = S6_MAGIC; __DSB();
    /* This token is an explicit host prerequisite acknowledgement, not a
     * cryptographic or physical attestation. No host uploader is provided. */
    while (g_mailbox.platform_ack != S6_PLATFORM_ACK) __NOP();
    if (SCB->CCR & SCB_CCR_DC_Msk) park_error(S6_E_CACHE);
    g_mailbox.state = S6_INITIALIZING;
    SCB->CPACR |= (3u << 20) | (3u << 22); __DSB(); __ISB();
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0; DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

    stai_network *network = (stai_network *)context;
    stai_network_info info;
    stai_ptr in[1] = {0}, out[1] = {0};
    stai_size nin=1, nout=1;
    g_mailbox.stage=1; checked(0, initialize_runtime_then_model(network));
    g_mailbox.stage=2; checked(1, stai_nsl_qcfs_seed0_get_info(network, &info));
    if (info.n_inputs != 1 || info.n_outputs != 1 ||
        !tensor_ok(info.inputs,41,164) || !tensor_ok(info.outputs,5,20)) park_error(S6_E_LAYOUT);
    g_mailbox.stage=3; checked(2, stai_nsl_qcfs_seed0_get_inputs(network,in,&nin));
    g_mailbox.stage=4; checked(3, stai_nsl_qcfs_seed0_get_outputs(network,out,&nout));
    g_mailbox.input_address=(uint32_t)(uintptr_t)in[0];
    g_mailbox.output_address=(uint32_t)(uintptr_t)out[0];
    if (nin != 1 || nout != 1 || (uintptr_t)in[0] != S6_RUNTIME_IO_ADDRESS ||
        (uintptr_t)out[0] != S6_RUNTIME_IO_ADDRESS) park_error(S6_E_LAYOUT);
    /* Input/output alias is intentional: different lifetimes in the fixed
     * generated model. Output is copied out before the next input is written. */
    measure_publish();
    uint32_t measure_seen = 0;
    g_mailbox.stage=0; __DMB(); g_mailbox.state=S6_READY; __DSB();
    uint32_t previous=0;
    for (;;) {
        measure_poll(network, in[0], out[0], &measure_seen);
        uint32_t seq=g_mailbox.request_sequence;
        if (seq == previous) { __NOP(); continue; }
        if (seq != previous + 1 || seq == 0) park_error(S6_E_CHANGED);
        if (g_mailbox.platform_ack != S6_PLATFORM_ACK) park_error(S6_E_PLATFORM);
        if (g_mailbox.command != S6_COMMAND_INFER) park_error(S6_E_COMMAND);
        if (g_mailbox.input_count != 41) park_error(S6_E_INPUT);
        const uint32_t row=g_mailbox.row_id;
        g_mailbox.output_count=0; g_mailbox.run_cycles=0;
        g_mailbox.stage=5; g_mailbox.state=S6_RUNNING; __DMB();
        for (unsigned i=0; i<41; ++i) {
            input_copy[i]=g_mailbox.input_words[i];
            if (!finite_word(input_copy[i])) park_error(S6_E_INPUT);
        }
        __DMB();
        if (!request_unchanged(seq,row)) park_error(S6_E_CHANGED);
        memcpy(in[0], input_copy, 164);
        __DSB(); uint32_t begin=DWT->CYCCNT;
        stai_return_code rc=stai_nsl_qcfs_seed0_run(network,STAI_MODE_SYNC);
        __DSB(); uint32_t end=DWT->CYCCNT;
        g_mailbox.run_cycles=end-begin; /* CPU cycles around full mixed run, not NPU-only time */
        checked(4,rc);
        checked(5,stai_nsl_qcfs_seed0_get_error(network));
        memcpy(output_copy,out[0],20);
        for (unsigned i=0; i<5; ++i) g_mailbox.output_words[i]=output_copy[i];
        g_mailbox.output_count=5;
        for (unsigned i=0; i<5; ++i) if (!finite_word(output_copy[i])) park_error(S6_E_OUTPUT);
        if (!request_unchanged(seq,row)) park_error(S6_E_CHANGED);
        g_mailbox.completed_row_id=row; g_mailbox.stage=0;
        previous=seq;
        g_mailbox.state=S6_DONE; __DMB(); g_mailbox.response_sequence=seq; __DSB();
    }
}
