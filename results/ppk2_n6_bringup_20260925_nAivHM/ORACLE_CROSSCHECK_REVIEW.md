# Offline official-JS/Python arithmetic crosscheck

PASS: final actual command `02f119`, exit 0; **50 cases / 25,600 synthetic
samples / zero binary64 bit-pattern mismatches**. Source, analyzer and independent
test hashes were held through execution and checked again by `3a5047`, exit 0.
No hardware, serial, power, genuine capture or device initializer was accessed.

The runner fetched the [official v4.4.1 source at fixed commit](https://github.com/NordicSemiconductor/pc-nrfconnect-ppk/blob/4cbb4c41c420ddb8125638fffc6d72f6b21c5aaa/src/device/serialDevice.ts)
using `gh api` and required whole-file SHA
`37bda3ca2fb927ec67aa0d981773ec09371a2a799138397f2da6b362bd1ae926`.
Only the uniquely located `getAdcResult` and `parseMeta` methods were extracted
in memory. Translation removed their signature types and exactly five TypeScript
non-null assertions. Defaults and `adcMult` were also extracted from that
original source; no arithmetic expression was rewritten. Node v24.15.0 ran
the methods on plain synthetic objects, not the device class.

Cases cover all five ranges, repeated transitions into/out of range 4, ADC zero
and upper-rail words, different polynomial/offset/gain coefficients, zero-valued
coefficients, metadata-exact versus explicit GUI fallback policy, and correction
voltages **0.8, 1.8, 3.3, 4.0 and 5.0 V**. For the Nordic spike filter, state is
carried through each 512-sample case. To check unfiltered conversion, each
official call receives a fresh state so the transition branch is not entered.
Inputs are ADC14 times four; official amperes are multiplied by 1e6 and compared
to Python microamperes as exact big-endian binary64 words, not approximate
tolerance comparisons. Each case retains full-output stream hashes.

Three early attempts failed before numerical comparison because the synthetic
JS object omitted the class's `adcMult` field. These are oracle-fixture failures,
not analyzer defects. Their outputs remain in `CROSSCHECK_ATTEMPT_01.txt` and
`CROSSCHECK_DRIVER_DIAGNOSTICS.txt`. The corrected initial 30-case success
`d45417` remains in `ORACLE_CROSSCHECK.json`; the final 50-case run adds only the
root-requested 4.0/5.0 V values. No decoder/test source was changed.

Final [raw result](ORACLE_CROSSCHECK_FINAL.json) SHA:
`a4fc5fc001e9aac3e641c219673f5162b2d6d1be538b0676b2a8110afd7e31a9`.
The separate [execution record](ORACLE_CROSSCHECK_EXECUTION.json) records tool
exit observations; the program's self-exit field remains null.

Final crosscheck source SHA:
`8f9483a0f44644c941c05f8f561a9c3a42ced2b61817371aae6bae4cced66932`.
Analyzer SHA: `7eae8347391b11e747be73a7368f55587a9f154e7749f622844e5fae8a9869a9`.
Independent tests SHA: `235f0fda7796a7bc2e68f59a22ab36240106b15e8e74ad4843dc3634db1bb1e9`.

This supports arithmetic and filter compatibility for the selected synthetic
cases, not physical accuracy, instrument calibration, true wiring/voltage,
full GUI initialization, capture integrity or board/model energy acceptance.
It does not replace the separate GPIO-window/unit/CLI tests or certify every
possible numerical input. All final files are HOLD.
