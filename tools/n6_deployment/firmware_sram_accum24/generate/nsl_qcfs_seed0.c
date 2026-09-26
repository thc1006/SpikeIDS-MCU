#define LL_ATON_EpochBlockItems_nsl_qcfs_seed0 original_epoch_items_sm05
#include "/home/thc1006/dev/SpikeIDS-MCU/results/ppk2_n6_bringup_20260925_nAivHM/internal_sram_actual_01/generate/nsl_qcfs_seed0.c"
#undef LL_ATON_EpochBlockItems_nsl_qcfs_seed0
#include "../../firmware_sram_firstfloat/schedule.c"
#include "../accum_epochs.c"
#include "../schedule.c"
extern void s6_requantize_accum(unsigned);
static void SM05_Post_19(const void *p){(void)p;s6_requantize_accum(0);}
static void SM05_Post_31(const void *p){(void)p;s6_requantize_accum(1);}
static void SM05_Post_43(const void *p){(void)p;s6_requantize_accum(2);}

const EpochBlock_ItemTypeDef *LL_ATON_EpochBlockItems_nsl_qcfs_seed0(void)
{
    static EpochBlock_ItemTypeDef first[40],repaired[43];
    const EpochBlock_FuncPtr_t os[]={LL_ATON_Start_EpochBlock_19,LL_ATON_Start_EpochBlock_31,LL_ATON_Start_EpochBlock_43};
    const EpochBlock_FuncPtr_t oe[]={LL_ATON_End_EpochBlock_19,LL_ATON_End_EpochBlock_31,LL_ATON_End_EpochBlock_43};
    const EpochBlock_FuncPtr_t ns[]={SM05_Start_19,SM05_Start_31,SM05_Start_43};
    const EpochBlock_FuncPtr_t ne[]={SM05_End_19,SM05_End_31,SM05_End_43};
    const EpochBlock_FuncPtr_t post[]={SM05_Post_19,SM05_Post_31,SM05_Post_43};
    first_float_schedule(original_epoch_items_sm05(),first,LL_ATON_End_EpochBlock_6,
                         LL_ATON_Start_EpochBlock_7,LL_ATON_End_EpochBlock_7);
    return accum_schedule(first,repaired,os,oe,ns,ne,post);
}
