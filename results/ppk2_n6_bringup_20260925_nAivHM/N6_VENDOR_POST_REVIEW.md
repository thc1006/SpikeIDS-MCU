# N6 vendor preparation — independent saved-only post-review

PASS within offline preparation/retention scope. The read-only checker completed as tool chunk `950c01`, actual exit 0. Its exact command/output and two earlier reviewer-assumption failures are retained in [N6_VENDOR_POST_REVIEW_EXECUTION.json](N6_VENDOR_POST_REVIEW_EXECUTION.json). No compiler, model, board, USB, programmer, or power operation was executed by this review.

## Original bindings and checks

- Wrapper source: `cd1bb490fa913d0ffde3c5c59ff8108134537228ded9ec130e5ac17939f7a94f`.
- Root first RESULT whole-file SHA: `220e16ebadb171e1bfecbcfc1a94d5e92a5c098ae2cbcf631289d163bff0e4e4`; canonical content seal: `f40e5ff80a29b7935d1c31ccdac22c4e13e15dafd6f940333576812cd1082f05`.
- Original external execution receipt SHA: `7f58b7067ef3f630a557f50071fc87b4916384084178193c0754e3b95fad921a`: session 90435, completion `5fc850 / exit 0`, invocation `f11e42e216334053a9c6742c0b762713`. Saved service output reports success, 34.242 seconds, memory peak 828.8M and swap 0B; these are retained observations, not new continuous telemetry.
- Rechecked all 23 original input/source/tool pins (7 artifacts, 14 selected vendor files, wrapper and original Python), plus 9 analyze files held before generate. Original isolated Python resolves to managed CPython 3.12.13; the configured timeout is 300 seconds. The first two checker attempts incorrectly assumed repository Python/default timeout; those assumptions were corrected without altering production files.
- Full SHA and original stat checks passed for 102 unique files. Exact output namespace is 77 files including RESULT and 8 directories excluding root, with no FAILED, symlink, hardlinked file, or extra entry. Namespace and all original stats were checked again after long reads.
- Exact version/analyze/generate argument lists, environment, working directory, original streams and embedded/sidecar receipts match; all three actual child return codes are integer 0, with no timeout or exception. The compiler input copy matches original QDQ SHA `22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d`.
- Required generated C/STAI/metadata files are nonempty. The sole advertised binary weight file is `generate/nsl_qcfs_seed0_atonbuf.xSPI2.raw`, 145457 bytes, SHA `cb5b641344e146a9a1b3d439953c9c3b078c706f5fa55eee40b5339ed2cb65ec`.
- The pinned generation report independently parses to 40 epochs: 31 software, 1 hybrid, 8 hardware; their sum and RESULT fields agree.

## Limits

This accepts only the consistency and retention of the recorded offline generation, not vendor-transformation correctness, firmware/linker suitability, on-target parity, pure-NPU execution, performance or energy. Weight bytes are preserved generated products, not proof of semantic equivalence to the original graph. All six acceptance/verification flags remain false, including full toolchain closure; the 17 historical export negatives are not promoted. Only the listed original files were rechecked, not the entire historical research archive or transitive toolchain. File checks are finite endpoint observations. No accepted source or vendor output was edited.

