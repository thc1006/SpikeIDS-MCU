#include "npu_trace.h"

_Static_assert(LL_ATON_RT_Callbacktype_PRE_START==0 && LL_ATON_RT_Callbacktype_POST_START==1 &&
               LL_ATON_RT_Callbacktype_PRE_END==2 && LL_ATON_RT_Callbacktype_POST_END==3,
               "ST3 callback ABI changed");
_Static_assert(EpochBlock_Flags_pure_hw==16 && EpochBlock_Flags_pure_sw==32 &&
               EpochBlock_Flags_hybrid==64 && EpochBlock_Flags_last_eb==8,
               "ST3 epoch flags changed");
_Static_assert(sizeof(npu_trace_event_t)==40, "fixed record size");
_Static_assert(sizeof(npu_trace_log_t)==6472, "fixed log size");
/* Literal projection of the pinned SRAM generated model, not epoch labels 0..40. */
static const uint16_t epoch_numbers[NPU_TRACE_EPOCHS]={
    1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,18,19,20,21,22,
    23,24,25,26,27,28,30,31,32,33,34,35,36,37,38,39,40,42,43,44};
static const uint16_t expected_flags[NPU_TRACE_EPOCHS]={
    35,19,35,35,67,19,35,35,35,35,35,35,35,35,35,19,19,35,35,35,
    35,35,35,35,35,35,19,19,35,35,35,35,35,35,35,35,35,19,19,35};
static const uint32_t expected_wait[NPU_TRACE_EPOCHS]={
    0,4,0,0,0,1,0,0,0,0,0,0,0,0,0,32,256,0,0,0,
    0,0,0,0,0,0,128,32,0,0,0,0,0,0,0,0,0,4,4,0};

