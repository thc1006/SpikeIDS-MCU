#include "portable_qdq.h"
#include <float.h>
#include <fenv.h>
#include <math.h>
#include <string.h>

#ifdef __FAST_MATH__
#error "Fast math is forbidden for this candidate"
#endif
_Static_assert(sizeof(float)==4 && FLT_RADIX==2 && FLT_MANT_DIG==24 &&
               FLT_MAX_EXP==128, "binary32 float required");
_Static_assert(sizeof(int8_t)==1 && sizeof(int32_t)==4, "fixed-width integers required");

/* Explicit volatile binary32 temporaries prevent contracted multiply/add and
 * excess-precision retention between graph operations. Build with
 * -fno-fast-math -ffp-contract=off -fexcess-precision=standard as well. */
static float add32(float a,float b) { volatile float x=a+b; return x; }
static float mul32(float a,float b) { volatile float x=a*b; return x; }
static float div32(float a,float b) { volatile float x=a/b; return x; }
static float dq32(int32_t x,int32_t zero,float scale) {
    volatile float d=(float)((int64_t)x-(int64_t)zero);
    return mul32(d,scale);
}
int pq_environment(void) {
    volatile float a=FLT_MIN, b=0.5f, c=a*b;
    return fegetround()==FE_TONEAREST && c>0.0f && signbit(-0.0f);
}
static int valid_quant(pq_quant q) {
    return isfinite(q.scale) && q.scale>0.0f && q.zero>=-128 && q.zero<=127;
}
int pq_quantize(float value,float scale,int32_t zero,int8_t *out) {
    if (!out || !valid_quant((pq_quant){scale,zero})) return PQ_BAD_ARGUMENT;
    if (!isfinite(value)) return PQ_NONFINITE;
    float q=div32(value,scale);
    /* Infinite division of finite input saturates without an unsafe int cast. */
    if (q >= (float)(127-zero)) { *out=127; return PQ_OK; }
    if (q <= (float)(-128-zero)) { *out=-128; return PQ_OK; }
    float lo=floorf(q), fraction=add32(q,-lo);
    int32_t nearest=(int32_t)lo;
    if (fraction>0.5f || (fraction==0.5f && nearest%2!=0)) ++nearest;
    /* Round x/scale to even BEFORE adding the integer zero point. */
    nearest += zero;
    if (nearest>127) nearest=127;
    if (nearest<-128) nearest=-128;
    *out=(int8_t)nearest;
    return PQ_OK;
}
static int qdq(float *values,uint32_t n,pq_quant q) {
    for (uint32_t i=0;i<n;i++) {
        int8_t quantized; int rc=pq_quantize(values[i],q.scale,q.zero,&quantized);
        if (rc) return rc;
        values[i]=dq32(quantized,q.zero,q.scale);
        if (!isfinite(values[i])) return PQ_NONFINITE;
    }
    return PQ_OK;
}
int pq_qcfs(float value,const pq_layer *p,float *out) {
    if (!p || !out || !isfinite(p->threshold) || p->threshold<=0.0f ||
        p->clip_low!=0.0f || p->clip_high!=1.0f || p->levels_mul!=4.0f ||
        p->half!=0.5f || p->levels_div!=4.0f) return PQ_BAD_ARGUMENT;
    if (!isfinite(value)) return PQ_NONFINITE;
    float x=div32(value,p->threshold);
    x=x<p->clip_low ? p->clip_low : (x>p->clip_high ? p->clip_high : x);
    x=mul32(x,p->levels_mul);
    x=add32(x,p->half);
    x=floorf(x);
    x=div32(x,p->levels_div);
    x=mul32(x,p->threshold);
    if (!isfinite(x)) return PQ_NONFINITE;
    *out=x; return PQ_OK;
}
int pq_infer(const pq_model *m,const float *input,size_t ni,float *output,size_t no) {
    if (!m || !input || !output || ni==0 || no==0 || ni>PQ_MAX_WIDTH ||
        no>PQ_MAX_WIDTH || ni!=m->layers[0].inputs ||
        no!=m->layers[PQ_LAYERS-1].outputs || !valid_quant(m->input_quant))
        return PQ_BAD_ARGUMENT;
    if (!pq_environment()) return PQ_BAD_ENVIRONMENT;
    uint32_t previous=(uint32_t)ni;
    for (uint32_t l=0;l<PQ_LAYERS;l++) {
        const pq_layer *p=&m->layers[l];
        if (p->inputs!=previous || p->outputs==0 || p->outputs>PQ_MAX_WIDTH ||
            !p->weights || !p->weight_zero || !p->weight_scale || !p->bias ||
            !p->bias_scale || !valid_quant(p->output_quant) ||
            (l<3 && !valid_quant(p->activation_quant))) return PQ_BAD_ARGUMENT;
        for (uint32_t j=0;j<p->outputs;j++)
            if (!isfinite(p->weight_scale[j]) || p->weight_scale[j]<=0.0f ||
                !isfinite(p->bias_scale[j]) || p->bias_scale[j]<=0.0f)
                return PQ_BAD_ARGUMENT;
        previous=p->outputs;
    }
    float a[PQ_MAX_WIDTH],b[PQ_MAX_WIDTH];
    memcpy(a,input,ni*sizeof(float));
    int rc=qdq(a,(uint32_t)ni,m->input_quant); if (rc) return rc;
    for (uint32_t l=0;l<PQ_LAYERS;l++) {
        const pq_layer *p=&m->layers[l];
        for (uint32_t j=0;j<p->outputs;j++) {
            float sum=0.0f;
            for (uint32_t k=0;k<p->inputs;k++) {
                float w=dq32(p->weights[j*p->inputs+k],p->weight_zero[j],p->weight_scale[j]);
                sum=add32(sum,mul32(a[k],w));
            }
            b[j]=add32(sum,dq32(p->bias[j],0,p->bias_scale[j]));
            if (!isfinite(b[j])) return PQ_NONFINITE;
        }
        rc=qdq(b,p->outputs,p->output_quant); if (rc) return rc;
        if (l<3) {
            for (uint32_t j=0;j<p->outputs;j++) {
                rc=pq_qcfs(b[j],p,&b[j]); if (rc) return rc;
            }
            rc=qdq(b,p->outputs,p->activation_quant); if (rc) return rc;
        }
        memcpy(a,b,p->outputs*sizeof(float));
    }
    /* Failure never publishes partial result; input/output alias is supported. */
    memcpy(output,a,no*sizeof(float));
    return PQ_OK;
}
