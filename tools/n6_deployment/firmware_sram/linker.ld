ENTRY(Reset_Handler)
MEMORY {
  RAM (rwx) : ORIGIN = 0x34064000, LENGTH = 0x8C000
  STACK (rw) : ORIGIN = 0x340F0000, LENGTH = 0x8000
  MAILBOX (rw) : ORIGIN = 0x340F8000, LENGTH = 0x8000
}
_estack = ORIGIN(STACK) + LENGTH(STACK);
_sstack = ORIGIN(STACK);
__npu_start = 0x34240000; __npu_end = 0x34244000;
__weights_start = 0x34200000; __weights_reserved_end = 0x34240000;
PHDRS { code PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); stack PT_LOAD FLAGS(6); mailbox PT_LOAD FLAGS(6); }
SECTIONS {
  .isr_vector : { KEEP(*(.isr_vector)) } > RAM :code
  .text : { *(.text .text.*) *(.glue_7 .glue_7t) KEEP(*(.init)) KEEP(*(.fini)) } > RAM :code
  .rodata : { *(.rodata .rodata.*) } > RAM :code
  .ARM.extab : { *(.ARM.extab*) } > RAM :code
  .ARM.exidx : { __exidx_start = .; *(.ARM.exidx*) __exidx_end = .; } > RAM :code
  .data : { . = ALIGN(8); _sdata = .; *(.data .data.*) _edata = .; } > RAM :data
  .bss (NOLOAD) : { . = ALIGN(32); _sbss = .; *(.bss .bss.*) *(COMMON) . = ALIGN(32); _ebss = .; } > RAM :data
  .heap (NOLOAD) : { . = ALIGN(32); _heap_start = .; . += 0x4000; _heap_end = .; } > RAM :data
  _end = _ebss; end = _ebss;
  .stack (NOLOAD) : { . = ALIGN(32); . += LENGTH(STACK); } > STACK :stack
  .mailbox (NOLOAD) : { . = ALIGN(32); KEEP(*(.mailbox)) } > MAILBOX :mailbox
  /DISCARD/ : { *(.note.GNU-stack) *(.comment) }
}
ASSERT(_ebss <= _sstack, "RAM image/bss overlaps stack")
ASSERT(_heap_end <= _sstack, "Bounded heap overlaps stack")
ASSERT(SIZEOF(.mailbox) == 512, "Mailbox ABI must be exactly 512 bytes")
ASSERT(ADDR(.mailbox) == 0x340F8000, "Mailbox address changed")
ASSERT(ORIGIN(MAILBOX) + LENGTH(MAILBOX) <= __npu_start, "Mailbox overlaps NPU")
ASSERT((__npu_start % 32) == 0, "Generated input/output alignment broken")
ASSERT(__npu_end - __npu_start == 16384, "Full activation reservation changed")
ASSERT(__weights_reserved_end - __weights_start == 262144, "Full weight reservation changed")
ASSERT(__weights_reserved_end == __npu_start, "SRAM pool boundary changed")
ASSERT(ORIGIN(MAILBOX) + LENGTH(MAILBOX) <= __weights_start, "MCU image overlaps weights")
ASSERT(__npu_end <= 0x34270000, "Pools exceed AXISRAM3")
