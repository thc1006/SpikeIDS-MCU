# Fixed-model internal SRAM generation candidate

One offline ST Edge AI 3.0 **generate** call, only after synthetic tests and
independent review. No analyze/validate/device call, training, ONNX re-export,
quantization revision, checkpoint or new scientific denominator. On failure,
retain output and stop; do not change the profile or retry automatically.

Input is the held NSL-KDD seed-0 QCFS QDQ ONNX, SHA256
`22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d`.
The unchanged original reference archive is pinned and its four NPY headers
checked: x(1024,41), reference_logits/original_logits(1024,5), row IDs(1024).
No reference inference or scoring occurs. All seven original deployment input
commitments and selected real compiler/config/front-end tools are retained via
the literal-pinned `prepare_vendor.py` read-only helpers. Its filesystem owner,
snapshot/inventory and environment helpers are reused, not its default commands.

Two absolute RAW pools only, both non-cacheable, wholly in AXISRAM3:

- weights `[0x34200000,0x34240000)`, 256 KiB, ACC_READ/constants_preferred;
- activations `[0x34240000,0x34244000)`, 16 KiB, ACC_WRITE.

All other pools, virtual pools, NPU cache optimization and epoch-controller
generation are excluded. CPU cache-maintenance code remains requested; that
does not enable a CPU or NPU cache. `cacheinfo: []` is an explicit candidate
syntax; only the one real compiler call can establish that this version accepts
it. If unsupported, retain the failure rather than silently substitute a profile.
ACC_READ is compiler placement, not physical SRAM write protection.

Local ST 3.0 evidence: `Documentation/stneuralart_memory_initializers.html`
(SHA1236cd79f6b32f3bb3a3e8d9df8c949e546c8e04d4e9ff382c663157316403d9),
`Documentation/stneuralart_neural_art_compiler.html`
(SHA20215905ac72e08e614ea0a751cf81821a78f1468ddb4384aa8287458453dfe9),
and `scripts/N6_reloc/test/mpools/stm32n6_int2.mpool`
(SHAdcce1bb3221edfbf8634501a86c2181fc129fbf028c094e0dfd267533abf3d2f),
under `/home/thc1006/opt/stedgeai/3.0`. The latter demonstrates logical read-only
weights in physical SRAM. Descriptors are not proof of powered/accessible RAM.

Postchecks require exactly two observed physical pools and all buffers within
their declared role and used byte extents; every initializer must fit the weights
RAW file, with no activation spill or external/cache allocation. Check 41/5 FP32
interface, generated address literals, real epoch mapping/counts, and unchanged
input and retained output namespaces. Generated epoch counts are observations,
not forced to equal the old 31 SW / 1 hybrid / 8 HW deployment. New addresses
must come from the real compiler, never textual substitution of frozen code.

Only fresh `internal_sram_actual_NN` direct children of the existing bringup
results root are allowed. Capture streams and actual process exit, preserve
FAILED/partial output, and publish own process exit as null; root observes it
externally. Metadata/hash bookends are finite checks, not an OS sandbox or full
transitive toolchain closure. All numerical parity, board, platform and energy
claims remain false. Before later board work, separately review SRAM clock /
shutdown, NPU clock/reset, precise RIF/security, FP software fallback, cache
policy, linker exclusion and byte readback. No OTP, flash or XSPI is initialized.
