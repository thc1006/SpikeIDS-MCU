# Hardware deployment gap review — 2026-09-21

## Scope and decision

This is a read-only source/vendor-tool review, not a board acceptance report. No USB connection, firmware load, compilation, training, reset, or flashing was performed for this review. Device identification and backups are separate work; this document does not certify their completion. No new formal v5 export or three-platform measurement is certified here.

**Decision:** existing transports and vendor validation infrastructure are reusable, but existing CAN models, synthetic kernels, clock assumptions, and timing summaries cannot become v5 deployment results. The smallest defensible next milestone is **one frozen v5 ReLU FP32 checkpoint → its exact exported validation inputs → full on-board output logits + raw cycle/clock evidence**, initially on STM32N6 Cortex-M55. This is a CPU FP32 milestone, not an INT8, NPU, QCFS, TinyCNN, energy, or three-platform claim.

Path notation below:

- `MCU/` = `/home/thc1006/dev/SpikeIDS-MCU/` (this repository).
- `RA4/` = `/home/thc1006/dev/SpikeIDS-RA4E1/` (adjacent repository, inspected relevant existing model/transport files only).
- `ST/` = `/home/thc1006/opt/stedgeai/3.0/` (installed vendor package).
- `AI/` = `ST/scripts/ai_runner/stm_ai_runner/`.

Line references identify inspected bytes; they are not a substitute for a future build's complete source/tool inventory.

## 1. Existing scientific export boundary

`MCU/spikeids_v5/export_verified.py:63-77` selects the frozen deployment seed/checkpoint and reconstructs the trained model. Lines 125-135 bind checkpoint, preprocessing/data identities and numerical tolerances. Lines 214-218 save `validation_vectors.npz` with `x`, `reference_logits`, `original_logits`, `validation_row_ids`, plus fit-only calibration row IDs and preprocessing.

The formal export context requires 1,024 validation samples and 1,000 fit calibration samples (`export_verified.py:50-55`, `:119-122`). “Full validation vectors” in this milestone means **every row of that frozen exported validation subset in its frozen order**, not all validation rows in the dataset and not a new hand-selected subset. Never use test performance to choose the deployment model or tune tolerances.

The QDQ recipe uses `per_channel=True` (`export_verified.py:198-203`). Its scope statement explicitly does not establish all-integer or all-NPU execution (`:209-212`). Export success itself leaves `board_validated`, `energy_measured`, and `npu_placement_verified` false (`:183`). These boundaries must remain intact.

## 2. Existing implementations: useful parts and blockers

