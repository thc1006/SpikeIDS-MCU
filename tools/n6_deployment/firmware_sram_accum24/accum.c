/* CPU postprocessing only; every dot product must come from actual NPU.
 * Diagnostic prototype. Raw signed24 packing still requires hardware proof. */
#include "accum_params.h"
_Noreturn void s6_compat_fail(void);

static int32_t signed24(const unsigned char *p)
{
    uint32_t u=(uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16);
    return (int32_t)u-((u&UINT32_C(0x800000))?INT32_C(16777216):0);
}

void s6_requantize_accum(unsigned layer)
{
    static const unsigned count[3]={256,128,5},offset[3]={1024,512,128};
    static const uint32_t input_scale[3]={ACCUM_INPUT_SCALE_0,ACCUM_INPUT_SCALE_1,ACCUM_INPUT_SCALE_2};
    static const uint32_t output_scale[3]={ACCUM_OUTPUT_SCALE_0,ACCUM_OUTPUT_SCALE_1,ACCUM_OUTPUT_SCALE_2};
    static const int zero[3]={ACCUM_OUTPUT_ZERO_0,ACCUM_OUTPUT_ZERO_1,ACCUM_OUTPUT_ZERO_2};
    static const uint32_t *const scale[3]={accum_scale_0,accum_scale_1,accum_scale_2};
    static const uint32_t *const bias[3]={accum_bias_0,accum_bias_1,accum_bias_2};
    static const int32_t *const bound[3]={accum_bound_0,accum_bound_1,accum_bound_2};
    if(layer>=3)s6_compat_fail();
    const unsigned char *raw=(const unsigned char *)(uintptr_t)0x34242000;
    int8_t temporary[256];float is,os;
    memcpy(&is,&input_scale[layer],4);memcpy(&os,&output_scale[layer],4);
    for(unsigned j=0;j<count[layer];j++){
        int32_t accumulator=signed24(raw+3*j);
        if(accumulator>bound[layer][j] || accumulator<-bound[layer][j])s6_compat_fail();
        float ws,b;memcpy(&ws,&scale[layer][j],4);memcpy(&b,&bias[layer][j],4);
        float value=add32(mul32(mul32((float)accumulator,is),ws),b);
        if(pq_quantize(value,os,zero[layer],&temporary[j])!=PQ_OK)s6_compat_fail();
    }
    /* Publish only a complete valid layer; never overwrite raw NPU evidence. */
    memcpy((void *)(uintptr_t)(0x34240000+offset[layer]),temporary,count[layer]);
}
