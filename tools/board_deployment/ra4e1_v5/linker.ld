/* Existing FSP startup tables, with last 4 KiB reserved from ordinary SRAM. */
ENTRY(Reset_Handler)
INCLUDE /home/thc1006/dev/SpikeIDS-RA4E1/firmware/ra4e1_skeleton/memory_regions.ld
RAM_LENGTH = 0x0001f000;
/* Exclude option/security/programming values even if accidentally emitted. */
SECTIONS { /DISCARD/ : { *(.option_setting*) } }
INCLUDE /home/thc1006/dev/SpikeIDS-RA4E1/firmware/ra4e1_skeleton/fsp_gen.ld
SECTIONS {
    .v5_mailbox 0x2001f000 (NOLOAD) : { KEEP(*(.v5_mailbox)) }
}
ASSERT(SIZEOF(.v5_mailbox)==512, "mailbox ABI size")
ASSERT(ADDR(.v5_mailbox)+SIZEOF(.v5_mailbox)<=0x20020000, "mailbox SRAM")