| Component and exact source | Reusable part | Blocker for a formal v5 result |
| --- | --- | --- |
| `MCU/firmware/n6/src/kernels_mlp.c:67-78`, `:99-106` | CMSIS-NN kernel exercise and mailbox mechanism | Representative fixed `Q_MULT=1073741824`, `Q_SHIFT=-1`, fabricated biases `(k & 7)-3`, fixed offsets/requantization. Not a v5 trained model. |
| `MCU/scripts/n6_bench.py:62-68`, `:169-179`, `:246-251`, `:358-371` | ELF segment load/readback and DWT-vs-host elapsed-clock diagnostic concept | Hard-coded legacy shapes and synthetic weights. Clock diagnostic must preserve raw timestamps/counters and wrap/error evidence before reuse; it is not model parity evidence. |
| `MCU/firmware/n6cpu/src/main_cpu.c:33-44`, `:61-75` | CPU runtime invocation | Explicit clock/voltage setup, zero input, 256 repeated inferences, last argmax/return code only. No complete per-vector logits. |
| `MCU/scripts/n6_cpu_run.py:39-44`, `:74-85`, `:109` | ELF readback, reading firmware clock metadata | Empirical clock divides by requested `2.0` seconds, not measured elapsed time; low clock result falls back to CLI value, default 800 MHz. Neither fallback nor requested sleep is acceptable raw clock evidence. |
| `MCU/firmware/n6b/src/main_npu.c:56`, `:72-79`; `MCU/scripts/n6b_run.py:102-115` | ATON invocation and mailbox transport | Zero input/argmax-only, default 800 MHz conversion; failed run prints and returns instead of fail-closed acceptance. |
| `MCU/scripts/n6_validate_pathB.py:132-169` | AiRunner serial invocation already obtains outputs and profiler | Generates random inputs (`:146`) and saves only timing summaries, dropping actual inputs, logits, raw counters and clock metadata. Model is selected as `names[0]`, not checked against a v5 build manifest. |
| `MCU/scripts/n6_validate_pathB.py:27-38`, `:43-52` | Known legacy Python compatibility workarounds | NumPy/protobuf shim and hard-coded validation ELF entry address must not silently carry over. Isolate/pin the adapter; resolve entry/symbols from the actual new ELF. |
| `MCU/firmware/n6b/build.sh:2-29` | Existing include/library/linker recipe as a reference | No `set -e`, hard-coded scratch paths, accumulated compile failures and potentially misleading later success output. Future build must check every return code and freeze actual inputs. Do not execute this legacy script as an acceptance pipeline. |
| `RA4/firmware/app/model/ids_model.h:8-14` | Concrete CMSIS model layout | CAN 11→64→64→32→5, 7,008 weights; not one of the new v5 four-dataset checkpoints. |
| `RA4/ml/export_deploy_model.py:43-55` | Example model-export plumbing | Retrains a CAN model independently. Deployment must consume the selected v5 checkpoint, never retrain a substitute. |
| `RA4/firmware/app/ids_infer.c:57-101` | Real weights/biases/requantization and CMSIS fully connected calls | Kernel return code ignored (`:73`); public inference returns argmax rather than full logits (`:90-101`). |
| `RA4/ml/export/onnx_to_cmsis.py:94-116`, `:193-203` | Limited quantized dense-layer parser | Skips non-Gemm/MatMul nodes; rejects nonuniform per-channel weight scales; missing scale can emit zero multiplier plus warning. This is not a general semantic-preserving ONNX converter. |
| `RA4/firmware/ra4e1_skeleton/src/hal_entry.c:50-59`, `:79-100` | DWT capture and interrupt-state control | Fixed CAN vector, 1,000 repeated samples, `SystemCoreClock` metadata. Not v5 parity, full-input latency coverage, or a WCET proof. |
| `RA4/scripts/read_latency.sh:43-55`, `:102-105`, `:117`, `:146-149`, `:32-33` | Resolving mailbox symbols from ELF and sanity-checking DWT/done/core values | Some sample-count/aggregate inconsistencies only warn; raw J-Link log is deleted on exit. Formal collection must retain raw logs and fail on inconsistent counts/aggregates. |

No persisted numerical host-parity harness was identified in the inspected RA4 model/export/app/latency paths; comments claiming argmax agreement are not an auditable result. This is a scoped finding, not a claim that every file in the adjacent repository was searched. ESP32 was not inspected in this bounded review; it remains a separate deployment milestone, not implicitly covered by N6/RA4 infrastructure.

### Model and quantization compatibility

Do not replace QCFS/Floor/Clip behavior with a ReLU dense network or ignore TinyCNN convolution/layout operations. Require complete ONNX operator coverage and input/output layout checks for each compiled graph. A successful compile or matching class prediction alone does not prove numerical equivalence.

The current RA4 converter's rejection of nonuniform per-channel weights conflicts with v5's fixed per-channel QDQ recipe. Resolve with a backend that supports the actual graph/quantization, or a separately frozen, explicitly different deployment quantization protocol and fresh parity validation. Do not silently change the existing recipe to make legacy code accept it. Float I/O around QDQ also does not establish an all-integer implementation.

## 3. What the current deployment gate does and does not establish

`MCU/spikeids_v5/deployment_gate.py` provides useful offline file-consistency checks:

- Lines 24-45 check the export inventory/seals, frozen tolerances, trained-model role, graph identity, evidence-file hashes, and validation NPZ hash.
- Lines 51-59 require positive integer cycle samples, no included warmup/unresolved wraps, full output shape/parity, and zero argmax disagreement against the exported reference.
- Lines 3 and 63-64 explicitly deny physical-measurement authentication and energy measurement. Preserve those statements.

Remaining acceptance gaps are concrete:

1. The compiler mapping file is hashed (`:41-44`), not parsed to establish CPU/NPU placement. An arbitrary text report cannot support an all-NPU claim.
2. Clock validation checks matching frequency and nonempty derivation/raw-evidence fields (`:49-50`), not a valid RCC derivation or measurement procedure. Independent semantic review remains required.
3. There is no enforced per-row input→output→timing→session association or full scheduled sample-count policy. A future collector must preserve and validate that association; the NPZ hash alone does not show the board received those rows.
4. The gate is not a substitute for validating compile/load identity, raw transport evidence, mutation-safe artifact collection, or instrument provenance. Do not label its returned `evidence_files_consistent` as physical attestation.

