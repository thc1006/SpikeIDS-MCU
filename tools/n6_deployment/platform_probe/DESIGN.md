# Minimal secure RAM execution probe — offline design

This is NOT a platform initializer, inference image, boot image, or board-ready
claim. No target execution is authorized by this design or by a successful build.

## Memory and source basis

Use half-open secure addresses: vectors/code/rodata `[0x34180400,0x34184000)`,
stack `[0x34184000,0x34185000)`, mailbox `[0x34185000,0x34185100)`.
The installed ST FSBL linker starts at `0x34180400`, length 511 KiB:
`/home/thc1006/opt/stedgeai/3.0/Projects/STM32N6570-DK/Applications/SNS/cubeIDE/FSBL/STM32N657X0HXQ_RAM.ld`
(SHA256 `321e6275ad1fdbdc8b22b8f6ab0df2e39d022e7a68e45fa63cfd982a6de7da0c`).
This is placement precedent, NOT proof of current SRAM clocks, access, ownership,
security or cache state. Do not retain a resident FSBL in this same region.
The whole probe is disjoint from frozen v5 RAM `[0x34064000,0x34100000)`
and NPU activation `[0x342e0000,0x342e0800)`; no v5 or flash region is loaded.
ST's [UM3249](https://www.st.com/resource/en/user_manual/um3249-getting-started-with-stm32cuben6-for-stm32n6-series-stmicroelectronics.pdf)
sections 4.2.1 and 5.3.1 describe RAM execution and inherited platform state.
BootROM developer mode does not bypass lifecycle/security restrictions.

## Exact core changes and prerequisites

Future host must establish halted **secure privileged Thread mode**, not handler
mode, with CONTROL.nPRIV=0 and SPSEL=0, Thumb execution, both CPU caches disabled,
accessible executable SRAM, and reviewed debug permissions. Host verifies loaded
initialized ELF segments and uses ELF Thumb entry; this is not a flash/OTP image.
No current device state is inferred from this offline build.

Entry records original VTOR, CONTROL, PRIMASK and MSP before using C. It refuses
non-Thread or CONTROL.nPRIV/SPSEL entries in assembly before changing stack or
VTOR; that refusal spins without claiming a valid mailbox (host timeout required).
Secure state is an external prerequisite, not detectable/proven by these fields.
It masks
configurable IRQs using CPSID I so inherited BootROM/peripheral interrupts cannot
enter unknown handlers during this deliberately nonreturning probe; it never
unmasks IRQs or changes NVIC/SysTick/peripheral configuration. It installs only
MSPLIM/MSP for the bounded private stack and SCB.VTOR for its fault vectors,
with DSB/ISB. No CONTROL/PSPLIM/CPACR/clock/voltage/cache/SAU/MPU/RIF/XSPI/NPU/
flash/OTP/watchdog write exists. No FP/MVE instructions or C library is needed.
No vendor SystemInit is linked: the installed implementation has forbidden
RCC/SAU/SYSCFG/PWR/XSPI side effects. Only pinned CMSIS device/core headers are
compiled; the pinned HAL header is provenance, not runtime initialization.

## ABI and readback

`ABI.json` is pure canonical JSON data, authoritative field offsets for a 256-byte
little-endian, uint32 mailbox. The build additionally checks C ABI offsets.
Target clears mailbox, sets magic/version/size, snapshots CPUID/CCR/CONTROL/VTOR,
including an initialization-only host_nonce clear; host submits no nonce until
RUNNING is published. ENTRY_REJECTED is reserved in ABI v1; invalid assembly
entry currently produces no new valid mailbox and must be treated as a timeout.
then publishes RUNNING only if entry mode and cache checks pass. The independent
host must still validate the actual pre-entry environment; checking after entry
cannot make stale instruction cache loading safe. RAM writes are expected.
Every target update uses odd sequence -> DMB -> body -> DMB -> even sequence. Host
reads sequence/body/sequence and accepts only equal even sequence values.
The only host-owned field is host_nonce; target publishes echo_nonce. Do not
read-modify-write the whole mailbox to submit a nonce. Two distinct heartbeat
values (or a new nonce echoed) prove only observed code activity, not elapsed
time or full platform initialization. Heartbeat and sequence wrap as uint32.
The fixed busy delay is not a timer. All platform_initialized values stay zero.

Fault vectors are best effort: a naked handler reads IPSR, EXC_RETURN, raw MSP/
PSP and SCB fault status without dereferencing an exception stack, publishes
FAULT and spins. Its sequence starts with current|1 even if the interrupted
writer was already odd; it never publishes an intermediate even state.
It does not clear fault flags, repair state, return, service a
watchdog or recover from inaccessible mailbox/stack/vector memory. Lockup or a
watchdog reset can prevent any record; a future host must have a bounded timeout.
Only 16 core vectors are present; configurable IRQs remain masked. NMI/fault
handling is not a complete fault-tolerant runtime.

## Offline validation and boundary

Independent reviewer must approve this bounded design before compilation.
Build uses fixed local ARM GNU 13.2.rel1, integer-only freestanding C, no standard
runtime or HAL objects. Preserve command exits/logs, discovered header/tool pins,
ELF/BIN/map/disassembly and a canonical build manifest. Validate vector MSP/Thumb
entry, PT_LOAD ranges and permissions, no unresolved symbols, ABI, allowed core
write sites, and source/artifact bookends. No SWD/USB access or target execution.
Even a fully green offline build cannot prove a functioning supply, successful
RAM load, usable SRAM, current security/cache/watchdog state, NPU or inference.
