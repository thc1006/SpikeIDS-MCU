/* B2 NPU measurement main — instrumented. Writes magic immediately, advances MB->boot[7] (phase)
 * through each init step, and fault-guards each step (records CFSR into boot[6], continues) so a
 * failure is diagnosable in one shot rather than a silent hang. LL_ATON_RT_POLLING => DWT counts
 * true NPU time. Weights: XSPI2 flash @0x71000000 (inherited OOB mapping); activations: NPU SRAM. */
#include <string.h>
#include <setjmp.h>
#include "stm32n6xx_hal.h"
#include "mailbox.h"
#include "watchdog.h"
#include "npu_init.h"
#include "stai_ids.h"

wdg_state_t g_wdg;
extern volatile uint32_t g_wdg_guard, g_wdg_fault;
extern jmp_buf g_wdg_jb;

static uint8_t g_ctx[STAI_IDS_CONTEXT_SIZE] __attribute__((aligned(8)));
static int8_t  g_in[STAI_IDS_IN_1_SIZE_BYTES];
static int8_t  g_out[STAI_IDS_OUT_1_SIZE_BYTES];
static inline uint32_t cyc(void){ __DSB(); __ISB(); return DWT->CYCCNT; }

/* run fn() under the fault guard; on fault record CFSR in boot[6] and return 0 */
#define GUARD(phase, stmt) do { MB->boot[7]=(phase); g_wdg_fault=0; g_wdg_guard=1; \
    if (setjmp(g_wdg_jb)==0) { stmt; } else { MB->boot[6]=SCB->CFSR; SCB->CFSR=SCB->CFSR; } \
    g_wdg_guard=0; } while(0)

int main(void)
{
    /* Guarantee CPU<->debugger coherence for the AXISRAM mailbox: with CPU L1 D-cache on,
     * pyOCD writes to seq/cmd and firmware writes to cycles could sit in L1 and never cross.
     * The NPU uses its own CACHEAXI, so disabling CPU D-cache does not affect measured NPU time. */
    if (SCB->CCR & SCB_CCR_DC_Msk) SCB_DisableDCache();

    /* housekeeping */
    SCB->CPACR |= (3u<<20)|(3u<<22); __DSB(); __ISB();
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0; DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
    IWDG_S_KR = IWDG_KEY_RELOAD;

    /* publish magic IMMEDIATELY so the host sees the firmware start even if a later step fails */
    memset((void *)MB, 0, sizeof(*MB));
    MB->version = MB_VERSION; MB->boot[0] = SCB->CPUID; MB->boot[7] = 1;
    __DSB(); MB->magic = MB_MAGIC; MB->state = MB_RUNNING;

    /* DEFANG the OOB IWDG before the slow NPU init (Phase A: kicking alone is not enough if
     * the reload is short/windowed). unlock + window=max + reload=max; then keep feeding. */
    uint32_t winr_after=0; wdg_defang_iwdg(&winr_after);

    uint32_t bw[8]={0};
    GUARD(2, wdg_probe(bw));          MB->boot[5]=g_wdg.iwdg_ok; wdg_feed();
    GUARD(3, NPU_Config());           wdg_feed();
    GUARD(4, RISAF_Config());         wdg_feed();

    stai_network *net = (stai_network *)g_ctx;
    stai_ptr inp[STAI_IDS_IN_NUM]={g_in}, outp[STAI_IDS_OUT_NUM]={g_out};
    memset(g_in,0,sizeof g_in);
    int rc_init=-99;
    GUARD(5, rc_init=(int)stai_ids_init(net));
    GUARD(6, stai_ids_set_inputs(net,inp,STAI_IDS_IN_NUM); stai_ids_set_outputs(net,outp,STAI_IDS_OUT_NUM));
    MB->boot[1]=(uint32_t)rc_init; MB->boot[2]=STAI_IDS_CONTEXT_SIZE;
    MB->boot[3]=STAI_IDS_IN_1_SIZE_BYTES; MB->boot[4]=STAI_IDS_OUT_1_SIZE_BYTES;
    MB->boot[7]=7; MB->state=MB_IDLE;               /* ready */

    uint32_t last_seq=0;
    for(;;){
        while(MB->seq==last_seq){ wdg_feed(); __NOP(); }
        last_seq=MB->seq; MB->ack=last_seq; MB->err=0; MB->state=MB_RUNNING; wdg_feed();
        if(MB->cmd==CMD_NPU_INFER){
            uint32_t iters=MB->param[0]; if(iters>MB_MAXRES) iters=MB_MAXRES;
            int rc=0; g_wdg_fault=0; g_wdg_guard=1;
            if(setjmp(g_wdg_jb)==0){
                rc=(int)stai_ids_run(net,STAI_MODE_SYNC);      /* warm-up */
                for(uint32_t i=0;i<iters;i++){ wdg_feed();
                    uint32_t t0=cyc(); rc=(int)stai_ids_run(net,STAI_MODE_SYNC); uint32_t t1=cyc();
                    MB->cycles[i]=t1-t0; }
                g_wdg_guard=0;
                int best=0; for(int c=1;c<STAI_IDS_OUT_1_SIZE_BYTES;c++) if(g_out[c]>g_out[best]) best=c;
                MB->last_rc=(uint32_t)rc; MB->last_argmax=(uint32_t)best; MB->sink=(uint32_t)g_out[0];
                MB->n_results=iters; MB->state=(rc==0)?MB_DONE:MB_ERROR; MB->err=(uint32_t)rc;
            } else { g_wdg_guard=0; MB->err=SCB->CFSR; MB->boot[6]=SCB->CFSR; MB->state=MB_ERROR; }
        } else { MB->n_results=0; MB->state=MB_DONE; }
        wdg_feed();
    }
}
