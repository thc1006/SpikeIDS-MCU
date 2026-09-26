#ifndef S6_N6_MAILBOX_H
#define S6_N6_MAILBOX_H
#include <stddef.h>
#include <stdint.h>

#define S6_MAGIC UINT32_C(0x53364E36)
#define S6_PROTOCOL 1u
#define S6_PLATFORM_ACK UINT32_C(0x504C4154)
#define S6_MAILBOX_ADDRESS UINT32_C(0x340F8000)
#define S6_RUNTIME_IO_ADDRESS UINT32_C(0x34240000)
#define S6_WEIGHTS_ADDRESS UINT32_C(0x34200000)
#define S6_WEIGHTS_RESERVED_BYTES UINT32_C(0x40000)
#define S6_ACTIVATION_RESERVED_BYTES UINT32_C(0x4000)
#define S6_DEPLOYMENT_TAG UINT32_C(0x534D3031)
enum { S6_WAIT_PLATFORM=1, S6_INITIALIZING=2, S6_READY=3, S6_RUNNING=4,
       S6_DONE=5, S6_ERROR=6, S6_FAULT=7 };
enum { S6_COMMAND_INFER=1 };
enum { S6_E_PLATFORM=-1, S6_E_COMMAND=-2, S6_E_INPUT=-3, S6_E_CHANGED=-4,
       S6_E_LAYOUT=-5, S6_E_OUTPUT=-6, S6_E_CACHE=-7 };

/* One outstanding transaction. Host writes payload first, then request_sequence
 * last, and must not touch the request until a stable DONE+response_sequence
 * matches it. response_sequence is the final DMB-ordered completion commit.
 * All FP32 data is transported as raw uint32 words, with no conversion. */
typedef struct {
    uint32_t magic, version, struct_bytes, state;
    uint32_t platform_ack, request_sequence, response_sequence, command;
    uint32_t row_id, input_count, output_count, stage;
    int32_t api_status[6]; /* init, info, get_inputs, get_outputs, run, get_error */
    int32_t adapter_error;
    uint32_t completed_row_id, run_cycles, cfsr, hfsr, cpuid;
    uint32_t input_address, output_address;
    uint32_t weights_address, weights_reserved_bytes, activation_address,
             activation_reserved_bytes, weights_bytes, deployment_tag;
    uint32_t input_words[41];
    uint32_t input_padding[7];
    uint32_t output_words[5];
    uint32_t output_padding[3];
    char model_sha256[65];
    char weights_sha256[65];
    uint8_t tail_padding[30];
} s6_mailbox_t;
_Static_assert(offsetof(s6_mailbox_t, input_words) == 128, "Input must be cache-line aligned");
_Static_assert(offsetof(s6_mailbox_t, output_words) == 320, "Output alignment changed");
_Static_assert(sizeof(s6_mailbox_t) == 512, "Protocol size changed");
extern volatile s6_mailbox_t g_mailbox;
#endif
