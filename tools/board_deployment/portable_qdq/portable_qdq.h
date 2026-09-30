#ifndef SPIKEIDS_PORTABLE_QDQ_H
#define SPIKEIDS_PORTABLE_QDQ_H
#include <stddef.h>
#include <stdint.h>

/* Candidate arithmetic, not an accepted board implementation. All pointers
 * refer to immutable generated constants; no heap, device or RTOS dependency. */
#define PQ_MAX_WIDTH 256u
#define PQ_LAYERS 4u
typedef struct { float scale; int32_t zero; } pq_quant;
typedef struct {
    uint32_t inputs, outputs;
    const int8_t *weights, *weight_zero;
    const float *weight_scale;
    const int32_t *bias;
    const float *bias_scale;
    pq_quant output_quant;
    float threshold, clip_low, clip_high, levels_mul, half, levels_div;
    pq_quant activation_quant;
} pq_layer;
typedef struct { pq_quant input_quant; pq_layer layers[PQ_LAYERS]; } pq_model;
enum { PQ_OK=0, PQ_BAD_ARGUMENT=1, PQ_BAD_ENVIRONMENT=2, PQ_NONFINITE=3 };
int pq_environment(void);
int pq_quantize(float value, float scale, int32_t zero, int8_t *out);
int pq_qcfs(float value, const pq_layer *layer, float *out);
int pq_infer(const pq_model *model, const float *input, size_t input_count,
             float *output, size_t output_count);
/* Generated file exports these fixed model identities. */
extern const pq_model spikeids_qdq_model;
extern const char spikeids_qdq_sha256[65];
extern const char spikeids_validation_sha256[65];
#endif
