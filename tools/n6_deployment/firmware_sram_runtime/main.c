/* Additive repair: keep the frozen S6 model and inference loop unchanged. */
#include "mailbox.h"
#include "stai_nsl_qcfs_seed0.h"
static stai_return_code initialize_runtime_then_model(stai_network *network);

#ifndef S6_RUNTIME_TEST_ONLY
/* Only the model-init call site is replaced. The generated model is not edited. */
#define stai_nsl_qcfs_seed0_init initialize_runtime_then_model
#include "../firmware_sram/main.c"
#undef stai_nsl_qcfs_seed0_init
#endif

static stai_return_code initialize_runtime_then_model(stai_network *network)
{
    /* Refuse early/repeated calls; never initialize hardware before ACK. */
    if (!network || g_mailbox.platform_ack != S6_PLATFORM_ACK ||
        g_mailbox.state != S6_INITIALIZING || g_mailbox.stage != 1 ||
        g_mailbox.input_padding[0] || g_mailbox.input_padding[1] ||
        g_mailbox.input_padding[2])
        return STAI_ERROR_NETWORK_INVALID_CONTEXT_HANDLE;
    g_mailbox.stage = 6; /* global runtime init, distinct from model init */
    g_mailbox.input_padding[0] = S6_RUNTIME_RECEIPT;
    g_mailbox.input_padding[1] = (uint32_t)INT32_MIN;
    g_mailbox.input_padding[2] = 1;
    stai_return_code rc = stai_runtime_init();
    g_mailbox.input_padding[1] = (uint32_t)rc;
    if (rc != STAI_SUCCESS) return rc;
    g_mailbox.stage = 1;
    return stai_nsl_qcfs_seed0_init(network);
}
