# Negative run05 and bounded diagnostic preflight

Run05 `c2fed4 -> 66721e / actual exit1`:all1024 completed,297/5120 values
failed original tolerance,81 rows affected,0 argmax disagreements. Independent
saved NumPy/struct reviewer `e1e33d / 0` agrees;4823/5120 output words bitwise
equal,max absolute error0.4961204528808594. No final RESULT/no acceptance.
This is an improvement from run04, not permission to weaken acceptance.

Combined old/new firmware regression235 tests+47 subtests passed. Separate
new host23 tests passed. Attempting pytest importlib mode first failed during
collection because legacy modules use sibling imports; standard isolated
collection passed. This was not a model/hardware test failure or hidden retry.

Next diagnostic targets the FIRST failing original validation index20,
rowID2656,not a selected passing example. Original full-run sequence/order
unchanged; diagnostic is distinct sequence1025,one row,never a formal run.
Fixed prior mailbox and PARITY hashes are checked; engine verifies exact
live mailbox, executable and complete weight pool before one commit.

Actual SM04 ELF provider and original generated scheduling table are used
to derive46 ordered callbacks (remove only epoch7 start/end from48). Hardware
breakpoints only; no instruction patch or FLASH operation. Callback captures
are at ENTRY, so observations are named for the next callback, not an assertion
that the named operator has executed. Each captures16KiB activations,mailbox,
registers and FP. All owned breakpoints removed and CPU halted on every exit.
No PPK access, latency/energy acceptance or automatic retry.

29 host tests `f63322 / 0` include46-stop success,timeout,wrongPC,shortwrite,
mid-capture persistence failure and wrong source schedule; fake transport,
not hardware evidence. First-failed-row2656 fixture added and rerun before
actual diagnostic. Original frozen observer remains byte-identical.
