/* Offline-built adapter, not a bootloader or board-ready power experiment.
 * REQUIRED before platform_ack: reviewed secure execution/SRAM clocks/RIF/NPU
 * setup, exact SRAM weights at 0x34200000, CPU D-cache disabled or noncacheable mailbox,
 * and a reviewed watchdog policy. This image does not configure those domains.
 * No USB, serial, GPIO, power, flash or self-test inference occurs at boot. */
#include <stdint.h>
#include <string.h>
#include "stm32n6xx.h"
#include "stai_nsl_qcfs_seed0.h"
#include "mailbox.h"

#if LL_ATON_RT_MODE != LL_ATON_RT_POLLING
#error "This IRQ-masked RAM adapter requires ATON polling mode"
#endif

_Static_assert(sizeof(float) == 4, "FP32 ABI required");
_Static_assert(STAI_NSL_QCFS_SEED0_IN_NUM == 1 && STAI_NSL_QCFS_SEED0_OUT_NUM == 1, "One I/O tensor required");
_Static_assert(STAI_NSL_QCFS_SEED0_IN_1_SIZE_BYTES == 164, "Expected 41 FP32 inputs");
_Static_assert(STAI_NSL_QCFS_SEED0_OUT_1_SIZE_BYTES == 20, "Expected five FP32 logits");
_Static_assert(STAI_NSL_QCFS_SEED0_IN_1_FORMAT == STAI_FORMAT_FLOAT32 &&
               STAI_NSL_QCFS_SEED0_OUT_1_FORMAT == STAI_FORMAT_FLOAT32, "FP32 I/O required");
_Static_assert(STAI_NSL_QCFS_SEED0_IN_1_ALIGNMENT == 32, "Input alignment must be 32");
_Static_assert((S6_RUNTIME_IO_ADDRESS % 32) == 0, "Runtime I/O address is not aligned");

volatile s6_mailbox_t g_mailbox __attribute__((section(".mailbox"), aligned(32)));
static uint8_t context[STAI_NSL_QCFS_SEED0_CONTEXT_SIZE] __attribute__((aligned(32)));
static uint32_t input_copy[48] __attribute__((aligned(32)));
static uint32_t output_copy[8] __attribute__((aligned(32)));

static int finite_word(uint32_t word) { return (word & UINT32_C(0x7F800000)) != UINT32_C(0x7F800000); }
static void park_error(int code)
{
    g_mailbox.adapter_error = code;
    __DMB(); g_mailbox.state = S6_ERROR; __DSB();
    for (;;) __NOP();
}
static void checked(unsigned index, stai_return_code rc)
{
    g_mailbox.api_status[index] = (int32_t)rc;
    if (rc != STAI_SUCCESS) park_error(0); /* exact vendor code remains in api_status */
}
static int tensor_ok(const stai_tensor *t, int width, int bytes)
{
    return t && t->format == STAI_FORMAT_FLOAT32 && t->size_bytes == bytes &&
           t->shape.size == 2 && t->shape.data && t->shape.data[0] == 1 &&
           t->shape.data[1] == width && t->scale.size == 0 && t->zeropoint.size == 0;
}
static int request_unchanged(uint32_t seq, uint32_t row)
{
    if (g_mailbox.request_sequence != seq || g_mailbox.row_id != row ||
        g_mailbox.platform_ack != S6_PLATFORM_ACK || g_mailbox.command != S6_COMMAND_INFER ||
        g_mailbox.input_count != 41) return 0;
    for (unsigned i=0; i<41; ++i)
        if (g_mailbox.input_words[i] != input_copy[i]) return 0;
    return 1;
}

