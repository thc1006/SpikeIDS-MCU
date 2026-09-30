# Three-platform deployment plan — fixed v5 model, additive engineering

This is a read-only repository inventory plus implementation plan, not board
acceptance. The user requires all three platforms, including actual N6 NPU work.
No historical CAN measurement is a result for the selected v5 model. No device,
compiler, training, export or inference was invoked for this inventory.

## Exact present targets

| Target | Current local project and SDK evidence | Present mismatch |
| --- | --- | --- |
| STM32N6570-DK | This repository; ST Edge AI 3.0; new [SRAM adapter](../n6_deployment/firmware_sram/BUILD_REVIEW.md) built once, outer exit 0 | Offline ELF only. Platform initialization, load/readback and board parity remain unfinished. Mixed 31 software / 1 hybrid / 8 hardware epochs, not all-NPU. |
| FPB-RA4E1, R7FA4E10D2CFM | [Adjacent FSP project](/home/thc1006/dev/SpikeIDS-RA4E1/firmware/ra4e1_skeleton/buildinfo.json), FSP 6.5.0, vendored CMSIS-NN recipe v6.0.0, optional µT-Kernel 3.0 integration; retained CMake cache selects Arm GNU 13.2.Rel1 | Existing CAN 11→64→64→32→5 INT8 model; `ids_infer` returns only argmax and discards CMSIS status. Not the selected model or a full-logit transport. |
| ESP32-S3 chip target; physical PCB/module SKU **unresolved** | [ESP project inside the same adjacent repository](/home/thc1006/dev/SpikeIDS-RA4E1/firmware/esp32s3/main/CMakeLists.txt), ESP-IDF 5.4.4, locked/installed ESP-NN 1.1.2, retained Xtensa GCC 14.2.0 tool path | Shares the same CAN model C file; 10 old INT8/argmax vectors and repeated first-vector benchmark. No raw 41-input/full-five-output protocol. |

The inventory records exact local file hashes in [THREE_PLATFORM_INVENTORY.json](THREE_PLATFORM_INVENTORY.json).
These are newly observed source/configuration hashes, not original experiment
pins, a clean-build claim, or a full SDK/firmware audit. Adjacent Git HEAD was
`dd54e01b1ff8fa3ec795265b008ccbda72328c3e`; tracked status was clean at inspection.

