# SM05 INIT-ONLY diagnostic preflight — 2026-09-26

Not a complete validation,not power acceptance. Root independent-method
review only;no independent-agent signoff. Original model/weights/rows retained.

SM04 failed297values;do not use its outputs for an accepted experiment.
This additive candidate keeps first-layer repair and uses signed24 final NPU
Conv outputs instead of shifted signed16/affine quantization. Actual NPU
packing/ordering/routing are hypotheses to test,not established facts.

12 native/structural tests `dc2f08 -> 2fcd30 / 0`:
all16777216 signed24 decode words;all398336 original1024-row later-layer
quantized outputs exact vs original ONNX;every channel positive/negative
out-of-bound rejection without partial publication;independent input/weight
descriptor equality and limited final Conv/DMA diff;exact routing/enable/
disable removal;actual new schedule inserts3SW epochs (7HW+35SW);actual
main's7 initialization/protocol/error/tag controls. Parameters derive only
from original graph,not references. Full-domain bound255*sum(abs(W))<2^23.
Earlier generator assumptions about different epoch IDs/shifts were rejected
before file emission,then corrected from actual original descriptors.

Actual ARM build `d61f0b -> 0fcd25 / exit0`:63commands,85740B BIN.
Independent pyelftools/fresh objdump `7f6477 / 0`:310source/input pins and
240artifacts match,content digest and ELF/BIN exact reconstruction,four
disjoint segments,no relocations/undefined/cpsie,actual NN interface binds
new provider. Code RX0x34064000+81693;RW0x34077f20+23552;stack/mailbox unchanged.

- RESULT:0d3b0707373cd907ba68f88bac5625648bedea8021ef85575dc10d74c6edb9ae
- ELF:f40c71597030f02fc2090316c950759de3c6fc028243304e173d05ffbc4b6043
- BIN:7df52bf42418665fb77d0e6cb7d7785daf49966e49ec621dbe59a7df076bc78b

29 host binding/initialization controls (`fac3d6 / 0`) pass. All four old
deployment tags rejected;original runtime/FP/IRQ/bus/receipt/retention gates
retained. INIT-ONLY explicitly stops before original collector,no request-
sequence commit,0inferences. Expected outcome INIT_READY,never RESULT/PARITY.
Separate fake full-flow controls exercise old controller;they do not enable
full-run CLI. Default command verifies original1024-row bundle with no USB.

Allowed next hardware operation is one fresh bounded RAM INIT-ONLY run,
then separately reviewed first-failed-row hardware-breakpoint diagnostic
comparing actual NPU signed24 dots to independent host integer dots.
No Flash/unlock,clock/voltage optimization,PPK control or scientific acceptance.
Output DMA confined toalready-initialized activation reservation0x34242000,
max768data+64prefetch bytes;input/weights untouched. PPK is absent.

Installed original LL headers document3byte outputs and stream widths;
ST programming model confirms integer8/16/24-bit datapaths. ST also warns
about optimized accumulation/rounding differences,not an acceptance waiver:
https://stedgeai-dc.st.com/assets/embedded-docs/stneuralart_programming_model.html
RM0486 web access exceeded retrieval size;direct HTTP2 failed and HTTP1
timed out with0bytes. No unsupported manual detail is claimed as verified.
