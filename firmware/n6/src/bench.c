/* SpikeIDS N6 bench firmware: host-driven experiments on a hot-halted STM32N657 (Cortex-M55).
 *
 * The host (scripts/n6_bench.py) halts the running OOB firmware, loads this image into SRAM3,
 * points SP/PC here and resumes. We then own the core: interrupts masked, MPU off (architectural
 * default memory map), caches reset, DWT cycle counter on. Clocks/XSPI configuration are
 * inherited from the OOB firmware and captured into MB->info[] so the report can state them. */
#include <setjmp.h>
#include <string.h>
#include "stm32n6xx.h"
#include "stm32n6xx_hal.h"
#include "mailbox.h"
#include "kernels.h"
#include "watchdog.h"

wdg_state_t g_wdg;

#ifndef BUILD_ID
#define BUILD_ID 0
#endif

static jmp_buf g_recover;
static volatile uint32_t g_in_run;

/* Fault recovery: HardFault_Handler (startup.c) rewrites the stacked PC to this trampoline
 * when a fault happens inside an experiment, so a bad address ends the run with MB_ERROR
 * instead of killing the session. Runs in thread mode, so longjmp is legal here. */
void bench_fault_trampoline(void) { longjmp(g_recover, 1); }
int  bench_fault_in_run(void)     { return g_in_run != 0; }

/* ---- cycle counter ---------------------------------------------------------------- */
static inline uint32_t cyc(void) { __DSB(); __ISB(); return DWT->CYCCNT; }

