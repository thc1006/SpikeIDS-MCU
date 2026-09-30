# Platform-stage author preflight

2026-09-25. This note is the implementation author's account, not an independent signoff. No hardware, ARM build, target load, power switch, model execution, flash or OTP operation was performed here.

The actual final host-C suite completed as tool `8e5ce3`, exit **0**, 13 tests (including bounded subcase matrices), 0.101 s reported by unittest. `/usr/bin/cc` compiled the exact portable `platform_init.c` into a temporary host shared object with `-Wall -Wextra -Werror`; its actual exit was 0 with empty stdout/stderr. The resulting C function ran against synthetic MMIO callbacks; it is not a chip emulator or a proof that the real target accepts the sequence. The eight source/test SHA bookends were identical.

Coverage includes DIV1/DIV2, preservation of unrelated bits, RCC SET/CLEAR alias-only writes, default RISAF checks at all six selected blocks including last base/subregions, locked compatible/incompatible attributes, cache/MPU/SAU/entry refusal, bounded HSI/CPU/SYS status polling, missing readbacks, late-state changes, reset-before-security-write ordering, and static ABI/native-barrier/fresh-nonce wiring. Fresh-nonce publication is statically checked, not executed on an ARM target. A separate reviewer is testing the sequence with a separately written MMIO provider.

History retained in actual tool records: `cbdb89`, exit 1, host compilation succeeded but two tests failed due to author transcription errors: ABI decimal addresses and a synthetic DIV2 word that inadvertently selected DIV8. Both were corrected. `bcd53b`, exit 0, passed the original 12 controls. Root then identified two implementation issues: resetting NPU only after changing security attributes, and a continuously updating seqlock too fast for a 4 KiB SWD read. The final source resets/readbacks NPU first and publishes only when the host nonce changes. No inference result or physical device defect is inferred from these software fixes.

Final source/test bindings:

| File | SHA-256 |
|---|---|
| `platform_init.c` | `f044508ad7b6336a737a8a2eb2555603811f612981b1a61d5384134f5f2c2f77` |
| `platform_init.h` | `d55d43b2e13bd9e257c2fd195686b23bc24befff541bda5e2fa3a8f37874e328` |
| `main.c` | `30d32be707d874b8072639c5a28afee958c1790ec4d8626be166d17bac4c44b5` |
| `startup.c` | `0d3beac9927d68bb66921cdc874cf30144790058a585a7e5fbd0e62499a65f1c` |
| `mailbox.h` | `cc97cb1b330768cd31888e44bb8f858182dc90e6f9ac3a1298bc46bb3d2fb7ae` |
| `linker.ld` | `86e4c625a565e6e5c8e59acdf7091c82ac0161e211b75d6d381355eb4425d186` |
| `ABI.json` | `66baa5f6a2499bdaac2e9666e1b3a489c2dddc6d570c347b8bcd6e795fd2bb80` |
| `test_platform_init.py` | `c2eafe06b40fc297b2cc05b4c9c5840ed8fc149b458c45c362814072b52f9071` |

Additional files read/hashed as `9edc1b`, exit 0: `build.py` SHA `b26cab338ddf9eb5a47f1a545b4372da6850cfe090348a3ebef09887fe5804b4`; README `8338d90b7343f8b85c56dc828b3401ec7c418ac7ce1a2d5ad171098e9659be27`. Build-script AST and ABI integer/address checks passed `59a5a1`, exit 0, before the later event-driven ABI text addition (addresses were unchanged). No ARM invocation is implied. The additional official LL bus header used to check the SET/CLEAR aliases is `firmware/n6/third_party/stm32n6xx-hal-driver/Inc/stm32n6xx_ll_bus.h`, SHA `5531f55470d517b40420aa7b81f492120e291e413b4309f9bdec0d590b8fb39d`.

Remaining required boundaries: independent source review, actual ARM compile/link/disassembly, externally confirmed secure/cache-off/exclusive entry, accepted physical power, live register/readback checks, exact SRAM payload load/verification, and separately controlled NPU execution with preserved output/status. The stage itself never starts inference. It can leave partial initialization on failure and does not roll back, shut down power, or promise hardware safety. Only selected RISAF IASR status is captured; global IAC is not. READY_FOR_PAYLOAD is not board/model/energy acceptance.
