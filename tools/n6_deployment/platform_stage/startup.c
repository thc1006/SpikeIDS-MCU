#include <stdint.h>
#include "mailbox.h"
extern uint32_t _estack,_sstack;
void Reset_Handler(void);void fault_handler(void);
__attribute__((section(".isr_vector"),used,aligned(1024)))
const uint32_t vectors[16]={
 (uint32_t)&_estack,(uint32_t)Reset_Handler,
 (uint32_t)fault_handler,(uint32_t)fault_handler,(uint32_t)fault_handler,
 (uint32_t)fault_handler,(uint32_t)fault_handler,(uint32_t)fault_handler,
 0,0,0,(uint32_t)fault_handler,(uint32_t)fault_handler,0,
 (uint32_t)fault_handler,(uint32_t)fault_handler
};
/* Soft/general-register-only build: no FP/MVE/C runtime before entry checks. */
__attribute__((naked,noreturn)) void Reset_Handler(void)
{
 __asm volatile(
  "mrs r1,control\n mrs r2,primask\n mrs r3,msp\n"
  "mrs r5,ipsr\n cmp r5,#0\n bne 1f\n tst r1,#3\n bne 1f\n"
  "ldr r4,=0xe000ed08\n ldr r0,[r4]\n cpsid i\n"
  "ldr r5,=_sstack\n msr msplim,r5\n ldr r5,=_estack\n msr msp,r5\n"
  "ldr r5,=vectors\n str r5,[r4]\n dsb\n isb\n b stage_main\n 1: b 1b\n");
}
/* Fault status is best effort, not an exception-frame dereference. */
__attribute__((naked,noreturn)) void fault_handler(void)
{
 __asm volatile(
  "ldr r0,=g_stage\n ldr r1,[r0,#16]\n orr r1,r1,#1\n str r1,[r0,#16]\n dmb\n"
  "mrs r2,ipsr\n str r2,[r0,#88]\n str lr,[r0,#92]\n"
  "mrs r2,msp\n str r2,[r0,#96]\n mrs r2,psp\n str r2,[r0,#100]\n"
  "ldr r3,=0xe000ed28\n ldr r2,[r3,#0]\n str r2,[r0,#64]\n"
  "ldr r2,[r3,#4]\n str r2,[r0,#68]\n ldr r2,[r3,#8]\n str r2,[r0,#72]\n"
  "ldr r2,[r3,#20]\n str r2,[r0,#76]\n ldr r2,[r3,#12]\n str r2,[r0,#80]\n"
  "ldr r2,[r3,#16]\n str r2,[r0,#84]\n movs r2,#0\n str r2,[r0,#104]\n"
  "movs r2,#4\n str r2,[r0,#12]\n dmb\n adds r1,r1,#1\n str r1,[r0,#16]\n"
  "dsb\n 1: b 1b\n");
}
