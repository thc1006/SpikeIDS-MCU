# Offline PPK2 current and energy analysis

> Scope warning: the offline description below applies to `analyze.py` and
> mocked tests, **not** to the separately added live `power_probe.py` and
> `power_probe_capture_v2.py`. Those scripts can enable DUT power. Their
> authored single-sample 700 mA / any-range ADC-top stop rules are not a
> manufacturer overload oracle and are **on hold for further normal-startup
> qualification**. Source bytes and failed captures remain retained, not
> relabelled successful. See the [policy review](../../results/ppk2_n6_bringup_20260925_nAivHM/POWER_DIAGNOSTIC_POLICY_REVIEW.md)
> before considering any new live acquisition; no larger replacement cutoff
> or automatic retry has been introduced.

This stage connects saved PPK2 raw frames to device-coefficient current and
GPIO-window integration. It **does not** open a serial port, enable power,
program a board, or accept a paper/hardware measurement. Run from the repository
root using the isolated existing Python environment:

```
uv run --no-project --python /home/thc1006/.local/opt/ppk2-headless/.venv/bin/python python -m unittest discover -s tools/ppk2_energy -p 'test_*.py' -v
```

`analyze.py --help` documents the input contract. Supply an existing
`ppk2-transport-diagnostic-v1` capture and its **previously recorded** report
SHA-256, an unused sibling output directory, selected digital channel,
expected window count, declared inferences per window, and explicit idle
sample interval `[start, stop)`. This is an engineering protocol; it does not
prove LOW means matched idle, HIGH means inference, or the divisor is true.

## Explicit voltage and coefficient choices

- `--correction-voltage-v` and its basis are mandatory. They feed the
  voltage-dependent current-correction term, not a hardware command.
- `--energy-voltage-v` and its basis are optional, together. With neither,
  charge is reported and energy is **null**. With both, energy is a
  **constant-voltage estimate**, never a synchronously measured V(t)·I(t).
- Metadata `VDD=4000` is never automatically used for either voltage.
- `metadata-exact` keeps all device coefficients including legitimate zeros.
  `nordic-gui-4.4.1` explicitly reproduces the GUI's zero-or-default rule and
  lists every changed effective coefficient. Neither mode replaces missing,
  nonfinite, or otherwise invalid metadata with generic calibration.
- `--spike-filter none` returns the unfiltered corrected current;
  `nordic-4.4.1` uses the documented stateful range-transition filter across
  the **entire stream**, not reset at GPIO edges or file-read boundaries.
- Source: Nordic `serialDevice.ts`, tag 4.4.1 / commit
  `4cbb4c41c420ddb8125638fffc6d72f6b21c5aaa`; source SHA-256
  `37bda3ca2fb927ec67aa0d981773ec09371a2a799138397f2da6b362bd1ae926`.
  GUI modifier replay is not a claim to duplicate the whole GUI lifecycle.
  No user-gain initialization/write or metadata update occurs.

## Numerical boundaries

Nominal spacing is 10 microseconds per received sample. HIGH windows contain
samples from the observed rising edge inclusive to the falling edge exclusive.
The nominal Riemann sum is current in microamperes × seconds = microcoulombs;
charge × explicit volts = microjoules. Both gross and declared-idle-subtracted
values are retained. Negative samples/energy are not clipped to zero.

Truncated edges, too-short windows (default 100 samples = 1 ms), an unexpected
number of windows, upper-ADC-rail values, or missing baseline fail window checks.
The minimum length does not certify precision. Short inference routines should
be grouped into a counted batch, with loop/marker overhead characterized, before
using this protocol. Counter discontinuities, invalid range, partial frames,
baseline overlap/out-of-bounds, mismatched raw hashes, modified source/report,
and missing/malformed coefficients fail analysis. Missing whole multiples of
64 samples can evade the raw counter; this tool does not prove zero data loss.

## Output and exit status

- 0: offline arithmetic/window checks passed; **not research acceptance**.
- 2: decoding completed but window checks failed (for example no GPIO pulses).
- 1/nonzero: invalid input, arithmetic/I/O failure; never a measured result.

An owned new directory contains `analysis.json`; optionally `current.csv`.
Failed analysis can leave a partial CSV for diagnosis; it is not an accepted
waveform. All reports keep `research_measurement_accepted=false`, plus explicit
false flags for physical voltage, calibration, GPIO wiring, sample-clock and
board/model/count verification. Pins establish read-time content identity
against a caller-supplied commitment, not external authenticity or immutable
archival storage. Existing captures are not modified. Use OS/storage snapshots
or the project's full retention tooling for stronger archival guarantees.

## Hardware work still separate

N6 currently needs v5-trained-model firmware, full fixed-vector input/output
checks, actual clocks/settings, counted inference/idle batches and a reviewed
GPIO pin assignment. PPK2 LOGIC VCC/GND/Dx need physical connection to the
matching I/O domain; power leads alone cannot identify inference windows.
The JP2 whole-board scope must not be labeled isolated NPU/core energy.
Electrical supply qualification is not replaced by any test in this folder.
