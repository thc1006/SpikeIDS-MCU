# First actual power pulse: interrupted diagnostic, not a failed-board verdict

Actual run: 2026-09-25T00:08:21 UTC, tool3b18b9/exit1. Exact PPK2 and
ST-LINK serials were present; fresh PPK metadata reported Ampere mode1.
ON and final OFF command write attempts were27.972158ms apart; all listed
OFF/START/ON/OFF/STOP writes completed. This is host command timing, not
a hardware GPIO measurement of the electrical ON interval.

The unfiltered current decoder crossed the program's conservative700mA stop
threshold at zero-based sample5062. It reported1.005119887A, exactly on the
first sample in range code4 (highest measurement range). This is a decoded
estimate using nominal, unmeasured5V and returned device coefficients, NOT
proof of1A true current or USB overvoltage.

## Saved-data checks

- Raw5120 little-endian32-bit frames/20480bytes; SHA
  `41424033b7b7235ba7cd1cd5c36d0406e7ae901a5babba675765cf4ffc8daada`.
- Report SHA `97fff127ff94ffb318bd3201225a9db51132b1d058eb54ec7d410c3a96130d62`.
- Source SHA `c74d945e81dce5f5647d3795e4f70bdcf0ebae3ccf27cca37daf6d3a00ef4e8f`.
- No counter discontinuities or ADC saturation in retained frames. This does
  not prove no loss of a whole multiple of64 counter values.
- Root offline replay310eef/exit0 retained-state official-compatible filter
  replaces the first highest-range peak with approximately14.953mA. That
  replacement is historical filter state, NOT proof actual current was15mA.
- Independent reviewer66ef55/exit0 used exact rational polynomial arithmetic,
  without importing Decoder/producer: agrees with the unfiltered reported
  peak to within1ULP; review was saved-only, no hardware.
- Later same-range estimates include845.61mA at5067,717.17mA at5070 and
  716.33mA at5071. Four retained samples exceed700mA; only one exceeds1A.
  Therefore the complete high-current feature cannot be dismissed as only
  the first range-transition sample.
- Additional independent direct official-JS comparison completedf59197/exit0:
  all5120 samples under both coefficient policies and both filter policies
  (20480 binary64 values) match exactly. Full-stream filtered maximum is
  **845.61mA at5067**, NOT14.953mA; the latter only describes the replaced first
  highest-range point. See `ACTUAL_PULSE_ORACLE_REVIEW.md` and retained
  `actual_pulse_oracle.json`/`actual_pulse_oracle_exit.json`. Arithmetic agreement
  is not a physical peak-current or instrument calibration verification.
- Live loop processed5063frames, stopping at the first offending sample;
  57 additional frames already received in that same chunk remain saved.
  Raw total nominal51.2ms includes about50ms pre-ON. Only58 highest-range
  samples (nominal580us) remain, not a full3-second startup observation.
  No steady-state conclusion can be drawn; final current decline is not
  tied to an electrical OFF marker, and unrecorded buffered bytes are not
  reconstructed or interpolated.

## Meaning and limits

Nordic confirms that upward measurement-range switching can cause peaks
that are not actual DUT current. The timing here is consistent with that
known artifact, but this single trace cannot separate all real capacitor
charging/inrush from instrument transitions. Both may contribute.

The manufacturer's Ampere-mode admissible current is1A continuous. The
700mA single-unfiltered-sample stop is OUR diagnostic policy, not a Nordic
overload flag or proof the board exceeded its continuous rating. The test
stopped as programmed; no stable boot was observed, so hardware acceptance
remains false. No second ON command or threshold increase was performed.

After OFF, root issued only ST-LINKf7 (dd7e53/exit0 at00:09:02.936904UTC):
raw`e205000002000000`, target-reference estimate0.003187251V. This supports
a low target reference after the test; it is not a5V VIN measurement or proof
that every board rail/input is electrically isolated. Receipt is retained in
`power_pulse_01_post_reference.json`.

Original pulse failures and raw bytes remain unchanged. The62 offline unit
tests (including10 independent pulse controls) passed in66d388/exit0; that
does not certify physical safety, calibrate the instrument or validate v5
inference. Offline firmware integration proceeds separately.

Sources:
- https://devzone.nordicsemi.com/f/nordic-q-a/109264/ppk2-52840-measure-the-current-in-rush-current
- https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_max_dut_current.html
- https://docs.nordicsemi.com/r/bundle/ug_ppk2/page/ug/ppk/ppk_measure_accuracy.html
