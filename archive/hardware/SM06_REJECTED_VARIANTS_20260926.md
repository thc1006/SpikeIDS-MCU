# Historical hardware evidence index — not executable experiment selection

Current entry point: [three-board status](../../tools/board_deployment/STATUS.md).
Only the exact SM06 artifact named by the
[selection gate](../../tools/board_deployment/N6_SM06_SELECTION.json) has
the new two-run numerical acceptance. This index deliberately retains
failed attempts instead of silently deleting, repairing or relabeling them.

| Historical variant / evidence | Why not selected for a new experiment |
| --- | --- |
| S6/SM01, runs01/02 | Wrong FP entry followed by missing global runtime initialization |
| SM02 runtime, run03 | 5103/5120 output values and 497 classifications disagree |
| SM03 qcompat, run04 | Signed16 repaired but first-dense semantic mismatch remained |
| SM04 firstfloat, run05 | 297/5120 output values disagree across 81 rows despite matching classes |
| SM05 accum24, diagnostic01 | Our third-dense switch-source error caused timeout; preserve original defective code and test |
| Original SRAM trace variant | Wrong numerical base and old 40-epoch/162-record contract; not SM06 |
| Earlier PPK electrical observations | No accepted model energy; do not use transient/near-zero current as inference power |
| RA01 / ESP03 cross-builds | Candidates only; not connected-board or energy acceptance |

Raw failures remain at their original `results/n6_*` paths. Old source
variants remain in `tools/n6_deployment/firmware_sram*` because new builds
intentionally pin/include earlier code. Moving these paths would break
source identity, invalidate retained evidence and encourage unverifiable
reconstruction. They are logically quarantined here, not destructively
removed or made to appear never to have existed. Do not select by directory
mtime, the largest version number, wildcard or an old README's command.

Use [new acceptance and all actual receipts](../../results/ppk2_n6_bringup_20260925_nAivHM/N6_SM06_NUMERICAL_ACCEPTANCE_20260926.md).
