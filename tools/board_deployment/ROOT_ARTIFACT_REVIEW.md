# Root saved-artifact review, 2026-09-25

No target, flash, PPK power or compiled model execution occurred in these checks.

## RA4E1

Standalone `7a2127 / 0`, reviewer `review_ra_saved.py`: 578 original input pins
and 172 saved artifact pins checked; 37 child return codes were typed integers
equal to zero. ARM ELF, all 123120 binary bytes and every Intel HEX data byte,
address and checksum agree. Initial MSP=0x20002000, entry=0x10c5, mailbox=0x2001f000
with 512 NOBITS bytes. Only ordinary flash/SRAM loads exist; no option/protection
programming records. Undefined-symbol output is empty. This validates retained
build artifacts, not board arithmetic or the maximum dynamic stack depth.

An earlier inline reader `e54083 / 1` omitted legal Intel HEX record type 3
(start-segment address). The saved HEX used it. The corrected reader parses and
checks both segment/linear extended and start-address types, requiring the
start address to match the ELF. No firmware output was changed for that fix.

## ESP32-S3 candidate02

Standalone saved check `ca2fba / 0`: the five recorded tool commands, including
compiler/link/image build, all returned zero. Original wrapper exit **1** and
FAILED remain. The final Xtensa ELF has zero nonempty relocation sections.
All 48 build archives (including bootloader archives) were independently scanned
with the installed nm; none references the three forced undefined SDK names.
The inspected set was `__cxx_fatal_exception`, `start_app`, `start_app_other_cores`,
not a blanket allowance for missing symbols. Original strict numerical flags,
PSRAM-disabled setting and both console-disabled settings were checked.

ELF SHA-256 `6f07e705dff6548a780fcd338f040f607e6838482b8aa1d5ac2b0a8000a9f9a9`.
App image: 269472 bytes. Eight PT_LOAD entries include the explicit 24-byte RTC
NOBITS reservation at 0x600fffe8. Mapped flash dummy reservations are not evidence
of installed/enabled PSRAM. This complements, rather than replaces, the author's
source/hash/stat inventory. A separate wrapper-v2 repair is required for future
automatic builds; this note never rewrites candidate02's original exit to zero.

## N6 NPU trace module

Standalone `02b850 / 0`: 123 source/header/tool pins, 43 saved artifact hashes,
11 successful commands, 38 host controls and two actual ARM relocatable objects
from `npu_trace/check_actual_05` checked. Root independently inspected the actual
ST3 sync-run/reset call chain and found the original missing NN_DeInit/NN_Init
events. The retained pre-fix negative test demonstrates this real defect.

The repaired trace requires 160 epoch events plus two ordered NULL-payload reset
events. Eight pure-HW, one hybrid and 31 pure-SW completions are counted separately;
the terminal descriptor is not an executable epoch. This is preparation for a
new instrumented image: the module is not yet linked into the existing frozen
N6 adapter or run on hardware. Callback traces and CPU timestamps are not
independent NPU hardware-cycle/energy measurements.
