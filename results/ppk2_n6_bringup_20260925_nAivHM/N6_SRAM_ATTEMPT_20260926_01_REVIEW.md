# Reconnect and first actual SRAM attempt: negative retained

User reported reconnection after PPK removal, JP2 3/4 closure, CN18 external
supply and CN6 workstation. Current exact probe serial is
`004000183234510E37333934`, USB `0483:3754`, Bus 001 Device 063.

Standalone F7 Vref query `e74777 / exit 0` returned three estimates:
3.2749003984063747, 3.273306772908366, 3.270119521912351 V.
Raw responses `e205000007080000`, `e205000006080000`, `e205000004080000`.
This supersedes the prior missing-USB/0.18 V observation; it is not a calibrated
voltage or sustained-power qualification. PPK was not operated.

First actual fixed-model SRAM run launched `63f686`, session 92265, completed
`3cc91f / exit 1`. Output: `results/n6_sram_validation_20260926_01`.
It backed up, wrote and read back three platform plus six model/weights
regions, initialized the platform and reached model WAIT_PLATFORM. It stopped
with `RuntimeError: Nondefault FP rounding/flush/default-NaN/half mode`.
No ACK, model init or inference was issued. No RESULT.json was written.
CPU halt cleanup reported no error; independent NPU quiescence was not verified.

Read-only halted diagnosis `8256b0 / exit 0` observed FPSCR `0x00c40000`,
FPDSCR `0x00040000`, FPCCR `0xc0000004`, CPACR `0x00f00000`, CONTROL=0,
PRIMASK=1, PC `0x34064224`, MSP `0x340f7d70`; mailbox state 1 and ACK/request/
response all zero. Nonzero RMode is a pre-entry gate mismatch; there were
no model outputs to characterize and no proven unique source of this state.

Root saved-only adversarial review `a3ed23 / exit 0` verified original input
and source pins, nine backup lengths, 106 verified load chunks, platform nonce
3648407584, 180 MMIO observations and nominal 64 MHz (not measured). Model
and platform live observations agreed before/after payload loading. Mailbox
remained fresh WAIT_PLATFORM, no row files or accepted result existed.

Key frozen evidence SHA-256:

- INTENT.json: `724f1e7fb3d728739e978a6468040d229d657372ceceb9004e69c14cb45eae5e`
- FAILED.json: `0e0ad3d650f5d12875177c2919d6100b00b27136012ff42b156ff2d046466a7e`
- completion_state.json: `2283f9255d234f75b056e40cb6b8422849f1db06ef32befe87a053ba51c4273b`
- load_events.json: `475dec33865f6f1120d5267d5f2258147ab992a64ec76d873953eb08001804fc`
- adapter_wait_platform.bin: `55249aa436417b600328d5eaea5ccc0dc79008abc511fc4d6784397e33517d9f`

The negative directory and original sources remain unchanged. A separately
tested additive explicit RMode initializer is described in
[FP-entry review](../../tools/n6_deployment/host_sram_fp/README.md).
No accepted board parity, NPU profiling, latency or energy results yet.
