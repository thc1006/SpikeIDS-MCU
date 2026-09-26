#include "npu_trace.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x);exit(1); } } while (0)
static unsigned tests;
static EpochBlock_ItemTypeDef table[NPU_TRACE_TABLE_ITEMS];
static npu_trace_context_t ctx;
static struct { uint32_t before; npu_trace_log_t log; uint32_t after; } guarded;
static uint32_t clock_word;
static stai_event_cb installed;
static void *installed_cookie;
static stai_return_code registration_rc;
static void start(const void *p) { (void)p; }
static void end(const void *p) { (void)p; }
static uint32_t counter(void *p) { (void)p;return clock_word+=7; }
static void fixture(void)
{
    const unsigned hw[]={1,5,15,16,26,27,37,38};
    const uint32_t waits[]={4,1,32,256,128,32,4,4};
    memset(table,0,sizeof(table));memset(&ctx,0,sizeof(ctx));memset(&guarded,0,sizeof(guarded));
    guarded.before=0x12567890;guarded.after=0x09abcdef;
    for (unsigned i=0;i<40;++i) { table[i].flags=35;table[i].end_epoch_block=end; }
    for (unsigned i=0;i<8;++i) { table[hw[i]].flags=19;table[hw[i]].wait_mask=waits[i];table[hw[i]].start_epoch_block=start; }
    table[4].flags=67;table[40].flags=8;
    clock_word=0;installed=NULL;installed_cookie=NULL;registration_rc=STAI_SUCCESS;
}
static void setup(void)
{
    fixture();CHECK(npu_trace_prepare(&ctx,&guarded.log,table,41,counter,NULL)==0);
    CHECK(npu_trace_begin(&ctx,1)==0);
}
static void emit(unsigned count)
{
    for (unsigned i=0;i<count;++i) npu_trace_callback(&ctx,(stai_event_type)(i%4),&table[i/4]);
}
static void reset_events(void)
{
    npu_trace_callback(&ctx,LL_ATON_RT_Callbacktype_NN_DeInit,NULL);
    npu_trace_callback(&ctx,LL_ATON_RT_Callbacktype_NN_Init,NULL);
}
static void failed(unsigned code)
{
    CHECK(guarded.log.error==code && !guarded.log.complete);
    CHECK(guarded.before==0x12567890 && guarded.after==0x09abcdef);++tests;
}
/* Link the real binder against synthetic metadata and registration, never a model/runtime. */
const EpochBlock_ItemTypeDef *LL_ATON_EpochBlockItems_nsl_qcfs_seed0(void) { return table; }
stai_return_code stai_nsl_qcfs_seed0_set_callback(stai_network *n,const stai_event_cb cb,void *cookie)
{ CHECK(n!=NULL);installed=cb;installed_cookie=cookie;return registration_rc; }

