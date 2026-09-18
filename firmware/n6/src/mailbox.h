/* Host <-> firmware mailbox at a fixed address (see linker/n6_sram3.ld). Every field is a
 * 32-bit word so pyOCD can read/write it with plain word accesses. */
#ifndef N6_MAILBOX_H
#define N6_MAILBOX_H
#include <stdint.h>

#define MB_ADDR      0x34260000UL
#define MB_MAGIC     0x4E36424EUL      /* 'N6BN' */
#define MB_VERSION   3
#define MB_MAX_RES   1024
#define MB_N_PARAM   16
#define MB_N_INFO    64
#define MB_N_BOOT    8

enum mb_state { MB_IDLE = 0, MB_RUNNING = 1, MB_DONE = 2, MB_ERROR = 3, MB_FAULT = 4 };

enum mb_cmd {
    CMD_NOP        = 0,   /* timing overhead of an empty region                       */
    CMD_READ_BW    = 1,   /* sequential read: p1=addr p2=bytes p3=cache p4=width       */
    CMD_MLP_FP32   = 2,   /* naive FP32 MLP: p1=weights p2=act buf p3=cache p5..p9=dims */
    CMD_MLP_S8     = 3,   /* CMSIS-NN INT8 MLP: p1=weights p2=work buf p3=cache p5..p9  */
    CMD_FILL       = 4,   /* fill p1..p1+p2 with LCG bytes (seed p4) — data prep        */
    CMD_MEMCPY     = 5,   /* memcpy p2 bytes p1 -> p4                                   */
    CMD_PEEK       = 6,   /* read one word at p1 into results[0] (bus-fault probe)      */
};

/* cache mode bits (param[3]) */
#define CM_ICACHE     (1u << 0)
#define CM_DCACHE     (1u << 1)
#define CM_INVAL_EACH (1u << 2)   /* invalidate D-cache before every iteration (cold reads) */

/* read-bandwidth kernel width (param[4]) */
enum { RW_LDR32 = 0, RW_LDRD64 = 1, RW_MVE128 = 2, RW_LDM32x8 = 3 };

typedef struct {
    volatile uint32_t magic;
    volatile uint32_t version;
    volatile uint32_t boot[8];   /* fast diagnostic snapshot, valid once magic is set */
    volatile uint32_t state;
    volatile uint32_t cmd;
    volatile uint32_t seq;             /* host bumps to start; fw copies into ack */
    volatile uint32_t ack;
    volatile uint32_t err;
    volatile uint32_t n_results;
    volatile uint32_t param[MB_N_PARAM];
    volatile uint32_t info[MB_N_INFO]; /* static platform info, see bench.c */
    volatile uint32_t sink;            /* optimisation barrier for kernels */
    volatile uint32_t results[MB_MAX_RES];
} mailbox_t;

#define MB ((mailbox_t *)MB_ADDR)

/* boot[] fast-snapshot indices (readable the instant magic appears) */
enum {
    BOOT_IWDG_SR = 0, BOOT_WWDG_CR, BOOT_RCC_APB1ENR1, BOOT_WWDG_CFR,
    BOOT_IWDG_OK, BOOT_WWDG_PRESENT, BOOT_SETUP_FAULT, BOOT_PHASE,
};

/* info[] indices */
enum {
    INFO_CPUID = 0, INFO_CCR_AT_ENTRY, INFO_MPU_CTRL_AT_ENTRY, INFO_MPU_TYPE,
    INFO_CPU_HZ_HAL, INFO_SYS_HZ_HAL, INFO_XSPI2_KER_HZ_HAL, INFO_XSPI1_KER_HZ_HAL,
    INFO_XSPI2_CR, INFO_XSPI2_DCR1, INFO_XSPI2_DCR2, INFO_XSPI2_CCR, INFO_XSPI2_TCR,
    INFO_RCC_AHB5ENR, INFO_RCC_APB5ENR, INFO_LTDC_WAS_ON,
    INFO_CLIDR, INFO_CCSIDR_I, INFO_CCSIDR_D, INFO_FPSCR,
    INFO_CFSR_LAST, INFO_HFSR_LAST, INFO_BFAR_LAST, INFO_FAULT_PC,
    INFO_MB_VERSION, INFO_BUILD_ID, INFO_IWDG_SR, INFO_WWDG_CR,
};
#endif
