#include "ll_aton_NN_interface.h"
#include <string.h>
_Noreturn void s6_compat_fail(void);

static const EpochBlock_ItemTypeDef *first_float_schedule(
    const EpochBlock_ItemTypeDef *original,EpochBlock_ItemTypeDef *out,
    EpochBlock_FuncPtr_t cast_end,EpochBlock_FuncPtr_t bias_start,EpochBlock_FuncPtr_t bias_end)
{
    const unsigned bounds=EpochBlock_Flags_epoch_start|EpochBlock_Flags_epoch_end;
    if(!original || !out || !cast_end || !bias_start || !bias_end ||
       original[40].flags!=EpochBlock_Flags_last_eb || original[40].start_epoch_block ||
       original[40].end_epoch_block || original[40].wait_mask || original[40].blob_address ||
       original[4].start_epoch_block || original[4].end_epoch_block!=cast_end ||
       original[4].wait_mask || original[4].blob_address ||
       original[4].flags!=(bounds|EpochBlock_Flags_hybrid) ||
       original[5].start_epoch_block!=bias_start || original[5].end_epoch_block!=bias_end ||
       original[5].wait_mask!=1 || original[5].blob_address ||
       original[5].flags!=(bounds|EpochBlock_Flags_pure_hw)) s6_compat_fail();
    unsigned hw=0,sw=0,hybrid=0;
    for(unsigned i=0;i<40;i++) {
        if(original[i].flags&EpochBlock_Flags_last_eb) s6_compat_fail();
        hw+=!!(original[i].flags&EpochBlock_Flags_pure_hw);
        sw+=!!(original[i].flags&EpochBlock_Flags_pure_sw);
        hybrid+=!!(original[i].flags&EpochBlock_Flags_hybrid);
    }
    if(hw!=8 || sw!=31 || hybrid!=1) s6_compat_fail();
    for(unsigned i=0,j=0;i<41;i++) if(i!=5) out[j++]=original[i];
    out[4].flags=bounds|EpochBlock_Flags_pure_sw;
    return out; /*39 executable:7 HW,32 SW; followed by original sentinel.*/
}
