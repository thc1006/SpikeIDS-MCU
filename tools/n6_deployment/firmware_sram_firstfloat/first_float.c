/* Restore original first Gemm+bias+Q semantics at the defective CPU/NPU
 * boundary. Later three dense layers retain their actual NPU implementation.
 * This does not establish final-model parity; it must still be measured. */
#include "ll_aton_NN_interface.h"
#include "first_bias.h"

void __wrap_ll_sw_forward_conv(void *opaque)
{
    if (!opaque) s6_compat_fail();
    Conv_sw_info *p=opaque;
    Tensor_info in=io_tensor(41,4,0,164,0);
    Tensor_info out=io_tensor(256,4,1024,1024,0);
    Tensor_info w=io_tensor(41,4,0,164,0),zero={0};
    w.dim.tensor_b=256;w.dim.num_elem=10496;
    w.mem.start_offset=(unsigned char *)(uintptr_t)0x34210020;
    if (p->general.type!=LL_SW_CONV || p->ngroup!=1 ||
        !tensor_equal(&p->general.input,&in) || !tensor_equal(&p->general.output,&out) ||
        !tensor_equal(&p->weights,&w) || !tensor_equal(&p->bias,&zero) ||
        !tensor_equal(&p->scratch,&zero) || !tensor_equal(&p->weights_permuted,&zero) ||
        p->pads[0] || p->pads[1] || p->pads[2] || p->pads[3] ||
        p->strides[0]!=1 || p->strides[1]!=1 || p->strides[2] || p->strides[3] ||
        p->dilations[0]!=1 || p->dilations[1]!=1) s6_compat_fail();
    float input[41];memcpy(input,in.mem.start_offset,sizeof input);
    for(unsigned k=0;k<41;k++) if(!isfinite(input[k])) s6_compat_fail();
    for(unsigned j=0;j<256;j++) {
        float sum=0.0f,bias;
        for(unsigned k=0;k<41;k++) {
            float weight;memcpy(&weight,w.mem.start_offset+4*(41*j+k),4);
            sum=add32(sum,mul32(input[k],weight));
        }
        memcpy(&bias,&first_bias_bits[j],4);
        float value=add32(sum,bias);
        if(!isfinite(value)) s6_compat_fail();
        memcpy(out.mem.start_offset+4*j,&value,4);
    }
}

static int cast_contract(const LL_Buffer_InfoTypeDef *p,int output)
{
    if(!p || !p->shape || !p->mem_shape || p->ndims!=4 || p->mem_ndims!=4 ||
        p->addr_base.i!=0x34240000 || p->offset_start!=1024 ||
        p->offset_end!=(output?1536u:2048u) || p->offset_limit!=(output?1600u:2112u) ||
        p->is_user_allocated || p->is_param || p->epoch!=6 || p->batch!=256 ||
        p->chpos!=CHPos_First || p->type!=(output?DataType_FXP:DataType_FLOAT) ||
        p->Qm!=(output?18:0) || p->Qn!=(output?-3:0) ||
        p->Qunsigned!=(output?0:1) || p->nbits!=(output?16:32) ||
        p->per_channel || p->scale || p->offset) return 0;
    const uint32_t shape[4]={1,1,1,256},mem[4]={1,256,1,1};
    return !memcmp(p->shape,shape,sizeof shape) && !memcmp(p->mem_shape,mem,sizeof mem);
}

int __wrap_LL_ATON_LIB_Cast(const LL_Buffer_InfoTypeDef *input,
                          const LL_Buffer_InfoTypeDef *output,int dma_in,int dma_out)
{
    if(!cast_contract(input,0) || !cast_contract(output,1) || dma_in!=2 || dma_out!=3)
        s6_compat_fail();
    /* The reviewed schedule removes epoch7. This point produces the original
     * first Gemm's signed8 output directly, not the broken Q18.-3 temporary.
     * In-place narrowing runs forward, never clobbering an unread float. */
    unsigned char *buffer=(unsigned char *)(uintptr_t)0x34240400;
    uint32_t bits=FIRST_OUTPUT_SCALE_BITS;float scale;memcpy(&scale,&bits,4);
    for(unsigned i=0;i<256;i++) {
        float value;memcpy(&value,buffer+4*i,4);
        if(!isfinite(value)) s6_compat_fail();
    }
    for(unsigned i=0;i<256;i++) {
        float value;int8_t q;memcpy(&value,buffer+4*i,4);
        if(pq_quantize(value,scale,FIRST_OUTPUT_ZERO,&q)!=PQ_OK) s6_compat_fail();
        memcpy(buffer+i,&q,1);
    }
    return 0; /* LL_ATON_OK */
}