int main(void)
{
    memset((void *)&g_mailbox, 0, sizeof g_mailbox);
    g_mailbox.version = S6_PROTOCOL;
    g_mailbox.struct_bytes = sizeof g_mailbox;
    g_mailbox.cpuid = SCB->CPUID;
    memcpy((void *)g_mailbox.model_sha256,
           "22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d", 65);
    memcpy((void *)g_mailbox.weights_sha256,
           "cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec", 65);
    for (unsigned i=0; i<6; ++i) g_mailbox.api_status[i] = INT32_MIN;
    g_mailbox.weights_address=S6_WEIGHTS_ADDRESS;
    g_mailbox.weights_reserved_bytes=S6_WEIGHTS_RESERVED_BYTES;
    g_mailbox.activation_address=S6_RUNTIME_IO_ADDRESS;
    g_mailbox.activation_reserved_bytes=S6_ACTIVATION_RESERVED_BYTES;
    g_mailbox.weights_bytes=145457;
    g_mailbox.deployment_tag=S6_DEPLOYMENT_TAG;
    g_mailbox.state = S6_WAIT_PLATFORM;
    __DMB(); g_mailbox.magic = S6_MAGIC; __DSB();
    /* This token is an explicit host prerequisite acknowledgement, not a
     * cryptographic or physical attestation. No host uploader is provided. */
    while (g_mailbox.platform_ack != S6_PLATFORM_ACK) __NOP();
    if (SCB->CCR & SCB_CCR_DC_Msk) park_error(S6_E_CACHE);
    g_mailbox.state = S6_INITIALIZING;
    SCB->CPACR |= (3u << 20) | (3u << 22); __DSB(); __ISB();
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0; DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

    stai_network *network = (stai_network *)context;
    stai_network_info info;
    stai_ptr in[1] = {0}, out[1] = {0};
    stai_size nin=1, nout=1;
    g_mailbox.stage=1; checked(0, stai_nsl_qcfs_seed0_init(network));
    g_mailbox.stage=2; checked(1, stai_nsl_qcfs_seed0_get_info(network, &info));
    if (info.n_inputs != 1 || info.n_outputs != 1 ||
        !tensor_ok(info.inputs,41,164) || !tensor_ok(info.outputs,5,20)) park_error(S6_E_LAYOUT);
    g_mailbox.stage=3; checked(2, stai_nsl_qcfs_seed0_get_inputs(network,in,&nin));
    g_mailbox.stage=4; checked(3, stai_nsl_qcfs_seed0_get_outputs(network,out,&nout));
    g_mailbox.input_address=(uint32_t)(uintptr_t)in[0];
    g_mailbox.output_address=(uint32_t)(uintptr_t)out[0];
    if (nin != 1 || nout != 1 || (uintptr_t)in[0] != S6_RUNTIME_IO_ADDRESS ||
        (uintptr_t)out[0] != S6_RUNTIME_IO_ADDRESS) park_error(S6_E_LAYOUT);
    /* Input/output alias is intentional: different lifetimes in the fixed
     * generated model. Output is copied out before the next input is written. */
    g_mailbox.stage=0; __DMB(); g_mailbox.state=S6_READY; __DSB();
    uint32_t previous=0;
    for (;;) {
        uint32_t seq=g_mailbox.request_sequence;
        if (seq == previous) { __NOP(); continue; }
        if (seq != previous + 1 || seq == 0) park_error(S6_E_CHANGED);
        if (g_mailbox.platform_ack != S6_PLATFORM_ACK) park_error(S6_E_PLATFORM);
        if (g_mailbox.command != S6_COMMAND_INFER) park_error(S6_E_COMMAND);
        if (g_mailbox.input_count != 41) park_error(S6_E_INPUT);
        const uint32_t row=g_mailbox.row_id;
        g_mailbox.output_count=0; g_mailbox.run_cycles=0;
        g_mailbox.stage=5; g_mailbox.state=S6_RUNNING; __DMB();
        for (unsigned i=0; i<41; ++i) {
            input_copy[i]=g_mailbox.input_words[i];
            if (!finite_word(input_copy[i])) park_error(S6_E_INPUT);
        }
        __DMB();
        if (!request_unchanged(seq,row)) park_error(S6_E_CHANGED);
        memcpy(in[0], input_copy, 164);
        __DSB(); uint32_t begin=DWT->CYCCNT;
        stai_return_code rc=stai_nsl_qcfs_seed0_run(network,STAI_MODE_SYNC);
        __DSB(); uint32_t end=DWT->CYCCNT;
        g_mailbox.run_cycles=end-begin; /* CPU cycles around full mixed run, not NPU-only time */
        checked(4,rc);
        checked(5,stai_nsl_qcfs_seed0_get_error(network));
        memcpy(output_copy,out[0],20);
        for (unsigned i=0; i<5; ++i) g_mailbox.output_words[i]=output_copy[i];
        g_mailbox.output_count=5;
        for (unsigned i=0; i<5; ++i) if (!finite_word(output_copy[i])) park_error(S6_E_OUTPUT);
        if (!request_unchanged(seq,row)) park_error(S6_E_CHANGED);
        g_mailbox.completed_row_id=row; g_mailbox.stage=0;
        previous=seq;
        g_mailbox.state=S6_DONE; __DMB(); g_mailbox.response_sequence=seq; __DSB();
    }
}
