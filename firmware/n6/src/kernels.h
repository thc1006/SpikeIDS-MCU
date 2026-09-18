#ifndef N6_KERNELS_H
#define N6_KERNELS_H
#include <stdint.h>
#include <stddef.h>
uint32_t rd_ldr32(const uint32_t *p, uint32_t words);
uint32_t rd_ldrd64(const uint32_t *p, uint32_t words);
uint32_t rd_mve128(const uint32_t *p, uint32_t words);
uint32_t rd_ldm32x8(const uint32_t *p, uint32_t words);

typedef struct { uint32_t dims[5]; } mlp_dims_t;   /* d, h1, h2, h3, c */

void   mlp_fp32_run(const float *w, const float *b, float *act, const mlp_dims_t *m, float *out);
size_t mlp_fp32_weight_bytes(const mlp_dims_t *m);

int    mlp_s8_setup(const int8_t *w, int32_t *work, const mlp_dims_t *m);   /* kernel sums, biases */
int    mlp_s8_run(const int8_t *w, int32_t *work, const mlp_dims_t *m, const int8_t *x);
size_t mlp_s8_weight_bytes(const mlp_dims_t *m);
size_t mlp_s8_work_words(const mlp_dims_t *m);
#endif
