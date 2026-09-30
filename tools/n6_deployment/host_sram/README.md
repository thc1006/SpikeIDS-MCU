# Fixed N6 SRAM deployment controller

This is an executable controller, not a claim that the attached board ran it.
The only selected model is the original NSL-KDD QCFS primary seed 0 QDQ
(`22dc7979...75e2d`), with the original 1024 validation rows and all five logits.
The generated program maps 8 hardware, 1 hybrid and 31 software epochs. It is
mixed CPU/NPU execution, not an all-NPU graph or temporal SNN.

## Offline check (no USB access)

From the repository root:

```sh
uv run --no-project --offline --python .venv/bin/python python tools/n6_deployment/host_sram/orchestrate.py
```

The fixed bundles validate the independently reviewed `platform_stage_actual_03`
initializer, `firmware_sram/build_actual_01`, internal-SRAM weight binary and
original model/vector hashes. There is no latest-model search or fallback to
legacy CAN firmware. Failed predecessor builds/generation remain preserved.

## Hardware execution (not yet performed)

Add `--execute-ram-validation --output /absolute/repository/results/fresh_name`
only with sustained target power. Use an outer process timeout. This program
does not turn PPK2 ON; leaving it OFF and attempting debug does not test a
powered board. A host timeout cannot prove NPU quiescence or electrical OFF.

The controller attaches to the exact ST-LINK serial with reset, automatic
unlock/mass erase, resume-on-close, debug pack scripts and ambient hooks
disabled. It explicitly halts, backs up every destination before the first
payload write, loads/readbacks the platform initializer and obtains a fresh
nonce response. It then repeats the backup/load/readback sequence for the
model and weights, checks live platform registers and the FP environment,
acknowledges initialization and sends all original 1024 full 41-float inputs.
Every response stores all five logits before the next row is requested.
Any ambiguous failure is retained and is not retried automatically.

Platform initialization does change RCC/NPU/CACHEAXI reset, SRAM and resource
attribution registers. No flash, OTP or MCU reset is performed. The initializer
and old minimal SRAM probe occupy overlapping memory and must not coexist.
The selected bring-up clock is the observed HSI divider's nominal 32/64 MHz,
not a final maximum-performance clock or a calibrated frequency measurement.

Numerical acceptance preserves `np.allclose(reference, actual, atol=1e-6,
rtol=1e-5)` with FP32 arithmetic and zero argmax disagreement. CPU cycle counts
span the whole mixed inference; they are not NPU-only cycles or board energy.
No `RESULT.json` is written if parity or cleanup fails. Numeric success alone
does not establish actual NPU epoch execution, final clock qualification,
GPIO-aligned current integration, or research/paper acceptance.

## Completed offline checks

- Actual N6 ARM model firmware and initializer builds, with independent saved
  ELF/map/layout reviews; failures before the successful builds are retained.
- Independent full-controller controls: 1024-row positive; ACK readback failure;
  a fifth-logit error only on the last row; post-validation floating environment
  failure; cleanup-halt failure. These use fake transport, not hardware.
- Actual fixed-bundle CLI and three stage-bundle test methods pass. The stage
  bundle's independent cross-review is recorded separately, not implied here.

See `INDEPENDENT_CONTROLLER_REVIEW.md` and the adjacent `platform_stage` and
`firmware_sram` review records. Finite review is not proof of zero defects.
