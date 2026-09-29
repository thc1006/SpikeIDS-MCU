/* RM01: RA01's linker script (FSP startup tables, option-setting output
 * discarded) with the top 16 KiB of SRAM reserved for the result block. */
ENTRY(Reset_Handler)
INCLUDE /home/thc1006/dev/SpikeIDS-RA4E1/firmware/ra4e1_skeleton/memory_regions.ld
RAM_LENGTH = 0x0001c000;
/* Exclude option/security/programming values even if accidentally emitted. */
SECTIONS { /DISCARD/ : { *(.option_setting*) } }
INCLUDE /home/thc1006/dev/SpikeIDS-RA4E1/firmware/ra4e1_skeleton/fsp_gen.ld
SECTIONS {
    .rm01_result 0x2001c000 (NOLOAD) : { KEEP(*(.rm01_result)) }
}
ASSERT(SIZEOF(.rm01_result)==0x2100, "RM01 result block size")
ASSERT(ADDR(.rm01_result)+SIZEOF(.rm01_result)<=0x20020000, "RM01 result block SRAM")
