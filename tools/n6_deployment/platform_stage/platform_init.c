#include "platform_init.h"

/* Exact secure aliases/masks from pinned stm32n657xx.h 559792ea...
 * Corresponding HAL/LL 1.4.0 semantics and limitations are in the review note.
 * No oscillator divider/PLL/PWR/flash/XSPI/OTP/watchdog/CPU-cache writes. */
#define RCC UINT32_C(0x56028000)
#define RIF UINT32_C(0x54024000)
#define CR       (RCC+0x000u)
#define SR       (RCC+0x004u)
#define CFGR1    (RCC+0x020u)
#define CFGR2    (RCC+0x024u)
#define HSICFGR  (RCC+0x048u)
#define RESET5   (RCC+0x220u)
#define MEMEN    (RCC+0x24cu)
#define AHB2EN   (RCC+0x254u)
#define AHB3EN   (RCC+0x258u)
#define AHB5EN   (RCC+0x260u)
#define RAM3CR   UINT32_C(0x52023100)
#define CACHECR  UINT32_C(0x580dfc00)
#define CCR      UINT32_C(0xe000ed14)
#define MPUCTRL  UINT32_C(0xe000ed94)
#define SAUCTRL  UINT32_C(0xe000edd0)
#define NPUSEC   (RIF+0x01cu)
#define NPUPRIV  (RIF+0x03cu)
#define NPULOCK  (RIF+0x05cu)
#define MASTERCR (RIF+0xc00u)
#define NPUATTR  (RIF+0xc14u)
#define NPUBIT   UINT32_C(0x80000000)
#define CACHEBIT UINT32_C(0x40000000)
#define DIVMASK  UINT32_C(0x00777077)

