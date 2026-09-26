ENTRY(Reset_Handler)
MEMORY {
 CODE (rx) : ORIGIN = 0x34180400, LENGTH = 0x7C00
 MAILBOX (rw) : ORIGIN = 0x34188000, LENGTH = 0x1000
 STACK (rw) : ORIGIN = 0x34189000, LENGTH = 0x2000
}
_sstack=ORIGIN(STACK); _estack=ORIGIN(STACK)+LENGTH(STACK);
PHDRS { code PT_LOAD FLAGS(5); mailbox PT_LOAD FLAGS(6); stack PT_LOAD FLAGS(6); }
SECTIONS {
 .isr_vector : { KEEP(*(.isr_vector)) } > CODE :code
 .text : { *(.text .text.*) *(.rodata .rodata.*) } > CODE :code
 .ARM.extab : { *(.ARM.extab*) } > CODE :code
 .ARM.exidx : { *(.ARM.exidx*) } > CODE :code
 .data : { *(.data .data.*) } > CODE :code
 .bss (NOLOAD) : { *(.bss .bss.*) *(COMMON) } > CODE :code
 .mailbox (NOLOAD) : { KEEP(*(.mailbox)) } > MAILBOX :mailbox
 .stack (NOLOAD) : { . += LENGTH(STACK); } > STACK :stack
 /DISCARD/ : { *(.comment) *(.note.GNU-stack) }
}
ASSERT(ADDR(.isr_vector)==0x34180400 && SIZEOF(.isr_vector)==64,"vector ABI")
ASSERT(SIZEOF(.data)==0 && SIZEOF(.bss)==0,"no uninitialized C runtime")
ASSERT(ADDR(.mailbox)==0x34188000 && SIZEOF(.mailbox)==4096,"mailbox ABI")
ASSERT(ORIGIN(CODE)+LENGTH(CODE)==ORIGIN(MAILBOX),"code/mail boundary")
ASSERT(ORIGIN(MAILBOX)+LENGTH(MAILBOX)==ORIGIN(STACK),"mail/stack boundary")
ASSERT(ORIGIN(STACK)+LENGTH(STACK)<=0x34200000,"outside SRAM2")
