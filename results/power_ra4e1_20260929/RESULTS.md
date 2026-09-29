# FPB-RA4E1 board-level energy per inference — result (2026-09-30)

## Headline (as registered)

On one unmodified FPB-RA4E1:
- ICLK is 100 MHz nominal (HOCO/PLL), and the flash cache is on.
- The model is v5 NSL-KDD QCFS primary seed-0, 41→256→256→128→5, strict FP32 portable-QDQ C, bit-exact on all 1024 validation rows.

Measured at the board's main 5 V net (J2-5), with a PPK2 Source Meter at a 5.000 V setpoint and J9 unplugged, whole-board energy is **3.48 mJ per inference**.
- The three power-on sessions gave 3.4775 / 3.4798 / 3.4783 mJ.
- The mean is **3.4785 mJ**, 95 % t-CI 3.4756–3.4814 mJ (n = 3). This is repeatability only.
- Each inference took **28.85 ms** at **0.1206 W**.

All three sessions were eligible. An independent re-decode of the raw frames agreed to ≤ 4.4e-16 relative.

## Mandatory caveats

1. **Type-B worst case ±22.4 %, i.e. 2.70–4.26 mJ.** PPK2 gain accounts for ±20 %. VOUT was not measured; its band of −3 %/+2 % is an assumption. Same-setup ratios are unaffected.
2. **Board-level, not MCU core.** The 0.104 W CPU-spin baseline is 86 % of the figure.
   - Incremental energy over the spin is 0.478 mJ/inference.
   - Sham-corrected, it is 0.4985 mJ (95 % CI 0.4979–0.4991).
3. **Marker-state band.** The PPK2 D0 input network shifts board current by −0.14 mA while P107 is HIGH, giving ±0.020 mJ (±0.58 %) on gross.
4. **Scope includes** the LDO, the J-Link OB section, and the PPK2 logic-port load on 3.3 V.
   - The J-Link OB section is powered in this setup: its DEBUG/POWER LED blinks.
   - It adds a ~10 Hz, ~0.8 mA peak-to-peak current modulation that averages out over the ≥ 1 s windows.
5. **Clock.** The HOCO ran at 100.07–100.16 MHz, so at exactly 100 MHz the value would be 0 to +0.12 % higher.
6. **One board**, room temperature not controlled, 22 minutes of sessions.
7. **N6 comparison.** The N6 value (49.41 mJ) was measured at 64 MHz with caches off, a different scope (whole board minus ST-LINK, VIN assumed), and a different meter mode and range. The ≈14× ratio is board power × latency, not an MCU-efficiency ranking.

## Provenance

- Pre-registration: `PROTOCOL.md`, with amendments 1–3, observations 1–2 and erratum 1, hash-logged in `PROTOCOL.sha256`.
- The pre-registration and code were pushed to `github.com/thc1006/SpikeIDS-MCU` branch `wip/power-ra4e1-20260930` (e787bc6) at 16:26:19Z, before the first formal ON at 16:26:38.6Z.
- Firmware: RM01 build_03 (`firmware.bin` 19532b80…).
- Driver, decoder and analysis: sha256 d30c0a8c… / 94ab0ec4… / 782ed8ba….
- Data: `formal_20260930/` holds the per-session analysis, summary and aggregate. Raw frames are kept locally in `ppk_main7/*.u32le` and are not in git.
