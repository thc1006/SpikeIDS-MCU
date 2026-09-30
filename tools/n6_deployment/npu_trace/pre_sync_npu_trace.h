#ifndef N6_NPU_TRACE_H
#define N6_NPU_TRACE_H
#include <stddef.h>
#include <stdint.h>
#include "stai.h"
#include "ll_aton_NN_interface.h"

#define NPU_TRACE_EPOCHS 40u
#define NPU_TRACE_TABLE_ITEMS 41u /* Includes one nonexecuted last_eb sentinel. */
#define NPU_TRACE_EVENTS 160u
#define NPU_TRACE_MAGIC 0x4e365452u
enum npu_trace_error {
    NPU_TRACE_OK=0, NPU_TRACE_ARGUMENT=1, NPU_TRACE_TABLE=2,
    NPU_TRACE_STATE=3, NPU_TRACE_EVENT=4, NPU_TRACE_POINTER=5,
    NPU_TRACE_CHANGED=6, NPU_TRACE_OVERFLOW=7, NPU_TRACE_INCOMPLETE=8,
    NPU_TRACE_RUN_FAILED=9, NPU_TRACE_REGISTRATION=10
};
typedef uint32_t (*npu_trace_counter_fn)(void *cookie);
typedef struct {
    uint32_t sequence, epoch_index, compiler_epoch, event_type;
    uint32_t raw_flags, raw_wait_mask, payload_address_low, payload_address_high;
    uint32_t cpu_counter_raw, cpu_counter_delta_mod32;
} npu_trace_event_t;
/* Fixed-width record. Read only after the caller has stopped publishing it.
 * This is not a seqlock mailbox or an atomic live-host publication protocol. */
typedef struct {
    uint32_t magic, version, run_id, active, complete, error;
    uint32_t received, stored, matched, completed_epochs;
    uint32_t completed_pure_hw, completed_hybrid, completed_pure_sw;
    uint32_t counter_present, counter_wrap_observed, runtime_return_code;
    uint32_t hardware_independently_proven, performance_accepted;
    npu_trace_event_t events[NPU_TRACE_EVENTS];
} npu_trace_log_t;
typedef struct {
    volatile npu_trace_log_t *log;
    const EpochBlock_ItemTypeDef *table;
    EpochBlock_ItemTypeDef original[NPU_TRACE_TABLE_ITEMS];
    npu_trace_counter_fn counter;
    void *counter_cookie;
    uint32_t prepared, last_run_id, previous_counter;
} npu_trace_context_t;

int npu_trace_prepare(npu_trace_context_t *ctx, volatile npu_trace_log_t *log,
                      const EpochBlock_ItemTypeDef *table, size_t count,
                      npu_trace_counter_fn counter, void *counter_cookie);
int npu_trace_begin(npu_trace_context_t *ctx, uint32_t fresh_run_id);
void npu_trace_callback(void *cookie, const stai_event_type event_type,
                        const void *event_payload);
int npu_trace_finish(npu_trace_context_t *ctx, stai_return_code runtime_result);
/* Bind after successful network init, before begin/run. No model execution. */
stai_return_code npu_trace_bind(stai_network *network, npu_trace_context_t *ctx,
                              volatile npu_trace_log_t *log,
                              npu_trace_counter_fn counter, void *counter_cookie);
#endif
