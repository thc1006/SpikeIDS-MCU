/* RAM-load image only. A separately reviewed loader must load initialized
 * PT_LOAD bytes at their VMA; there is no BootROM/FSBL/flash image here. */
#include <stdint.h>
#include <string.h>
#include "stm32n6xx.h"
#include "mailbox.h"
extern uint32_t _estack, _sbss, _ebss;
extern int main(void);
void Reset_Handler(void);
static void fault_handler(void)
{
    g_mailbox.cfsr=SCB->CFSR; g_mailbox.hfsr=SCB->HFSR;
    g_mailbox.state=V5_FAULT; __DSB();
    for (;;) __NOP(); /* No fault recovery, watchdog guessing or continued inference. */
}
__attribute__((section(".isr_vector"), used, aligned(128)))
const uint32_t vectors[16] = {
    (uint32_t)&_estack,(uint32_t)Reset_Handler,
    (uint32_t)fault_handler,(uint32_t)fault_handler,(uint32_t)fault_handler,(uint32_t)fault_handler,
    (uint32_t)fault_handler,(uint32_t)fault_handler,0,0,0,(uint32_t)fault_handler,
    (uint32_t)fault_handler,0,(uint32_t)fault_handler,(uint32_t)fault_handler
};
__attribute__((used,noreturn)) void reset_c(void)
{
    __disable_irq();
    SCB->VTOR=(uint32_t)vectors; __DSB(); __ISB();
    memset(&_sbss,0,(uintptr_t)&_ebss-(uintptr_t)&_sbss);
    main();
    for (;;) __NOP();
}
__attribute__((naked)) void Reset_Handler(void)
{
    __asm volatile("cpsid i\n mov r0,#0\n msr msplim,r0\n msr psplim,r0\n"
                   "msr control,r0\n isb\n ldr r0,=_estack\n msr msp,r0\n"
                   /* Enable FP/MVE access before any optimized C/library call. */
                   "ldr r1,=0xE000ED88\n ldr r2,[r1]\n orr r2,r2,#0x00F00000\n"
                   "str r2,[r1]\n dsb\n isb\n b reset_c\n");
}
