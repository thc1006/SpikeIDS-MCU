# SRAM adapter offline build preflight

Author final **12 synthetic/source controls passed**: actual tool `939924`,
exit 0, 0.001 s. All nine source, ABI, document and test SHA bookends matched.
No ARM compiler or device was invoked in this test run.

- build.py: `37194ebe0a164873310855e11ec911f8acab468e1728e1c382addf31808d2872`
- main.c: `7af7972cc89b2137a2a6d7cee80ccdd69209d77c33f4ce0225863869bee6bf94`
- startup.c: `cdfafb4fd5cf4d55123358fab1396d5bb9afa18a60ba5eb0a62f7bf1b3ce9160`
- syscalls.c: `e1ce7b80b8e3e64c9b0d888674e0c68e1a4cd6197450b0b1bc07eff78b934f6a`
- mailbox.h: `29f9f4fd7d96e3cd3ec14dec99d14dad7353f8cca8eef421bb9a7fd5ca434e78`
- linker.ld: `b2179f2bbd0cf749998b68185f8b8a6918dd06a57d9c447449a4f0c3fafacc38`
- ABI.json: `af5fc1970e128ac548a856838b53ba585f66dddcb67602d1b151f573efcfd8b1`
- README.md: `5ba7de11a59d081235fb17eadd058391cfe44b569de00e52d98ed4493b1d456a`
- test_build.py: `1b152f5d85f3fd3aa8812dd6eaf77988d8e674d4af41a70dc7060d9512a4dd5f`

Tests cover a complete synthetic four-segment ARM ELF; bad machine/Thumb entry/
initial MSP; writable code; overlap with the otherwise unused portions of both
full SRAM reservations; stale output before input capture; unknown CLI options;
fixed architecture/polling/software fallback and absent USE_NPU_CACHE define;
ABI identities/counts/offsets; WAIT_PLATFORM before the first vendor call;
all five output words; and final response-sequence publication ordering.

Changes from the separately held v5 adapter are explicit: new deployment magic
and six pool-identity fields in the formerly reserved mailbox words; I/O address
0x34240000; complete 256 KiB weights and 16 KiB activation exclusions; unchanged
model/RAW identities; immutable-request field checks before and after run; and
DONE before the final DMB-ordered response commit. The startup's privileged
Secure Thread/cache assumptions remain prerequisites, not newly verified state.

Independent preflight caught and preserved three bounded build defects before
any real compile: draft literal-backslash ELF magic (proof `d7fd3d`, exit 0);
late original-candidate empty directory plus parent-symlink output creation
(`7eefab`, exit 1); and fresh capture overwriting an already committed generated
source pin (`efe021`, exit 1). The final source corrects the magic, pins/checks
the original output parent before FD-anchored mkdir, rechecks retained original
names after hash callbacks, and compares existing original pins instead of
overwriting them. Independent final regression is reported by its owner.

Selected prior compile tool/runtime/header identities and the saved SRAM review
are bound explicitly, not inferred from file existence. The original SRAM
generation wrapper exit 1, compiler exit 0, FAILED/no RESULT and later saved
review exit 0 are distinct. A future successful ELF build will still not prove
target execution, RAM/clock/RIF/NPU initialization, parity, performance or power.
