# Second actual SRAM attempt: FP entry verified; inference timeout retained

## Execution and limited acceptance

Command: `tools/n6_deployment/host_sram_fp/run.py
--execute-ram-validation-with-rne-entry --output
/home/thc1006/dev/SpikeIDS-MCU/results/n6_sram_validation_20260926_02`, under
`timeout --signal=INT --kill-after=10s 180s` and the offline project venv.
External launch `06b295`, session 5481; completion **`69ac91 / exit 1`**.

The explicit FP transition succeeded on real hardware: FPSCR `0x00c40000`
to `0x00040000`, only RMode bits cleared. Before/after mailbox and all other
observed context/FP fields were unchanged. The original strict FP gate passed.
This closes the narrow entry-mode issue, not board/model acceptance.

The original model and weights were again SRAM-loaded/read back. Platform
observations agreed before/after loading and before ACK. The model's four
initialization/I/O APIs reported success. Exactly one inference request was
committed: sequence 1, original first row ID 20, all 41 original FP32 inputs.
No reply arrived inside the unchanged five-second host deadline. The host
stopped with `ProtocolError: Inference deadline crossed during transport read`.
No automatic retry, row file, PARITY.json or RESULT.json exists. Cleanup halt
reported no error, independently confirmed by later halted-only diagnostic reads.
This is not proof of independent NPU quiescence or power removal.

Root saved-only adversarial review **`ec3c44 / exit 0`** rechecked all source,
model/stage pins, the exact two-bit FP transition, unchanged platform snapshots,
all three inference staging/commit writes, exact first-row bytes, 985 mailbox
events, RUNNING state/stage 5, success of init slots 0–3, untouched run/error
slots 4–5, zero completed rows and absence of accepted output. No hardware was
accessed by this review. It is a root review, not an independent-agent signoff.

Key SHA-256 values inside the unchanged second-attempt directory:

- INTENT.json: `591d6cdcdad454cf7b10c899ecd09143a7599643202ee52d429f4007a646d19f`
- FAILED.json: `027aaa4f374ba481f3db6a7ca71bf7e717161f66446c70082ed38edd262bc189`
- fp_entry_before.json: `f00fd6be9ef22b4e27e4d4ed4f9b4fa8ea9b97b519d8426614144af6a532fb63`
- fp_entry_after.json: `f44068ff5f88c8aa264e3d4885fc72a8890983d64811fb23a8375764e2a2af8b`
- fp_entry_verified.json: `944615ed40adae7bf7ad9a34b6d053ac15a7cec3e0196fc7786bb590e695aa95`
- completion_state.json: `2283f9255d234f75b056e40cb6b8422849f1db06ef32befe87a053ba51c4273b`
- mailbox_events.json: `cd44ecae55c2e36ab3902d5f1e8b538fd0ec591fc3f1bddb2e2e77b639235aac`

## Halted diagnosis and newly identified firmware defect

Reads `0e3ccb`/session48753 → **`639295 / exit 0`**, **`143409 / exit 0`**,
and **`e946f5 / exit 0`** used the exact ST-LINK backend, required an already
halted target, and did not write target memory/registers or resume/reset it.
Debug attach itself changes debug state. These receipts retain observations
in the tool transcript; values below are a transcription, not a raw capture file.

- PC `0x340661b8`: vendor `checkWatchdog`, LR `0x34066511`: `LL_Streng_Wait`.
  Frozen ELF addr2line/disassembly identifies these functions; the first
  addr2line invocation accidentally passed decimal addresses as hexadecimal
  and returned `??`; corrected hex invocation succeeded (`95741b / exit 0`).
- Model context `0x34077320` points to current epoch `0x34074f58`, the second
  20-byte descriptor, corresponding to generated hardware epoch 3; wait mask 4.
  Descriptor bytes: `154d06343d4a0634000000000400000013000000`.
- NPU stream 2 control `0x8088010d`, address `0x342400b0`; stream 9 control
  `0x80080105`, address `0x34240110`. Both RUNNING bits set.
- NPU CLKCTRL CTRL/AGATES0/AGATES1 at `0x580e0000/08/0c` all **zero**;
  BGATES at `0x580e0010` was `0x40204`. BUSIF 0/1 CTRL at
  `0x580e2000/3000` both **zero**. These are not a completed NPU execution.
- CFSR/HFSR/SFSR zero; DFSR 1 (debug halt event). MMFAR/BFAR/SFAR contents
  are not valid fault addresses without their validity bits. The six inspected
  RISAF IASR registers were zero. Correct IAESR/IADDR offsets are **+0x20/+0x24**;
  earlier +0x10/+0x14 reads were reserved and provide no fault evidence.
- NPU RIMC attribute `0x310`, SYSCFG NPU_ICNCR zero, DBGMCU NPU freeze zero.
  RCC MEMENR `0x13f1`; SRAM3 CR zero, SRAM4/5/6 CR `0x100000`.
  Do not infer that other SRAM banks need enabling just from these values.

Concrete source defect: `firmware_sram/main.c` calls the generated model init
but never **`stai_runtime_init()` / `LL_ATON_RT_RuntimeInit()`**. The generated
model init only initializes network context. The actual linked symbol table
contains neither runtime init nor LL_ATON_Init: gc-sections removed unused code.
Local ST 3.0 source `ll_aton_stai_internal.c` exposes `stai_runtime_init`, which
calls `LL_ATON_RT_RuntimeInit`; this calls `LL_ATON_Init` to enable global
clocks and bus interfaces. The separate trace variant's main also lacks the
global runtime init and must not be treated as a ready workaround.

[ST runtime API documentation](https://stm32ai-cs.st.com/assets/embedded-docs/stneuralart_api_and_stack.html)
requires runtime initialization separately from network initialization. Online
page is version 4.0; exact 3.0 behavior was checked in the installed sources,
not assumed identical from the web page. Polling mode is supported (although
not recommended for final performance); IRQ masking alone is not a demonstrated
cause of this polling wait.

This omission and the observed disabled NPU global controls are consistent;
fixing it is required, but no claim that it is the only remaining issue or
that adding it already fixes numerical parity is justified.

## Next phase: required before another validation or power experiment

1. Preserve both negative run directories and the frozen original sources/build.
2. Produce a separate firmware variant that calls and checks global runtime
   initialization **after platform ACK and before model init**, records its
   status, and has explicitly bound new firmware identity/layout. Keep original
   generated model, weights, all 1024 vectors and numerical tolerance unchanged.
3. Test runtime-before-model ordering and failure paths using host C controls;
   actually cross-build and inspect linked init call chain, MMIO operations,
   layout and immutable source/artifact pins. Review trace variant separately.
4. Bind the new artifact in a reviewed host bundle, retain FP initialization,
   and run a new bounded full-row validation. Do not resume/reclassify this
   failed first-row attempt or merely increase its deadline.
5. Only after parity passes, qualify actual NPU execution/clocking and a newly
   reviewed PPK measurement path. PPK remains physically removed according to
   the user's latest topology report; no energy measurement occurred here.

Runtime-init repair is **identified but not implemented/cross-built/deployed**
by this record. No third hardware attempt or background continuation is armed.
