/* MLP kernels. Layer i: in = dims[i], out = dims[i+1]; weights row-major [out][in], contiguous
 * per layer in the order fc0..fc3. Biases live in the work buffer (RAM), so the *only* thing
 * that changes between the "flash" and "SRAM" conditions is the weight base address. */
#include <stddef.h>
#include "kernels.h"
#include "arm_nnfunctions.h"

#define NL 4

size_t mlp_fp32_weight_bytes(const mlp_dims_t *m)
{
    size_t n = 0;
    for (int i = 0; i < NL; i++) n += (size_t)m->dims[i] * m->dims[i + 1];
    return n * sizeof(float);
}

/* Plain C, compiled at -O2 with MVE available: GCC may vectorise the inner loop. This is the
 * "unoptimised FP32 on the CPU" reference, not an attempt at peak throughput. */
static void fc_fp32(const float *w, const float *b, const float *x, float *y,
                    uint32_t in, uint32_t out, int relu)
{
    for (uint32_t o = 0; o < out; o++) {
        const float *wr = w + (size_t)o * in;
        float acc = b[o];
        for (uint32_t i = 0; i < in; i++) acc += wr[i] * x[i];
        y[o] = (relu && acc < 0.f) ? 0.f : acc;
    }
}

void mlp_fp32_run(const float *w, const float *b, float *act, const mlp_dims_t *m, float *out)
{
    /* act: [x(d) | a(h1) | b(h2) | c(h3)] scratch; out: c floats */
    const float *x = act;
    float *a = act + m->dims[0];
    float *bb = a + m->dims[1];
    float *c = bb + m->dims[2];
    size_t wo = 0, bo = 0;
    fc_fp32(w + wo, b + bo, x, a, m->dims[0], m->dims[1], 1);  wo += (size_t)m->dims[0] * m->dims[1]; bo += m->dims[1];
    fc_fp32(w + wo, b + bo, a, bb, m->dims[1], m->dims[2], 1); wo += (size_t)m->dims[1] * m->dims[2]; bo += m->dims[2];
    fc_fp32(w + wo, b + bo, bb, c, m->dims[2], m->dims[3], 1); wo += (size_t)m->dims[2] * m->dims[3]; bo += m->dims[3];
    fc_fp32(w + wo, b + bo, c, out, m->dims[3], m->dims[4], 0);
}

/* ---- INT8, CMSIS-NN arm_fully_connected_s8 (MVE path on the M55) ----
 * work buffer layout (int32 words): [bias L0..L3 | kernel_sum L0..L3 | act a | act b]
 * (activations are int8 but we reserve words for alignment). */
size_t mlp_s8_weight_bytes(const mlp_dims_t *m)
{
    size_t n = 0;
    for (int i = 0; i < NL; i++) n += (size_t)m->dims[i] * m->dims[i + 1];
    return n;
}

static size_t s8_outs(const mlp_dims_t *m) { return m->dims[1] + m->dims[2] + m->dims[3] + m->dims[4]; }
static uint32_t s8_maxact(const mlp_dims_t *m)
{
    uint32_t mx = m->dims[0];
    for (int i = 1; i <= NL; i++) if (m->dims[i] > mx) mx = m->dims[i];
    return (mx + 3u) & ~3u;
}

size_t mlp_s8_work_words(const mlp_dims_t *m)
{
    return 2 * s8_outs(m) + 2 * (s8_maxact(m) / 4);
}

/* Per-layer quant params: fixed, representative values (timing is data-independent). */
static const int32_t Q_MULT = 1073741824;  /* 0.5 in Q31 */
static const int32_t Q_SHIFT = -1;

int mlp_s8_setup(const int8_t *w, int32_t *work, const mlp_dims_t *m)
{
    int32_t *bias = work;
    int32_t *ksum = work + s8_outs(m);
    size_t wo = 0, o = 0;
    for (int i = 0; i < NL; i++) {
        uint32_t in = m->dims[i], out = m->dims[i + 1];
        for (uint32_t k = 0; k < out; k++) bias[o + k] = (int32_t)(k & 7) - 3;
        /* Kernel sums are a one-time weight preprocessing step (deployment-time), so they
         * are computed here, outside the timed region, exactly as a deployment would. */
        arm_vector_sum_s8(ksum + o, (int32_t)in, (int32_t)out, w + wo, /*lhs_offset*/ 0, /*rhs_offset*/ 0, bias + o);
        wo += (size_t)in * out; o += out;
    }
    return 0;
}

int mlp_s8_run(const int8_t *w, int32_t *work, const mlp_dims_t *m, const int8_t *x)
{
    const int32_t *bias = work;
    const int32_t *ksum = work + s8_outs(m);
    int8_t *a = (int8_t *)(work + 2 * s8_outs(m));
    int8_t *b = a + s8_maxact(m);
    const int8_t *in = x;
    int8_t *out = a;
    size_t wo = 0, o = 0;
    for (int i = 0; i < NL; i++) {
        uint32_t ind = m->dims[i], outd = m->dims[i + 1];
        cmsis_nn_context ctx = { (void *)(ksum + o), (int32_t)(outd * sizeof(int32_t)) };
        cmsis_nn_fc_params fc = { .input_offset = 0, .filter_offset = 0, .output_offset = 0,
                                  .activation = { i < NL - 1 ? 0 : -128, 127 } };   /* ReLU as clamp */
        cmsis_nn_per_tensor_quant_params q = { Q_MULT, Q_SHIFT };
        cmsis_nn_dims in_d = { 1, 1, 1, (int32_t)ind };
        cmsis_nn_dims fil_d = { (int32_t)ind, 1, 1, (int32_t)outd };
        cmsis_nn_dims bia_d = { 1, 1, 1, (int32_t)outd };
        cmsis_nn_dims out_d = { 1, 1, 1, (int32_t)outd };
        if (arm_fully_connected_s8(&ctx, &fc, &q, &in_d, in, &fil_d, w + wo, &bia_d, bias + o, &out_d, out)
            != ARM_CMSIS_NN_SUCCESS) return -1;
        wo += (size_t)ind * outd; o += outd;
        in = out; out = (out == a) ? b : a;
    }
    /* argmax over the last layer (in points to it) */
    int best = 0;
    for (uint32_t c = 1; c < m->dims[NL]; c++) if (in[c] > in[best]) best = (int)c;
    return best;
}
