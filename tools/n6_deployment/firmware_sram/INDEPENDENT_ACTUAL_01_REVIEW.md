# Independent saved ARM build review

PASS for the bounded **offline artifact** scope; no new blocker found. Saved-only check `554374`, actual exit **0**, verified all 281 original input pins and 240 pre-RESULT artifacts by full SHA and original stat bookends, exact 241-file output namespace, and all 63 raw command receipts with typed exit 0. The original SRAM-generation failure still has the same 34 files / 5 directories, FAILED and no RESULT. No compiler, model or target was rerun.

Bound result: `49225e31bc906e86fe73c3ca7f5a0d18592411f7692fa4173fdbe83c059a2e01`, canonical seal `6c9ce6e585df38bc4e4e4c27194b46b695dd5f105c3ac18b82c92a6da2036b84`; outside build receipt `bb7337211b69c1ea6a8c4c1578bc6c0519f741c5ee8223b8019b8d3a4d3cb02e` records author session 84432 / completion 0386bb / exit 0. The result itself retains a null process exit. Reviewed source remains `37194ebe0a164873310855e11ec911f8acab468e1728e1c382addf31808d2872`.

The ELF is ARM ELF32 ET_EXEC, hard-float Cortex-M55/MVE attributes, entry `0x34064061`. Actual Reset_Handler masks IRQ, establishes MSP `0x340f8000`, sets CPACR CP10/CP11 using `0x00f00000`, then DSB/ISB before entering reset_c and memset. This requires the documented privileged Secure Thread entry; it is not a platform initializer.

| PT_LOAD | Start | File bytes | Memory bytes |
|---|---|---:|---:|
| RX | 0x34064000 | 74271 | 74271 |
| RW data/BSS/heap | 0x34076220 | 4116 | 23680 |
| Stack | 0x340f0000 | 0 | 32768 |
| Mailbox | 0x340f8000 | 0 | 512 |

All segments are disjoint from the separate probe region and full weights `[0x34200000,0x34240000)` / activation `[0x34240000,0x34244000)` reservations. Linker symbols match; the 78388-byte BIN matches every initialized PT_LOAD byte. ELF SHA `9a68e6893b59d3d8d0952b70ccecdae6af14c3f3561532bd2a22540d69b562ca`; BIN SHA `59c61c71937eea2fd7d839b41cf84eb8e94e5b5517f4ccc5c3e1d3b4c34de41b`. Exact 145457-byte RAW/hash is unchanged and not embedded as the full RAW blob in those segments. A loader must still load/read back weights and handle BSS/reserved memory correctly.

Actual linked symbols contain LL_Streng_TensorInit, LL_ATON_RT_RunEpochBlock and convolution/activation/arithmetic/quantize/dequantize software fallback, plus MCU cache-maintenance helpers. NPU-cache enable/disable and HAL_CACHEAXI_Enable/HAL_RCC_OscConfig are not linked symbols; their map entries are discarded sections. This is mixed CPU/NPU code, not proof NPU ran, nor a claim the ST runtime never touches clock/control registers. Pinned generated descriptors retain the separately reviewed SRAM/cache-zero semantics.

Disassembly confirms all five raw output stores at mailbox offsets 320..336, both request-validation calls, and completion state store at 0x3406446a before DMB at 0x3406446c and response-sequence store at 0x34064470. No undefined symbols. The new S6 mailbox and stable matching DONE/sequence host contract remain necessary.

An initial reviewer check `a21044` / 1 incorrectly treated arbitrary unaligned byte substrings as addresses. Follow-up `c415fa` / 0 located all three 0x71000000 byte-pattern coincidences at unaligned positions; zero aligned old 0x71000000 or 0x342e0000 words were found in PT_LOAD bytes. This scan is only a supplementary observation, not general pointer analysis or a producer failure; no artifact or source was changed.

Limits: local AI-authored inspection of fixed artifacts and command receipts, not a human/OS signature, independent reproducible rebuild, hardware execution, initialized platform, numerical equivalence, latency, energy or deployment acceptance. All corresponding producer flags remain false. The old failed generation is not rewritten as successful.