static void dwt_init(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

/* ---- caches ----------------------------------------------------------------------- */
static void caches_reset_at_entry(void)
{
    /* The host cleared CCR.IC/DC before loading; whatever is left in the caches belongs to the
     * OOB firmware and must be discarded WITHOUT clean (dirty lines could overwrite our image). */
    SCB->CCR &= ~(SCB_CCR_IC_Msk | SCB_CCR_DC_Msk);
    __DSB(); __ISB();
    SCB_InvalidateICache();
    SCB_InvalidateDCache();
}

static void apply_cache_mode(uint32_t mode)
{
    if (mode & CM_ICACHE) SCB_EnableICache(); else SCB_DisableICache();
    if (mode & CM_DCACHE) SCB_EnableDCache(); else SCB_DisableDCache();
    __DSB(); __ISB();
}

static inline void cold_start(uint32_t mode)
{
    if (mode & CM_INVAL_EACH) { SCB_CleanInvalidateDCache(); __DSB(); __ISB(); }
}

/* ---- platform capture ------------------------------------------------------------- */
static void capture_info(uint32_t ccr_at_entry, uint32_t mpu_ctrl_at_entry)
{
    MB->info[INFO_CPUID]            = SCB->CPUID;
    MB->info[INFO_CCR_AT_ENTRY]     = ccr_at_entry;
    MB->info[INFO_MPU_CTRL_AT_ENTRY]= mpu_ctrl_at_entry;
    MB->info[INFO_MPU_TYPE]         = MPU->TYPE;
    MB->info[INFO_CPU_HZ_HAL]       = HAL_RCC_GetCpuClockFreq();
    MB->info[INFO_SYS_HZ_HAL]       = HAL_RCC_GetSysClockFreq();
    MB->info[INFO_XSPI2_KER_HZ_HAL] = HAL_RCCEx_GetPeriphCLKFreq(RCC_PERIPHCLK_XSPI2);
    MB->info[INFO_XSPI1_KER_HZ_HAL] = HAL_RCCEx_GetPeriphCLKFreq(RCC_PERIPHCLK_XSPI1);
    MB->info[INFO_RCC_AHB5ENR]      = RCC->AHB5ENR;
    MB->info[INFO_RCC_APB5ENR]      = RCC->APB5ENR;
    if (RCC->AHB5ENR & RCC_AHB5ENR_XSPI2EN) {
        MB->info[INFO_XSPI2_CR]   = XSPI2->CR;
        MB->info[INFO_XSPI2_DCR1] = XSPI2->DCR1;
        MB->info[INFO_XSPI2_DCR2] = XSPI2->DCR2;
        MB->info[INFO_XSPI2_CCR]  = XSPI2->CCR;
        MB->info[INFO_XSPI2_TCR]  = XSPI2->TCR;
    }
    /* Stop the LCD controller if it is scanning a framebuffer: it is the one bandwidth
     * consumer the OOB demo leaves running. Only touch it if it is clocked. */
    if (RCC->APB5ENR & RCC_APB5ENR_LTDCEN) {
        MB->info[INFO_LTDC_WAS_ON] = (LTDC->GCR & LTDC_GCR_LTDCEN) ? 1u : 0u;
        LTDC->GCR &= ~LTDC_GCR_LTDCEN;
    }
    MB->info[INFO_CLIDR]   = SCB->CLIDR;
    SCB->CSSELR = 1u; __DSB(); MB->info[INFO_CCSIDR_I] = SCB->CCSIDR;   /* L1 I */
    SCB->CSSELR = 0u; __DSB(); MB->info[INFO_CCSIDR_D] = SCB->CCSIDR;   /* L1 D */
    MB->info[INFO_FPSCR]      = __get_FPSCR();
    MB->info[INFO_MB_VERSION] = MB_VERSION;
    MB->info[INFO_BUILD_ID]   = BUILD_ID;
}

/* ---- experiments ------------------------------------------------------------------ */
static uint32_t lcg(uint32_t *s) { *s = *s * 1664525u + 1013904223u; return *s; }

static void run_fill(void)
{
    uint8_t *p = (uint8_t *)MB->param[1];
    uint32_t n = MB->param[2], seed = MB->param[4] ? MB->param[4] : 0x12345678u;
    if (MB->param[5] == 1) {                       /* float32 in [-1, 1) */
        float *f = (float *)p;
        for (uint32_t i = 0; i < n / 4; i++) f[i] = ((int32_t)lcg(&seed) >> 8) * (1.0f / 8388608.0f);
    } else {                                        /* int8 in [-127, 127] */
        for (uint32_t i = 0; i < n; i++) { int8_t v = (int8_t)(lcg(&seed) >> 24); p[i] = (uint8_t)(v == -128 ? -127 : v); }
    }
    MB->n_results = 0;
}

static void run_read_bw(void)
{
    const uint32_t *src = (const uint32_t *)MB->param[1];
    uint32_t words = MB->param[2] / 4, mode = MB->param[3], width = MB->param[4];
    uint32_t iters = MB->param[0] > MB_MAX_RES ? MB_MAX_RES : MB->param[0];
    apply_cache_mode(mode);
    uint32_t acc = 0;
    for (uint32_t it = 0; it < iters; it++) {
        wdg_feed();
        cold_start(mode);
        uint32_t t0 = cyc();
        switch (width) {
            case RW_LDRD64:  acc += rd_ldrd64(src, words); break;
            case RW_MVE128:  acc += rd_mve128(src, words); break;
            case RW_LDM32x8: acc += rd_ldm32x8(src, words); break;
            default:         acc += rd_ldr32(src, words); break;
        }
        uint32_t t1 = cyc();
        MB->results[it] = t1 - t0;
    }
    MB->sink = acc;
    MB->n_results = iters;
}

static void run_nop(void)
{
    uint32_t iters = MB->param[0] > MB_MAX_RES ? MB_MAX_RES : MB->param[0];
    apply_cache_mode(MB->param[3]);
    for (uint32_t it = 0; it < iters; it++) {
        uint32_t t0 = cyc();
        __NOP();
        uint32_t t1 = cyc();
        MB->results[it] = t1 - t0;
    }
    MB->n_results = iters;
}

static void run_memcpy(void)
{
    uint32_t iters = MB->param[0] > MB_MAX_RES ? MB_MAX_RES : MB->param[0];
    apply_cache_mode(MB->param[3]);
    for (uint32_t it = 0; it < iters; it++) {
        cold_start(MB->param[3]);
        uint32_t t0 = cyc();
        memcpy((void *)MB->param[4], (const void *)MB->param[1], MB->param[2]);
        uint32_t t1 = cyc();
        MB->results[it] = t1 - t0;
    }
    MB->n_results = iters;
}

static void get_dims(mlp_dims_t *m) { for (int i = 0; i < 5; i++) m->dims[i] = MB->param[5 + i]; }

static void run_mlp_fp32(void)
{
    mlp_dims_t m; get_dims(&m);
    const float *w = (const float *)MB->param[1];
    float *scratch = (float *)MB->param[2];            /* [bias(Σout) | act | out] in RAM */
    uint32_t mode = MB->param[3];
    uint32_t iters = MB->param[0] > MB_MAX_RES ? MB_MAX_RES : MB->param[0];
    uint32_t nout = m.dims[1] + m.dims[2] + m.dims[3] + m.dims[4];
    float *bias = scratch, *act = scratch + nout;
    float *out = act + m.dims[0] + m.dims[1] + m.dims[2] + m.dims[3];
    uint32_t seed = 7;
    for (uint32_t i = 0; i < nout; i++) bias[i] = ((int32_t)lcg(&seed) >> 8) * (1.0f / 8388608.0f);
    for (uint32_t i = 0; i < m.dims[0]; i++) act[i] = ((int32_t)lcg(&seed) >> 8) * (1.0f / 8388608.0f);
    apply_cache_mode(mode);
    mlp_fp32_run(w, bias, act, &m, out);              /* warm-up (code into I-cache) */
    float sink = 0.f;
    for (uint32_t it = 0; it < iters; it++) {
        cold_start(mode);
        uint32_t t0 = cyc();
        mlp_fp32_run(w, bias, act, &m, out);
        uint32_t t1 = cyc();
        MB->results[it] = t1 - t0;
        sink += out[0];
    }
    MB->sink = (uint32_t)sink;
    MB->n_results = iters;
}

static void run_mlp_s8(void)
{
    mlp_dims_t m; get_dims(&m);
    const int8_t *w = (const int8_t *)MB->param[1];
    int32_t *work = (int32_t *)MB->param[2];
    uint32_t mode = MB->param[3];
    uint32_t iters = MB->param[0] > MB_MAX_RES ? MB_MAX_RES : MB->param[0];
    static int8_t x[512];
    uint32_t seed = 11;
    for (uint32_t i = 0; i < m.dims[0] && i < sizeof x; i++) x[i] = (int8_t)(lcg(&seed) >> 25);
    if (mlp_s8_setup(w, work, &m) != 0) { MB->err = 0xE5; MB->state = MB_ERROR; return; }
    apply_cache_mode(mode);
    int r = mlp_s8_run(w, work, &m, x);                /* warm-up */
    for (uint32_t it = 0; it < iters; it++) {
        cold_start(mode);
        uint32_t t0 = cyc();
        r += mlp_s8_run(w, work, &m, x);
        uint32_t t1 = cyc();
        MB->results[it] = t1 - t0;
    }
    MB->sink = (uint32_t)r;
    MB->n_results = iters;
}

static void run_peek(void)
{
    MB->results[0] = *(volatile uint32_t *)MB->param[1];
    MB->n_results = 1;
}

/* ---- main loop -------------------------------------------------------------------- */
int main(void)
{
    uint32_t ccr0 = SCB->CCR, mpu0 = MPU->CTRL;
    uint32_t boot[MB_N_BOOT] = {0};

    /* 1) Neutralise the OOB watchdog(s) BEFORE anything slow. Probe (fault-guarded) which
     *    watchdogs are live, then service them; keep servicing throughout. */
    wdg_probe(boot);
    wdg_feed();
    uint32_t winr_after = 0;
    boot[BOOT_SETUP_FAULT] = (uint32_t)wdg_defang_iwdg(&winr_after);  /* reuse slot 6 as defang-ok */
    wdg_feed();
    wdg_freeze_in_debug();
    wdg_feed();

    caches_reset_at_entry();
    ARM_MPU_Disable();                                  /* architectural default memory map */
    SCB->CPACR |= (3u << 20) | (3u << 22);              /* CP10/CP11: FPU + MVE full access */
    __DSB(); __ISB();
    __set_FPSCR(__get_FPSCR() | (1u << 24) | (1u << 25)); /* FZ + DN: data-independent FP timing */
    SysTick->CTRL = 0;
    dwt_init();
    wdg_feed();

    memset((void *)MB->info, 0, sizeof(MB->info));
    capture_info(ccr0, mpu0);
    boot[BOOT_PHASE] = 1;
    for (int i = 0; i < MB_N_BOOT; i++) MB->boot[i] = boot[i];
    MB->state = MB_IDLE;
    MB->cmd = MB->seq = MB->ack = MB->err = MB->n_results = 0;
    MB->version = MB_VERSION;
    __DSB();
    MB->magic = MB_MAGIC;                               /* publish LAST: magic implies boot[] valid */
    wdg_feed();

    uint32_t last_seq = 0;
    for (;;) {
        if (setjmp(g_recover)) {                        /* landed here from a fault in a run */
            g_in_run = 0;
            MB->err = SCB->CFSR ? SCB->CFSR : MB->info[INFO_CFSR_LAST];
            MB->state = MB_ERROR;
            apply_cache_mode(0);
        }
        while (MB->seq == last_seq) { wdg_feed(); __NOP(); }
        last_seq = MB->seq;
        MB->ack = last_seq;
        MB->err = 0;
        MB->n_results = 0;
        MB->state = MB_RUNNING;
        wdg_feed();
        g_in_run = 1;
        switch (MB->cmd) {
            case CMD_NOP:      run_nop();      break;
            case CMD_READ_BW:  run_read_bw();  break;
            case CMD_MLP_FP32: run_mlp_fp32(); break;
            case CMD_MLP_S8:   run_mlp_s8();   break;
            case CMD_FILL:     run_fill();     break;
            case CMD_MEMCPY:   run_memcpy();   break;
            case CMD_PEEK:     run_peek();     break;
            default: MB->err = 0xBADC; MB->state = MB_ERROR; g_in_run = 0; continue;
        }
        g_in_run = 0;
        apply_cache_mode(0);                            /* leave caches off between runs */
        if (MB->state == MB_RUNNING) MB->state = MB_DONE;
    }
}
