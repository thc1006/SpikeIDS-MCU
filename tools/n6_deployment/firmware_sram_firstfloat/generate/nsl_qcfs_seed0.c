/* Additive schedule adapter; the original generated source stays frozen. */
#define LL_ATON_EpochBlockItems_nsl_qcfs_seed0 original_epoch_items_sm04
#include "/home/thc1006/dev/SpikeIDS-MCU/results/ppk2_n6_bringup_20260925_nAivHM/internal_sram_actual_01/generate/nsl_qcfs_seed0.c"
#undef LL_ATON_EpochBlockItems_nsl_qcfs_seed0
#include "../schedule.c"
const EpochBlock_ItemTypeDef *LL_ATON_EpochBlockItems_nsl_qcfs_seed0(void)
{
    static EpochBlock_ItemTypeDef repaired[40];
    return first_float_schedule(original_epoch_items_sm04(),repaired,
        LL_ATON_End_EpochBlock_6,LL_ATON_Start_EpochBlock_7,LL_ATON_End_EpochBlock_7);
}
