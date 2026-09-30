/* Vector table + Reset_Handler for the debugger-loaded N6 bench image.
 * The image is entered by the host setting SP/PC (no BootROM, no FSBL); the OOB firmware's
 * clock tree, XSPI configuration and power state are inherited and documented, not changed. */
#include <stdint.h>
#include <string.h>
#include "stm32n6xx.h"
#include "mailbox.h"
#include "watchdog.h"
#include <setjmp.h>

extern uint32_t _estack, _sbss, _ebss;
extern int main(void);

void Reset_Handler(void);
static void Default_Handler(void);
static void HardFault_Handler(void);

__attribute__((section(".isr_vector"), used))
const uint32_t g_vectors[16 + 8] = {
    (uint32_t)&_estack,
    (uint32_t)Reset_Handler,
    (uint32_t)Default_Handler,   /* NMI */
    (uint32_t)HardFault_Handler,
    (uint32_t)HardFault_Handler, /* MemManage */
    (uint32_t)HardFault_Handler, /* BusFault */
    (uint32_t)HardFault_Handler, /* UsageFault */
    (uint32_t)HardFault_Handler, /* SecureFault */
    0, 0, 0,
    (uint32_t)Default_Handler,   /* SVC */
    (uint32_t)Default_Handler,   /* DebugMon */
    0,
    (uint32_t)Default_Handler,   /* PendSV */
    (uint32_t)Default_Handler,   /* SysTick */
    /* a few external IRQ slots, all parked: interrupts stay masked for the whole run */
    (uint32_t)Default_Handler, (uint32_t)Default_Handler, (uint32_t)Default_Handler, (uint32_t)Default_Handler,
    (uint32_t)Default_Handler, (uint32_t)Default_Handler, (uint32_t)Default_Handler, (uint32_t)Default_Handler,
};

void Reset_Handler(void)
{
    IWDG_S_KR = IWDG_KEY_RELOAD;                        /* feed the OOB watchdog immediately */
    __disable_irq();                                   /* PRIMASK = 1 for the whole session */
    SCB->VTOR = (uint32_t)g_vectors;
    __DSB(); __ISB();

    /* Zero .bss (data has VMA == LMA: already in place). */
    memset(&_sbss, 0, (size_t)((uintptr_t)&_ebss - (uintptr_t)&_sbss));

    main();
    for (;;) { __NOP(); }
}

static void Default_Handler(void)
{
    MB->state = MB_FAULT;
    MB->info[INFO_FAULT_PC] = 0xDEADBEEF;
    for (;;) { __NOP(); }
}

extern void bench_fault_trampoline(void);
extern int  bench_fault_in_run(void);

/* watchdog boot-probe guard (watchdog.h) */
volatile uint32_t g_wdg_guard;
volatile uint32_t g_wdg_fault;
jmp_buf          g_wdg_jb;
static void wdg_guard_trampoline(void) { longjmp(g_wdg_jb, 1); }

/* Record the fault registers so the host can print them. If the fault happened inside an
 * experiment, clear the fault status, redirect the stacked PC to the trampoline and return:
 * the run ends with MB_ERROR and the session survives. Otherwise park. */
static void HardFault_Handler(void)
{
    uint32_t *frame;
    __asm volatile ("tst lr, #4\n ite eq\n mrseq %0, msp\n mrsne %0, psp" : "=r"(frame));
    MB->info[INFO_CFSR_LAST] = SCB->CFSR;
    MB->info[INFO_HFSR_LAST] = SCB->HFSR;
    MB->info[INFO_BFAR_LAST] = SCB->BFAR;
    MB->info[INFO_FAULT_PC]  = frame[6];
    if (g_wdg_guard) {                          /* fault while probing a watchdog register */
        SCB->CFSR = SCB->CFSR;
        SCB->HFSR = SCB->HFSR;
        frame[6] = (uint32_t)wdg_guard_trampoline & ~1u;
        frame[7] |= (1u << 24);
        __DSB();
        return;
    }
    if (bench_fault_in_run()) {
        SCB->CFSR = SCB->CFSR;                 /* write-1-to-clear */
        SCB->HFSR = SCB->HFSR;
        frame[6] = (uint32_t)bench_fault_trampoline & ~1u;
        frame[7] |= (1u << 24);                /* keep Thumb bit */
        __DSB();
        return;
    }
    MB->state = MB_FAULT;
    for (;;) { __NOP(); }
}
