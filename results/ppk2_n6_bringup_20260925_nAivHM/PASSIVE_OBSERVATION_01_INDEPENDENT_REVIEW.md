# Passive observation 01 — saved-only independent review

Producer execution was reported by root as session 85312, completion `4ece60`, exit 0 (launch `ffa7bd`). This reviewer did not access hardware. Independent saved-file decoding completed as actual tool `e79c3a`, exit 0; the preceding six additional offline collector controls completed as `058837`, exit 0.

Original capture: `passive_observation_01/`. Exact namespace: `INTENT.json`, `samples.u32le`, `report.json`. The original report's raw-file pin and all four original source pins matched; the three saved files plus decoder had equal hash/stat bookends. No atime comparison was used.

| File | SHA-256 |
|---|---|
| `INTENT.json` | `b23b23c35d9938bdceeb35016ba0ff7b969fd7dd2d102beba5ef547242f4dac3` |
| `report.json` | `6e8d9bdc30977bf47c0b01f757d83499f1998fc80d06b34d99659e8b37f1b019` |
| `samples.u32le` | `25601d1450cf41cd867d27163128c3724c149c16d37a69966d0c0e03d2857618` |
| `tools/ppk2_energy/analyze.py` | `7eae8347391b11e747be73a7368f55587a9f154e7749f622844e5fae8a9869a9` |

Recomputed: 1,200,128 bytes, 300,032 complete frames, all range 0, modulo-64 counters continuous (first 1, last 0), 17 ADC upper-rail observations, digital byte always 255. ADC min/median/mean/max: 0 / 31 / 33.3560686860 / 16383. This matches the collector's structural records. Modulo counters cannot exclude loss in multiples of 64; digital 255 is not a validated inference marker.

The host START-attempt-to-before-STOP interval was 3.000590509 s; START and STOP write calls took about 85.3 and 113.5 microseconds. The nominal sample-count duration is 3.00032 s. These are different time domains, not a measurement of electrical ON duration. The command record is metadata `19`, START `06`, STOP `07`; both sampling writes completed, cleanup errors are empty and the post-STOP drain observed an empty read. No output-switch, voltage, mode, debug or target command was sent by this collector.

No actual correction voltage is established. A **sensitivity calculation**, using the pinned decoder with no spike filter and assumed correction voltages 0.8 and 5.0 V, gives metadata-exact mean 0.069118–0.073318 microampere and max 720.0289–720.0331 microampere. The explicit Nordic-GUI coefficient policy gives mean 0.069153–0.073353 microampere and max 720.5473–720.5515 microampere. These are conditional calibration arithmetic, not voltage-qualified current measurements; saturation maxima are not reliable load-peak estimates. The units are microampere, not milliampere. Negative decoded samples remain negative. Metadata VDD=4000 is not measured VIN, and Calibrated=0 is retained without inventing a physical calibration verdict.

Conclusion: bounded raw acquisition completed and saved data are structurally consistent. Near-zero conditional mean does not identify PPK output state, the board's supply route, boot status, NPU operation, protection state or a wiring fault. No model ran. Energy, board/hardware safety and research measurement acceptance remain false. This does not authorize an ON command or retry.
