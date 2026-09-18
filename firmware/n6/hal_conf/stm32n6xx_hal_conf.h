/* Minimal HAL configuration for the N6 bench: only RCC (clock decode) is compiled. */
#ifndef STM32N6xx_HAL_CONF_H
#define STM32N6xx_HAL_CONF_H
#define HAL_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_GPIO_MODULE_ENABLED
#define HSE_VALUE              48000000UL   /* STM32N6570-DK: 48 MHz crystal (UM3300) */
#define HSE_STARTUP_TIMEOUT    100UL
#define MSI_VALUE               4000000UL
#define HSI_VALUE              64000000UL
#define LSI_VALUE                 32000UL
#define LSE_VALUE                 32768UL
#define LSE_STARTUP_TIMEOUT     5000UL
#define EXTERNAL_CLOCK_VALUE   12288000UL
#define VDD_VALUE               3300UL
#define TICK_INT_PRIORITY       0x0FUL
#define USE_RTOS                0
#define PREFETCH_ENABLE         0
#define INSTRUCTION_CACHE_ENABLE 0
#define DATA_CACHE_ENABLE       0
#define USE_HAL_ADC_REGISTER_CALLBACKS 0
#include "stm32n6xx_hal_rcc.h"
#include "stm32n6xx_hal_gpio.h"
#include "stm32n6xx_hal_cortex.h"
#define assert_param(expr) ((void)0U)
#endif