RA4E1's generated memory map gives 512 KiB code flash and 128 KiB RAM, matching
the [manufacturer's exact-part specification](https://www.renesas.com/en/products/ra4e1/part-details/r7fa4e10d2cfm-ha0).
This is a Cortex-M33 CPU deployment, not an NPU target. ESP32-S3 has LX7 CPUs with
vector instructions and 512 KiB on-chip SRAM; vector acceleration is not an N6
Neural-ART NPU. See the [Espressif chip description](https://www.espressif.com/en/taxonomy/term/793).
Configured memory is not physically confirmed board capacity: ESP `sdkconfig`
selects 16 MB flash and disables PSRAM, but that does not identify a DevKit,
module suffix, populated PSRAM, or wiring.

## Existing contradictions that must not be inherited

- ESP source comments mention ESP-NN 1.2.3; its exact dependency lock and installed
  component manifest both say **1.1.2**, with component commit
  `596b08401a63da3a2e1b40868c442f582a99ae26`. Pin actual implementation before build.
- ESP current `sdkconfig` uses USB Serial/JTAG. Retained `build_uart` instead
  records UART0 at 115200 plus secondary USB Serial/JTAG, and external temporary
  configuration paths. Those files still existed when inspected; they are not
  a reproducible new source-tree configuration. Do not select transport by the
  directory name or reuse the old binary as a v5 image.
- Existing ESP code may silently retain flash weights if internal allocation
  fails. Its layer-time sum and fallback 240 MHz divisor are not a new complete
  inference/placement/clock measurement. Existing aligned-width kernel routing
  is not evidence that 41-wide input is safe for every optimized kernel.
- The old ONNX-to-CMSIS exporter iterates only Gemm/MatMul, rejects nonuniform
  per-channel scales, and can emit zero multipliers for missing scales. ReLU
  clamping cannot replace QCFS Div/Clip/Mul/Add/Floor stages. Do not invoke that
  exporter, retrain a CAN substitute, change scales, or drop unsupported nodes.
- Older audit recommendations for CPU/ReLU-first and old cross-platform CAN
  numbers remain historical; neither replaces this QCFS/N6-NPU objective.

## Common immutable numerical target

The first common engineering candidate is NSL-KDD QCFS primary seed 0,
41→256→256→128→5, the quantized ANN described in the
[selected-model identity](../../results/ppk2_n6_bringup_20260925_nAivHM/SELECTED_MODEL_IDENTITY.md).
Consume the original QDQ graph SHA
`22dc7979340c34af613840a8cef70bc07f469ae2143925660cf3312f36475e2d`
and validation archive SHA
`cb5b3415cdbfb8a27db471f972f73910f7a5503687d79446458b8a48c4ae1edb`.
No new export, training, calibration, label/test access or seed selection.
Preserve original 1024 row order/IDs, all 41 FP32 input words and all five FP32
outputs. Reproduce the held validator's actual call orientation:
`np.allclose(reference, actual, atol=1e-6, rtol=1e-5)` on FP32 arrays, so the
relative-tolerance anchor is **actual**, with NumPy's FP32 threshold arithmetic.
Do not silently swap the arguments or substitute a Python-FP64 threshold;
require zero argmax differences. This is not the separate historical 1% QDQ/FP32
quantization allowance. Native C success is not board parity or energy acceptance.

## Bounded implementation order

1. **N6:** retain the new SRAM ELF and separate raw weights, both identities;
   root/core own minimal reviewed platform setup and loader. Reserve whole
   256 KiB weights / 16 KiB activation pools, not just 145457 / 2048 used bytes.
   WAIT_PLATFORM is not proof of initialized clocks/RIF/NPU. Preserve original
   ST-generation wrapper exit 1, child exit 0, and separate saved-review exit 0.
2. **Shared RA/ESP candidate:** add a fixed-graph portable C backend in this
   repository, not the adjacent frozen firmware. Keep quantized constant storage
   where possible; RA's 128 KiB RAM precludes blindly copying N6's 145457-byte
   raw initializer into RAM. That ST-specific packed RAW is not a portable model.
   Strictly support each actual graph operator, attributes, rounding, per-channel
   scales and QCFS stages; reject anything unimplemented. First build/test only
   tiny synthetic cases. Root reviews before the one full native 1024-row probe;
   retain numerical failures without relaxing policy.
3. **Board adapters:** add new FSP and ESP-IDF projects/configurations using that
   same reviewed backend. Pin SDK/tool versions and inspect ELF/map placement.
   Stream one FP32 request at a time, return all five raw FP32 words, row ID,
   sequence, model/build identity and explicit status. A finite versioned frame
   with length/integrity checks must reject truncation, stale sequence, wrong
   shape and output failure. Do not print decimal logits as the sole evidence.
   Freeze serial/USB transport only after exact ESP module/PCB and console path
   are identified; this does not block native backend work.
4. **Subsequent hardware stage after technical prerequisites/review:** actual
   board programming/readback, 1024-row
   parity, measured clock/placement and validated timing/power windows. Neither
   compiler exit nor heartbeat qualifies inference. No board action is part of
   this inventory author's role. The user's authorization to continue ordinary
   three-board deployment/testing already exists; this is not a request to pause
   for fresh permission at each stage. Novel irreversible OTP/security changes
   remain separately scoped. This inventory does not shrink or complete the
   wider three-board matrix.

Read-only observations: tool chunks `bcc219`, `ca5f5d`, `a6fece` exited 0.
Some discovery calls queried nonexistent guessed paths; those misses were
resolved by file listing and are not missing-SDK findings. No claimed build or
hardware result is inferred from a search command's exit status.
