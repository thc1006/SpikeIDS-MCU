# Review C: documents, claims, statistics and pre-registration (ESP32-S3 EM01, 7.976 mJ)

Read-only. I recomputed from `formal_20260930/*.json`, `diag_esp_02_run/`, `ppk_esp2/`, `ppk_esp*/events.jsonl`, git objects and the GitHub activity API. I also disassembled RM01 build_03 and N6 SM07M build_03.

## VERDICT: CLEAN

No blocker. The headline and every registered number reproduce. There are 3 MAJOR fixes and 12 MINOR fixes to make before publication.

### MAJOR
- **M1. "Independent reviewer" is not disclosed as a separate AI-agent re-analysis run by the same operator.** The formal re-analysis also imports the pipeline's `ppk2_session.Converter`.
  - **Fix:** say "separate automated re-analysis with its own decoder", not "independent review".
- **M2. Observation 1 rules are only half applied, and the post-hoc reading is presented as registered.**
  - Observation 1 requires each session's between-schedule CI "reported as such". The CIs are 7.888–7.955, 7.969–8.032 and 8.001–8.011 mJ, and none appears.
  - It also requires the post-mask logic-port fraction to be reported (100 %). It is not reported either.
  - RESULTS item 3 says "reported as fixed in Observation 1". But Observation 1 covers drift within one power-on only. The cold-versus-warm reading of the between-session CI is post hoc.
  - **Fix:** add the missing values, and label the cold/warm interpretation as post hoc.
- **M3. The same sham confound exists on the N6, and the RA erratum overclaims.**
  - N6 SM07M build_03 `main()` holds 7 inlined DWT wait loops. The ones at 0x3406514e and 0x3406516c are 30 B apart, which fits the HIGH and LOW waits of `run_pulses`. The N6 sham (−0.058 mA) is therefore exposed too. RA Amendment 2 cites that N6 sham as corroboration.
  - The RA erratum calls ±0.020 mJ "a conservative sensitivity bound". A confounded sham can hide a larger marker effect, so "conservative" is not supported.
  - **Fix:** add an N6 erratum, and change the wording to "sensitivity band; not shown to be conservative".

### MINOR
1. **Clock agreement.** "Clocks agree to 0.2 ppm" is the reviewer's own estimator. The registered `cpu_hz_estimate` session means span **1.08 ppm** (per schedule, 1.77 ppm). Write "≈1 ppm".
2. **Original heading time.** The original heading says "Written 03:25 +08". That is later than both the registration (03:20:36) and the server push (03:21:05), and it matches the diag_esp_01 ON time (03:25:14 +08). It was never corrected, unlike Amendment 1's. Add an erratum.
3. **Push times.**
   - RESULTS and `PROTOCOL.sha256` quote commit times (22:36:48Z, 23:03:48Z) as push or "external" times.
   - GitHub's server-side push times are 19:21:05, 21:38:50, 22:20:39, 22:36:50 and 23:03:50Z. Cite these.
4. **Selective dose example.** The session 2 example (−0.64 mJ) is the smallest intercept.
   - Session 1: −5.51 mJ (CI −6.28 to −4.74).
   - Session 3: −0.81 mJ.
   - All three exclude 0, and all three slopes (8.006 / 8.008 / 8.021) lie above their headlines.
   - Report all three.
5. **The "up to 3.1 mA" figure** (RESULTS, Amendment 3, RA erratum) is a single adjacent pair (L6−L7 = −3.118).
   - The spread across marker-LOW copies is 64.49–67.91 mA, i.e. 3.42 mA; review 1 said 3.5 mA.
   - The IDLE copies alone differ by 2.78 mA.
6. **Item 12 is wrong about checksums.** It says the BENCH checksums were not re-derived, but the reviewer did recompute BENCH ×1/×2/×4. Only the OVERHEAD checksum and the 0.5 % rule were not re-derived. The headline's "every registered gate" should add "except item 12".
7. **Inrush.**
   - Session 2 has 5 R0 ADC upper-rail frames at ON + 6.54–6.62 ms; `ppk_esp10` has 6 in total. These frames coincide with session 2's counter glitches.
   - Because of them, the 1.025 A peak is only a lower bound.
   - These frames are unreported, although Amendment 1 did report them for diag_esp_01.
8. **Registered board-state records are missing.** The operator's USB-removal confirmation and the LED states were not recorded.
   - The instruments do exclude USB power before session 1's ON, and each session shows a fresh POWERON boot.
   - They cannot exclude a native-USB cable plugged in during ON.
   - Call both omissions deviations, and soften "shown by instruments".
9. **PPK2 calibration flag.** The metadata reads `Calibrated: 0`. The N6 protocol lists "PPK2 calibrated" as not claimable. Carry that caveat over.
10. **Conditionality.** Item 6 omits two things:
    - the only evidence on how much the BENCH figure depends on code layout: build_02 vs build_04 gave 7.917 vs 7.937 mJ, both cold starts and confounded;
    - the ~1/3 LDO share. The protocol's "LDO ≈ 1/3 on every board" is unverified for the N6.
11. **Wording.**
    - "Repeatability only" is inaccurate, because conditions changed (1 cold start, 2 warm). Call it "between-power-on spread incl. one cold start".
    - "≪ 0.5 mA" for 0.120 mA is loose.
12. **RA documents.**
    - RA caveat 3 still states the withdrawn attribution, with no inline pointer to the erratum.
    - "−0.137 mA" is the diag_07 value; the formal sessions gave −0.139 / −0.138 / −0.142 mA.
    - "erratum 1" clashes with PROTOCOL Erratum 1.
    - The diag02 review's unexplained +0.25 mA step and the recorder hash 8b63b9cf (changed from RA's f92f3c16) are also missing from RESULTS.

### Verified correct
- **Numbers.** Every other RESULTS, Amendment and Observation number is correct:
  - per-schedule values; mean 7.97604; sd 0.04759; t₂ CI 7.8578–8.0943 (±1.48 %);
  - cold −1.03 % against the warm mean 8.0035;
  - Type-B 6.149–9.805 mJ; RSS −20.3/+20.1 %;
  - band 0.0026/0.0031/0.0150 mJ (≤ 0.187 %);
  - 98.6 %; incremental values; C1–C3; sham values;
  - off-times 1103.2 / 24.0 / 23.6 s; 22.8 min of sessions; ratio 2.293×;
  - RA R3 and 86 %;
  - Observation 1 drifts +0.26 % / +0.43 %; 32 287.
- **Hash chain.** Prefixes at 145 / 207 / 264 / 306 lines, and the full file, give cca7ecb8 / e73f3cfb / 81436b20 / 7509bf44 / c94e91fc. Each commit's file equals that prefix.
- **Code.** The driver, decoder, analysis, `lowspan_check.py` and recorder used in the formal sessions equal the files pushed at 19016bc, before the first ON.
- **Every PPK2-powered run is disclosed.** Observation 1 was pushed 55 s after the first ON. At that moment the only formal values were two live 1-s readings (62.95 / 62.65 mA), the same as diag_esp_02's (62.98 / 62.70), so they carried no information.
- **RA disassembly.** In RM01 build_03, `pulses()` has its loops at 0x1a0 and 0x1c4, each within one 16-byte line.

## NOT DONE
- The raw-frame decode of the inrush and upper-rail frames per session; I relied on the formal review.
- Mapping the N6 loops to `run_pulses`; this is inferred from the 30 B spacing.
- Evidence for "N6 FNV 0xccc5eb8b"; I found only a decoder comment.
- Checks of the flash time (06:23:11) and the 335–372 s window timing.
- Web research on the PPK2 `Calibrated: 0` field.
