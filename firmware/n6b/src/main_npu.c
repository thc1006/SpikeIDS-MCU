/* B2 NPU measurement main. Inherits the OOB clock/XSPI mapping via pyOCD takeover, re-asserts the
 * NPU (ST NPU_Config/RISAF_Config), then times stai_ids_run on the Neural-ART with DWT and reports
 * per-iteration cycles over the mailbox. Weights are read by the NPU from XSPI2 flash @0x71000000
 * (flashed separately); activations live in the NPU SRAM pools. */
#include <string.h>
#include "stm32n6xx_hal.h"
#include "mailbox.h"
#include "watchdog.h"
#include "npu_init.h"
#include "stai_ids.h"

wdg_state_t g_wdg;                                  /* consumed by watchdog.h wdg_feed() */

static uint8_t g_ctx[STAI_IDS_CONTEXT_SIZE] __attribute__((aligned(8)));
static int8_t  g_in[STAI_IDS_IN_1_SIZE_BYTES];
static int8_t  g_out[STAI_IDS_OUT_1_SIZE_BYTES];

static inline uint32_t cyc(void) { __DSB(); __ISB(); return DWT->CYCCNT; }

int main(void)
{
    /* housekeeping: FPU/MVE, DWT, feed watchdog (inherit OOB clock/XSPI) */
    uint32_t bootw[8] = {0};
    wdg_probe(bootw); wdg_feed();
    SCB->CPACR |= (3u<<20)|(3u<<22); __DSB(); __ISB();
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0; DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

    /* NPU bring-up (ST-correct; re-asserts over inherited OOB state) */
    NPU_Config();
    RISAF_Config();
    wdg_feed();

    /* STAI network init */
    stai_network *net = (stai_network *)g_ctx;
    stai_ptr inp[STAI_IDS_IN_NUM]  = { g_in };
    stai_ptr outp[STAI_IDS_OUT_NUM] = { g_out };
    memset(g_in, 0, sizeof g_in);
    int rc_init = (int)stai_ids_init(net);
    stai_ids_set_inputs(net, inp, STAI_IDS_IN_NUM);
    stai_ids_set_outputs(net, outp, STAI_IDS_OUT_NUM);

    memset((void *)MB, 0, sizeof(*MB));
    MB->boot[0] = SCB->CPUID; MB->boot[1] = (uint32_t)rc_init;
    MB->boot[2] = STAI_IDS_CONTEXT_SIZE; MB->boot[3] = STAI_IDS_IN_1_SIZE_BYTES;
    MB->boot[4] = STAI_IDS_OUT_1_SIZE_BYTES; MB->boot[5] = g_wdg.iwdg_ok; MB->boot[7] = 1;
    MB->version = MB_VERSION; __DSB(); MB->magic = MB_MAGIC; MB->state = MB_IDLE;

    uint32_t last_seq = 0;
    for (;;) {
        while (MB->seq == last_seq) { wdg_feed(); __NOP(); }
        last_seq = MB->seq; MB->ack = last_seq; MB->err = 0; MB->state = MB_RUNNING;
        wdg_feed();
        if (MB->cmd == CMD_NPU_INFER) {
            uint32_t iters = MB->param[0]; if (iters > MB_MAXRES) iters = MB_MAXRES;
            int rc = 0;
            /* warm-up */
            rc = (int)stai_ids_run(net, STAI_MODE_SYNC);
            for (uint32_t i = 0; i < iters; i++) {
                wdg_feed();
                uint32_t t0 = cyc();
                rc = (int)stai_ids_run(net, STAI_MODE_SYNC);
                uint32_t t1 = cyc();
                MB->cycles[i] = t1 - t0;
            }
            MB->last_rc = (uint32_t)rc;
            int best = 0; for (int c = 1; c < STAI_IDS_OUT_1_SIZE_BYTES; c++) if (g_out[c] > g_out[best]) best = c;
            MB->last_argmax = (uint32_t)best; MB->sink = (uint32_t)g_out[0];
            MB->n_results = iters;
            MB->state = (rc == 0) ? MB_DONE : MB_ERROR; MB->err = (uint32_t)rc;
        } else {
            MB->n_results = 0; MB->state = MB_DONE;
        }
        wdg_feed();
    }
}
