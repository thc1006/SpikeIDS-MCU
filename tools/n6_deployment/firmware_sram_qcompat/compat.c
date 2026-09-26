/* Fixed-model compatibility, NOT a general-purpose dtype inference heuristic.
 * Generated metadata has signedness but no width. Only the nine audited
 * descriptors of original graph 22dc7979... are accepted; no other layout.
 * Original installed ST sources and generated graph are never modified.
 */
#include <stdint.h>
#include <string.h>
#include "ll_sw.h"

_Noreturn void s6_compat_fail(void);
void __real_ll_sw_forward_quantizelinear(void *);
void __real_ll_sw_forward_dequantizelinear(void *);

typedef struct {
    unsigned quant, n, width, in_offset, out_offset, scale_offset, zp_offset;
    uint32_t scale_bits;
    int zp, scale_sign, out_sign;
} qcfs_contract;

/* width is integer width, explicit by frozen call site, never stride-derived.
 * Signed zero points independently decoded from retained original weights. */
static const qcfs_contract qcfs_contracts[] = {
    {1, 41,1,   0,272,144880,145328,0x3e900788,-119,1,1},
    {0, 41,2, 176,  0,145152,145360,0x3e900788,   0,0,0},
    {0,256,1,1024,  0,145168,145376,0x3e286b17,  18,0,0},
    {1,256,1,1024,  0,145184,145392,0x3aaee88d,-128,0,1},
    {0,256,1,1024,  0,145200,145408,0x3cfc5e2f,  -3,0,0},
    {1,256,1,1024,  0,145216,145424,0x3b0b5210,-128,0,1},
    {0,128,1, 512,  0,145232,145440,0x3d096e1e, -15,0,0},
    {1,128,1, 512,  0,145248,145456,0x3bb1e291,-128,0,1},
    {0,  5,1, 128,  0,145136,145344,0x3dcb35ff,  -1,1,1},
};

static int tensor_equal(const Tensor_info *a, const Tensor_info *b)
{
    return a->dim.tensor_b==b->dim.tensor_b && a->dim.tensor_h==b->dim.tensor_h &&
        a->dim.tensor_w==b->dim.tensor_w && a->dim.tensor_c==b->dim.tensor_c &&
        a->dim.num_elem==b->dim.num_elem && a->stride.b==b->stride.b &&
        a->stride.h==b->stride.h && a->stride.w==b->stride.w &&
        a->stride.c==b->stride.c && a->mem.start_offset==b->mem.start_offset &&
        a->format.is_signed==b->format.is_signed;
}

static Tensor_info io_tensor(unsigned n, unsigned bytes, unsigned offset,
                             unsigned wstride, int sign)
{
    Tensor_info t = {0};
    t.dim.tensor_b=t.dim.tensor_h=t.dim.tensor_w=1;
    t.dim.tensor_c=t.dim.num_elem=n;
    t.stride.b=t.stride.h=n*bytes; t.stride.w=wstride; t.stride.c=bytes;
    t.mem.start_offset=(unsigned char *)(uintptr_t)(0x34240000u+offset);
    t.format.is_signed=sign;
    return t;
}

static const qcfs_contract *descriptor(const General *g, const Tensor_info *scale,
                                       const Tensor_info *zp, unsigned quant)
{
    if (!g || !scale || !zp) return 0;
    for (unsigned i=0; i<sizeof qcfs_contracts/sizeof *qcfs_contracts; ++i) {
        const qcfs_contract *c=&qcfs_contracts[i];
        if (c->quant!=quant) continue;
        Tensor_info s={0}, z={0};
        s.dim.num_elem=z.dim.num_elem=1;
        s.mem.start_offset=(unsigned char *)(uintptr_t)(0x34200000u+c->scale_offset);
        z.mem.start_offset=(unsigned char *)(uintptr_t)(0x34200000u+c->zp_offset);
        s.format.is_signed=c->scale_sign; z.format.is_signed=1;
        unsigned iw=quant?4:c->width, ow=quant?c->width:4;
        Tensor_info in=io_tensor(c->n,iw,c->in_offset,c->width==2?c->n*iw:iw,!quant);
        Tensor_info out=io_tensor(c->n,ow,c->out_offset,c->width==2?c->n*ow:ow,c->out_sign);
        if (g->type!=(quant?LL_SW_QUANTIZELINEAR:LL_SW_DEQUANTIZELINEAR) ||
            !tensor_equal(&g->input,&in) || !tensor_equal(&g->output,&out) ||
            !tensor_equal(scale,&s) || !tensor_equal(zp,&z)) continue;
        /* Validate constants before any output. No read through unknown pointers. */
        uint32_t bits; memcpy(&bits,s.mem.start_offset,4);
        int32_t zero;
        if (c->width==2) { int16_t v; memcpy(&v,z.mem.start_offset,2); zero=v; }
        else { int8_t v; memcpy(&v,z.mem.start_offset,1); zero=v; }
        if (bits!=c->scale_bits || zero!=c->zp) return 0;
        return c;
    }
    return 0;
}

void __wrap_ll_sw_forward_dequantizelinear(void *opaque)
{
    if (!opaque) s6_compat_fail();
    Dequantizelinear_sw_info *p=opaque;
    const qcfs_contract *c=descriptor(&p->general,&p->is,&p->izp,0);
    if (!c) s6_compat_fail();
    if (c->width==2) {
        /* Exactly epoch4: disjoint [176,258) input and [0,164) output.
         * Difference fits int32 and is exactly representable in FP32. */
        float scale; memcpy(&scale,p->is.mem.start_offset,4);
        for (unsigned i=0; i<c->n; ++i) {
            int16_t q; memcpy(&q,p->general.input.mem.start_offset+2*i,2);
            float value=(float)((int32_t)q-c->zp)*scale;
            memcpy(p->general.output.mem.start_offset+4*i,&value,4);
        }
    } else {
        /* ST3.0 reads the SCALE signedness field for ZERO-POINT metadata.
         * Adapt a local descriptor copy only; keep original vendor kernel. */
        Dequantizelinear_sw_info copy=*p;
        copy.is.format.is_signed=copy.izp.format.is_signed;
        __real_ll_sw_forward_dequantizelinear(&copy);
    }
}

void __wrap_ll_sw_forward_quantizelinear(void *opaque)
{
    if (!opaque) s6_compat_fail();
    Quantizelinear_sw_info *p=opaque;
    if (!descriptor(&p->general,&p->os,&p->ozp,1)) s6_compat_fail();
    Quantizelinear_sw_info copy=*p;
    copy.os.format.is_signed=copy.ozp.format.is_signed;
    __real_ll_sw_forward_quantizelinear(&copy);
}