int main(void)
{
    setup();emit(160);
    reset_events();
    CHECK(npu_trace_finish(&ctx,STAI_SUCCESS)==0);
    CHECK(guarded.log.complete && !guarded.log.active && guarded.log.matched==160);
    CHECK(guarded.log.completed_epochs==40 && guarded.log.completed_pure_hw==8 &&
          guarded.log.completed_hybrid==1 && guarded.log.completed_pure_sw==31);
    CHECK(!guarded.log.hardware_independently_proven && !guarded.log.performance_accepted);
    CHECK(guarded.log.events[0].compiler_epoch==1 && guarded.log.events[159].compiler_epoch==44);
    CHECK(guarded.log.events[159].cpu_counter_delta_mod32==7);++tests;

    CHECK(guarded.log.completed_lifecycle==2 && guarded.log.stored==162 && guarded.log.received==162);
    CHECK(guarded.log.events[160].epoch_index==UINT32_MAX && guarded.log.events[161].event_type==4);
    CHECK(npu_trace_begin(&ctx,2)==0);emit(160);reset_events();CHECK(npu_trace_finish(&ctx,0)==0);++tests;
    CHECK(npu_trace_begin(&ctx,2)!=0);failed(NPU_TRACE_STATE);
    setup();CHECK(npu_trace_begin(&ctx,2)!=0);failed(NPU_TRACE_STATE);
    setup();emit(159);CHECK(npu_trace_finish(&ctx,0)!=0);failed(NPU_TRACE_INCOMPLETE);
    setup();emit(160);reset_events();npu_trace_callback(&ctx,0,&table[40]);failed(NPU_TRACE_OVERFLOW);
    CHECK(guarded.log.stored==162);CHECK(npu_trace_finish(&ctx,0)!=0);
    setup();emit(160);reset_events();CHECK(npu_trace_finish(&ctx,STAI_ERROR_GENERIC)!=0);failed(NPU_TRACE_RUN_FAILED);
    setup();emit(160);reset_events();table[40].wait_mask=1;CHECK(npu_trace_finish(&ctx,0)!=0);failed(NPU_TRACE_CHANGED);
    setup();table[0].end_epoch_block=start;npu_trace_callback(&ctx,0,&table[0]);failed(NPU_TRACE_CHANGED);
    setup();table[0].flags=19;npu_trace_callback(&ctx,0,&table[0]);failed(NPU_TRACE_CHANGED);
    CHECK(guarded.log.events[0].raw_flags==19); /* retain the rejected raw metadata */
    setup();npu_trace_callback(&ctx,0,NULL);failed(NPU_TRACE_POINTER);
    setup();EpochBlock_ItemTypeDef clone=table[0];npu_trace_callback(&ctx,0,&clone);failed(NPU_TRACE_POINTER);
    setup();npu_trace_callback(&ctx,0,&table[1]);failed(NPU_TRACE_POINTER);
    setup();npu_trace_callback(&ctx,4,&table[0]);failed(NPU_TRACE_EVENT);
    setup();npu_trace_callback(&ctx,-1,&table[0]);failed(NPU_TRACE_EVENT);
    setup();npu_trace_callback(&ctx,1,&table[0]);failed(NPU_TRACE_EVENT);
    setup();emit(2);npu_trace_callback(&ctx,3,&table[0]);failed(NPU_TRACE_EVENT);
    unsigned retained=guarded.log.stored;emit(160);CHECK(guarded.log.stored==retained);
    CHECK(npu_trace_finish(&ctx,0)!=0);CHECK(npu_trace_begin(&ctx,2)!=0);++tests;
    setup();emit(160);reset_events();CHECK(npu_trace_finish(&ctx,0)==0);
    npu_trace_callback(&ctx,0,&table[0]);failed(NPU_TRACE_STATE);
    setup();clock_word=UINT32_MAX-10;emit(160);reset_events();CHECK(npu_trace_finish(&ctx,0)==0);
    CHECK(guarded.log.counter_wrap_observed==1 && guarded.log.events[1].cpu_counter_delta_mod32==7);++tests;
    fixture();CHECK(npu_trace_prepare(&ctx,&guarded.log,table,41,NULL,NULL)==0);
    CHECK(npu_trace_begin(&ctx,1)==0);emit(160);reset_events();CHECK(npu_trace_finish(&ctx,0)==0);
    CHECK(!guarded.log.counter_present && !guarded.log.events[159].cpu_counter_raw);++tests;

    fixture();CHECK(npu_trace_prepare(&ctx,&guarded.log,table,40,NULL,NULL)!=0);failed(NPU_TRACE_ARGUMENT);
    fixture();table[1].wait_mask=8;CHECK(npu_trace_prepare(&ctx,&guarded.log,table,41,NULL,NULL)!=0);failed(NPU_TRACE_TABLE);
    fixture();table[4].flags=35;CHECK(npu_trace_prepare(&ctx,&guarded.log,table,41,NULL,NULL)!=0);failed(NPU_TRACE_TABLE);
    fixture();table[0].blob_address=4;CHECK(npu_trace_prepare(&ctx,&guarded.log,table,41,NULL,NULL)!=0);failed(NPU_TRACE_TABLE);
    fixture();table[1].start_epoch_block=NULL;CHECK(npu_trace_prepare(&ctx,&guarded.log,table,41,NULL,NULL)!=0);failed(NPU_TRACE_TABLE);
    fixture();table[40].flags=35;CHECK(npu_trace_prepare(&ctx,&guarded.log,table,41,NULL,NULL)!=0);failed(NPU_TRACE_TABLE);
    fixture();CHECK(npu_trace_prepare(&ctx,&guarded.log,table,41,NULL,NULL)==0);
    table[0].wait_mask=1;CHECK(npu_trace_begin(&ctx,1)!=0);failed(NPU_TRACE_CHANGED);
    fixture();CHECK(npu_trace_prepare(&ctx,&guarded.log,table,41,NULL,NULL)==0);
    CHECK(npu_trace_begin(&ctx,0)!=0);failed(NPU_TRACE_STATE);

    fixture();unsigned char network_byte;
    CHECK(npu_trace_bind((stai_network *)&network_byte,&ctx,&guarded.log,counter,NULL)==STAI_SUCCESS);
    CHECK(installed==npu_trace_callback && installed_cookie==&ctx);
    CHECK(npu_trace_begin(&ctx,1)==0);
    for (unsigned i=0;i<160;++i) installed(installed_cookie,(stai_event_type)(i%4),&table[i/4]);
    installed(installed_cookie,LL_ATON_RT_Callbacktype_NN_DeInit,NULL);
    installed(installed_cookie,LL_ATON_RT_Callbacktype_NN_Init,NULL);
    CHECK(npu_trace_finish(&ctx,STAI_SUCCESS)==0);++tests;
    fixture();registration_rc=STAI_ERROR_GENERIC;
    CHECK(npu_trace_bind((stai_network *)&network_byte,&ctx,&guarded.log,NULL,NULL)==STAI_ERROR_GENERIC);
    failed(NPU_TRACE_REGISTRATION);CHECK(npu_trace_begin(&ctx,1)!=0);
    CHECK(npu_trace_bind(NULL,&ctx,&guarded.log,NULL,NULL)!=STAI_SUCCESS);++tests;
    setup();emit(160);CHECK(npu_trace_finish(&ctx,0)!=0);failed(NPU_TRACE_INCOMPLETE);
    setup();emit(160);npu_trace_callback(&ctx,5,NULL);CHECK(npu_trace_finish(&ctx,0)!=0);failed(NPU_TRACE_INCOMPLETE);
    setup();emit(160);npu_trace_callback(&ctx,4,NULL);failed(NPU_TRACE_EVENT);
    setup();emit(160);npu_trace_callback(&ctx,5,&table[0]);failed(NPU_TRACE_POINTER);
    setup();emit(160);npu_trace_callback(&ctx,5,NULL);npu_trace_callback(&ctx,5,NULL);failed(NPU_TRACE_EVENT);
    setup();npu_trace_callback(&ctx,5,NULL);CHECK(npu_trace_finish(&ctx,0)!=0);failed(NPU_TRACE_POINTER);
    printf("{\"host_control_tests_passed\":%u,\"synthetic_callbacks_only\":true,\"hardware_executed\":false}\n",tests);
    return 0;
}
