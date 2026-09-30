# Independent S6 host component review

Final **19 independent controls passed**, actual `be58ae` / exit **0**, 0.04 s, scope `spikeids-n6-host-independent-final02.scope`, invocation `f9a744502b054a638c1e8241447ec20c`, 4 GiB / swap 0. Source/test hashes matched before and after (`f5233a` / 0). No real pyOCD enumeration, session, USB, target memory operation, compiler or inference was invoked.

One actual defect was reproduced and fixed: initial protocol `f1d534f1...` checked its deadline before, but not after, a potentially blocking snapshot. Two mocked three-second reads returned DONE after a five-second deadline and were accepted (`895450` / 1: nine pass, one fail; XML retained). Final `78b25d26...` checks elapsed time after the snapshot and returns that same checked duration; the regression now rejects and poisons the session.

The literal 512-byte independent fixture verifies two ordered requests, all 41 raw input words including signed-zero/subnormal bits, all five raw output words, new S6/SM01 and exact SRAM/model identity, readback before sequence commit, no platform-ACK write, late last-input mutation, bad completion/status/row/nonfinite last logit, partial commit uncertainty, transport failure, bounded unstable reads, exhausted sequences and poll budgets. No automatic retry follows a potentially issued request.

Tiny RAM tests verify all backups precede any payload write, 4096-byte chunking, second-backup persistence failure leaves RAM unwritten, ambiguous write retains attempted/not-verified evidence without retry, and an earlier region corrupted by a later write fails the final full readback. Mock backend tests verify exact entry-register writes, failed register readback prevents resume, bad context/cache/security or mismatched entry/stack refuses writes, MMIO/flash/old-external-address writes are forbidden, and an exact-serial session is closed even if opening fails. Duplicate matching serials are refused before session construction.

Static review of `bundle.py` finds fixed whole-file commitments, immutable load bytes, exact 1024 raw 41-input/5-reference rows and IDs, ELF+full-pool zero initialization, and no target calls. `validation.py` retains FP32 `np.isclose(reference, actual)` with the original `atol=1e-6`, `rtol=1e-5` direction and separate argmax condition, checked against the held export/deployment comparison source. Collection durably retains each result before submitting the next row. This paragraph is source review, not independent execution of the original vectors or the author's numerical tests.

Installed pyOCD source was read: explicit `no_config` bypasses ambient config; disabled pack debug sequences return without running DFP sequences; explicit empty script and cache/auto-unlock/auto-resume options are valid. Attaching still changes debug registers and is not read-only hardware access. `Session.__init__` changes the process cwd to `project_dir`, so future orchestration must make evidence and backup paths absolute beforehand. Pack/hash options and source reads are not a full installed-library provenance or side-effect proof.

Limits: the backup sink's durability and immutable bundle ownership are caller contracts; no platform initialization, loader/orchestrator integration or device identity authentication is proved. A matched RAM readback is a finite observation, not immutable future target state. Current `Core.entry_snapshot` is read-only register access; no malicious callback mutation is misreported as a concrete production fault. Backend calls still need an outer process timeout. NPU execution, 1024-row on-board parity, frequency/latency, energy and deployment acceptance remain unverified/false.

Reviewed SHA-256:

| File | SHA-256 |
|---|---|
| protocol.py | 78b25d2622774d77b7241c943f884bd1cadb1517657246d398e2702785afe50e |
| bundle.py | d83e032d018c564936d30016c2f26e2933f71ce45b9595f536da73f44ca6a423 |
| ram_loader.py | 847e1cb3f0c876f2cd0a5dcdf7433c859e2f353538c2b7f2806802752a9ff950 |
| pyocd_backend.py | 263f25ddf8ef3a7a3b8c50f75be9e989d617983b50cfc02786af73a13aaab611 |
| validation.py | 684068f35b9c55d4fec967fcb5e8fc7d34d3af5b729f361e722452cd39947f75 |
| empty_user_script.py | e37f0c329b40ee23e5f014079276ac040d517be8981fe6101a809a0b005f6480 |
| test_protocol_independent.py | 258268ced282891ca0f4060bed27a11c99d2802d3789e99b5a98c1efde2c6063 |
| test_host_io_independent.py | b197ad53826eceba8149eafba755e45ab4317129ebcbc0b88ee331429542229e |
| host_independent_final_02.xml | 8b757f421471c6afe8f9d9ec6c486a62510746896595eb993b3a6873517e7065 |
