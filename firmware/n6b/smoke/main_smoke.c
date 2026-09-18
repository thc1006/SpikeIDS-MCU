/* B2 link smoke-test: reference the STAI + ATON runtime entry points so the linker must resolve
 * the whole model + runtime graph. Not run — this only proves compile + link (ABI, symbols). */
#include <stdint.h>
#include "stai_ids.h"

static uint8_t g_ctx[STAI_IDS_CONTEXT_SIZE] __attribute__((aligned(8)));
static int8_t  g_in[STAI_IDS_IN_1_SIZE_BYTES];
static int8_t  g_out[STAI_IDS_OUT_1_SIZE_BYTES];

volatile int g_rc;

int npu_smoke(void)
{
    stai_network *net = (stai_network *)g_ctx;
    stai_ptr in_ptr[STAI_IDS_IN_NUM]  = { g_in };
    stai_ptr out_ptr[STAI_IDS_OUT_NUM] = { g_out };

    g_rc = (int)stai_ids_init(net);
    stai_ids_set_inputs(net, in_ptr, STAI_IDS_IN_NUM);
    stai_ids_set_outputs(net, out_ptr, STAI_IDS_OUT_NUM);
    g_rc = (int)stai_ids_run(net, STAI_MODE_SYNC);
    return g_rc;
}

/* minimal reset entry so the linker has a root; not a real startup */
void _start(void) { npu_smoke(); for (;;) {} }
