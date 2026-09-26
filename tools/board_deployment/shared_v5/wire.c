#include "wire.h"
#include "portable_qdq.h"
#include <string.h>
uint32_t v5_get32(const uint8_t *p) { return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24); }
void v5_put32(uint8_t *p,uint32_t v) { for (unsigned i=0;i<4;i++) p[i]=(uint8_t)(v>>(8*i)); }
uint32_t v5_crc32(const uint8_t *p,size_t n) {
    uint32_t c=0xffffffffu;
    while (n--) { c^=*p++; for(unsigned i=0;i<8;i++) c=(c>>1)^((0u-(c&1u))&0xedb88320u); }
    return ~c;
}
static uint8_t digit(char c) { return (uint8_t)(c>='0' && c<='9' ? c-'0' : c-'a'+10); }
int v5_hello_query(const uint8_t q[V5_HELLO_QUERY_BYTES]) {
    return q && v5_get32(q)==V5_HELLO_QUERY_MAGIC && v5_get32(q+4)==1 &&
           v5_get32(q+8)==v5_crc32(q,8);
}
void v5_hello(uint8_t r[V5_HELLO_BYTES],uint32_t board_id) {
    memset(r,0,V5_HELLO_BYTES);
    v5_put32(r,V5_HELLO_MAGIC); v5_put32(r+4,1); v5_put32(r+8,board_id);
    v5_put32(r+12,1); /* CPU portable FP32 arithmetic, not NPU */
    v5_put32(r+16,pq_environment()?1u:0u);
    v5_put32(r+20,41); v5_put32(r+24,5);
    memcpy(r+28,spikeids_qdq_sha256,64); memcpy(r+92,V5_VECTORS_SHA256,64);
    v5_put32(r+156,v5_crc32(r,156));
}
static void base(const uint8_t *q,uint8_t *r) {
    memset(r,0,V5_RESPONSE_BYTES);
    v5_put32(r,V5_RESPONSE_MAGIC); v5_put32(r+4,1);
    memcpy(r+8,q+8,16); /* sequence, ordinal, original row-ID 64-bit word */
    for(unsigned i=0;i<32;i++) r[32+i]=(uint8_t)((digit(spikeids_qdq_sha256[2*i])<<4)|digit(spikeids_qdq_sha256[2*i+1]));
}
void v5_error(const uint8_t q[V5_REQUEST_BYTES],uint8_t r[V5_RESPONSE_BYTES],uint32_t status) {
    base(q,r); v5_put32(r+24,status); /* output count zero, words invalid */
    v5_put32(r+84,v5_crc32(r,84));
}
uint32_t v5_process(const uint8_t q[V5_REQUEST_BYTES],uint8_t r[V5_RESPONSE_BYTES],uint32_t *next) {
    if (!q || !r || !next) return V5_BAD_FRAME;
    if (v5_get32(q)!=V5_REQUEST_MAGIC || v5_get32(q+4)!=1 ||
        v5_get32(q+24)!=41 || v5_get32(q+28)!=164 ||
        v5_get32(q+228)!=v5_crc32(q,228)) {
        v5_error(q,r,V5_BAD_FRAME); return V5_BAD_FRAME;
    }
    base(q,r);
    if (memcmp(q+32,r+32,32)!=0) { v5_error(q,r,V5_BAD_MODEL); return V5_BAD_MODEL; }
    uint32_t seq=v5_get32(q+8),ordinal=v5_get32(q+12);
    if (!seq || seq>1024 || seq!=*next || ordinal!=seq-1) {
        v5_error(q,r,V5_BAD_SEQUENCE); return V5_BAD_SEQUENCE;
    }
    float input[41],output[5];
    for(unsigned i=0;i<41;i++) { uint32_t w=v5_get32(q+64+4*i); memcpy(input+i,&w,4); }
    int rc=pq_infer(&spikeids_qdq_model,input,41,output,5);
    ++*next; /* Every valid framed request is consumed once, including model failure. */
    if (rc) { v5_error(q,r,V5_ARITHMETIC_ERROR+(uint32_t)rc); return V5_ARITHMETIC_ERROR+(uint32_t)rc; }
    v5_put32(r+24,V5_OK); v5_put32(r+28,5);
    for(unsigned i=0;i<5;i++) { uint32_t w; memcpy(&w,output+i,4); v5_put32(r+64+4*i,w); }
    v5_put32(r+84,v5_crc32(r,84));
    return V5_OK;
}
