/* Watchdog neutralisation for the takeover bench (STM32N657, Secure aliases).
 *
 * The OOB demo enables a watchdog; if we take over and stop servicing it, it resets the board
 * (~100 ms) back into the sleeping demo — which is why the debug AP kept dying. We do not know
 * which watchdog, so we service BOTH every loop: IWDG by refresh, WWDG by a window-safe reload,
 * and we probe their state at boot (fault-guarded) so the host can see it. Register addresses
 * are computed from stm32n657xx.h (Secure aliases; we run Secure).
 */
#ifndef N6_WATCHDOG_H
#define N6_WATCHDOG_H
#include <stdint.h>
#include <setjmp.h>

#define IWDG_S_KR     (*(volatile uint32_t *)0x56004800UL)
#define IWDG_S_PR     (*(volatile uint32_t *)0x56004804UL)
#define IWDG_S_RLR    (*(volatile uint32_t *)0x56004808UL)
#define IWDG_S_SR     (*(volatile uint32_t *)0x5600480CUL)
#define IWDG_S_WINR   (*(volatile uint32_t *)0x56004810UL)
#define RCC_S_RSR     (*(volatile uint32_t *)0x56028034UL)
#define WWDG_S_CR     (*(volatile uint32_t *)0x50002C00UL)   /* WDGA[7], T[6:0]            */
#define WWDG_S_CFR    (*(volatile uint32_t *)0x50002C04UL)   /* W[6:0], WDGTB[13:11]       */
#define RCC_S_APB1ENR1 (*(volatile uint32_t *)0x56028264UL)  /* bit11 = WWDGEN             */
#define DBGMCU_S_APB1LFZ1 (*(volatile uint32_t *)0x54001010UL)
#define DBGMCU_S_APB4FZ1  (*(volatile uint32_t *)0x5400101CUL)

#define IWDG_KEY_RELOAD  0x0000AAAAu
#define IWDG_KEY_ENABLE  0x0000CCCCu
#define IWDG_KEY_UNLOCK  0x00005555u
#define IWDG_RL_MAX      0x00000FFFu
#define WWDG_WDGA       (1u << 7)
#define RCC_WWDGEN      (1u << 11)
#define DBG_WWDG1_STOP  (1u << 11)
#define DBG_IWDG_STOP   (1u << 18)

/* Fault-guarded single reads/writes for boot probing. HardFault_Handler (startup.c) checks
 * g_wdg_guard and, when set, records the fault and longjmps back here instead of parking. */
extern volatile uint32_t g_wdg_guard;
extern volatile uint32_t g_wdg_fault;
extern jmp_buf          g_wdg_jb;

static inline uint32_t wdg_try_read(volatile uint32_t *a, uint32_t dflt)
{
    uint32_t v = dflt;
    g_wdg_fault = 0; g_wdg_guard = 1;
    if (setjmp(g_wdg_jb) == 0) v = *a; else g_wdg_fault = 1;
    g_wdg_guard = 0;
    return v;
}
static inline int wdg_try_write(volatile uint32_t *a, uint32_t v)
{
    g_wdg_fault = 0; g_wdg_guard = 1;
    if (setjmp(g_wdg_jb) == 0) { *a = v; g_wdg_guard = 0; return 1; }
    g_wdg_guard = 0; return 0;
}

/* Flags decided once at boot (which watchdogs are safely accessible). */
typedef struct { uint8_t iwdg_ok; uint8_t wwdg_present; uint8_t wwdg_window; uint8_t _pad; } wdg_state_t;
extern wdg_state_t g_wdg;

/* Called before touching anything risky and periodically thereafter (guarded reads inside). */
static inline void wdg_probe(uint32_t boot_out[8])
{
    /* IWDG: refresh is always safe (no unlock needed); confirm by a guarded write. */
    g_wdg.iwdg_ok = (uint8_t)wdg_try_write(&IWDG_S_KR, IWDG_KEY_RELOAD);
    uint32_t apb1 = wdg_try_read(&RCC_S_APB1ENR1, 0);
    g_wdg.wwdg_present = (uint8_t)((apb1 & RCC_WWDGEN) && !g_wdg_fault);
    uint32_t wcr = 0xFFFFFFFFu, wcfr = 0xFFFFFFFFu;
    if (g_wdg.wwdg_present) {
        wcr  = wdg_try_read(&WWDG_S_CR, 0xFFFFFFFFu);
        wcfr = wdg_try_read(&WWDG_S_CFR, 0xFFFFFFFFu);
        g_wdg.wwdg_window = (uint8_t)(wcfr & 0x7Fu);
        if (!(wcr & WWDG_WDGA)) g_wdg.wwdg_present = 0;   /* clock on but WWDG not activated */
    }
    (void)wcr; (void)wcfr;
    boot_out[0] = wdg_try_read(&IWDG_S_SR, 0xFFFFFFFFu);
    boot_out[1] = wdg_try_read(&IWDG_S_WINR, 0xFFFFFFFFu);   /* window: < RLR ⇒ windowed IWDG */
    boot_out[2] = wdg_try_read(&RCC_S_RSR, 0xFFFFFFFFu);     /* last reset cause flags          */
    boot_out[3] = wdg_try_read(&IWDG_S_RLR, 0xFFFFFFFFu);
    boot_out[4] = g_wdg.iwdg_ok;
    boot_out[5] = wdg_try_read(&IWDG_S_PR, 0xFFFFFFFFu);
    /* boot_out[6]=defang result, [7]=phase — filled by main. */
}

/* Defang a (possibly windowed) IWDG so free kicking can never trigger a reset:
 * unlock, set the window to max (disables the window), set max reload. The counter keeps
 * running but reset only occurs on underflow, which our per-loop refresh prevents.
 * Returns 1 if the register writes did not fault. */
static inline int wdg_defang_iwdg(uint32_t *winr_after)
{
    if (!wdg_try_write(&IWDG_S_KR, IWDG_KEY_UNLOCK)) return 0;
    (void)wdg_try_write(&IWDG_S_WINR, IWDG_RL_MAX);          /* window = max ⇒ no window; also reloads */
    (void)wdg_try_write(&IWDG_S_RLR, IWDG_RL_MAX);           /* longest period                          */
    (void)wdg_try_write(&IWDG_S_KR, IWDG_KEY_RELOAD);        /* reload + re-lock                        */
    *winr_after = wdg_try_read(&IWDG_S_WINR, 0xFFFFFFFFu);
    return 1;
}

/* Service both watchdogs. No setjmp here (only touches confirmed-safe regs), so it is cheap
 * enough for the tight spin loop. WWDG: reload T to max only while T<=W (writing above the
 * window would itself trigger a reset), keeping WDGA set. */
static inline void wdg_feed(void)
{
    if (g_wdg.iwdg_ok) IWDG_S_KR = IWDG_KEY_RELOAD;
    if (g_wdg.wwdg_present) {
        uint32_t cr = WWDG_S_CR;
        if ((cr & 0x7Fu) <= g_wdg.wwdg_window) WWDG_S_CR = WWDG_WDGA | 0x7Fu;
    }
}

static inline void wdg_freeze_in_debug(void)
{
    (void)wdg_try_write(&DBGMCU_S_APB4FZ1,  DBGMCU_S_APB4FZ1  | DBG_IWDG_STOP);
    (void)wdg_try_write(&DBGMCU_S_APB1LFZ1, DBGMCU_S_APB1LFZ1 | DBG_WWDG1_STOP);
}
#endif
