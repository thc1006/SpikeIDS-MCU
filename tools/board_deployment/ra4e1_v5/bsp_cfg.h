/* Additive wrapper: retain reviewed FSP settings, enlarge the main stack. */
#ifndef SPIKEIDS_V5_RA_BSP_OVERRIDE_H
#define SPIKEIDS_V5_RA_BSP_OVERRIDE_H
#include "/home/thc1006/dev/SpikeIDS-RA4E1/firmware/ra4e1_skeleton/ra_cfg/fsp_cfg/bsp/bsp_cfg.h"
#undef BSP_CFG_STACK_MAIN_BYTES
#define BSP_CFG_STACK_MAIN_BYTES (0x2000)
#endif
