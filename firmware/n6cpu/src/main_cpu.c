/* CPU-int8 baseline for the STM32N6 Cortex-M55 (Helium/MVE) — same CAN IDS model as the NPU run,
 * executed purely on the CPU (ST AI lite runtime + NetworkRuntime CM55 lib, no Neural-ART), DWT-timed
 * for the same-chip NPU-vs-CPU comparison.
 *
 * Fairness: I- and D-cache ON (realistic CPU steady state; the 7761 B weights + 128 B activations fit
 * the 32 KB L1). No live mailbox polling — run N inferences, store per-iter cycles, then SCB_CleanDCache
 * once and publish magic, so pyOCD reads the results coherently from RAM after it halts the spinning core. */
#include <string.h>
#include "stm32n6xx_hal.h"
#include "stai.h"
#include "cpunet.h"
#include "mailbox.h"

void n6_system_init_post(void);
void n6_vddcore_overdrive(void);
void n6_clock_800mhz(void);

#define N_ITERS 256   /* <= MB_MAXRES (512) */

static uint8_t g_ctx[STAI_CPUNET_CONTEXT_SIZE] __attribute__((aligned(STAI_CPUNET_CONTEXT_ALIGNMENT)));
static uint8_t g_acts[STAI_CPUNET_ACTIVATIONS_SIZE] __attribute__((aligned(8)));
static int8_t  g_in[STAI_CPUNET_IN_SIZE_BYTES]  __attribute__((aligned(4)));
static int8_t  g_out[STAI_CPUNET_OUT_SIZE_BYTES] __attribute__((aligned(4)));
static inline uint32_t cyc(void){ __DSB(); __ISB(); return DWT->CYCCNT; }

int main(void)
{
    SCB->CPACR |= (3u<<20)|(3u<<22); __DSB(); __ISB();   /* enable CP10/CP11 (FPU + Helium/MVE) */
    HAL_Init();
    n6_system_init_post();          /* RAMs + MEMSYSCTL cache-activate gate (else L1 caches are inert) */
    SCB_EnableICache();
    SCB_EnableDCache();
    n6_vddcore_overdrive();         /* VDDCORE 0.89V via PF4 SMPS (required for 800MHz) */
    n6_clock_800mhz();              /* HSI -> PLL1 => CPU 800MHz, matching the ST NPU validation fw */
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0; DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

    memset((void *)MB, 0, sizeof(*MB));
    MB->version = MB_VERSION; MB->boot[0] = SCB->CPUID; MB->boot[7] = 1;

    stai_network *net = (stai_network *)g_ctx;
    stai_ptr inp[STAI_CPUNET_IN_NUM]  = { g_in };
    stai_ptr outp[STAI_CPUNET_OUT_NUM] = { g_out };
    memset(g_in, 0, sizeof g_in); memset(g_out, 0, sizeof g_out);

    int rc = (int)stai_cpunet_init(net);
    MB->boot[1] = (uint32_t)rc; MB->boot[2] = STAI_CPUNET_CONTEXT_SIZE;
    MB->boot[3] = STAI_CPUNET_IN_1_SIZE_BYTES; MB->boot[4] = STAI_CPUNET_OUT_1_SIZE_BYTES;
    /* ST order (aiValidation_ST_AI.c): init -> set_activations -> set_inputs -> set_outputs -> run.
     * Weights are STAI_FLAG_PREALLOCATED (baked into cpunet_data.c), so no set_weights needed. */
    stai_ptr act[STAI_CPUNET_ACTIVATIONS_NUM] = { g_acts };
    MB->boot[5] = (uint32_t)stai_cpunet_set_activations(net, act, STAI_CPUNET_ACTIVATIONS_NUM);
    (void)stai_cpunet_set_inputs(net, inp, STAI_CPUNET_IN_NUM);
    (void)stai_cpunet_set_outputs(net, outp, STAI_CPUNET_OUT_NUM);
    MB->boot[7] = 5;

    MB->boot[6] = SCB->CCR;                    /* cache state: bit16=DC, bit17=IC (fairness proof) */
    MB->param[2] = HAL_RCC_GetCpuClockFreq();  /* on-device CPU clock (must read ~800MHz now) */
    { uint32_t o0 = cyc(); uint32_t o1 = cyc(); MB->param[0] = o1 - o0; }  /* cyc() self-overhead */

    /* warm-up so weights + activations are resident in L1 (steady-state IDS operation) */
    (void)stai_cpunet_run(net, STAI_MODE_SYNC);

    uint32_t n = N_ITERS;
    for (uint32_t i = 0; i < n; i++) {
        uint32_t t0 = cyc();
        rc = (int)stai_cpunet_run(net, STAI_MODE_SYNC);
        uint32_t t1 = cyc();
        MB->cycles[i] = t1 - t0;
    }

    int best = 0;
    for (int c = 1; c < STAI_CPUNET_OUT_1_SIZE_BYTES; c++) if (g_out[c] > g_out[best]) best = c;
    MB->last_rc = (uint32_t)rc; MB->last_argmax = (uint32_t)best; MB->sink = (uint32_t)g_out[0];
    MB->n_results = n; MB->boot[7] = 7; MB->state = MB_DONE;
    __DSB();
    MB->magic = MB_MAGIC;
    SCB_CleanDCache();                 /* flush cycles[] + mailbox to RAM for the pyOCD reader */
    __DSB(); __ISB();
    for (;;) { __NOP(); }
}
