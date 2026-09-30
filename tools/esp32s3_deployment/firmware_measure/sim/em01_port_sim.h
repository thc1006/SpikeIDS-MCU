/* Host-simulation port for em01.c (test only). One em_cycles() call advances
 * simulated time by one PPK2 sample at 240 MHz (2400 cycles); marker writes are
 * logged with their simulated time. */
#ifndef EM01_PORT_SIM_H
#define EM01_PORT_SIM_H
#include <stdint.h>
extern uint32_t sim_cpu_hz;
#define SystemCoreClock sim_cpu_hz
uint32_t sim_cycles(void);
void sim_marker(int high);
void sim_dsb(void);
void sim_nop(void);
void sim_snapshot(volatile rm_result_t *r);
#define __DSB() sim_dsb()
#define __DMB() sim_dsb()
#define __NOP() sim_nop()
#define EM_WAIT_ATTR __attribute__((noinline))
static inline uint32_t em_cycles(void) { return sim_cycles(); }
static inline void em_marker_write(int high) { sim_marker(high); }
static inline void em_marker_setup(void) { sim_marker(0); }
static inline void em_snapshot(volatile rm_result_t *r) { sim_snapshot(r); }
#endif
