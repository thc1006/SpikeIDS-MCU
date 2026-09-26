# Actual offline trace-variant build (author observation)

One authorized build completed: launch `d75f9d`, session **5289**, observed completion **`ec39e3 / exit 0`**. Systemd service `spikeids-n6-sram-trace-build-20260925-01.service`, invocation `74438de2f44141da860003f53b3c4633`, reported 11.532 s runtime, 10.119 s CPU, 287.6M peak memory and 0B swap. Limits were 4 GiB memory, zero swap, CPU 200%, TasksMax 128, RuntimeMaxSec 170, outer timeout 180 s. No automatic retry or target/device operation occurred.

All **67** saved compiler/tool commands have exact integer return code zero, including 25 source compilations and the final link. The completed output namespace is exactly **257 files**: 256 original artifacts plus RESULT. Saved-only author postcheck **`2a804b / exit 0`** rehashed/bookended **291 original input/source/tool pins** and all **257 output pins** (548 total), checked the producer seal, exact output namespace and retained original generation namespace, and rechecked the five ELF segments. This reused the author's validator; root/peer saved review remains independent. The unsealed `BUILD_ACTUAL_01_POSTCHECK.json` field `content_sha256` refers to the original producer RESULT seal, not to a seal of that postcheck file. Large stat integers were preserved as raw Python JSON text, not passed through a JavaScript number round-trip.

Observed ELF: ARM ELF32, hard-float Cortex-M55 attributes, Thumb entry `0x34064061`, initial MSP `0x340f8000`. RX begins `0x34064000` (76,151 bytes); RW data begins `0x34076978` (4,116 initialized bytes, 24,520 total bytes). Stack is 32,768 bytes at `0x340f0000`, mailbox 512 bytes at `0x340f8000`, and dedicated trace **6,556 NOLOAD bytes at `0x340f8200`**. Stack/mailbox/trace have zero file bytes. Full weight and activation reservations remain outside the ELF. No ELF undefined symbols remained; trace bind/begin/callback/finish and fixed log symbols are retained. This proves offline integration/linkage, not callback execution on an NPU.

Key whole-file SHA-256 values:

- RESULT: `aae2d1f3e3572f8afac200f17a8cc7671d051770c9a3182a2664f983e7e38f42`; producer seal `e9994415834a134925a02e83e1b4bf5e1e05d1629c016f6bbcf95259ef852c22`.
- ELF: `2fa120c9bb3d2fc58840a2e2668f8bd6e3090a9afa69ee359153a3f3ada5926d`.
- BIN: `0672dca402d57755f4568ebc6ea20d079981cde4c7287cbc3b8ae2ed5a642129`.
- Map: `5f1b7ffa5cf7bc6048608fefa227b74319f971493418afa7571916ad73e8bc65`.
- Disassembly: `9c876f1b4e3064534adc654f06a9d113af83294318f14708480da279d78ee958`.

The earlier author preflight 21 controls (`ebb197 / 0`) and peer 13 integration/source controls plus author 21 (`00815b / 0`, supplied by the independent reviewer) preceded this build. New sources and all original sources remain HOLD. Frozen pre-build README/preflight statements are historical observations at their creation; this additive note records the subsequently authorized actual build without rewriting them.

No model was run, no firmware was uploaded, and no board/NPU/performance/energy acceptance is made. Trace-aware host retention and new-ABI recognition are still required before any future experiment; the old S6 host cannot be reused silently. Callback windows perturb execution, CPU halt does not prove NPU quiescence, and full on-target logits/parity and platform/power conditions are not established by compilation.
