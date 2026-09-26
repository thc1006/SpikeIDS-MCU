# Independent platform-stage preflight

No remaining concrete blocker to a separately authorized **offline ARM build** of the reviewed stage. Independent final eight controls passed, actual `8d916e` / exit **0**, 0.11 s; 4 GiB / swap 0 scope `spikeids-n6-platform-independent-final02.scope`, invocation `0a04a3e5eb7342beb7ef83ccbe353c30`. Eight source/ABI/build hashes matched before/after (`59c641` / 0). Only `/usr/bin/cc` compiled the portable C into a temporary host library; no ARM compiler, hardware transport, real MMIO or model ran.

The independent literal MMIO provider (not the author's Device) executes the actual `platform_init.c`. It models read-only RCC status with SET/CLEAR aliases and confirms NPU reset assertion **and readback precede every NPU attribution write**; unchanged HSI DIV1/DIV2 produce nominal 64/32 MHz metadata; only selected divider/clock/security/RAM masks change, unrelated bits remain; locked incompatible attributes and RISAF region/error status reject without clearing locks/history or releasing NPU; failed reset readback stops before security writes; unavailable HSI stops after exactly 65536 reads. Entry/cache/MPU/SAU refusal precedes writes. These are software-sequence tests, not a silicon/power oracle.

Fixed local ST CMSIS/HAL source was independently checked for RCC aliases and bit masks, RAMCFG SRAM3 shutdown bit20, NPU peripheral index3 bit10, and RIMC NPU index1 at `0x54024c14`: raw CID1 + secure + privileged is `0x310` under mask `0x370`. No PLL/HSI-divider/trim/PWR/flash/OTP/RIF-lock/CPU-cache write is part of the portable sequence. It deliberately retains a narrow default-filter profile and reports only RISAF error observations, not complete global-IAC or physical supply verification.

Static startup review confirms Thread/privilege/MSP checks before reconfiguration; IRQ masking, private MSPLIM/MSP and vector setup; integer-only soft/general-register compilation with no libraries; stackless best-effort fault capture. The mailbox is 4096 bytes with the 2368-byte platform report at offset128. READY sequence2 stays stable until a fresh nonce; only that event publishes a new seqlock/heartbeat. Secure entry, powered rails, exclusive ownership, clocks/access permitting the loader's initial stage RAM write and watchdog policy remain external prerequisites. Failure can leave partial initialization and does not imply rollback/shutdown. This stage replaces the old minimal probe at the same code address; it is not a co-resident second probe. Its regions are separate from the S6 adapter and weights/activations.

Initial independent run `ef2347` / 1 had seven pass and one reviewer test typo: searching `msr msp` also matched `msr msplim`. The exact-comma token correction produced the final pass; no producer code changed for that failure. Original XML is retained. Root's earlier reset-order and continuous-seqlock issues were already fixed before this independent run; this report does not invent independent pre-fix executions.

A separate host cross-check uses the actual host-C report in the real stage decoder: positive decode/live masks/nonce and last RISAF-subregion rejection passed (`5278c3`); its third test reproduced acceptance of an impossible double publication for one nonce and is being fixed in **host** `stage_protocol.py`. This does not require changing the stage C or defer offline ARM compilation, but host integration must consume the corrected exact +2 sequence / +1 heartbeat behavior before any target use. Components are not a completed hardware pipeline.

Final pins:

| File | SHA-256 |
|---|---|
| platform_init.c | f044508ad7b6336a737a8a2eb2555603811f612981b1a61d5384134f5f2c2f77 |
| platform_init.h | d55d43b2e13bd9e257c2fd195686b23bc24befff541bda5e2fa3a8f37874e328 |
| main.c | 30d32be707d874b8072639c5a28afee958c1790ec4d8626be166d17bac4c44b5 |
| startup.c | 0d3beac9927d68bb66921cdc874cf30144790058a585a7e5fbd0e62499a65f1c |
| mailbox.h | cc97cb1b330768cd31888e44bb8f858182dc90e6f9ac3a1298bc46bb3d2fb7ae |
| linker.ld | 86e4c625a565e6e5c8e59acdf7091c82ac0161e211b75d6d381355eb4425d186 |
| ABI.json | 66baa5f6a2499bdaac2e9666e1b3a489c2dddc6d570c347b8bcd6e795fd2bb80 |
| build.py | b26cab338ddf9eb5a47f1a545b4372da6850cfe090348a3ebef09887fe5804b4 |
| test_platform_stage_independent.py | faa9f0db08dedb4399c7834c7979dc96f31df25e8ee6096b7306565eb0aef6a3 |
| platform_independent_final_02.xml | f71065d39b20371105b10aab0a1f70cf544e791cd04b94c8acad49c35d7b5a4e |
