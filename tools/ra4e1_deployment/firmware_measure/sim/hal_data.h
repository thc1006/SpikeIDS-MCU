/* Host-simulation shim for rm01.c (test only; never linked into firmware).
 * Every timer (GPT321) access advances simulated time, so rm01.c's busy-wait loops run
 * unchanged; marker writes are logged with their simulated cycle time. */
#ifndef RM01_SIM_HAL_DATA_H
#define RM01_SIM_HAL_DATA_H
#include <stddef.h>
#include <stdint.h>

typedef struct { int unused; } can_callback_args_t;
typedef struct { volatile uint32_t CYCCNT, CTRL; } sim_dwt_t;
typedef struct { volatile uint32_t GTCNT, GTCR, GTUDDTYC, GTPR; } sim_gpt_t;
typedef struct { volatile uint32_t DEMCR; } sim_dcb_t;
typedef struct { volatile uint32_t CPUID; } sim_scb_t;
typedef struct { volatile uint16_t FCACHEE; volatile uint8_t FLWT; } sim_fcache_t;
typedef struct { volatile uint32_t SCKDIVCR; volatile uint8_t SCKSCR; volatile uint16_t PLLCCR;
                 volatile uint8_t PLLCR, HOCOCR, MOCOCR, OPCCR; } sim_system_t;
extern sim_system_t sim_system;
extern uint32_t sim_ofs1_sec;
typedef struct { volatile uint32_t PCNTR3; } sim_port_t;

sim_dwt_t *sim_dwt(void);
sim_gpt_t *sim_gpt(void);
void sim_module_start(int channel);
extern sim_dcb_t sim_dcb;
extern sim_scb_t sim_scb;
extern sim_fcache_t sim_fcache;
extern sim_port_t sim_port1;
extern uint32_t SystemCoreClock;
void sim_dsb(void);
void sim_nop(void);
void sim_pincfg(uint32_t pin, uint32_t cfg);

#define DWT (sim_dwt())
#define R_GPT1 (sim_gpt())
#define R_BSP_MODULE_START(ip, ch) sim_module_start(ch)
#define DCB (&sim_dcb)
#define SCB (&sim_scb)
#define R_FCACHE (&sim_fcache)
#define R_SYSTEM (&sim_system)
#define RM_OFS1_SEC_PTR (&sim_ofs1_sec)
#define R_PORT1 (&sim_port1)
#define DWT_CTRL_CYCCNTENA_Msk (1UL)
#define DWT_CTRL_NOCYCCNT_Msk (1UL << 25)
#define DCB_DEMCR_TRCENA_Msk (1UL << 24)
#define BSP_IO_PORT_01_PIN_07 0x0107u
#define BSP_IO_PFS_PDR_OUTPUT (4U)
#define __DSB() sim_dsb()
#define __DMB() sim_dsb()
#define __NOP() sim_nop()
#define __WFI() sim_nop()
static inline void R_BSP_PinAccessEnable(void) {}
static inline void R_BSP_PinAccessDisable(void) {}
#define R_BSP_PinCfg(p, c) sim_pincfg((p), (c))
#endif
