/* Minimal startup for the pyOCD-loaded B2 NPU firmware (AXISRAM1). Naked Reset_Handler clears
 * MSPLIM and sets SP before any stack push (the inherited BootROM MSPLIM sits above our AXISRAM1
 * stack and would STKOF-fault the C prologue), then continues in C. Fault handlers record to the
 * mailbox; watchdog-probe faults recover via the guard (watchdog.h). */
#include <stdint.h>
#include <string.h>
#include <setjmp.h>
#include "stm32n6xx.h"
#include "mailbox.h"
#include "watchdog.h"

extern uint32_t _estack, _sbss, _ebss;
extern int main(void);
void Reset_Handler(void);
static void Default_Handler(void);
static void HardFault_Handler(void);

/* watchdog boot-probe guard (watchdog.h) */
volatile uint32_t g_wdg_guard, g_wdg_fault;
jmp_buf g_wdg_jb;
static void wdg_guard_trampoline(void) { longjmp(g_wdg_jb, 1); }

__attribute__((section(".isr_vector"), used))
const uint32_t g_vectors[16] = {
    (uint32_t)&_estack, (uint32_t)Reset_Handler, (uint32_t)Default_Handler, (uint32_t)HardFault_Handler,
    (uint32_t)HardFault_Handler, (uint32_t)HardFault_Handler, (uint32_t)HardFault_Handler, (uint32_t)HardFault_Handler,
    0,0,0, (uint32_t)Default_Handler, (uint32_t)Default_Handler, 0, (uint32_t)Default_Handler, (uint32_t)Default_Handler,
};

__attribute__((used)) void reset_c(void); 
__attribute__((used)) void reset_c(void)
{
    IWDG_S_KR = IWDG_KEY_RELOAD;                    /* feed the OOB watchdog immediately */
    __disable_irq();
    SCB->VTOR = (uint32_t)g_vectors; __DSB(); __ISB();
    memset(&_sbss, 0, (size_t)((uintptr_t)&_ebss - (uintptr_t)&_sbss));
    main();
    for (;;) { __NOP(); }
}

__attribute__((naked)) void Reset_Handler(void)
{
    __asm volatile(
        "mov   r0, #0        \n\t"
        "msr   msplim, r0    \n\t"   /* clear inherited stack limit before any push */
        "ldr   r0, =_estack  \n\t"
        "mov   sp, r0        \n\t"
        "b     reset_c       \n\t"
    );
}

static void Default_Handler(void) { MB->state = MB_FAULT; for (;;) __NOP(); }

static void HardFault_Handler(void)
{
    uint32_t *frame;
    __asm volatile ("tst lr,#4\n\t ite eq\n\t mrseq %0,msp\n\t mrsne %0,psp" : "=r"(frame));
    if (g_wdg_guard) { SCB->CFSR = SCB->CFSR; SCB->HFSR = SCB->HFSR;
        frame[6] = (uint32_t)wdg_guard_trampoline & ~1u; frame[7] |= (1u<<24); __DSB(); return; }
    MB->err = SCB->CFSR; MB->boot[6] = SCB->CFSR; MB->boot[7] = 0xFA017; MB->state = MB_FAULT;
    for (;;) { __NOP(); }
}
