# SM05 actual diagnostic failure — preserved,not accepted

`66d7ff -> d867d2 / actual exit1`:first original diagnostic row2656 timed
out after the third dense Start callback,waiting for its CPU Post callback.
Cleanup removed all owned HWbreakpoints and halted CPU with errors[]. No
automatic retry. CPU halt is not NPU quiescence;next fresh initialization
must reset NPU before payload reload. No PPK/Flash/physical supply action.

Saved actual first signed24 NPU dot atSM05_Post_19 independently agrees
256/256 with original int8 W times actual captured unsigned input. Exact
integer range-438393..509420 (`17703d / 0`). This establishes only that one
layer/row's raw result,not complete inference or generic bit-exactness.

Read-only halted observation `0acc5e / 0`:SM05 BUSY,req1,resp0,stage5,no
firmware fault. PC0x34067858 maps toLL_ATON.c:479,stream-engine stop/wait.
Fresh source inspection `f98404 / 0` finds our adapter routes STRENG5 from
CONVACC1 in epoch31 while original layer configures/enables CONVACC2/3.
Correct producer isCONVACC3. This is our source-generator error. Earlier
structural test duplicated the wrong hardcoded ID;its pass did not prove
topological consistency. Do not blame vendor code or original model for this.

New additive SM06 changes only those two source-port tokens (start/end),
derives producer from original graph route,adds tests rejecting original
SM05 and all other incorrect IDs,checks enabled/configured producer and
new mailbox identity. Original SM05 build inputs and failure stay frozen.
Require repeat controlled raw-dot diagnostic before any full1024run.
