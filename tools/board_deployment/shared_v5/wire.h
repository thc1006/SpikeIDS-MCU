#ifndef SPIKEIDS_V5_WIRE_H
#define SPIKEIDS_V5_WIRE_H
#include <stddef.h>
#include <stdint.h>
#define V5_REQUEST_BYTES 232u
#define V5_RESPONSE_BYTES 88u
#define V5_REQUEST_MAGIC 0x51523556u /* LE "V5RQ" */
#define V5_RESPONSE_MAGIC 0x53523556u /* LE "V5RS" */
#define V5_HELLO_QUERY_MAGIC 0x51483556u /* LE "V5HQ" */
#define V5_HELLO_MAGIC 0x49483556u /* LE "V5HI" */
#define V5_HELLO_QUERY_BYTES 12u
#define V5_HELLO_BYTES 160u
#define V5_VECTORS_SHA256 "cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb"
enum { V5_OK=0, V5_BAD_FRAME=1, V5_BAD_MODEL=2, V5_BAD_SEQUENCE=3,
       V5_REQUEST_CHANGED=4, V5_ARITHMETIC_ERROR=0x100 };
uint32_t v5_get32(const uint8_t *p);
void v5_put32(uint8_t *p,uint32_t value);
uint32_t v5_crc32(const uint8_t *data,size_t n);
int v5_hello_query(const uint8_t query[V5_HELLO_QUERY_BYTES]);
void v5_hello(uint8_t response[V5_HELLO_BYTES],uint32_t board_id);
void v5_error(const uint8_t request[V5_REQUEST_BYTES],uint8_t response[V5_RESPONSE_BYTES],uint32_t status);
uint32_t v5_process(const uint8_t request[V5_REQUEST_BYTES],uint8_t response[V5_RESPONSE_BYTES],uint32_t *next_sequence);
#endif
