# SM06 route repair preflight — 2026-09-26

SM05 timeout and our generator/test assumption error are preserved in
`../host_sram_accum24/ACTUAL_DIAGNOSTIC_FAILURE.md`. No success reclassification.
Fix only two epoch31 source-port records,CONVACC1->3,derived from actual
original ARITH-input topology. Model/data/parameters/error policy unchanged.

16 new native/source tests pass:old SM05 explicitly rejected,all wrong IDs
rejected,configured/enabled producer checked,exactly2numeric source changes,
actual SM06main/tag/runtime7controls. Combined28 arithmetic/schedule/main/
topology tests pass (`a417db -> cd0870 / 0`). Raw integer first-layer result
from old failed diagnostic is limited evidence,not whole-model acceptance.

Actual ARM build `141f84 -> fa0da4 / 0`:63commands,85740B BIN. Independent
saved ELF review `fb3582 / 0`:314input pins,240artifacts,exact content hash,
ELF/BIN bytes,4 disjoint segments,actual NN provider,no undefined/relocations/
cpsie. RX ends0x34077f1d. Old SM05 and SM04 sources remain unchanged.

- RESULT:582163fddcd5e08836588fd4d89f7f6c45540ce0bc017c76fc9ae999d4dc73c6
- ELF:aa31c20c3f3d3078c5b5e356efaee9fae0a46dfbdf42e6262624033fdaafaec4
- BIN:656c04d59f1ad1cc009d1240ca29110714d2f292b0c7640f35a241373bf6c689

30 host tests pass (`1f2935`):all old tags rejected,private binding,no inference
commit in INIT-only,all original FP/runtime/receipt and persistence controls.
Default CLI verifies original1024rows with no USB. Allow one new init-only
RAM run followed by separately checked same-row2656 raw-dot diagnostic.
Stage initialization resets NPU before payload;no Flash/PPK/power/clock
change. No research result or full-run pass until actual evidence succeeds.
