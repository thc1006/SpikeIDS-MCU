/* SpikeIDS N6 bench — RAM-only image loaded by the debugger into SRAM3_AXI (secure alias).
 * SRAM3_AXI_S: 0x34200000, 448 KB. Layout:
 *   0x34200000 .. 0x3425FFFF  code + data + bss            (384 KB)
 *   0x34260000 .. 0x34263FFF  mailbox (host <-> firmware)  (16 KB, fixed, see mailbox.h)
 *   0x34268000 .. 0x3426FFFF  stack                        (32 KB)
 * Weight/activation buffers are NOT linked here: the host passes their addresses at run time
 * (SRAM2/SRAM4.. or the memory-mapped XSPI2 flash), so placement is an experiment parameter.
 */
ENTRY(Reset_Handler)
MEMORY
{
  RAM (rwx) : ORIGIN = 0x34200000, LENGTH = 0x60000
}
_estack = 0x34270000;
_sstack = 0x34268000;
SECTIONS
{
  .isr_vector : { . = ALIGN(4); KEEP(*(.isr_vector)) . = ALIGN(4); } > RAM
  .text : { . = ALIGN(4); *(.text .text.*) *(.glue_7) *(.glue_7t) *(.eh_frame) KEEP(*(.init)) KEEP(*(.fini)) . = ALIGN(4); _etext = .; } > RAM
  .rodata : { . = ALIGN(4); *(.rodata .rodata.*) . = ALIGN(4); } > RAM
  .ARM.extab : { *(.ARM.extab* .gnu.linkonce.armextab.*) } > RAM
  .ARM.exidx : { __exidx_start = .; *(.ARM.exidx*) __exidx_end = .; } > RAM
  .data : { . = ALIGN(4); _sdata = .; *(.data .data.*) . = ALIGN(4); _edata = .; } > RAM
  .bss : { . = ALIGN(4); _sbss = .; *(.bss .bss.*) *(COMMON) . = ALIGN(4); _ebss = .; } > RAM
  /DISCARD/ : { *(.note.GNU-stack) }
}