## 4. Installed ST Edge AI 3.0: observed offline capabilities

Only `ST/Utilities/linux/stedgeai --help` and `... generate --target stm32n6 --help` were executed. They exited successfully; the tool reported `ST Edge AI Core v3.0.0-20426 123672867`, and target help reported `STM32CubeAI 11.0.0-RC6`. Help availability is not a successful compile or hardware validation.

### AiRunner output, cycles, clocks and transport

| Source | Observed interface | Required interpretation |
| --- | --- | --- |
| `AI/ai_runner.py:518-525`, `:745-847` | `runner.invoke(inputs, name=..., mode=AiRunner.Mode.IO_ONLY, disable_pb=True)` returns output tensors and profiler; high-level batching loops one sample at a time | Use exact frozen data, explicit model, exact requested/returned mode; require all scheduled outputs. Callback can stop early (`:836-839`). |
| `AI/ai_runner.py:686-729` | Unsupported profiling capabilities may be stripped; input check tolerates singleton-shape differences | Explicitly validate actual mode, dtype, feature order and frozen layout adapter. Do not rely on permissive shape matching. |
| `AI/ai_runner.py:792-803`, `:840-847`; `AI/pb_mgr_drv.py:1232-1264` | `profiler.c_durations`, `profiler.debug.exec_times`, `profiler.debug.counters.{type,values}`, stack/heap, full output tensors | Save all raw fields. `debug.host_duration` is whole-batch host/transport milliseconds, not board inference. Per-layer duration accounting differs from IO_ONLY whole-inference duration. |
| `AI/pb_mgr_drv.py:143-165`, `:262-264`; `AI/nanopb/stm32msg.proto:142-155` | Counter descriptor plus 32-bit or paired-word 64-bit decode | Preserve raw descriptor, all counter values, and firmware-specific meaning. A decoded 64-bit container alone does not prove that the underlying timer could not wrap. |
| `ST/Middlewares/ST/AI/Validation/Src/aiValidation_ATON_ST_AI.c:1276-1283`; `ST/Middlewares/ST/AI/Validation/Inc/ai_wrapper_ATON.h:84-89` | This ATON implementation transmits five uint64 fields: `cpu_start`, `cpu_core`, `cpu_end`, `cpu_all`, `extra`; duration is derived from `cpu_all` | For this matched firmware, total inference CPU cycles are index 3. Do not sum all five and double-count. Bind actual firmware/source/runtime before applying this interpretation. |
| `AI/pb_mgr_drv.py:924-977`, `:979-989` | Model info includes name, model signature, runtime/tool versions, tensor/memory descriptors; device info includes `sys_clock`, `bus_clock` | `hash` here is vendor `model_info.signature`, not automatically the ONNX SHA-256. `get_info` is cached, not a fresh clock measurement. |
| `ST/Middlewares/ST/AI/Misc/Src/aiTestUtility.c:764-770`; `ST/Middlewares/ST/AI/Misc/Inc/ai_device_adaptor.h:294-305` | N6 reported CPU/system clocks are HAL-derived | Useful metadata, but not raw RCC register evidence or an independent frequency measurement. Preserve both derivation and raw observations separately. |
| `AI/pb_mgr_drv.py:1180-1188`; `AI/nanopb/stm32msg.proto:163` | `PERF_ONLY` enables constant input and omits I/O payload exchange; constant/fixed-input modes also exist | Forbid these modes for same-vector parity. Fast timing on a constant input cannot replace scheduled validation I/O. |
| `AI/pb_mgr_drv.py:866-897`, `:1201-1220`, `:1242-1253` | Serial path sends little-endian tensor bytes, receives acknowledgements and output tensor payloads | Ordinary RUN does not provide a cryptographic per-input checksum echo. Retain TX/RX transcript, expected input bytes/row IDs and responses; do not invent stronger receipt authentication. |
| `AI/serial_hw_drv.py:128-153`, `:197-221` | Explicit serial descriptor; exclusive port access; `io_hw_log=True` routes through pySerial `spy://...` into `stai_serial_log.txt` | Use a fresh session working directory so the fixed log name cannot overwrite another run. The spy trace is transport evidence, not inference-clock evidence. |

