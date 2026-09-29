/* EM01 platform layer: ESP32-S3 (ESP-IDF 5.4) or host simulation (EM01_HOST_SIM).
 * Everything else in em01.c is RM01's measurement logic, byte for byte. */
#ifndef EM01_PORT_H
#define EM01_PORT_H
#include <stddef.h>
#include <stdint.h>
#include "em01.h"

#ifdef EM01_HOST_SIM
#include "em01_port_sim.h"
#else
#include "driver/gpio.h"
#include "esp_chip_info.h"
#include "esp_cpu.h"
#include "esp_flash.h"
#include "esp_idf_version.h"
#include "esp_private/esp_clk.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "soc/gpio_reg.h"
#include "soc/soc.h"
#include "soc/system_reg.h"

#define __DSB() __asm__ __volatile__("memw" ::: "memory")
#define __DMB() __asm__ __volatile__("memw" ::: "memory")
#define __NOP() __asm__ __volatile__("nop")
/* CPU clock in Hz (240 MHz with CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ_240, no DFS). */
#define SystemCoreClock ((uint32_t)esp_clk_cpu_freq())

static inline uint32_t em_cycles(void)
{
    return esp_cpu_get_cycle_count();          /* CCOUNT: CPU cycles, 32-bit */
}

static inline void em_marker_write(int high)
{
    REG_WRITE(high ? GPIO_OUT_W1TS_REG : GPIO_OUT_W1TC_REG, UINT32_C(1) << EM_MARKER_GPIO);
}

static inline void em_marker_setup(void)
{
    /* No internal pull-up/down: a pull on the marker would draw marker-state-
     * dependent current (gpio_reset_pin() would enable the pull-up). */
    const gpio_config_t cfg = {
        .pin_bit_mask = UINT64_C(1) << EM_MARKER_GPIO,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    REG_WRITE(GPIO_OUT_W1TC_REG, UINT32_C(1) << EM_MARKER_GPIO);   /* LOW before enabling the driver */
    gpio_config(&cfg);
}

static inline void em_snapshot(volatile rm_result_t *r)
{
    esp_chip_info_t ci;
    esp_chip_info(&ci);
    r->chip_info = (uint32_t)ci.model | ((uint32_t)ci.cores << 8) | ((uint32_t)ci.revision << 16);
#ifdef CONFIG_SPIRAM
    r->psram_enabled = 1u;
#else
    r->psram_enabled = 0u;
#endif
    r->apb_hz = (uint32_t)esp_clk_apb_freq();
    r->xtal_hz = (uint32_t)esp_clk_xtal_freq();
    r->cpu_hz_clk = (uint32_t)esp_clk_cpu_freq();
    r->reset_reason = (uint32_t)esp_reset_reason();
    r->marker_gpio = EM_MARKER_GPIO;
    r->tick_hz = (uint32_t)configTICK_RATE_HZ;
    r->core_id = (uint32_t)xPortGetCoreID();
    uint32_t flash = 0;                        /* physical size from the flash JEDEC ID, */
    if (esp_flash_get_physical_size(NULL, &flash) != ESP_OK) flash = 0;   /* not the image header */
    r->flash_bytes = flash;
    r->idf_version = (uint32_t)ESP_IDF_VERSION;
    /* Hardware clock configuration as it is, not the software frequency variable:
     * CPUPERIOD_SEL[1:0] (2 = 240 MHz), PLL_FREQ_SEL[2] (1 = 480 MHz PLL),
     * SOC_CLK_SEL[11:10] (1 = PLL), PRE_DIV_CNT[9:0]. */
    r->cpu_per_conf = REG_READ(SYSTEM_CPU_PER_CONF_REG);
    r->sysclk_conf = REG_READ(SYSTEM_SYSCLK_CONF_REG);
}
#endif
#endif
