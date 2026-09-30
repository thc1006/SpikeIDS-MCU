#ifndef N6_PLATFORM_STAGE_MAILBOX_H
#define N6_PLATFORM_STAGE_MAILBOX_H
#include "platform_init.h"
#define STAGE_MAGIC UINT32_C(0x4e365349)
#define STAGE_MAILBOX UINT32_C(0x34188000)
enum { STAGE_INITIALIZING=1, STAGE_READY=2, STAGE_REJECTED=3, STAGE_FAULT=4 };
typedef struct {
    uint32_t magic,version,struct_bytes,state,sequence,heartbeat,host_nonce,echo_nonce;
    uint32_t entry_vtor,entry_control,entry_primask,entry_msp,cpuid,ccr,ipsr,control;
    uint32_t cfsr,hfsr,dfsr,afsr,mmfar,bfar,fault_ipsr,fault_exc_return,fault_msp,fault_psp;
    uint32_t ready_for_payload,model_executed,energy_measured,board_accepted,reserved[2];
    platform_report_t platform;
    uint32_t padding[400];
} stage_mailbox_t;
_Static_assert(sizeof(stage_mailbox_t)==4096,"stage mailbox size");
_Static_assert(offsetof(stage_mailbox_t,sequence)==16,"sequence ABI");
_Static_assert(offsetof(stage_mailbox_t,host_nonce)==24,"nonce ABI");
_Static_assert(offsetof(stage_mailbox_t,cfsr)==64,"fault assembly ABI");
_Static_assert(offsetof(stage_mailbox_t,fault_ipsr)==88,"fault assembly ABI");
_Static_assert(offsetof(stage_mailbox_t,platform)==128,"platform ABI");
extern volatile stage_mailbox_t g_stage;
#endif