The existing `n6_validate_pathB.py` already receives the rich profiler but discards most of it. Reuse the transport concept, not its random inputs and lossy result format. A standalone adapter must pin the Python/package versions and explicitly test the existing protobuf/NumPy compatibility shim before hardware use. Do not import a legacy script merely to inherit global monkeypatches.

### Compile CLI and mapping reports

The installed help exposes `analyze`, `generate`, `validate`, `supported-ops`, `--model`, `--type onnx`, `--name`, `--target stm32n6`, `--c-api st-ai|legacy`, input/output data types, optimization, output/workspace paths, and optional `--st-neural-art`, `--memory-pool`, `--relocatable`. Reports are enabled unless disabled; preserve reports and workspace. The default memory-pool description is effectively unbounded SRAM, so it must not be accepted as evidence of actual board fit.

- `ST/Documentation/network_c_info_json.html:1062-1065` documents N6 Neural-ART generation yielding `network_c_info.json` and validation via `--val-json`.
- That document's lines 2149-2154 define mapping labels `NODE_UNDEF`, `NODE_SW`, `NODE_HW`, `NODE_SW_HW`, `NODE_EC`.
- `ST/scripts/N6_reloc/json_reader.py:80-87`, `:94-155` checks schema 2.0 and recursively handles epoch-controller subgraphs. Reuse its schema knowledge, not an assumption that `NODE_EC` means every nested operation is hardware-only. Reject unknown/missing mappings, and distinguish software/control/compute scope in any placement claim.
- `ST/Documentation/stneuralart_getting_started.html:1305-1315` documents intermediate optimized ONNX/quantization JSON and reports containing compiler options, memory and epoch types. Line 1757 shows `--all-buffers-info --output-info-file c_info.json` at the lower-level compiler interface.
- `MCU/firmware/n6b/model/ids_generate_report.txt:3`, `:72` contains a historical command and mapping-output option, but is for a legacy CAN model and cannot validate a new v5 build.

For NPU deployment later, preserve the complete vendor JSON/text report, optimized graph, memory pools, generated source/weights, link map, ELF/BIN and exact commands. Parse nested mappings and account for every original/optimized graph operation. Neither the filename `int8` nor successful `--st-neural-art` execution establishes all-NPU placement.

## 5. Minimal future build and collection API — proposal only

Implement two narrow, separately reviewed operations rather than a general deployment framework. Neither should implicitly flash, reset, or select a different board.

### `build_v5_n6(bundle, build_root, backend, frozen_build_policy)`

1. Require an accepted, frozen v5 export, its formal-run/export-plan identity, selected checkpoint and preprocessing binding. Refuse failed/partial exports or nonempty output directories.
2. For the first milestone require `backend="cm55_fp32"`, one explicitly selected ReLU graph, and float32 input/output. Freeze all tool/library/source/linker/memory-policy bytes and argv before build.
3. Generate and build using checked return codes, retaining complete stdout/stderr, outputs and workspace. Check graph/tensor mappings, physical memory capacities, linker layout and binary identity. Build success is not parity success.
4. Produce an immutable build manifest binding the export graph, compiler metadata, reports, firmware source and binary; no loading/flashing side effect.

Illustrative generator command, **not executed or claimed validated for this graph**:

```text
/home/thc1006/opt/stedgeai/3.0/Utilities/linux/stedgeai generate
  --target stm32n6 --model BUNDLE/model_fp32.onnx --type onnx
  --name v5_relu --c-api st-ai
  --input-data-type float32 --output-data-type float32
  --optimization time --binary
  --output BUILD/generated --workspace BUILD/workspace
```

This is the proposed CPU generation route without `--st-neural-art`; generated code still requires a matching validation firmware/runtime build and an actual memory/linker check. A later NPU route needs its own pinned Neural-ART profile/memory pools/options and placement acceptance, not a flag retroactively added to the CPU result.

### `collect_v5_n6(bundle, build_manifest, explicit_serial, session_root, frozen_collection_policy)`

