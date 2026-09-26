# USB2-port observation 01 — pre-execution protocol

User reports moving all USB connections to USB 2.0 sockets and explicitly
retaining the original pin wiring. This supersedes the proposed USB_SNK
rewiring: VIN remains reported on JP2 1, VOUT on JP2 2, common GND unchanged,
no JP2 shunts. Physical continuity, socket labels and voltage are not remotely
verified. Do not claim the proposed JP2 3/4 or charger connection occurred.

One new bounded observation is authorized by this user request. It is not a
blind automatic retry, firmware deployment, inference or research acceptance.

- Frozen collector `tools/ppk2_energy/observe_fixed.py` SHA-256
  `7ed8fcd668f939665e638e55bb8c486ba727e90687ddf35e91a0b88acf030334`.
- Metadata/low-level ST-LINK helper pins matched (`40b526 / 0`).
- Offline adversarial/author controls: `a86600 / 0`, 48 tests and 4 subtests.
- Initial metadata `USB2_PREFLIGHT_METADATA_01.json` showed mode `1`.
  Subsequent kernel log showed PPK USB disconnect/re-enumeration at
  2026-09-25 15:15:41–42 +08:00, device 55 -> 57, exact serial unchanged.
  Cause unknown. This metadata is therefore not treated as a post-reconnect
  guarantee; the collector must query fresh metadata on its exclusive port
  and refuse non-AM mode or an absent/nonunique device pair.
- PPK serial `F4728E9B55E0`, ST-LINK `004000183234510E37333934`.
- Same OFF/START/ON/final OFF/STOP protocol; nominal 3 seconds from host ON
  attempt, no single-sample current/ADC-top cutoff and no firmware commands.
- External timeout 20 s with TERM and 2 s kill grace. These are host software
  bounds, not a hardware current limiter or electrical OFF acknowledgement.
- Fresh output `usb2_fixed_am_observation_01/`; preserve failures and raw data.
- Compare saved raw range/time structure and conditional current decoding
  with `fixed_am_observation_01/`. Do not equate range0 ADC-top with >1 A.
- Ask for fresh LD3 observation after the capture; earlier red predates the
  user's latest reconnect. No automatic second ON if this diagnostic fails.

USB link speed/topology does not prove a physical socket label or its power
budget. Moving sockets alone does not establish a changed CN6 current limit.
No changes to physical protection, original model, tolerances or frozen builds.
