# Fixed AM observation 01 — saved-waveform review

The saved waveform contains a short high-current event followed by a prolonged return to near-zero measured-path current. This is evidence consistent with the load/supply path becoming inactive well before the commanded end of the observation. It is **not a direct voltage-collapse measurement**, a diagnosis of the particular protection element, or proof of board boot. The former pulse03 red LD3 observation is not a fresh LED observation for this capture.

Root reported the hardware execution as launch `6c48b8`, session `12809`, completion `c59d4e`, exit 0, report UTC `2026-09-25T03:20:09.757704Z`. This reviewer performed no hardware access. The reviewer authored the fixed collector earlier; this is a separate saved-data analysis using the existing pinned decoder, not an independent reimplementation of that decoder or independent certification of its own collector.

## Actual saved-only checks

Exploratory decoding: session `10364`, completion `4398f9`, exit 0. Final source/evidence-bookended decoding: launch `2bc927`, session `58613`, completion `08dfa1`, exit 0. Six files (report, raw data, decoder and the three original collector/helper sources) matched their fixed SHA-256 values, with equal eight-field metadata before/after and a final stat pass. The original capture namespace remains exactly `report.json` and `samples.u32le`. No files there were modified.

- Report SHA-256: `d718b7dd1fe708c467ca9a670c22db00f1544dd9e5364a9fbf36176385fc959d`.
- Raw SHA-256: `594b60173f76e7e08df1de75bebf7a701fbb409972bff83671375e0d632fd29e`.
- Decoder SHA-256: `7eae8347391b11e747be73a7368f55587a9f154e7749f622844e5fae8a9869a9`.
- Full independent arithmetic record: `FIXED_AM_OBSERVATION_01_INDEPENDENT_RAW.json`, SHA-256 `aab2fe0b9f8c81d088b21e8322747ab0851d79a1e9a5a199e455f81d98d2c7a8`.

Recomputed structure: 1,200,128 bytes; 300,032 whole frames; zero observed modulo-64 counter discontinuities; range histogram `[299930, 2, 4, 39, 57]`; digital byte always 255. Modulo continuity cannot exclude loss of exact multiples of 64 samples. Digital 255 is not a validated inference marker.

## Waveform chronology

All sample intervals below are half-open, with nominal 10 microseconds per frame and origin at the first retained sample. They are **not timestamps relative to an observed electrical ON edge**.

| Samples | Nominal interval | Observation |
|---|---|---|
| 0–244 | 0–2.44 ms | Range 0 before the upward range transitions. |
| 244–284 | 2.44–2.84 ms | Ranges 1, 2, then 3. |
| 284–341 | 2.84–3.41 ms | One contiguous range-4 interval: 57 frames, 0.57 ms; ADC 78–1077, no ADC upper-rail sample. |
| 341–346 | 3.41–3.46 ms | Ranges 3, 2, 1 on the downward transition. |
| 346–62787 | 3.46–627.87 ms | Range 0 throughout, but all 7,099 upper-rail observations occur in this interval. Do not interpret it as clean, accurately bounded near-zero current. |
| 62787–300032 | 627.87 ms–3.00032 s | Range 0, no further upper-rail samples; conditional decoded values remain close to zero. |

The nonzero-range excursion spans only 102 frames / nominal 1.02 ms. There is no later return to a higher range. The first and last upper-rail samples are 397 and 62,786, both in range 0. Under the unfiltered calibration arithmetic, a range-0 upper rail maps to about **720 microamperes = 0.720 milliamperes**, not 720 milliamperes. Clipping/range uncertainty means this mapped value is not an upper bound on the true instantaneous physical current.

## Explicit correction-voltage sensitivity, not voltage qualification

The record evaluates both `metadata-exact` and `nordic-gui-4.4.1` coefficient policies, each with correction voltage **assumed** to be 0.8 V or 5.0 V and with no filter or the explicit Nordic range-transition filter. These are sensitivity cases, not measured voltages, physical error bars, or certification that VIN lay within that interval. Metadata VDD=4000 is not measured VIN; Calibrated=0 is retained without inventing a calibration verdict.

- Range-4 unfiltered maximum is 833.162–844.757 mA at sample 284, the first range-4 sample. The Nordic filtered maximum is 741.667–753.263 mA at sample 288. Both policies give the same range-4 numbers. A hundreds-of-milliamperes transient is supported by the conditional decode, but range-transition response and absent voltage qualification prevent claiming either maximum is a precise physical peak or protection-trip threshold.
- The last 200,032 samples (nominal 1.0–3.00032 s) have no clipping. Metadata-exact mean is −0.047798 to −0.043598 microampere; the union of their min/max values is −0.386914 to +0.365886 microampere. GUI-policy differences here are negligible and reported explicitly in the raw record. Negative offset/noise values are retained, not clamped or interpreted as proof of physical reverse load current.
- The entire tail after the last upper rail is close to zero under both assumptions; this conclusion does not depend on treating the earlier 7,099 clipped observations as accurate current measurements.

## What this resolves and what remains unknown

The collector stayed active to its 3-second host deadline rather than cutting off on current. Host ON-attempt to OFF-attempt was 3.000641709 s; 299,520 frames were already processed before cleanup and 512 additional frames were retained in the bounded post-STOP drain. No cleanup error was reported. Thus the early range drop is not explained by this collector's former 700 mA or short-reference cutoff policies: this collector had neither. The record still does not turn completed USB writes into firmware acknowledgements or exact electrical switching times.

The before-START/OFF F7 estimate was 0.176775 V; after-cleanup/OFF it was 0.003185 V. Neither measured VIN or the ON-period board rail, and neither establishes boot failure. No present LED observation, rail waveform, or target execution exists here. The trace is compatible with protection shutdown or another interruption/nonconduction of the measured supply path after a startup transient, but does not distinguish those causes from one another or prove sustained rail collapse. A brief inrush followed by another powering path likewise cannot be eliminated from these current bytes alone.

Conclusion: raw acquisition completed, but **sustained powered-board/model operation is not demonstrated**. The waveform justifies investigating the short startup event and subsequent inactive measured path; it does not justify declaring successful board power from the ON bytes. Missing a multimeter is not the basis of this conclusion—the saved waveform is. No formal model/inference energy measurement has occurred. Board, boot, electrical safety, unique-cause and research-energy acceptance remain false; this note authorizes no retry or hardware action.