1. Require the specifically identified board already running the independently loaded/read-back verified binary. Explicit serial path and expected board/build identity are mandatory; no `names[0]` selection, arbitrary port discovery, load/reset, or implicit fallback.
2. Freeze row order, repetitions, warmup count, timing scope, clock procedure, mode and parity tolerances before the first invocation. Load the NPZ with `allow_pickle=False`; check all identities, float32 values, dimensions and finite values. A declared singleton/layout adapter may only preserve the exact input values/order.
3. In a fresh session directory connect with an explicit descriptor such as `serial:/dev/serial/by-id/EXPLICIT_DEVICE:921600`, enabling `io_hw_log=True`. Baud rate must be a frozen supported setting, not inferred from this example. Check model/runtime/tensor metadata against the build manifest.
4. Keep warmup separately recorded/excluded. For every scheduled exported row call `runner.invoke([x[i:i+1]], name=expected_name, mode=AiRunner.Mode.IO_ONLY, disable_pb=True)` and retain complete outputs/profiler. Require exact output shape/dtype/count, finite logits, expected mode and counter semantics. Each separate call's internal sample index starts at zero: the outer row/session sequence is essential.
5. Record monotonic host start/end, input row ID and exact sent bytes/hash, returned full logits, all raw counter fields, device-duration fields, and transport/session linkage. Keep full serial trace; host elapsed time is not substituted for board cycles.
6. Capture clock evidence separately: raw relevant clock registers and documented derivation plus an independent raw counter/time observation with wrap/debug-halt/uncertainty treatment. Preserve before/after values and timestamps, verify clock stability, and fail if inconsistent. Never fall back to 800 MHz, `SystemCoreClock`, or a requested sleep duration alone.
7. Verify all scheduled rows are present exactly as planned, input→output→timing linkage, frozen numerical tolerances, complete artifact inventory, and unchanged input/build identities. Preserve failures and partial traces; they cannot be converted to passing evidence by dropping rows or retrying only difficult inputs.

Minimal outputs: frozen collection plan, build/export/board identities, session metadata, raw per-row JSONL and tensor payloads, serial trace, `board_logits.npy`, `raw_timing_log.json`, `clock_evidence.json`, and an inventory-bound `board_evidence.json`. A separate per-layer diagnostic may be useful, but do not mix its observer-instrumented timings with the IO_ONLY latency population. Consumer acceptance must add the missing semantic/session gates in §3; merely making the old validator return success is insufficient.

### Earlier engineering-only step: inspect the existing unknown N6 model

Before a new v5 export exists, a narrower, explicitly authorized engineering probe can load the **pinned installed ST validation ELF into SRAM**, then read model metadata and optionally exchange a fixed four-row zero/ramp input batch twice. This changes running board state and initializes peripherals and volatile SAU/TrustZone state; it is not a read-only board observation. It must not program/erase flash, change persistent security configuration (option bytes/OTP/RDP/debug authentication), bypass access restrictions after an error, or claim that the unknown external-flash NBIN is a v5 model. Matching a generic MREL header cannot establish model identity.

Pinned artifact: `ST/scripts/N6_reloc/test/stm32n6570-dk-validation-reloc.elf`, SHA-256 `7f3251a9ccae9735f33091c60092ef36e07697ee7143757a43a2c77038a728db`. Offline ELF inspection found three PT_LOAD segments contained in `[0x34000000, 0x340269ba)`, entry `0x3401e7bd`, initial MSP `0x34024810`. Derive/check these from actual ELF bytes/vector/symbols; never copy an old hard-coded entry into a general loader. Validate both `p_filesz` and `p_memsz`, segment overlap and entry permissions before any connection.

Offline `arm-none-eabi-objdump` of that pinned ELF establishes: `Reset_Handler` at `0x3401e7bc` sets MSPLIM and SP and calls `SystemInit` at `0x3400c2b0`; `SystemInit:0x3400c2b2..0x3400c2b8` writes `0x34000000` to VTOR, whose literal at `0x3400c554` is `0xe000ed08`. Thus this firmware sets its own VTOR before normal execution. However, `SystemInit:0x3400c2ce..0x3400c31a` also initializes SAU RNR/RBAR/RLAR at `0xe000edd8/0xe000eddc/0xe000ede0`, and later touches nonsecure CPACR (`0xe002ed88`). SAU addresses are confirmed by `ST/Projects/STM32N6570-DK/Applications/Drivers/CMSIS/Core/Include/core_cm55.h:2897-2899`, `:3635`. This **volatile security-state initialization is a disclosed side effect** of the authorized normal firmware startup, not permission to unlock a protected device. If those volatile changes are outside the operator's authorization, do not execute this ELF. Never patch its SAU setup to overcome a connection failure.

