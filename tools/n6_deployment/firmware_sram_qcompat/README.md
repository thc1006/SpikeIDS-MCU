# Fixed-model Q/DQ compatibility candidate SM03

Original GPU NSL-KDD QCFS primary seed0, QDQ graph, weights and ordered vectors
are unchanged. This new variant retains original S6 inference loop and SM02
global-runtime ordering, with a new deployment tag. PPK remains out of scope.

Actual diagnostic identified signed16 input misread as signed8 at epoch4.
Full source audit additionally found ST3.0 quant/dequant wrappers select the
zero-point signedness from the scale descriptor. Three inserted quant nodes
have negative signed8 zero points but unsigned scale flags; two later
dequant nodes likewise have negative zero points. This adapter checks all
semantic fields and original scale/zero-point bytes for exactly nine frozen
call sites, handles only the verified signed16 dequant site in scalar FP32,
and passes local signedness-corrected copies to the original eight-bit vendor
kernels. Width is explicit per call site, not guessed from arbitrary stride.
Unknown/corrupt descriptors park in ERROR(-8) without invoking a kernel.

The original ST installation and generated source are not patched. GNU ld
--wrap redirects the two symbols only in this variant. Old hosts reject SM03.
Build uses the frozen builder with the same compiler, dependencies, layout,
no-overwrite checks and runtime archive; ffp-contract=off and no-fast-math are
explicit. No claim of full numerical parity, profiling, energy, optimization
or research acceptance follows from compilation or host tests.

Validation prerequisites: test all generated descriptors against this table,
signed16 full-domain arithmetic, negative zero points and malformed metadata;
review actual ELF wrappers and original identity pins; then run every original
validation row under unchanged numerical policy. Keep negative evidence.
