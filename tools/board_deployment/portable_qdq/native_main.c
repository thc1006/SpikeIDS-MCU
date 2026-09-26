/* Host-only fixed protocol: stdin exactly 1024 x 41 little-endian FP32 words.
 * stdout exactly 1024 records: LE u32 row ordinal, status, five FP32 words.
 * A nonzero row status has invalid NaN sentinels, never fabricated logits.
 * There is deliberately no device, file-path, model, shape or row selector. */
#include "portable_qdq.h"
#include <stdio.h>
#include <string.h>
#define ROWS 1024u
#define INPUTS 41u
#define OUTPUTS 5u
static uint32_t le32(const unsigned char *p) {
    return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);
}
static void put32(unsigned char *p,uint32_t x) {
    for (unsigned i=0;i<4;i++) p[i]=(unsigned char)(x>>(8*i));
}
int main(void) {
    unsigned failures=0;
    fprintf(stderr,"model=%s\nvalidation=%s\n",spikeids_qdq_sha256,spikeids_validation_sha256);
    for (uint32_t row=0;row<ROWS;row++) {
        unsigned char raw[INPUTS*4], record[(OUTPUTS+2)*4];
        float input[INPUTS], output[OUTPUTS];
        if (fread(raw,1,sizeof raw,stdin)!=sizeof raw) {
            fprintf(stderr,"short input at row %u\n",row); return 3;
        }
        for (unsigned j=0;j<INPUTS;j++) { uint32_t w=le32(raw+4*j); memcpy(input+j,&w,4); }
        for (unsigned j=0;j<OUTPUTS;j++) { uint32_t w=0x7fc00000u; memcpy(output+j,&w,4); }
        int rc=pq_infer(&spikeids_qdq_model,input,INPUTS,output,OUTPUTS);
        put32(record,row); put32(record+4,(uint32_t)rc);
        for (unsigned j=0;j<OUTPUTS;j++) { uint32_t w; memcpy(&w,output+j,4); put32(record+8+4*j,w); }
        if (fwrite(record,1,sizeof record,stdout)!=sizeof record) return 4;
        if (rc!=PQ_OK) failures++;
    }
    if (fgetc(stdin)!=EOF || ferror(stdin)) { fputs("trailing input/read failure\n",stderr); return 3; }
    if (fflush(stdout)!=0) return 4;
    fprintf(stderr,"rows=%u failures=%u\n",ROWS,failures);
    return failures ? 2 : 0;
}
