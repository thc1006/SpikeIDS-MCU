# Offline internal-SRAM generation preflight

Author synthetic execution `94eb25`, actual exit 0: **22 controls passed**
(0.055 s), with source/test/plan/two-profile SHA bookends identical.
No ST compiler or device was invoked by these controls.

- `generate.py`: `673fae4638731a6f0edbe45c5ef8e61c152e57b52ce1afae38e4224901cbf19a`
- `test_generate.py`: `6db15e1eafb2af3910960dd22e638cf8ec61e9f583adb00e6b9e37dc287a695c`
- `PLAN.md`: `3d3d7a08fdd32fc75b2288547a238d2ce1e6d1c5d8377050c8cb0707d2e5d914`
- `internal_sram.mpool`: `4969fd25574d5db4e603080f9fa03ef092b12ffa7b26b29bc65aab22daf94a15`
- `neural_art.json`: `64fb217c2a0fce1452f97b21ac31dd74f07149a0d5e7d25cce68fbe1e9c959f9`

The positive exercises actual output ownership, file hashing, metadata/address
validation and result publication, using a fake Popen compiler and tiny opaque
inputs. Negative controls include nonzero child exit (23) retained without a
retry, stale output, arbitrary CLI arguments, extra/unknown/cacheable pools,
weight spill/overrun/alignment/membership, typed IDs, initial and allocated FP32
41/5 interfaces, epoch-count mismatch, extra RAW, external/unused-range pointers,
enabled cache allocation, and wrong reference sample-count headers. The profile
hash and exact two-pool contract are also checked. This is not compiler emulation.

Peer lifecycle review independently reproduced two final-callback acceptance
gaps on the draft (`1149d3`, exit 1; positive passed and two expected rejections
failed): replacement of RESULT or addition of an empty output directory after
the final input hash. The current source adds direct original stat and exact
namespace checks after hash callbacks. The historical source snapshot is retained
as `generate_candidate_723562.py`; it has an extra trailing newline and therefore
is not described as byte-identical to the original draft hash. Peer final
regression is separately reported, not claimed as an author execution here.

Selected original model/reference/tool/doc hashes are enforced through the
literal-pinned vendor helper; neither references nor original generated code
are modified. The real candidate will require one fresh compiler invocation to
test the explicit empty-cache-descriptor syntax. Any refusal is retained without
automatic profile changes or retry. Passing generation would establish only
an offline placement candidate, not SRAM accessibility, target initialization,
numerical parity, board inference, hardware safety, energy results, or changes
to the scientific experiment matrix.