static void clear_log(volatile npu_trace_log_t *log)
{
    volatile unsigned char *p=(volatile unsigned char *)log;
    for (size_t i=0;i<sizeof(*log);++i) p[i]=0;
    log->magic=NPU_TRACE_MAGIC; log->version=1;
}
static int fail(npu_trace_context_t *ctx, enum npu_trace_error error)
{
    if (ctx && ctx->log) {
        if (ctx->log->error==NPU_TRACE_OK) ctx->log->error=(uint32_t)error;
        ctx->log->complete=0;
    }
    return -1;
}
static int same_item(const EpochBlock_ItemTypeDef *a, const EpochBlock_ItemTypeDef *b)
{
    if (a->start_epoch_block!=b->start_epoch_block || a->end_epoch_block!=b->end_epoch_block ||
        a->blob_address!=b->blob_address || a->wait_mask!=b->wait_mask || a->flags!=b->flags) return 0;
#ifdef LL_ATON_EB_DBG_INFO
    if (a->epoch_num!=b->epoch_num || a->last_epoch_num!=b->last_epoch_num ||
        a->in_streng_mask!=b->in_streng_mask || a->out_streng_mask!=b->out_streng_mask ||
        a->estimated_npu_cycles!=b->estimated_npu_cycles || a->estimated_tot_cycles!=b->estimated_tot_cycles) return 0;
#endif
    return 1;
}
static int unchanged(npu_trace_context_t *ctx)
{
    for (uint32_t i=0;i<NPU_TRACE_TABLE_ITEMS;++i)
        if (!same_item(&ctx->table[i],&ctx->original[i])) return 0;
    return 1;
}
int npu_trace_prepare(npu_trace_context_t *ctx, volatile npu_trace_log_t *log,
                      const EpochBlock_ItemTypeDef *table, size_t count,
                      npu_trace_counter_fn counter, void *counter_cookie)
{
    if (!ctx || !log) return -1;
    ctx->log=log;ctx->prepared=0;ctx->last_run_id=0;ctx->previous_counter=0;
    ctx->table=table;ctx->counter=counter;ctx->counter_cookie=counter_cookie;
    clear_log(log);
    if (!table || count!=NPU_TRACE_TABLE_ITEMS) return fail(ctx,NPU_TRACE_ARGUMENT);
    for (uint32_t i=0;i<NPU_TRACE_EPOCHS;++i) {
        const EpochBlock_ItemTypeDef *e=&table[i];
        if (e->flags!=expected_flags[i] || e->wait_mask!=expected_wait[i] || e->blob_address ||
            !e->end_epoch_block || ((e->start_epoch_block!=NULL)!=(expected_flags[i]==19)))
            return fail(ctx,NPU_TRACE_TABLE);
#ifdef LL_ATON_EB_DBG_INFO
        if (e->epoch_num!=epoch_numbers[i] || e->last_epoch_num!=epoch_numbers[i])
            return fail(ctx,NPU_TRACE_TABLE);
#endif
    }
    const EpochBlock_ItemTypeDef *end=&table[NPU_TRACE_EPOCHS];
    if (end->flags!=EpochBlock_Flags_last_eb || end->start_epoch_block ||
        end->end_epoch_block || end->wait_mask || end->blob_address) return fail(ctx,NPU_TRACE_TABLE);
    for (uint32_t i=0;i<NPU_TRACE_TABLE_ITEMS;++i) ctx->original[i]=table[i];
    ctx->prepared=1;
    return 0;
}
int npu_trace_begin(npu_trace_context_t *ctx, uint32_t fresh_run_id)
{
    if (!ctx || !ctx->log || !ctx->prepared) return -1;
    if (ctx->log->error || ctx->log->active || !fresh_run_id || fresh_run_id<=ctx->last_run_id)
        return fail(ctx,NPU_TRACE_STATE);
    if (!unchanged(ctx)) return fail(ctx,NPU_TRACE_CHANGED);
    clear_log(ctx->log);
    ctx->last_run_id=fresh_run_id;ctx->previous_counter=0;
    ctx->log->run_id=fresh_run_id;ctx->log->counter_present=(ctx->counter!=NULL);
    ctx->log->active=1;
    return 0;
}
void npu_trace_callback(void *cookie, const stai_event_type event_type, const void *payload)
{
    npu_trace_context_t *ctx=(npu_trace_context_t *)cookie;
    if (!ctx || !ctx->log) return;
    volatile npu_trace_log_t *log=ctx->log;
    if (log->received!=UINT32_MAX) ++log->received;
    if (log->error) return; /* First error latches; existing evidence is retained. */
    if (!ctx->prepared || !log->active) { (void)fail(ctx,NPU_TRACE_STATE);return; }
    if (log->stored>=NPU_TRACE_EVENTS) { (void)fail(ctx,NPU_TRACE_OVERFLOW);return; }
    uint32_t slot=log->stored, index=log->matched/4u;
    volatile npu_trace_event_t *row=&log->events[slot];
    row->sequence=slot;row->epoch_index=index;row->compiler_epoch=epoch_numbers[index];
    row->event_type=(uint32_t)event_type;
    uint64_t address=(uint64_t)(uintptr_t)payload;
    row->payload_address_low=(uint32_t)address;row->payload_address_high=(uint32_t)(address>>32);
    row->cpu_counter_raw=ctx->counter ? ctx->counter(ctx->counter_cookie) : 0;
    row->cpu_counter_delta_mod32=slot ? row->cpu_counter_raw-ctx->previous_counter : 0;
    if (slot && row->cpu_counter_raw<ctx->previous_counter) ++log->counter_wrap_observed;
    ctx->previous_counter=row->cpu_counter_raw;
    ++log->stored;
    if (payload!=&ctx->table[index]) { (void)fail(ctx,NPU_TRACE_POINTER);return; }
    /* Dereference only after exact pointer membership; even rejected metadata is retained. */
    const EpochBlock_ItemTypeDef *e=(const EpochBlock_ItemTypeDef *)payload;
    row->raw_flags=e->flags;row->raw_wait_mask=e->wait_mask;
    if (event_type<0 || (uint32_t)event_type!=log->matched%4u) { (void)fail(ctx,NPU_TRACE_EVENT);return; }
    if (!same_item(e,&ctx->original[index])) { (void)fail(ctx,NPU_TRACE_CHANGED);return; }
    ++log->matched;
    if (event_type==LL_ATON_RT_Callbacktype_POST_END) {
        ++log->completed_epochs;
        if (e->flags&EpochBlock_Flags_pure_hw) ++log->completed_pure_hw;
        else if (e->flags&EpochBlock_Flags_hybrid) ++log->completed_hybrid;
        else ++log->completed_pure_sw;
    }
}
int npu_trace_finish(npu_trace_context_t *ctx, stai_return_code runtime_result)
{
    if (!ctx || !ctx->log || !ctx->prepared) return -1;
    volatile npu_trace_log_t *log=ctx->log;
    log->runtime_return_code=(uint32_t)runtime_result;
    if (!log->active) return fail(ctx,NPU_TRACE_STATE);
    log->active=0;
    if (log->error) return -1;
    if (runtime_result!=STAI_SUCCESS) return fail(ctx,NPU_TRACE_RUN_FAILED);
    if (log->matched!=NPU_TRACE_EVENTS || log->stored!=NPU_TRACE_EVENTS ||
        log->received!=NPU_TRACE_EVENTS || log->completed_epochs!=40 ||
        log->completed_pure_hw!=8 || log->completed_hybrid!=1 || log->completed_pure_sw!=31)
        return fail(ctx,NPU_TRACE_INCOMPLETE);
    if (!unchanged(ctx)) return fail(ctx,NPU_TRACE_CHANGED);
    log->complete=1;
    return 0;
}
