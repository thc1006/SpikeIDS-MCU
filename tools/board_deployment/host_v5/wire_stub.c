/* Test double only, never compiled into board firmware; no trained inference. */
#include "portable_qdq.h"
#include <math.h>
const char spikeids_qdq_sha256[65]="22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d";
const char spikeids_validation_sha256[65]="cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb";
const pq_model spikeids_qdq_model={0};
int stub_environment=1;
int stub_calls=0;
int pq_environment(void) { return stub_environment; }
int pq_infer(const pq_model *m,const float *x,size_t ni,float *out,size_t no) {
    (void)m;stub_calls++;
    if(ni!=41 || no!=5) return PQ_BAD_ARGUMENT;
    if(!stub_environment) return PQ_BAD_ENVIRONMENT;
    for(unsigned i=0;i<41;i++) if(!isfinite(x[i])) return PQ_NONFINITE;
    for(unsigned i=0;i<5;i++) out[i]=x[10*i];
    return PQ_OK;
}