typedef struct { const platform_io_t *io; volatile platform_report_t *r; } state_t;
static uint32_t read_reg(state_t *s, uint32_t address)
{
    uint32_t value=s->io->read32(s->io->context,address);
    s->r->reads++;
    uint32_t n=s->r->observation_count;
    for (uint32_t i=0;i<n;i++) {
        if (s->r->observations[i].address==address) {
            s->r->observations[i].after=value;
            return value;
        }
    }
    if (n>=PLATFORM_OBSERVATIONS) { s->r->error=PLATFORM_OVERFLOW; return value; }
    s->r->observations[n].address=address;
    s->r->observations[n].before=value;
    s->r->observations[n].after=value;
    s->r->observation_count=n+1u;
    return value;
}
static int fail(state_t *s, uint32_t error, uint32_t address,
                uint32_t mask, uint32_t expected, uint32_t actual)
{
    s->r->error=error; s->r->failed_address=address; s->r->failed_mask=mask;
    s->r->expected=expected; s->r->observed=actual;
    return 0;
}
static int check(state_t *s, uint32_t address, uint32_t mask, uint32_t expected,
                 uint32_t error)
{
    uint32_t actual=read_reg(s,address);
    if (s->r->error) return 0;
    return (actual&mask)==expected || fail(s,error,address,mask,expected,actual);
}
static int change(state_t *s, uint32_t address, uint32_t mask, uint32_t expected)
{
    uint32_t old=read_reg(s,address);
    if (s->r->error) return 0;
    if ((old&mask)!=expected) {
        s->io->write32(s->io->context,address,(old&~mask)|expected);
        s->r->writes++;
        s->io->barrier(s->io->context);
    }
    return check(s,address,mask,expected,PLATFORM_READBACK);
}
static int alias_change(state_t *s, uint32_t address, uint32_t mask, uint32_t expected)
{
    /* RCC status/control register readback, dedicated SET/CLEAR writes as in
     * LL_RCC_HSI_Enable / LL_MEM / LL_AHBx. Never RMW the status register. */
    uint32_t old=read_reg(s,address);
    if (s->r->error) return 0;
    uint32_t set=(~old)&expected&mask, clear=old&(~expected)&mask;
    if (set) { s->io->write32(s->io->context,address+0x800u,set); s->r->writes++; }
    if (clear) { s->io->write32(s->io->context,address+0x1000u,clear); s->r->writes++; }
    if (set||clear) s->io->barrier(s->io->context);
    return check(s,address,mask,expected,PLATFORM_READBACK);
}
static int wait_mask(state_t *s, uint32_t address, uint32_t mask, uint32_t expected)
{
    uint32_t actual=0;
    for (uint32_t i=0;i<PLATFORM_POLL_LIMIT;i++) {
        actual=read_reg(s,address); s->r->poll_reads++;
        if (s->r->error) return 0;
        if ((actual&mask)==expected) return 1;
    }
    return fail(s,PLATFORM_TIMEOUT,address,mask,expected,actual);
}
static int default_filters(state_t *s)
{
    /* CPU RAM1/2, both NPU master ports, CPU NPU-RAM port, CACHEAXI control.
     * No write to any RISAF configuration, lock or historical error register. */
    const uint32_t bases[6]={0x54027000u,0x54028000u,0x54029000u,
                            0x5402a000u,0x5402b000u,0x54034000u};
    const uint32_t counts[6]={7,7,11,11,11,2};
    for (uint32_t b=0;b<6;b++) {
        (void)read_reg(s,bases[b]); /* retain lock state; it is not rewritten */
        if (!check(s,bases[b]+8u,0xffffffffu,0,PLATFORM_RIF_ERROR)) return 0;
        for (uint32_t n=0;n<counts[b];n++) {
            uint32_t region=bases[b]+0x40u+n*0x40u;
            if (!check(s,region,1u,0,PLATFORM_RISAF_PROFILE) ||
                !check(s,region+0x10u,1u,0,PLATFORM_RISAF_PROFILE) ||
                !check(s,region+0x20u,1u,0,PLATFORM_RISAF_PROFILE)) return 0;
        }
    }
    return 1;
}
static int npu_security(state_t *s)
{
    uint32_t sec=read_reg(s,NPUSEC),priv=read_reg(s,NPUPRIV);
    uint32_t global=read_reg(s,RIF),lock=read_reg(s,NPULOCK);
    if (((sec&0x400u)==0u || (priv&0x400u)==0u) && ((global&1u)||(lock&0x400u)))
        return fail(s,PLATFORM_LOCKED,NPULOCK,0x400u,0,lock);
    if (!change(s,NPUSEC,0x400u,0x400u) || !change(s,NPUPRIV,0x400u,0x400u)) return 0;
    uint32_t master=read_reg(s,NPUATTR),mlock=read_reg(s,MASTERCR);
    if ((master&0x370u)!=0x310u && (mlock&1u))
        return fail(s,PLATFORM_LOCKED,MASTERCR,1u,0,mlock);
    return change(s,NPUATTR,0x370u,0x310u);
}