Use explicit ST-Link UID `004000183234510E37333934`, target `stm32n657x0hxq`, and serial `/dev/serial/by-id/usb-STMicroelectronics_STLINK-V3_004000183234510E37333934-if01`. pyOCD's UID argument is a **substring** match (`MCU/.venv/lib/python3.13/site-packages/pyocd/core/helpers.py:254-272`), so require full UID equality before opening. Options must include `auto_unlock=False`, `pack.debug_sequences.enable=False`, `no_config=True`, a fresh project directory without inherited user scripts, and disabled `cache.enable_memory`, `cache.enable_register`, `cache.read_code_from_elf`. Otherwise a nominal readback could be served from a cache; `auto_unlock` defaults to erase-enabled (`pyocd/core/options.py:36-44`). Do not enable option-byte/debug-security changes. Authorized reset/halt and required core-register setup must fail visibly, not fall back or suppress errors.

A session-local helper may live under `MCU/results/v5_hardware_20260921_7dMGgC/`, not the formal scientific source tree. Before takeover, revalidate the saved readback report and both 128 MiB N6 flash backups against their recorded size/hash. Use fresh output directories, a frozen helper snapshot, verified segment write/readback, required register checks, and a 120-second outer process deadline that preserves partial logs/exceptions. If interrupted, report board state as uncertain; never automatically “recover” through flashing or security changes.

Metadata-only success or repeated I/O bit equality is **engineering status only**. Preserve all model-info fields, input/output arrays, full profiler, raw counter descriptor/values and serial trace. Unknown model identity, independently unverified clock and energy must remain explicit. Do not convert firmware-reported durations into a formal latency claim or label this synthetic-input exchange v5 parity.

## 6. Acceptance order and adversarial checks

1. **Build-only review:** exact export/checkpoint and complete operator coverage; actual memory fit; all compiler return codes; actual binary/entry identity; no legacy quantization constants or model substitution. Freeze artifacts before collection.
2. **One-board FP32 parity review:** all exported vectors, full logits, exact per-row linkage, explicit clock/timing scope, immutable raw logs. Unit counterexamples must reject wrong model/shape/dtype/feature order, constant/PERF_ONLY mode, omitted/duplicate/reordered rows, partial output, nonfinite values, changed artifacts, fabricated clock derivation, and missing/overflowing counter evidence. Repetitions/warmup are checked against the frozen plan.
3. **Only then expand:** separate QCFS/TinyCNN and QDQ/operator-compatibility milestones; separate NPU placement review; separate RA4/ESP32 build/transport/parity acceptance. An unavailable platform or unsupported graph remains a reported gap, not an extrapolated result.
4. **Energy is separate:** require real calibrated voltage/current acquisition, rail and instrument identity, timestamps/triggers synchronized to the inference window, raw samples, integration method and an explicit idle/baseline policy. TDP × latency, vendor estimates or CPU cycles are not measured energy. Keep `energy_measured=False` until this evidence exists.

This phase is complete only as a documented gap/design audit. It does not close any physical deployment, numerical parity, latency, NPU, or energy gate. A second reviewer should check this document's source references and proposed boundary before implementation; then each implemented build/collection phase needs its own adversarial review.

## 7. Partial vendor fingerprints for this review

These SHA-256 values identify only the inspected tool/adapter subset, **not** a complete reproducible firmware-build dependency inventory:

```text
0aa7d9222af9620fce802037f09432f0320b77e90d3415f1d2c1d366b7872714  ST/Utilities/linux/stedgeai
9f0476d75ec5bdb7b0df54549ac490eb02033bdfa17b2be7727f3505ef880cb2  AI/ai_runner.py
472519f5ba7c1d3d82ff2f2ba39f0ad5d548311bb946d5c3ac063c5521a3639e  AI/pb_mgr_drv.py
45dd6ecd95d4380b1be45d01d951dec9ba9cb60f6bd5713261996ea0d99ee5d1  AI/serial_hw_drv.py
cc2c83d476b59c8aad34bc0fdf2ef30674b8069705b22e2fd2dd5b4d817b892f  AI/nanopb/stm32msg.proto
```
