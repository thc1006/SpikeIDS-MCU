#ifndef S6_QCOMPAT_MAILBOX_H
#define S6_QCOMPAT_MAILBOX_H
#include "../firmware_sram_runtime/mailbox.h"
#undef S6_DEPLOYMENT_TAG
#define S6_DEPLOYMENT_TAG UINT32_C(0x534D3033)
#endif
