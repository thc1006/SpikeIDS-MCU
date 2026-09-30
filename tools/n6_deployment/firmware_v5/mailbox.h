#ifndef V5_N6_MAILBOX_H
#define V5_N6_MAILBOX_H
#include <stddef.h>
#include <stdint.h>

#define V5_MAGIC UINT32_C(0x56354E36)
#define V5_PROTOCOL 1u
#define V5_PLATFORM_ACK UINT32_C(0x504C4154)
#define V5_MAILBOX_ADDRESS UINT32_C(0x340F8000)
#define V5_RUNTIME_IO_ADDRESS UINT32_C(0x342E0000)
enum { V5_WAIT_PLATFORM=1, V5_INITIALIZING=2, V5_READY=3, V5_RUNNING=4,
       V5_DONE=5, V5_ERROR=6, V5_FAULT=7 };
enum { V5_COMMAND_INFER=1 };
enum { V5_E_PLATFORM=-1, V5_E_COMMAND=-2, V5_E_INPUT=-3, V5_E_CHANGED=-4,
       V5_E_LAYOUT=-5, V5_E_OUTPUT=-6, V5_E_CACHE=-7 };

/* One outstanding transaction. Host writes payload first, then request_sequence
 * last, and must not touch the request until response_sequence matches it.
 * All FP32 data is transported as raw uint32 words, with no conversion. */
typedef struct {
    uint32_t magic, version, struct_bytes, state;
    uint32_t platform_ack, request_sequence, response_sequence, command;
    uint32_t row_id, input_count, output_count, stage;
    int32_t api_status[6]; /* init, info, get_inputs, get_outputs, run, get_error */
    int32_t adapter_error;
    uint32_t completed_row_id, run_cycles, cfsr, hfsr, cpuid;
    uint32_t input_address, output_address;
    uint32_t reserved[6];
    uint32_t input_words[41];
    uint32_t input_padding[7];
    uint32_t output_words[5];
    uint32_t output_padding[3];
    char model_sha256[65];
    char weights_sha256[65];
    uint8_t tail_padding[30];
} v5_mailbox_t;
_Static_assert(offsetof(v5_mailbox_t, input_words) == 128, "Input must be cache-line aligned");
_Static_assert(offsetof(v5_mailbox_t, output_words) == 320, "Output alignment changed");
_Static_assert(sizeof(v5_mailbox_t) == 512, "Protocol size changed");
extern volatile v5_mailbox_t g_mailbox;
#endif
