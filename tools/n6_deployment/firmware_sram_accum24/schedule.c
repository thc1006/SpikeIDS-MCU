#include "ll_aton_NN_interface.h"
#include <string.h>
_Noreturn void s6_compat_fail(void);

static const EpochBlock_ItemTypeDef *accum_schedule(
    const EpochBlock_ItemTypeDef *base,EpochBlock_ItemTypeDef *output,
    const EpochBlock_FuncPtr_t old_start[3],const EpochBlock_FuncPtr_t old_end[3],
    const EpochBlock_FuncPtr_t new_start[3],const EpochBlock_FuncPtr_t new_end[3],
    const EpochBlock_FuncPtr_t post[3])
{
    if(!base || !output || !old_start || !old_end || !new_start || !new_end || !post)
        s6_compat_fail();
    const uint16_t flags=EpochBlock_Flags_epoch_start|EpochBlock_Flags_epoch_end;
    const uint32_t waits[3]={1u<<8,1u<<5,1u<<2};
    unsigned match=0,hw=0,sw=0;
    if(base[39].flags!=EpochBlock_Flags_last_eb || base[39].start_epoch_block ||
       base[39].end_epoch_block || base[39].blob_address || base[39].wait_mask)s6_compat_fail();
    for(unsigned i=0;i<39;i++){
        const EpochBlock_ItemTypeDef *b=&base[i];
        if(b->flags&EpochBlock_Flags_last_eb)s6_compat_fail();
        hw+=!!(b->flags&EpochBlock_Flags_pure_hw);sw+=!!(b->flags&EpochBlock_Flags_pure_sw);
        for(unsigned j=0;j<3;j++)if(b->start_epoch_block==old_start[j]){
            if(j!=match || !old_start[j] || !new_start[j] || !new_end[j] || !post[j] ||
               b->end_epoch_block!=old_end[j] || b->flags!=(flags|EpochBlock_Flags_pure_hw) ||
               b->blob_address || b->wait_mask!=waits[j])s6_compat_fail();
            match++;
        }
    }
    if(match!=3 || hw!=7 || sw!=32)s6_compat_fail();
    unsigned at=0;
    for(unsigned i=0;i<40;i++){
        output[at]=base[i];
        int selected=-1;
        for(unsigned j=0;j<3;j++)if(base[i].start_epoch_block==old_start[j])selected=(int)j;
        if(selected>=0){
            output[at].start_epoch_block=new_start[selected];output[at].end_epoch_block=new_end[selected];
            at++;memset(&output[at],0,sizeof output[at]);
            output[at].end_epoch_block=post[selected];output[at].flags=flags|EpochBlock_Flags_pure_sw;
        }
        at++;
    }
    if(at!=43)s6_compat_fail();
    return output; /*42 executable,7HW+35SW,then sentinel.*/
}
