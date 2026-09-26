#include "stm32n6xx.h"
#include "mailbox.h"
__attribute__((section(".mailbox"), used, aligned(32)))
volatile probe_mailbox_t g_mailbox;

static uint32_t begin_update(void)
{
    uint32_t odd = g_mailbox.sequence | 1u;
    g_mailbox.sequence = odd;
    __DMB();
    return odd;
}
static void end_update(uint32_t odd)
{
    __DMB();
    g_mailbox.sequence = odd + 1u;
}
__attribute__((noreturn))
void probe_main(uint32_t entry_vtor, uint32_t entry_control,
                uint32_t entry_primask, uint32_t entry_msp)
{
    /* No data/bss/runtime outside this mailbox; explicitly initialize all words.
     * Host must not submit a nonce until a complete RUNNING snapshot exists. */
    volatile uint32_t *words = (volatile uint32_t *)&g_mailbox;
    for (uint32_t i=0; i<64u; ++i) words[i]=0u;
    uint32_t odd=begin_update();
    g_mailbox.magic=PROBE_MAGIC; g_mailbox.version=1u;
    g_mailbox.struct_bytes=sizeof(g_mailbox); g_mailbox.state=INITIALIZING;
    g_mailbox.cpuid=SCB->CPUID; g_mailbox.ccr=SCB->CCR;
    g_mailbox.control=__get_CONTROL(); g_mailbox.vtor=SCB->VTOR;
    g_mailbox.entry_vtor=entry_vtor; g_mailbox.entry_control=entry_control;
    g_mailbox.entry_primask=entry_primask; g_mailbox.entry_msp=entry_msp;
    g_mailbox.primask=__get_PRIMASK(); g_mailbox.ipsr=__get_IPSR();
    g_mailbox.msp=__get_MSP(); g_mailbox.msplim=__get_MSPLIM();
    g_mailbox.cfsr=SCB->CFSR; g_mailbox.hfsr=SCB->HFSR;
    g_mailbox.dfsr=SCB->DFSR; g_mailbox.afsr=SCB->AFSR;
    g_mailbox.mmfar=SCB->MMFAR; g_mailbox.bfar=SCB->BFAR;
    if ((g_mailbox.ccr & (SCB_CCR_DC_Msk|SCB_CCR_IC_Msk)) != 0u) {
        g_mailbox.state=CACHE_UNSUPPORTED; end_update(odd);
        for (;;) __NOP();
    }
    g_mailbox.state=RUNNING; end_update(odd);
    for (;;) {
        odd=begin_update();
        g_mailbox.echo_nonce=g_mailbox.host_nonce;
        g_mailbox.heartbeat += 1u;
        end_update(odd);
        /* Observation gap, not a clock, timeout or energy measurement. */
        for (volatile uint32_t i=0; i<4096u; ++i) __NOP();
    }
}
