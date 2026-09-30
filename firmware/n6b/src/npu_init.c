/* NPU bring-up for the B2 measurement firmware — logic lifted from ST hello_world misc_toolbox.c
 * (HAL RCC + RIF only). Re-asserts NPU clock/reset, cache and RIF/RISAF so the NPU master can
 * reach the weights (XSPI2 flash) and activations (SRAM) after a pyOCD takeover. */
#include "stm32n6xx_hal.h"
#include "npu_cache.h"
#include "npu_init.h"

static uint32_t get_risaf_max_addr(RISAF_TypeDef *risaf)
{
    uint32_t m = 0U;
    if      ((risaf==RISAF1_S)||(risaf==RISAF1_NS))   m=RISAF1_LIMIT_ADDRESS_SPACE_SIZE;
    else if ((risaf==RISAF2_S)||(risaf==RISAF2_NS))   m=RISAF2_LIMIT_ADDRESS_SPACE_SIZE;
    else if ((risaf==RISAF3_S)||(risaf==RISAF3_NS))   m=RISAF3_LIMIT_ADDRESS_SPACE_SIZE;
    else if ((risaf==RISAF4_S)||(risaf==RISAF4_NS))   m=RISAF4_LIMIT_ADDRESS_SPACE_SIZE;
    else if ((risaf==RISAF5_S)||(risaf==RISAF5_NS))   m=RISAF5_LIMIT_ADDRESS_SPACE_SIZE;
    else if ((risaf==RISAF6_S)||(risaf==RISAF6_NS))   m=RISAF6_LIMIT_ADDRESS_SPACE_SIZE;
    else if ((risaf==RISAF7_S)||(risaf==RISAF7_NS))   m=RISAF7_LIMIT_ADDRESS_SPACE_SIZE;
    else if ((risaf==RISAF8_S)||(risaf==RISAF8_NS))   m=RISAF8_LIMIT_ADDRESS_SPACE_SIZE;
    else if ((risaf==RISAF9_S)||(risaf==RISAF9_NS))   m=RISAF9_LIMIT_ADDRESS_SPACE_SIZE;
    else if ((risaf==RISAF11_S)||(risaf==RISAF11_NS)) m=RISAF11_LIMIT_ADDRESS_SPACE_SIZE;
    else if ((risaf==RISAF12_S)||(risaf==RISAF12_NS)) m=RISAF12_LIMIT_ADDRESS_SPACE_SIZE;
    else if ((risaf==RISAF13_S)||(risaf==RISAF13_NS)) m=RISAF13_LIMIT_ADDRESS_SPACE_SIZE;
    else if ((risaf==RISAF14_S)||(risaf==RISAF14_NS)) m=RISAF14_LIMIT_ADDRESS_SPACE_SIZE;
    else if ((risaf==RISAF15_S)||(risaf==RISAF15_NS)) m=RISAF15_LIMIT_ADDRESS_SPACE_SIZE;
    return m;
}

static void set_risaf_default(RISAF_TypeDef *risaf)
{
    RISAF_BaseRegionConfig_t c;
    c.StartAddress   = 0x0;
    c.EndAddress     = get_risaf_max_addr(risaf);
    c.Filtering      = RISAF_FILTER_ENABLE;
    c.PrivWhitelist  = RIF_CID_NONE;
    c.ReadWhitelist  = RIF_CID_MASK;
    c.WriteWhitelist = RIF_CID_MASK;
    c.Secure = RIF_ATTRIBUTE_SEC;   HAL_RIF_RISAF_ConfigBaseRegion(risaf, 0, &c);
    c.Secure = RIF_ATTRIBUTE_NSEC;  HAL_RIF_RISAF_ConfigBaseRegion(risaf, 1, &c);
}

void RISAF_Config(void)
{
    set_risaf_default(RISAF2_S);   /* SRAM1_AXI  */
    set_risaf_default(RISAF3_S);   /* SRAM2_AXI  */
    set_risaf_default(RISAF4_S);   /* NPU MST0   */
    set_risaf_default(RISAF5_S);   /* NPU MST1   */
    set_risaf_default(RISAF6_S);   /* SRAM3-6    */
    set_risaf_default(RISAF7_S);   /* FLEXMEM    */
    set_risaf_default(RISAF8_S);   /* NPU_CACHE  */
    set_risaf_default(RISAF15_S);  /* NPU_CACHE config */
    set_risaf_default(RISAF11_S);  /* OCTOSPI1 0x90000000 */
    set_risaf_default(RISAF12_S);  /* OCTOSPI2 0x70000000 (weights) */
}

void NPU_Config(void)
{
    __HAL_RCC_NPU_CLK_ENABLE();
    __HAL_RCC_NPU_FORCE_RESET();
    __HAL_RCC_NPU_RELEASE_RESET();
    npu_cache_enable();
    RIMC_MasterConfig_t master_conf;
    master_conf.MasterCID = RIF_CID_1;
    master_conf.SecPriv   = RIF_ATTRIBUTE_SEC | RIF_ATTRIBUTE_PRIV;
    HAL_RIF_RIMC_ConfigMasterAttributes(RIF_MASTER_INDEX_NPU, &master_conf);
    HAL_RIF_RISC_SetSlaveSecureAttributes(RIF_RISC_PERIPH_INDEX_NPU,
                                          RIF_ATTRIBUTE_PRIV | RIF_ATTRIBUTE_SEC);
}