int platform_init(const platform_io_t *io, const platform_entry_t *entry,
                  volatile platform_report_t *r)
{
    if (!r) return 0;
    volatile uint32_t *words=(volatile uint32_t *)r;
    for (uint32_t i=0;i<sizeof(*r)/sizeof(*words);i++) words[i]=0;
    r->source_profile=PLATFORM_SOURCE_PROFILE; r->step=STEP_ENTRY;
    if (!io || !io->read32 || !io->write32 || !io->barrier || !entry) {
        r->error=PLATFORM_BAD_API; return 0;
    }
    state_t s={io,r};
    if ((entry->control&3u)!=0u || entry->ipsr!=0u || entry->primask!=1u)
        return fail(&s,PLATFORM_ENTRY,0,3u,0,entry->control);
    if (!check(&s,CCR,0x30000u,0,PLATFORM_CACHE) ||
        !check(&s,MPUCTRL,1u,0,PLATFORM_MEMORY_POLICY) ||
        !check(&s,SAUCTRL,3u,0,PLATFORM_MEMORY_POLICY)) return 0;
    uint32_t divider=read_reg(&s,HSICFGR)&0x180u;
    if (divider!=0 && divider!=0x80u)
        return fail(&s,PLATFORM_HSI_PROFILE,HSICFGR,0x180u,0,divider);
    r->hsi_divider=divider; r->nominal_hz=divider ? 32000000u:64000000u;

    r->step=STEP_CONTROL_CLOCKS;
    if (!alias_change(&s,AHB2EN,0x1000u,0x1000u) ||
        !alias_change(&s,AHB3EN,0x4200u,0x4200u)) return 0;
    r->step=STEP_NPU_RESET;
    if (!alias_change(&s,AHB5EN,NPUBIT|CACHEBIT,NPUBIT|CACHEBIT) ||
        !alias_change(&s,RESET5,NPUBIT,NPUBIT)) return 0;
    /* A halted CPU alone does not quiesce NPU. Assert/readback reset BEFORE
     * changing its master/slave attribution, not merely before clock change. */
    r->step=STEP_RIF;
    if (!default_filters(&s) || !npu_security(&s)) return 0;
    r->step=STEP_HSI;
    if (!alias_change(&s,CR,8u,8u) || !wait_mask(&s,SR,8u,8u)) return 0;
    r->step=STEP_CPU_CLOCK;
    if (!change(&s,CFGR1,0x00030000u,0) || !wait_mask(&s,CFGR1,0x00300000u,0)) return 0;
    r->step=STEP_SYS_CLOCK;
    if (!change(&s,CFGR1,0x03000000u,0) || !wait_mask(&s,CFGR1,0x30000000u,0)) return 0;
    r->step=STEP_DIVIDERS;
    if (!change(&s,CFGR2,DIVMASK,0x00100000u)) return 0;
    r->step=STEP_RAM;
    if (!alias_change(&s,MEMEN,1u,1u) || !change(&s,RAM3CR,0x00100000u,0)) return 0;
    r->step=STEP_CACHE_RESET;
    if (!alias_change(&s,RESET5,CACHEBIT,CACHEBIT) ||
        !alias_change(&s,RESET5,CACHEBIT,0) || !check(&s,CACHECR,1u,0,PLATFORM_CACHE)) return 0;
    r->step=STEP_NPU_RELEASE;
    if (!alias_change(&s,RESET5,NPUBIT,0)) return 0;
    r->step=STEP_FINAL;
    /* Finite endpoint checks after all mutable configuration callbacks. */
    if (!default_filters(&s) || !check(&s,CCR,0x30000u,0,PLATFORM_CACHE) ||
        !check(&s,MPUCTRL,1u,0,PLATFORM_MEMORY_POLICY) ||
        !check(&s,SAUCTRL,3u,0,PLATFORM_MEMORY_POLICY) ||
        !check(&s,HSICFGR,0x180u,divider,PLATFORM_READBACK) ||
        !check(&s,CR,8u,8u,PLATFORM_READBACK) || !check(&s,SR,8u,8u,PLATFORM_READBACK) ||
        !check(&s,CFGR1,0x33330000u,0,PLATFORM_READBACK) ||
        !check(&s,CFGR2,DIVMASK,0x00100000u,PLATFORM_READBACK) ||
        !check(&s,AHB2EN,0x1000u,0x1000u,PLATFORM_READBACK) ||
        !check(&s,AHB3EN,0x4200u,0x4200u,PLATFORM_READBACK) ||
        !check(&s,AHB5EN,NPUBIT|CACHEBIT,NPUBIT|CACHEBIT,PLATFORM_READBACK) ||
        !check(&s,MEMEN,1u,1u,PLATFORM_READBACK) ||
        !check(&s,RAM3CR,0x00100000u,0,PLATFORM_READBACK) ||
        !check(&s,NPUSEC,0x400u,0x400u,PLATFORM_READBACK) ||
        !check(&s,NPUPRIV,0x400u,0x400u,PLATFORM_READBACK) ||
        !check(&s,NPUATTR,0x370u,0x310u,PLATFORM_READBACK) ||
        !check(&s,RESET5,NPUBIT|CACHEBIT,0,PLATFORM_READBACK) ||
        !check(&s,CACHECR,1u,0,PLATFORM_CACHE)) return 0;
    r->ready_for_payload=1;
    return 1;
}
