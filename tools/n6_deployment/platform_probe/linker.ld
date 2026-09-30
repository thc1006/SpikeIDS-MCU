ENTRY(Reset_Handler)
MEMORY {
  CODE (rx) : ORIGIN = 0x34180400, LENGTH = 0x3C00
  STACK (rw) : ORIGIN = 0x34184000, LENGTH = 0x1000
  MAILBOX (rw) : ORIGIN = 0x34185000, LENGTH = 0x100
}
_sstack = ORIGIN(STACK); _estack = ORIGIN(STACK)+LENGTH(STACK);
PHDRS { code PT_LOAD FLAGS(5); stack PT_LOAD FLAGS(6); mailbox PT_LOAD FLAGS(6); }
SECTIONS {
  .isr_vector : { KEEP(*(.isr_vector)) } > CODE :code
  .text : { *(.text .text.*) *(.rodata .rodata.*) } > CODE :code
  .ARM.extab : { *(.ARM.extab*) } > CODE :code
  .ARM.exidx : { *(.ARM.exidx*) } > CODE :code
  .data : { *(.data .data.*) } > CODE :code
  .bss (NOLOAD) : { *(.bss .bss.*) *(COMMON) } > CODE :code
  .stack (NOLOAD) : { . += LENGTH(STACK); } > STACK :stack
  .mailbox (NOLOAD) : { KEEP(*(.mailbox)) } > MAILBOX :mailbox
  /DISCARD/ : { *(.comment) *(.note.GNU-stack) }
}
ASSERT(ADDR(.isr_vector)==0x34180400, "vector address")
ASSERT(SIZEOF(.isr_vector)==64, "core vectors only")
ASSERT(SIZEOF(.data)==0 && SIZEOF(.bss)==0, "no hidden C runtime state")
ASSERT(SIZEOF(.mailbox)==256 && ADDR(.mailbox)==0x34185000, "mailbox ABI")
ASSERT(ORIGIN(CODE)>=0x34100000, "overlap frozen v5")
ASSERT(ORIGIN(MAILBOX)+LENGTH(MAILBOX)<=0x34200000, "outside ST FSBL window")
