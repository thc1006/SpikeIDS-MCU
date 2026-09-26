#include "../firmware_sram/mailbox.h"
/* Same offsets, new deployment identity; input_padding[0:3] is now a receipt. */
#undef S6_DEPLOYMENT_TAG
#define S6_DEPLOYMENT_TAG UINT32_C(0x534D3032)
#define S6_RUNTIME_RECEIPT UINT32_C(0x52544932)
