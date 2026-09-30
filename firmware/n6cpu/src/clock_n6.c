/* STM32N6 CPU@800MHz bring-up for the CPU-int8 baseline, extracted from ST's proven sequence
 * (STM32N6570-DK hello_world / CM55_Validation: system_init_post + BSP_SMPS_Init + SystemClock_Config_HSI_overdrive).
 * Needed because a pyOCD-loaded image inherits the BootROM's 64 MHz HSI clock — measuring there and
 * calling it 800 MHz was wrong. This reaches the SAME operating point as the ST NPU validation firmware
 * (CPU 800 MHz, VDDCORE overdrive 0.89 V, caches actually active via MEMSYSCTL). */
#include "stm32n6xx_hal.h"

/* CMSIS globals normally in system_stm32n6xx_s.c (which needs a TrustZone partition header we don't
 * ship). Minimal, correct substitutes: the update delegates to the HAL's RCC-register computation. */
uint32_t SystemCoreClock = 64000000u;   /* HSI reset default; refreshed below and by HAL_RCC_ClockConfig */
void SystemCoreClockUpdate(void) { SystemCoreClock = HAL_RCC_GetCpuClockFreq(); }

/* Un-shutdown the AXI SRAMs and, critically, set MEMSYSCTL DCACTIVE/ICACTIVE — the boot leaves these
 * 0, which gates the L1 caches OFF even when CCR.DC/IC are set. Without this the cache is inert. */
void n6_system_init_post(void)
{
    __HAL_RCC_SYSCFG_CLK_ENABLE();
    RCC->MEMENR |= RCC_MEMENR_AXISRAM3EN | RCC_MEMENR_AXISRAM4EN |
                   RCC_MEMENR_AXISRAM5EN | RCC_MEMENR_AXISRAM6EN | RCC_MEMENR_CACHEAXIRAMEN;
    RAMCFG_SRAM2_AXI->CR &= ~RAMCFG_CR_SRAMSD;
    RAMCFG_SRAM3_AXI->CR &= ~RAMCFG_CR_SRAMSD;
    RAMCFG_SRAM4_AXI->CR &= ~RAMCFG_CR_SRAMSD;
    RAMCFG_SRAM5_AXI->CR &= ~RAMCFG_CR_SRAMSD;
    RAMCFG_SRAM6_AXI->CR &= ~RAMCFG_CR_SRAMSD;
    MEMSYSCTL->MSCR |= MEMSYSCTL_MSCR_DCACTIVE_Msk | MEMSYSCTL_MSCR_ICACTIVE_Msk;
    __DSB(); __ISB();
}

/* VDDCORE overdrive (0.89 V) via the DK's external SMPS control pin PF4 high (rev C01+).
 * Required for a stable 800 MHz CPU clock. */
void n6_vddcore_overdrive(void)
{
    __HAL_RCC_GPIOF_CLK_ENABLE();
    GPIO_InitTypeDef g = {0};
    g.Pin = GPIO_PIN_4; g.Mode = GPIO_MODE_OUTPUT_PP; g.Pull = GPIO_NOPULL;
    g.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    HAL_GPIO_Init(GPIOF, &g);
    HAL_GPIO_WritePin(GPIOF, GPIO_PIN_4, GPIO_PIN_SET);   /* SMPS_VOLTAGE_OVERDRIVE */
    /* VDDCORE ramp settle. NOT HAL_Delay: startup disables IRQs, so the SysTick tick never advances
     * and HAL_Delay would hang. Busy-wait ~a few ms at the current 64 MHz HSI. */
    for (volatile uint32_t i = 0; i < 300000u; i++) { __NOP(); }
}

/* HSI(64MHz) -> PLL1 M2/N25 = 800 MHz. CPU=IC1=PLL1/1=800MHz, SYSCLK=IC2=400MHz,
 * NPU IC6=PLL2=1GHz, AXISRAM IC11=PLL3=900MHz — identical to ST's overdrive tree. */
void n6_clock_800mhz(void)
{
    RCC_OscInitTypeDef osc = {0};
    RCC_ClkInitTypeDef clk = {0};
    osc.OscillatorType = RCC_OSCILLATORTYPE_HSI; osc.HSIState = RCC_HSI_ON;
    osc.PLL1.PLLState = RCC_PLL_ON; osc.PLL1.PLLSource = RCC_PLLSOURCE_HSI;
    osc.PLL1.PLLM = 2;  osc.PLL1.PLLN = 25;  osc.PLL1.PLLP1 = 1; osc.PLL1.PLLP2 = 1; osc.PLL1.PLLFractional = 0;
    osc.PLL2.PLLState = RCC_PLL_ON; osc.PLL2.PLLSource = RCC_PLLSOURCE_HSI;
    osc.PLL2.PLLM = 8;  osc.PLL2.PLLN = 125; osc.PLL2.PLLP1 = 1; osc.PLL2.PLLP2 = 1; osc.PLL2.PLLFractional = 0;
    osc.PLL3.PLLState = RCC_PLL_ON; osc.PLL3.PLLSource = RCC_PLLSOURCE_HSI;
    osc.PLL3.PLLM = 16; osc.PLL3.PLLN = 225; osc.PLL3.PLLP1 = 1; osc.PLL3.PLLP2 = 1; osc.PLL3.PLLFractional = 0;
    osc.PLL4.PLLState = RCC_PLL_OFF;
    if (HAL_RCC_OscConfig(&osc) != HAL_OK) { for(;;){} }

    clk.ClockType = RCC_CLOCKTYPE_CPUCLK | RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK |
                    RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2 | RCC_CLOCKTYPE_PCLK4 | RCC_CLOCKTYPE_PCLK5;
    clk.IC1Selection.ClockSelection  = RCC_ICCLKSOURCE_PLL1; clk.IC1Selection.ClockDivider  = 1;  /* CPU 800 */
    clk.IC2Selection.ClockSelection  = RCC_ICCLKSOURCE_PLL1; clk.IC2Selection.ClockDivider  = 2;  /* SYS 400 */
    clk.IC6Selection.ClockSelection  = RCC_ICCLKSOURCE_PLL2; clk.IC6Selection.ClockDivider  = 1;  /* NPU 1G  */
    clk.IC11Selection.ClockSelection = RCC_ICCLKSOURCE_PLL3; clk.IC11Selection.ClockDivider = 1;  /* RAM 900 */
    clk.CPUCLKSource = RCC_CPUCLKSOURCE_IC1;
    clk.SYSCLKSource = RCC_SYSCLKSOURCE_IC2_IC6_IC11;
    clk.AHBCLKDivider  = RCC_HCLK_DIV4;
    clk.APB1CLKDivider = RCC_APB1_DIV1; clk.APB2CLKDivider = RCC_APB2_DIV1;
    clk.APB4CLKDivider = RCC_APB4_DIV1; clk.APB5CLKDivider = RCC_APB5_DIV1;
    if (HAL_RCC_ClockConfig(&clk) != HAL_OK) { for(;;){} }
}
