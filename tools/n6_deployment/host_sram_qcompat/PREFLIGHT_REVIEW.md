# SM03 actual build and host pre-execution review, 2026-09-26

Actual ARM build `f2f737 -> 2d9d3c / exit0`:63 successful commands,83876-byte
BIN. Root saved-only independent-method ELF review `6592fd / exit0` used
pyelftools and fresh objdump, held290 input pins and240 artifacts, checked
exact ELF/BIN byte reconstruction,4 disjoint load regions, no undefined
symbols/relocations, no cpsie. Original model/vector/weight inputs unchanged.

- RESULT SHA256:1b27bd8e56fcdf631a1ae3ea61d113e8ff7e86c1a027870a37cad4fa2016e2be
- ELF SHA256:daca1f2ce38f8082cb2b848862d1926aa1c3ff90961d6f9267eae4b22e8abc81
- BIN SHA256:55fcdc14f4ffd38ecd6399238957ea222423ba95cf4f9cc032491276d1265d9f

Fresh wrapper disassembly `3412f6 / exit0` confirms5 generated dequant calls
and4 quant calls actually target wrappers, not just unused linked symbols.
Signed16 path has ldrsh, signed conversion and vmul.f32; eight-bit paths copy
the descriptor, transfer zero-point sign to the vendor-consumed field, then
call original vendor functions. Validation failure calls ERROR(-8) park.
Actual main runtime-init call0x340644e8 precedes model-init0x34064504.

Host loads source-pinned original launcher/controller/protocol into private
module namespaces, changes only selected build and SM03 tag, restores the
shared import namespace, and retains all original wire/FP/MMIO/numerical gates.
It does not normalize raw values, outputs or tolerance.22 host tests passed
(`bdfffe / exit0`), including old-tag rejection, raw identity, invalid receipt,
full1024 fake flow and before/after inference failure controls. Combined suite
`2db313 -> 2a3959 / exit0`:216 tests and47 subtests. These are not board results.
Default offline CLI `e70bc4 / exit0` checked all1024 original rows without USB.

Fresh exact-probe read-only F7 `983e5d / exit0`:3.273306772908366,
3.276494023904382,3.270119521912351V; no power/debug/reset. These are uncalibrated
probe indications. No new wiring requested. PPK remains disconnected.

Reviewed next action: one fresh RAM run `results/n6_sram_validation_20260926_04`,
180s outer interrupt deadline and10s kill fallback. Same original row sequence,
no retries or skips, fail on any mismatch. Stage resets NPU before payload;
CPU cleanup halt alone is not NPU-quiescence certification. No Flash/unlock,
PPK access, paper updates or research acceptance. This root review is not an
independent-agent signoff or proof all future mismatches have been eliminated.
