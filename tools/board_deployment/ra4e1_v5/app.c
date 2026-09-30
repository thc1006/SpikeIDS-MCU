#include "hal_data.h"
#include "wire.h"
#include "portable_qdq.h"
#include <stddef.h>
enum { READY=1, BUSY=2, DONE=3, ERROR=4 };
typedef struct {
    uint32_t magic,version,state,fp_environment;
    uint32_t request_commit,response_commit,next_sequence,system_core_clock;
    uint8_t request[V5_REQUEST_BYTES],response[V5_RESPONSE_BYTES];
    uint8_t hello[V5_HELLO_BYTES];
} mailbox;
_Static_assert(sizeof(mailbox)==512 && offsetof(mailbox,request)==32 &&
               offsetof(mailbox,response)==264 && offsetof(mailbox,hello)==352,"mailbox layout");
volatile mailbox g_v5_mailbox __attribute__((section(".v5_mailbox"),aligned(8),used));

/* Generated CAN vectors remain linked with the unchanged FSP configuration;
 * this candidate never opens CAN or the old CAN application. */
void can_callback(can_callback_args_t *args) { (void)args; }
void hal_entry(void) {
    volatile uint8_t *all=(volatile uint8_t *)&g_v5_mailbox;
    for(size_t i=0;i<sizeof(mailbox);i++) all[i]=0;
    g_v5_mailbox.magic=0x41353556u; g_v5_mailbox.version=1;
    g_v5_mailbox.fp_environment=(uint32_t)pq_environment();
    g_v5_mailbox.system_core_clock=SystemCoreClock; /* SDK metadata, not measurement. */
    uint8_t hello[V5_HELLO_BYTES]; v5_hello(hello,1);
    for(unsigned i=0;i<V5_HELLO_BYTES;i++) g_v5_mailbox.hello[i]=hello[i];
    uint32_t next=1; g_v5_mailbox.next_sequence=next;
    __DMB(); g_v5_mailbox.state=READY;
    for(;;) {
        uint32_t commit=g_v5_mailbox.request_commit;
        if(!commit || commit==g_v5_mailbox.response_commit) continue;
        g_v5_mailbox.state=BUSY; __DMB();
        uint8_t request[V5_REQUEST_BYTES],response[V5_RESPONSE_BYTES];
        for(unsigned i=0;i<V5_REQUEST_BYTES;i++) request[i]=g_v5_mailbox.request[i];
        __DMB();
        uint32_t status;
        if(commit!=g_v5_mailbox.request_commit || commit!=v5_get32(request+8)) {
            status=V5_REQUEST_CHANGED; v5_error(request,response,status);
        } else status=v5_process(request,response,&next);
        __DMB();
        int same=(commit==g_v5_mailbox.request_commit);
        for(unsigned i=0;i<V5_REQUEST_BYTES;i++) if(request[i]!=g_v5_mailbox.request[i]) same=0;
        if(!same) { status=V5_REQUEST_CHANGED; v5_error(request,response,status); }
        for(unsigned i=0;i<V5_RESPONSE_BYTES;i++) g_v5_mailbox.response[i]=response[i];
        g_v5_mailbox.next_sequence=next;
        __DMB(); g_v5_mailbox.state=status==V5_OK?DONE:ERROR;
        __DMB(); g_v5_mailbox.response_commit=commit; /* final publication */
    }
}
