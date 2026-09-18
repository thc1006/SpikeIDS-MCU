/* Sequential-read bandwidth probes. Explicit inline asm so the access width is exactly what
 * the experiment says, independent of compiler auto-vectorisation. `words` must be a multiple
 * of 8 (32 bytes). The returned checksum is stored by the caller so the loads cannot be elided. */
#include "kernels.h"

uint32_t rd_ldr32(const uint32_t *p, uint32_t words)
{
    uint32_t acc = 0, t0, t1, t2, t3;
    for (uint32_t i = 0; i < words; i += 4) {
        __asm volatile (
            "ldr %0, [%4, #0]\n ldr %1, [%4, #4]\n ldr %2, [%4, #8]\n ldr %3, [%4, #12]\n"
            : "=r"(t0), "=r"(t1), "=r"(t2), "=r"(t3) : "r"(p + i) : "memory");
        acc += t0 ^ t1 ^ t2 ^ t3;
    }
    return acc;
}

uint32_t rd_ldrd64(const uint32_t *p, uint32_t words)
{
    uint32_t acc = 0, t0, t1, t2, t3;
    for (uint32_t i = 0; i < words; i += 4) {
        __asm volatile (
            "ldrd %0, %1, [%4, #0]\n ldrd %2, %3, [%4, #8]\n"
            : "=r"(t0), "=r"(t1), "=r"(t2), "=r"(t3) : "r"(p + i) : "memory");
        acc += t0 ^ t1 ^ t2 ^ t3;
    }
    return acc;
}

uint32_t rd_ldm32x8(const uint32_t *p, uint32_t words)
{
    uint32_t acc = 0, t0, t1, t2, t3, t4, t5, t6, t7;
    for (uint32_t i = 0; i < words; i += 8) {
        __asm volatile (
            "ldm %8, {%0, %1, %2, %3, %4, %5, %6, %7}\n"
            : "=r"(t0), "=r"(t1), "=r"(t2), "=r"(t3), "=r"(t4), "=r"(t5), "=r"(t6), "=r"(t7)
            : "r"(p + i) : "memory");
        acc += t0 ^ t1 ^ t2 ^ t3 ^ t4 ^ t5 ^ t6 ^ t7;
    }
    return acc;
}

/* 128-bit Helium loads: VLDRW.32 q0, [rN], #16 (post-increment), 2 per iteration. */
uint32_t rd_mve128(const uint32_t *p, uint32_t words)
{
    uint32_t acc;
    __asm volatile (
        "vmov.i32 q1, #0\n"
        "1:\n"
        "vldrw.u32 q0, [%1], #16\n"
        "veor q1, q1, q0\n"
        "vldrw.u32 q0, [%1], #16\n"
        "veor q1, q1, q0\n"
        "subs %2, %2, #8\n"
        "bne 1b\n"
        "vaddv.u32 %0, q1\n"
        : "=r"(acc), "+r"(p), "+r"(words) : : "q0", "q1", "cc", "memory");
    return acc;
}
