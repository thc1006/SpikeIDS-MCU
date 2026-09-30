#include "npu_trace.h"
#include "nsl_qcfs_seed0.h"
#ifndef NPU_TRACE_HOST_CONTROL
#include "stai_nsl_qcfs_seed0.h"
#else
/* Explicit host-only registration seam: generated header imports ARM intrinsics.
 * The ARM compile below uses the unmodified real generated declaration. */
extern stai_return_code stai_nsl_qcfs_seed0_set_callback(stai_network *,const stai_event_cb,void *);
#endif
LL_ATON_DECLARE_NAMED_NN_PROTOS(nsl_qcfs_seed0)

stai_return_code npu_trace_bind(stai_network *network, npu_trace_context_t *ctx,
                              volatile npu_trace_log_t *log,
                              npu_trace_counter_fn counter, void *counter_cookie)
{
    if (!network || npu_trace_prepare(ctx,log,LL_ATON_EpochBlockItems_nsl_qcfs_seed0(),
                                     NPU_TRACE_TABLE_ITEMS,counter,counter_cookie))
        return STAI_ERROR_GENERIC;
    stai_return_code rc=stai_nsl_qcfs_seed0_set_callback(network,npu_trace_callback,ctx);
    if (rc!=STAI_SUCCESS) { log->error=NPU_TRACE_REGISTRATION;ctx->prepared=0; }
    return rc;
}
