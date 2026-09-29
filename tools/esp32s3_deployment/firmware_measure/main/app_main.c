/* EM01 entry: run RM01's autonomous measurement sequence (em01.c hal_entry) on
 * core 0 at the highest task priority. Nothing else is started: no Wi-Fi/BT,
 * no console (CONFIG_ESP_CONSOLE_NONE), no power management (no DFS or light
 * sleep), task watchdog disabled in sdkconfig so the busy-waits are allowed.
 * The FreeRTOS tick (CONFIG_FREERTOS_HZ) keeps running and is reported in the
 * snapshot; its ISR time falls into every window alike. Core 1 runs only its
 * idle task. */
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void hal_entry(void);

void app_main(void)
{
    vTaskPrioritySet(NULL, configMAX_PRIORITIES - 1);
    hal_entry();                                   /* never returns */
}
