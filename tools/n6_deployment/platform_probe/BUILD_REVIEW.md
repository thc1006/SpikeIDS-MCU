# Minimal secure RAM probe — author offline build review

The RAM-only stub compiled and linked once: tool `4c8d8c`, actual exit **0**,
scope `spikeids-n6-platform-probe-build-01.scope`, invocation
`76fad53296554d58ae69f8d9e15238f6`, configured MemoryMax 4 GiB / swap 0.
The independent lifecycle reviewer approved the bounded design before compilation;
its separate artifact review is not represented here as an author-independent run.
This is author review and local tool observation, not hardware attestation.

## Exact result

- [Pure data ABI](ABI.json): `fe4d6f0c01c2aadf07cdd293f11cfab67e4bf3955c9158a11f729fb4406c1cce`.
- [Build result](build_actual_01/RESULT.json): whole
  `b56bd6bde31101be9b0c56a737c9fef9ab579834a6b247a0cbad861c6c3a7eab`,
  seal `4c4bfc2d8ab1c74b11711877f5a0132f7bc275ea7cd7540a517320b31420ae6e`.
- [ELF](build_actual_01/probe.elf):
  `20da6cdc22415f08dcd91982768a3d22b0bc3399a5c6e3bdade2c33c63dbb956`.
- [BIN](build_actual_01/probe.bin): **472 bytes**,
  `d4a45281814a7bd80da88a196c45d25877b8818419d109be1ba2b37c69ecf143`.
- [External author exit observation](BUILD_ACTUAL_01_EXECUTION.json).

All 15 retained compiler/binutils commands returned integer 0 with no timeout.
The ELF is little-endian ARM EABI soft-float. Its three PT_LOADs are RX code
`[0x34180400,0x341805d8)`, RW NOLOAD stack `[0x34184000,0x34185000)`, and RW
NOLOAD mailbox `[0x34185000,0x34185100)`. Entry is Thumb **0x34180441**, initial
MSP **0x34185000**. Undefined-symbol output is empty; no C runtime/HAL object is
linked, and no initialized data or BSS outside the explicitly cleared mailbox.
The ELF debug sections explain its larger host-file size; they are not target
load segments. BIN is exactly the initialized RX PT_LOAD bytes.

## Bounded checks actually performed

Manual source/disassembly review `bf95a4 / 0` verified pre-C IPSR/CONTROL gates,
the sole SCB write to VTOR, explicit CPSID I/MSPLIM/MSP startup, DSB/ISB, mailbox
odd/DMB/body/DMB/even publication, and a stackless nonreturning fault handler
which reads raw MSP/PSP rather than an exception frame. No FP/MVE instruction or
peripheral initialization call is present. Cortex-M55 integer low-overhead-loop
instructions DLS/LE occur in mailbox clearing; these are not FPU instructions.
Masking configurable interrupts is deliberate; no NVIC/SysTick/watchdog mutation
or interrupt unmask is performed. Invalid pre-C entry spins without a valid new
record; ENTRY_REJECTED is an unused reserved ABI state.

Postcheck `87aaf0 / 0` verified the result seal, **34 input full hash/stat pins**,
**54 pre-result artifact full hash/stat pins**, exact 55 names including RESULT,
and actual command outcomes. It also accepted the original ELF and rejected six
in-memory mutated ELF layouts: even entry, wrong vector MSP, wrong machine,
writable code, wrong code address, and wrong mailbox size. This did not invoke
the compiler again or execute any target instruction. Finite file bookends are
not a whole-host atomic snapshot or full transitive runtime verification.

Source SHA256 values retained by RESULT and unchanged at postcheck:

```text
675becff11678e0baa88a0faabb089cc1e9c99c77f655ba519c57e1441047a35 build.py
e27b1c2fbfe3f011de44b504be6278d26ee9e180093e52ad19e5f4d37f51b525 DESIGN.md
3af509b6d59d8eae933dfdc0764616086f0fdf751c1b2f821bc60ff0d6150557 main.c
8f62adcec638d582447209da87361af96df9c1ac8ca372637e9bf3ebb05ed754 startup.c
03b3937942d4f3921ccc01c04e008db5534664ada252f410d40c967ee48dc169 mailbox.h
d3de4ff6a238a24a2c141d11b89728247bde24c8695e1e54d1cbd9cba09e2e9c linker.ld
```

## Not established

No USB/SWD connection, RAM load, target execution, cache maintenance, model
inference, power action, clock/voltage/RIF/NPU/XSPI initialization, flash/OTP write
or numerical/energy validation occurred. Actual SRAM access, secure privileged
entry, cache-disabled load coherence, watchdog behavior and power stability are
unverified. The ST FSBL layout is a placement precedent, not proof of live RAM
ownership. Host nonce submission starts only after a complete RUNNING record;
an unchanged old mailbox alone is not evidence of current execution. Fault
recording remains best effort and may fail on stack/vector/mailbox access faults.
All platform/readiness/inference/energy acceptance flags remain **false**.
