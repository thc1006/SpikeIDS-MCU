# Independent internal-SRAM generation preflight

2026-09-25. PASS within the offline candidate scope; not hardware authorization.

Final independent execution: session `2330`, initial chunk `bbfc74`, completion
`d54728`, actual process exit **0**, **25 passed** in 1.06 s. Dedicated scope
`spikeids-n6-internal-sram-independent-01.scope` requested MemoryMax=4G,
MemorySwapMax=0 and single-thread environment. No measured peak is asserted.

Held source `generate.py` SHA256
`673fae4638731a6f0edbe45c5ef8e61c152e57b52ce1afae38e4224901cbf19a`;
independent test SHA256
`013a078f67acf7fb896e5b45c2656c7fea53e979c894dde4c250e8b874975644`.
Six source/config/test SHA bookends (`ebf37f` before, `324859` after) matched,
including PLAN `3d3d7a08...`, mpool `4969fd25...`, profile `64fb217c...`, and
held vendor helper `cd1bb490...`.

The earlier real tiny-I/O/fake-compiler run `1149d3`, exit 1, had one positive
pass and two concrete DID NOT RAISE failures on source `723562f8...`: replacing
RESULT or adding an empty directory in the final input-hash callback was
accepted. The final source closes these finite windows using original stat
pins and exact namespace checks after hash callbacks. No atomic or continuous
protection against future external changes is claimed.

The independent fixture uses a real stdlib child process and real capture,
NPY-header parsing, exclusive output ownership, copy, inventory, metadata
validation, hashing and publication. Original payload/tool/source locations
and fixed expected hashes are substituted with temporary fixtures; document
hashes are an explicit empty policy seam. Model bytes are opaque and reference
arrays are synthetic. No ST executable, actual model/reference arrays, target
driver, inference, USB or programmer was invoked. The two-epoch positive
fixture deliberately differs from the older compilation footprint.

Controls cover the exact two-pool profile, original-model SHA rejection before
output, no adoption, real child exit 23 with retained streams, source
mutate/restore rejection, foreign-root failure-marker protection, external or
probe-region pools, cache flags, parameter spill, buffer membership/type/size/
alignment, RAW size/namespace, generated C pointer extents and both demonstrated
publication failures. Static review also covered timeout cleanup and fixed
generate-only arguments; timeout behavior was not independently fault-injected.

The two 64-byte-aligned absolute RAW pools lie inside the installed ST 3.0
SRAM3 description and outside probe AXISRAM2. The local, pinned 3.0 memory
initializer/compiler documentation and `stm32n6_int2.mpool` support logical
read-only weights in physical SRAM. ACC_READ is compiler placement, not a
hardware protection setting. `cacheinfo: []` syntax remains unproven until
the authorized real compiler accepts it; failure must be retained, not retried
with a substituted profile. Initializer loading, SRAM availability, clocks,
security permissions, cache coherence and a future firmware linker remain
separate requirements.

No remaining blocker was identified for one root-authorized offline generation.
The real result still needs saved-artifact review. No numerical equivalence,
board readiness, deployment, energy, full toolchain closure or publication
acceptance follows from these tests. All older artifacts remain unchanged.
