#include "driver/usb_serial_jtag.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "wire.h"
#include <string.h>

static int read_rest(uint8_t *data,size_t n) {
    size_t done=0;
    while(done<n) {
        int got=usb_serial_jtag_read_bytes(data+done,n-done,pdMS_TO_TICKS(1000));
        if(got<=0) return 0;
        done+=(size_t)got;
    }
    return 1;
}
static int send_all(const uint8_t *data,size_t n) {
    size_t sent=0;
    while(sent<n) {
        int count=usb_serial_jtag_write_bytes(data+sent,n-sent,pdMS_TO_TICKS(1000));
        if(count<=0) return 0;
        sent+=(size_t)count;
    }
    return 1;
}
static void worker(void *unused) {
    (void)unused;
    usb_serial_jtag_driver_config_t config={.tx_buffer_size=256,.rx_buffer_size=512};
    if(usb_serial_jtag_driver_install(&config)!=ESP_OK) { vTaskDelete(NULL); return; }
    uint32_t next=1;
    uint8_t request[V5_REQUEST_BYTES],response[V5_RESPONSE_BYTES];
    uint32_t magic=0;
    for(;;) {
        uint8_t byte;
        if(usb_serial_jtag_read_bytes(&byte,1,pdMS_TO_TICKS(1000))!=1) continue;
        magic=(magic>>8)|((uint32_t)byte<<24);
        if(magic==V5_HELLO_QUERY_MAGIC) {
            uint8_t query[V5_HELLO_QUERY_BYTES],hello[V5_HELLO_BYTES];
            v5_put32(query,magic); magic=0;
            if(!read_rest(query+4,V5_HELLO_QUERY_BYTES-4) || !v5_hello_query(query)) continue;
            v5_hello(hello,2);
            if(!send_all(hello,sizeof(hello))) { vTaskDelete(NULL); return; }
            continue; /* Identity query does not reset sequence or invoke model. */
        }
        if(magic!=V5_REQUEST_MAGIC) continue;
        v5_put32(request,magic); magic=0;
        if(!read_rest(request+4,V5_REQUEST_BYTES-4)) continue; /* incomplete frame never inferred */
        (void)v5_process(request,response,&next);
        if(!send_all(response,sizeof(response))) { vTaskDelete(NULL); return; }
        vTaskDelay(1);
    }
}
void app_main(void) {
    /* Fixed CPU0 task, internal stack/RAM; no PSRAM, Wi-Fi, CAN or ESP-NN model. */
    if(xTaskCreatePinnedToCore(worker,"v5_qdq",8192,NULL,5,NULL,0)!=pdPASS) return;
}
