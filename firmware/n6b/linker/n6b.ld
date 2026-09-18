/* B2 NPU firmware: RAM image loaded by pyOCD into AXISRAM1 (0x34064000, 624 KB), clear of the
 * NPU activation/scratch region (AXISRAM3-6, 0x34200000+) and the weights in XSPI2 flash. */
ENTRY(Reset_Handler)
MEMORY { RAM (rwx) : ORIGIN = 0x34064000, LENGTH = 0x94000 }   /* up to 0x340F8000 (mailbox above) */
_estack = 0x340F8000;
_sstack = 0x340F0000;
SECTIONS {
  .isr_vector : { . = ALIGN(4); KEEP(*(.isr_vector)) . = ALIGN(4); } > RAM
  .text : { . = ALIGN(4); *(.text .text.*) *(.glue_7 .glue_7t) *(.eh_frame) KEEP(*(.init)) KEEP(*(.fini)) . = ALIGN(4); _etext = .; } > RAM
  .rodata : { . = ALIGN(4); *(.rodata .rodata.*) . = ALIGN(4); } > RAM
  .ARM.extab : { *(.ARM.extab*) } > RAM
  .ARM.exidx : { __exidx_start = .; *(.ARM.exidx*) __exidx_end = .; } > RAM
  .data : { . = ALIGN(4); _sdata = .; *(.data .data.*) . = ALIGN(4); _edata = .; } > RAM
  .bss : { . = ALIGN(4); _sbss = .; *(.bss .bss.*) *(COMMON) . = ALIGN(4); _ebss = .; } > RAM
  . = ALIGN(8); PROVIDE(end = .); PROVIDE(_end = .);
  /DISCARD/ : { *(.note.GNU-stack) }
}
