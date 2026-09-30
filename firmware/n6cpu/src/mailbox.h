/* NPU measurement mailbox (fixed address in AXISRAM1, clear of code+stack and the NPU pools). */
#ifndef N6B_MAILBOX_H
#define N6B_MAILBOX_H
#include <stdint.h>
#define MB_ADDR    0x340F8000UL
#define MB_MAGIC   0x4E365542UL   /* 'N6UB' */
#define MB_VERSION 1
#define MB_MAXRES  512
enum { MB_IDLE=0, MB_RUNNING=1, MB_DONE=2, MB_ERROR=3, MB_FAULT=4 };
enum { CMD_NOP=0, CMD_NPU_INFER=1 };   /* param[0]=iterations */
typedef struct {
    volatile uint32_t magic, version, state, cmd, seq, ack, err, n_results;
    volatile uint32_t param[8];
    volatile uint32_t boot[8];        /* [0]=CPUID [1]=init_rc [2]=stai_init_rc [3]=in_bytes [4]=out_bytes [5]=IWDG_ok [6]=cpu_hz [7]=phase */
    volatile uint32_t last_rc, last_argmax, sink;
    volatile uint32_t cycles[MB_MAXRES];
} mailbox_t;
#define MB ((mailbox_t *)MB_ADDR)
#endif
