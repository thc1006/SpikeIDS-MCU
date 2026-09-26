#ifndef N6_PROBE_MAILBOX_H
#define N6_PROBE_MAILBOX_H
#include <stdint.h>
#include <stddef.h>
#define PROBE_MAGIC UINT32_C(0x4e365052)
#define PROBE_MAILBOX UINT32_C(0x34185000)
enum { INITIALIZING=1, RUNNING=2, CACHE_UNSUPPORTED=3, FAULT=4, ENTRY_REJECTED=5 };
typedef struct {
    uint32_t magic, version, struct_bytes, state;
    uint32_t sequence, heartbeat, host_nonce, echo_nonce;
    uint32_t cpuid, ccr, control, vtor;
    uint32_t entry_vtor, entry_control, entry_primask, entry_msp;
    uint32_t primask, ipsr, msp, msplim;
    uint32_t cfsr, hfsr, dfsr, afsr, mmfar, bfar;
    uint32_t fault_ipsr, fault_exc_return, fault_msp, fault_psp;
    uint32_t platform_initialized, reserved0, reserved[32];
} probe_mailbox_t;
_Static_assert(sizeof(probe_mailbox_t)==256, "mailbox size");
_Static_assert(offsetof(probe_mailbox_t, sequence)==16, "sequence");
_Static_assert(offsetof(probe_mailbox_t, host_nonce)==24, "nonce");
_Static_assert(offsetof(probe_mailbox_t, cfsr)==80, "fault asm offsets");
_Static_assert(offsetof(probe_mailbox_t, fault_ipsr)==104, "fault asm offsets");
_Static_assert(offsetof(probe_mailbox_t, platform_initialized)==120, "scope flag");
extern volatile probe_mailbox_t g_mailbox;
#endif
