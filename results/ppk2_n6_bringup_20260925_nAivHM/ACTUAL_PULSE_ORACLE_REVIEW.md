# Saved pulse: official arithmetic matches, physical interpretation remains open

Saved-only command **f59197 exited 0**. All **5120 saved frames**, under both
metadata-exact and GUI coefficient policies, with unfiltered and official
range-transition-filtered conversion, give **20480/20480 identical binary64
results** between Python and the extracted official v4.4.1 JavaScript method.
The fixed source's whole SHA was verified again through `gh api`; no device,
serial, power command, board or model was executed by this review.

The original report SHA `97fff127ff94ffb318bd3201225a9db51132b1d058eb54ec7d410c3a96130d62`
and raw SHA `41424033b7b7235ba7cd1cd5c36d0406e7ae901a5babba675765cf4ffc8daada`
match, with unchanged original bytes/stat endpoints. The held decoder and
cross-language extraction sources were also unchanged. Correction used the
report's **unmeasured nominal 5.0 V**, not metadata VDD=4000 or measured VIN.

Key distinctions:

- The unfiltered **1.005119887 A** value at sample **5062** is reproducible
  arithmetic, not a transcription/unit mistake. It is the first range-4 sample,
  ADC14=1263. The official filter makes this particular sample **14.953298 mA**.
- That is **not** the complete filtered maximum: sample **5067** reaches
  **845.609917 mA even with the official filter**. Filtering does not establish
  the true physical waveform or prove the large transient was absent.
- The last eight stored samples are roughly **96.6–118.7 mA**; final sample
  5119 is **96.627148 mA**. This tiny tail is not a steady-state measurement.
- Online processing stopped after **5063 frames**, while the already-written
  buffer contains **5120**: **57 frames were saved but not processed online**.
  The first nonzero-range sample is 5041; the saved tail covers only **79
  nominal samples / 0.79 ms** from there. It cannot establish a three-second
  stable pulse. The original report explicitly marks the pulse incomplete.

Nordic support confirms that [automatic range switching can itself cause large
spikes](https://devzone.nordicsemi.com/f/nordic-q-a/109264/ppk2-52840-measure-the-current-in-rush-current).
That makes a range-related artifact a credible explanation to investigate,
not proof that every value in this particular capture is an artifact. A real
startup transient and measurement settling are not separated by these saved
data. Neither “sustained real 1 A” nor “normal and safe current” is established.

The complete [machine result](actual_pulse_oracle.json), SHA
`27f4c499fb4a96d2497d96bfb72d6a10631a133ea730793c9127bea6fcf3e6f0`,
retains all four stream hashes, transition samples, peak neighborhood and final
tail; [external exit](actual_pulse_oracle_exit.json) is recorded separately.
No full-GUI initialization, calibration accuracy, synchronous voltage,
absolute sample-clock accuracy or invisible whole-64-frame-loss exclusion is
claimed. This review authorizes no further power-on operation.
