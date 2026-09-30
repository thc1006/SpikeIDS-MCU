/* SM03: original inference loop and runtime ordering, audited Q/DQ ABI repair. */
#include "mailbox.h"
#include "stai_nsl_qcfs_seed0.h"
static stai_return_code initialize_runtime_then_model(stai_network *network);
#define stai_nsl_qcfs_seed0_init initialize_runtime_then_model
#include "../firmware_sram/main.c"
#undef stai_nsl_qcfs_seed0_init

static stai_return_code initialize_runtime_then_model(stai_network *network)
{
    if (!network || g_mailbox.platform_ack != S6_PLATFORM_ACK ||
        g_mailbox.state != S6_INITIALIZING || g_mailbox.stage != 1 ||
        g_mailbox.input_padding[0] || g_mailbox.input_padding[1] ||
        g_mailbox.input_padding[2])
        return STAI_ERROR_NETWORK_INVALID_CONTEXT_HANDLE;
    g_mailbox.stage = 6;
    g_mailbox.input_padding[0] = S6_RUNTIME_RECEIPT;
    g_mailbox.input_padding[1] = (uint32_t)INT32_MIN;
    g_mailbox.input_padding[2] = 1;
    stai_return_code rc = stai_runtime_init();
    g_mailbox.input_padding[1] = (uint32_t)rc;
    if (rc != STAI_SUCCESS) return rc;
    g_mailbox.stage = 1;
    return stai_nsl_qcfs_seed0_init(network);
}

_Noreturn void s6_compat_fail(void)
{
    park_error(-8); /* unrecognized/corrupt fixed Q/DQ descriptor */
    __builtin_unreachable();
}
#include "compat.c"
