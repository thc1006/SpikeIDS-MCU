#include "stm32n6xx.h"
#include "mailbox.h"
__attribute__((section(".mailbox"),used,aligned(32))) volatile stage_mailbox_t g_stage;
static uint32_t read32(void *unused,uint32_t address)
{ (void)unused; return *(volatile uint32_t *)(uintptr_t)address; }
static void write32(void *unused,uint32_t address,uint32_t value)
{ (void)unused; *(volatile uint32_t *)(uintptr_t)address=value; }
static void barrier(void *unused)
{ (void)unused; __DSB(); __ISB(); }
__attribute__((noreturn))
void stage_main(uint32_t entry_vtor,uint32_t entry_control,uint32_t entry_primask,uint32_t entry_msp)
{
    /* Host must wait for an even READY/REJECTED snapshot before writing nonce.
     * Startup permits only privileged Thread/MSP and masks IRQ. Secure entry
     * and exclusive ownership remain explicit loader preconditions. */
    volatile uint32_t *words=(volatile uint32_t *)&g_stage;
    for (uint32_t i=0;i<sizeof(g_stage)/4u;i++) words[i]=0;
    g_stage.sequence=1; __DMB();
    g_stage.magic=STAGE_MAGIC; g_stage.version=1; g_stage.struct_bytes=sizeof(g_stage);
    g_stage.state=STAGE_INITIALIZING;
    g_stage.entry_vtor=entry_vtor;g_stage.entry_control=entry_control;
    g_stage.entry_primask=entry_primask;g_stage.entry_msp=entry_msp;
    g_stage.cpuid=SCB->CPUID;g_stage.ccr=SCB->CCR;
    g_stage.ipsr=__get_IPSR();g_stage.control=__get_CONTROL();
    platform_io_t io={0,read32,write32,barrier};
    platform_entry_t entry={__get_CONTROL(),__get_IPSR(),__get_PRIMASK()};
    int ok=platform_init(&io,&entry,&g_stage.platform);
    g_stage.ready_for_payload=ok ? 1u:0u;
    g_stage.state=ok ? STAGE_READY:STAGE_REJECTED;
    __DMB();g_stage.sequence=2;__DSB();
    /* This loop never launches the adapter or model. Liveness is not proof of
     * NPU/energy correctness. Host controls only the single nonce word. */
    for (;;) {
        uint32_t nonce=g_stage.host_nonce;
        /* Event-driven: leave the 4 KiB snapshot stable while host reads it
         * over slow SWD. Each fresh nonce causes exactly one publication. */
        if (nonce!=g_stage.echo_nonce) {
            uint32_t odd=g_stage.sequence|1u;g_stage.sequence=odd;__DMB();
            g_stage.echo_nonce=nonce;g_stage.heartbeat++;
            __DMB();g_stage.sequence=odd+1u;
        }
        for (volatile uint32_t i=0;i<4096u;i++) __NOP();
    }
}
