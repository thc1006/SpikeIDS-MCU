# Explicit retained FP entry for the frozen S6 controller

This additive wrapper initializes only FPSCR RMode[23:22] to round-nearest,
ties-to-even at fresh, halted WAIT_PLATFORM, before platform ACK or model init.
It does not change the frozen controller, ELF, weights, vectors, tolerance,
FPDSCR, or any other FPSCR bit. In particular MVE LTPSIZE is preserved.
The original strict floating-environment check still runs before ACK and
after validation. A later mode change is rejected, never repaired.

Default invocation verifies fixed artifacts offline and does not open USB:

```sh
uv run --no-project --offline --python .venv/bin/python python tools/n6_deployment/host_sram_fp/run.py
```

Hardware execution requires `--execute-ram-validation-with-rne-entry` and a
fresh absolute `--output` directory below repository `results/`. Run with an
outer process deadline. The underlying controller writes verified SRAM and
configures platform clocks/NPU attribution; it does not flash, reset the MCU,
unlock, or control PPK power. Cleanup attempts CPU halt, not independent NPU
quiescence. No latency, power or independent NPU-execution claim follows.

Before/intent/after/verified records retain the FP transition. One failed or
ambiguous write is not retried. Entry is rechecked after durable intent,
before writing. A failure poisons the adapter. Original numerical policy is
`np.allclose(reference, actual, atol=1e-6, rtol=1e-5)` and no argmax mismatch.

## Issue review and pre-execution evidence (2026-09-26)

The original run `results/n6_sram_validation_20260926_01` stopped at the strict
FP gate before ACK, model init or inference. A subsequent halted read observed
FPSCR `0x00c40000`, FPDSCR `0x00040000`, CONTROL=0. RMode was 3, not 0.
This is a gate mismatch, not evidence of erroneous model outputs or proof
of the origin of the register value. A later FP context activation may itself
initialize modes from FPDSCR; this wrapper makes the required entry explicit.

Mode definitions were checked against local primary CMSIS `core_cm55.h`
(RMode bits 23:22; LTPSIZE bits 18:16), indexed ST PM0273 §6.12, and Arm's
architecture reference. The full ST PDF was not retrieved in the web tool.

- [ST PM0273](https://www.st.com/resource/en/programming_manual/pm0273-stm32-cortexm55-mcus-programming-manual-stmicroelectronics.pdf)
- [Armv8-M architecture reference](https://community.arm.com/cfs-file/__key/communityserver-discussions-components-files/471/DDI0553B_5F00_y_5F00_armv8m_5F00_arm.pdf)

Actual preflight `cb4d58 / exit 0`: 124 tests and 47 subtests passed (48 new
and 76 original tests), then new default CLI checked all 1024 rows offline.
Root adversarial review includes fresh mailbox/identity checks, all four
rounding modes, preservation of every other bit, invalid mode rejection,
durable-retention failures, stale entry after intent publication, ambiguous
flush, one-write-only behavior, final-row corruption and original full-engine
1024-row integration. These are host/fake tests, not hardware evidence and
not an independent-agent review. Hardware acceptance is still pending.

Reviewed source SHA-256:

- `fp_entry.py`: `60178340e307a55b3c9a4c88440828694092f4ccd27a7ac1c53fc3c725db1403`
- `run.py`: `20a6e45afc01731eb02983f2a3ff8a7af01b524b54f46dd349279d0424c13371`
- `test_fp_entry.py`: `35443bdf768643bf9d069163e5c3177187628562f78903a4709927173dba1a2c`

The planned second hardware attempt uses fresh output
`results/n6_sram_validation_20260926_02`; this paragraph is not execution proof.
