# SpikeIDS v5 adversarial review gates

Date: 2026-09-21. This is a living issue- and phase-level gate log. A phase
may advance only after every issue in that phase is either `PASS` with sealed
evidence or explicitly `OUT-OF-SCOPE` with the corresponding paper claim
removed. `PENDING` and `FAIL` both block downstream acceptance.

## Current authoritative status (supersedes historical PASS rows below)

**2026-09-21 23:52 Asia/Taipei:** the actual corrected-data neural/statistics
continuation completed at 16:19:48. All 16 stage receipts passed, 220 primary
and 220 replica fits and evaluations completed, and the independent verifier
checked 440 checkpoints and 440 prediction artifacts. Evidence lives under
`results/v5_research_continuation_20260921_r6_recovery1/` and
`results/v5_run_20260921_r6_recovery1/`; the completed service must not be rerun.
The requested post-run lifecycle/science review has **passed within its stated
boundaries**. All demonstrated tree pre-launch adapter/controller issues were
closed, including the transitive-source omission found after earlier tests had
passed. Root final regression: 901 PASS; separately rerun attacks: 151 PASS;
both actual exits 0. The new fixed 84-fit tree service completed at 23:39 with
an owner-observed actual exit 0, then passed fresh full-model science and
lifecycle/resource reviews. Tree-only acceptance was published at 23:52 in
`TREE_PHASE_ACCEPTANCE.json`, seal `005cfff750a37a19a2c1dc7f26a03863e666e7a8ecb31199fb0827f50fc65e9c`.
Neural export/paper/release/hardware remain unaccepted:
`results/v5_postrun_review_20260921_BtSToy/REVIEW_STATUS.md`.
Tree readiness and the completed lifecycle/scientific evidence are separately
reviewed; any blocking counterexample stops the next launch. Recorded software
stack reproducibility does not establish cross-platform determinism, and new
statistics do not restore the superseded all-four-indistinguishable claim.
The 15-second resource sample-gap gate was locally pre-frozen, not publicly or
independently preregistered; see `TREE_ACCEPTANCE_WRITER_REVIEW.md`'s terminology
erratum accompanying the unchanged lifecycle report. Producer ledger 1/1 does
not erase independent verification/audit test reads or historical exposure.

All older running/not-started/pending-data statements below are retained history,
not current progress. Existing failed attempts remain failed and preserved.

**Latest bounded implementation closure:** the arbitrary closure cap, missing
independent fold/history replay, and UNSW excluded-duplicate lineage issue are
fixed and independently reviewed. Verifier `df9d7bd2...` passed 61 focused
tests and fresh real NSL/UNSW replay (including all 18 UNSW rounds). Attempt 01
remains a preserved failure; attempt 02 is a two-dataset diagnostic, not G2
acceptance. Performance qualifier `fd872220...` passed 113 focused tests plus
five independent positive controls and five rejected attacks. It now rejects
candidate failure omission, invented event durations, changed inputs during
verification, and changed worker runtime relative to the parent profile.

The latest combined stationary-source regression passed **745 tests**, 8 ONNX
deprecation warnings, no skips, in 132.75 seconds, including the data-continuation
tool. Evidence: `results/v5_review_20260921_aqHrbg/post_continuation_tests.{log,xml}`;
XML SHA-256 `1c6c84c1c5702ea7e5bf30837acda04abb8c0187492004a0d8a7d736fa489c2f`.
The preceding 676-test run remains preserved in `post_lineage_performance_tests.*`.
The continuation tool's 69 focused tests and independent 10 rejected attacks /
one positive complete synthetic control passed after fixing omitted mandatory
pins, final source-drift windows, resource scalar types, worker identity and
post-consumption phase-receipt mutation. Its actual r6 plan is frozen and running:
root recorded A's actual owner-observed exit code 0 (57:05.39 elapsed), all four
A structural checks passed (4,085,276,672-byte cgroup peak, zero swap/OOM), and
fresh B has started. Full raw replay / byte-identical rebuild acceptance is still
pending. Source SHA is `2eaeb78b6e0c8043e7eb1f42c30e48d8afd650c3bf101c396ed32f67715ce6bc`.
Top-level scientific sources remain unchanged from the source-bound r7 synthetic
44-fit integration. First-cache CIC reached zero new unions in round 7; complete
independent replay is still pending, and rare-class supports remain a limitation.
**G2 still awaits both complete four-dataset caches and independent acceptance;
G1 still awaits real corrected-data performance measurement. No new formal
440-fit run has started.** The next paragraphs retain the preceding discovery
state, not an assertion that these now-fixed implementation issues remain open.

Hardware permission was explicitly granted by the user. Live connections and
recoverable readback work are recorded separately under
`results/v5_hardware_20260921_7dMGgC/`; neither USB discovery nor legacy-model
diagnostics count as v5 trained-model deployment or energy evidence.

**New real-data blocker:** fresh r5 raw-source audit passed all four datasets,
but r5a cache generation stopped on UNSW after the hard-coded eight collision
rounds. NSL alone completed. The partial r5a root is not accepted. A nonformal
instrumented diagnostic records strict component coarsening and continuing
positive unions at round eight; it explicitly forbids publishing a cache.
Production bounds, independent-verifier closure checks, and protocol replay
are under review before a fresh full acceptance run. No formal training has
started. Evidence: `results/v5_review_20260921_aqHrbg/cache_r5a.log` and
`unsw_closure_diagnostic_r1.log` in the same review directory.

Consolidated implementation acceptance is now recorded in
`results/v5_review_20260921_aqHrbg/IMPLEMENTATION_ACCEPTANCE.md`: 531 full
regression tests passed with no skips, and stationary-source r6 completed 44
synthetic fits plus evaluation/statistics/mutation checks. The implementation
subgate permits fresh real-data preparation. **G1 remains incomplete until the
corrected-data performance profile is measured; G2 remains pending two fresh
real caches and independent acceptance. G3–G8 have no accepted real results.**
The paragraphs and tables below preserve the discovery history, not current
acceptance of the superseded caches, timing profiles or manuscript.

The user requested a consolidated restart only after blocking defects are
closed. No new formal 440-fit run has started. The rejected r1 run was stopped
with the user's authorization; all results, checkpoints and logs were retained.
Its exact 24-file source snapshot and stop accounting are recorded in
`results/v5_run_20260920_r1/STOPPED_NONFORMAL.md`. The GPU is now at the
165 W enforced/default limit. No r1 artifact may initialize a formal fit or
contribute a paper number.

Historical `PASS` statements refer only to the implementation and evidence at
that point. In particular DATA-05/06, ENV-03/04 and the earlier lifecycle test
counts do not accept the corrected protocol, performance profile, or final
release. Current phase status is G1/G2 blocked pending integrated review; G3–G8
remain pending. Physical claims remain out of scope without board evidence.

Candidate corrections under consolidation include:

- Immutable raw identities and monotonically merged assignment components;
  final `(FP32 X,label)` dedup preserves label ambiguity and multiplicities.
- Single-file-descriptor reads, immutable private arrays, no linked cache
  aliases, source stat/hash snapshots across preparation, and explicit
  identity-to-component coarsening checks.
- Fit-only physical array loading; independent execution IDs in checkpoint,
  ledger and outputs; immutable fit snapshots; all 22 execution artifacts
  revalidated before any formal test tensor is materialized.
- Exact data-acceptance binding, including the independent verifier,
  raw-audit producer and IoT provenance report. Raw audit alone cannot pass G2.
- Frozen 22-attempt export policy and one-time registration; structured
  numerical-failure replay excludes OOM, signals and storage failures.
- Neural/tree cache cross-binding, protected paper macro/protocol inputs,
  and package/archive consumer integration are being independently reviewed.
- Baseline and final resource samples close the short-action counter gap.
  A cgroup v2 scope enforces a 16 GiB workload budget and zero swap allowance;
  raw trace replay checks boundaries, counter deltas, sampled RSS/GPU limits
  and kernel cgroup peak/OOM evidence. GPU sub-interval peaks are not proved
  absent by sampling. A workload limit is not a 16 GB whole-machine proof.

Focused checks recorded during this consolidation: 106 data/science/barrier
tests passed; 15 resource evidence tests passed; a real fresh user scope
reported `memory.max=17179869184`, `memory.swap.max=0`, and zero OOM events.
The export agent reported 29 focused passes including real CPU ORT. These are
not a final combined acceptance report. A concurrent source edit invalidated
one later execution-identity test; rerun on stationary sources is required.

Next mandatory sequence: freeze candidate edits → coordinated merge → complete
unit/mutation and 44-fit synthetic integration → independent adversarial
review → fresh raw audit and two real caches → independent data acceptance →
corrected fit-only performance benchmark → new sealed formal plan → 440 fits.
Any counterexample returns the affected gate to FAIL, without silently relaxing
thresholds or hiding failed attempts.

Resource-limit semantics were checked against the
[Linux cgroup v2 documentation](https://cdn.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html).
Checksums establish consistency, not independent authenticity or experimental
history beyond the evidence collected by this workflow.

### Consolidated integration correction: resource attribution

The `v5_synthetic_review_20260921_r5` attempt failed at the primary-to-replica
boundary and remains failed. Its trace records host `pswpin=413` and
`pswpout=85417` increments, but all 28 workload cgroup samples had a 16 GiB cap,
zero allowed/current swap, zero OOM events, and a kernel peak of 1,317,642,240
bytes. Host-wide counters cannot attribute these events to this workload.
Independent review approved a scope-correct policy before any formal run:
formal plans require the bounded cgroup, zero workload swap, no cgroup OOM,
and sampled worker membership within that scope; host swap remains recorded
context, while host OOM still fails. Missing limits or escaped workers never
permit this context-only mode. A fresh interpreter must be started inside the
scope, not moved there after allocating memory. This is not a claim that every
physical host page is charged to that cgroup.

New counterexamples cover host swap with valid bounded workload (passes),
missing/unbounded cgroup, workload swap/OOM, worker escape and host OOM
(all fail). Resource tests: 29 passed. The rejected r5 plan is not modified;
a new r6 integration attempt uses the new source and explicit bounded smoke
policy. See the kernel's
[memory ownership boundary](https://docs.kernel.org/admin-guide/cgroup-v2.html#memory-ownership).

The review asks how an apparently successful run could still be wrong. It
does not use expected accuracy as an oracle, and it does not upgrade checksum
identity into upstream trust, unseen-group generalization, NPU mapping, or
physical-board attestation.

## Gate matrix

| Phase | Gate | Status | Blocking condition |
|---|---|---|---|
| 1. Environment and implementation | G1 | PENDING | The performance profile remains useful, but the corrected final implementation must be retested and frozen in a fresh plan. |
| 2. Data provenance and cache | G2 | FAIL | Source identity passed, but exact model-input groups cross split boundaries and CIC contains a duplicated semantic feature. A fresh protocol, audit, and cache are required. |
| 3. Formal neural training | G3 | PENDING | All 220 primary and 220 independently trained replica fits plus test evidence must verify. |
| 4. Tree baselines | G4 | PENDING | RF/XGBoost outputs must be independently recomputed from the same cache and barrier. |
| 5. Statistics | G5 | PENDING | Saved predictions must independently reproduce metrics, pairings, families, and multiplicity decisions. |
| 6. ONNX/QDQ export | G6 | PENDING | Every frozen seed-0 checkpoint must produce sealed FP32 and QDQ evidence under the fixed gate. |
| 7. Paper and PDF | G7 | PENDING | Generated macros, prose, citations, tables, figures, strict checker, build, and rendered PDF must agree. |
| 8. Packaging and archival | G8 | PENDING | Bundle must verify independently; stale material moves recoverably; current source archives remain reproducible. |

## G1 — environment, source freeze, and performance

| Issue | Adversarial question | Evidence and resolution | Status |
|---|---|---|---|
| ENV-01 | Could the environment record describe a different runtime? | The rejected r2 plan recorded RTX 4060 Ti, torch 2.10.0+cu128, deterministic algorithms, IEEE FP32, and TF32 disabled. The final corrected implementation requires a fresh environment record and canonical plan comparison. | PENDING |
| ENV-02 | Could code have changed after freeze? | r1/r2 source seals were intact, but newly discovered data and evidence-chain defects require source changes. Freeze and recheck a fresh final plan only after every blocking fix passes. | PENDING |
| ENV-03 | Was the fastest setting selected by name or accuracy? | `results/v5_benchmark_cicids2017_20260920_r1/benchmark.json` contains two reversed-order repeats for four profiles, no test evaluation, exact within-profile training digests, and chooses `fused:4` by median wall time only. | PASS |
| ENV-04 | Does worker concurrency silently alter science or exceed memory? | CUDA smoke comparisons for 4/6/8 workers preserved scientific digests. Eight workers was fastest and peaked at about 9.8 GiB process-tree RSS, below the 16 GiB target; the formal plan records 8 workers. Full-run replica verification remains the final determinism gate. | PASS |
| ENV-05 | Could aggressive tuning modify clocks, power, precision, batch size, or epochs? | The suite changes none of these dynamically. The formal plan fixes optimizer, threads, workers, FP32 mode, batch sizes, and epochs. Hardware power/clock changes and AMP/TF32 fallback are forbidden. | PASS |

## G2 — provenance, source identity, and cache

| Issue | Adversarial question | Evidence and resolution | Status |
|---|---|---|---|
| DATA-01 | Are UNSW train/test roles inferred from misleading filenames or sizes? | Roles were checked against official row counts and file contents. The pinned mirror's `test.csv` carries official training content and `train.csv` carries official testing content; local files are renamed to their semantic roles and byte-bound. | PASS |
| DATA-02 | Could the CIC inputs omit or substitute a capture CSV? | All eight fixed MachineLearningCSV members are individually byte- and SHA-256-bound; the container archive is also bound. GeneratedLabelledFlows is explicitly supporting provenance, not model input. | PASS |
| DATA-03 | Could the IoT combined Parquet differ from its claimed pinned source? | All 6,046,623 rows and 21 columns were compared to the three pinned Hugging Face shards in 65,536-row chunks, including order and missingness. Only Arrow representation differences were accepted. | PASS |
| DATA-04 | Could correct local bytes retain false upstream metadata? | Incorrect IoT LFS hashes and an invalid CIC mirror revision were found adversarially. The source specs were corrected, the r1 cache/run was demoted, and fresh audit/cache/r2 plan namespaces were created. | PASS |
| DATA-05 | Could label mapping, feature order, or row count drift silently? | `results/v5_data_audit_20260921_r3/data_audit.json` seals physical files, selected feature order, mappings, per-class counts, and rows: NSL 148,517; UNSW 257,673; CIC 2,830,743; IoT 6,046,623. `data_audit_passed` is true. | PASS |
| DATA-06 | Could cache preparation leak validation/test state? | The cache contract fits categorical vocabulary, scaler, and class weights on fit rows only and seals split row-ID hashes. Independent r3/r4 cache generation agreed byte-for-byte and audit-to-cache validation passed. | PASS |
| DATA-07 | Could row splitting be misrepresented as unseen device/capture/time generalization? | Cache metadata keeps group/upstream limitations false; the paper explicitly limits CIC/IoT claims to row-split benchmark performance. No missing group IDs are fabricated. | PASS |
| DATA-08 | Could archival remove inputs required to reproduce the audit? | `tools/archive_pre_v5.py` was corrected to keep `GeneratedLabelledFlows.zip` and `MachineLearningCSV.zip` at repository root because source specs refer to them. | PASS |
| DATA-09 | Can disjoint row IDs still leak identical model inputs across splits? | Yes. An exact full-vector audit found train-to-test overlap of 2.945% (NSL), 10.401% (UNSW), 24.880% (CIC), and 90.459% (IoT); fit-to-validation overlap is also material and reaches 89.981% for IoT. The existing row-split caches are rejected. A model-view duplicate/group-aware protocol and zero-overlap gate are required before any new formal freeze. | FAIL |
| DATA-10 | Can CSV parser header mangling hide duplicate semantic features? | Yes. Every CIC shard contains two physical `Fwd Header Length` headers. Pandas renamed the second to `.1`, bypassing the post-parse duplicate-name check, and the two cached columns are bit-identical. The raw-header audit must detect this before mangling and the declared feature policy must explicitly retain one semantic column only. | FAIL |

G2 phase decision: **FAIL / BLOCKED AT DATA REDESIGN**. Exact local source
identity and fit-only scaler/encoder provenance remain useful evidence, but
disjoint row IDs did not imply disjoint model inputs. The r3/r4 caches and all
runs derived from them are non-formal engineering evidence only. Before a new
formal freeze, the split/deduplication policy, CIC header handling, support
counts, zero-overlap audit, independent cache regeneration, and paper scope
must all pass a new issue- and phase-level adversarial review.

## G3 — formal neural training issues

| Issue | Adversarial question | Required acceptance evidence | Status |
|---|---|---|---|
| TRAIN-01 | Can the provenance-inaccurate r1 run contaminate final claims? | r1 remains labelled non-formal engineering validation and must be archived separately; no r1 checkpoint/result may enter final macros or bundle. | PENDING |
| TRAIN-02 | Are there exactly 11 jobs and seeds 0–19 in primary and replica? | Verify identities, counts, and no duplicates/missing seeds from sealed outputs. | PENDING |
| TRAIN-03 | Are replicas genuinely independent retraining rather than checkpoint rereads? | Verify distinct execution namespaces plus exact training-state/batch-order/RNG/optimizer/scheduler digests for every pair. | PENDING |
| TRAIN-04 | Was test opened only after the global fit barrier? | Verify manifests, zero premature test sessions, `verification_fit.json`, then test evidence and `verification_evaluate.json`. | PENDING |
| TRAIN-05 | Could resume, partial files, NaN/Inf, OOM, or wrong budget pass? | Check every checkpoint/history/seal, epoch/batch budget, finite tensors/metrics, logs, and fail-closed resume behavior. | PENDING |
| TRAIN-06 | Could the source/environment/cache identities differ from the frozen plan? | Repeat exact hash and canonical identity checks before launch, after fit, and after evaluation. | PENDING |

## G4–G8 pending adversarial reviews

- G4 tree baselines: recompute every RF/XGBoost prediction and metric from the
  sealed cache; verify seeds, train-only fitting, test barrier, and RF ONNX.
- G5 statistics: use an independent sklearn/SciPy oracle; reject reordered or
  missing pairs, altered aggregates, reduced families, post-hoc margins, and
  undefined zero-variance inference presented as success.
- G6 export: independently rerun ONNX Runtime; bind cache/checkpoint/vectors;
  verify BN folding, fit-only calibration, operators, QDQ format/type, fixed
  disagreement threshold, and all 22 expected mode/job identities. QDQ is not
  full-INT8, NPU, latency, or energy evidence.
- G7 paper: reject old/manual result numbers, stale macro inputs, unsupported
  physical-deployment language, citation mismatches, and PDF/macro freshness.
- G8 bundle/archive: verify every copied byte, model/evidence provenance,
  rollback behavior, dry-run scope, preservation of full formal run evidence,
  and regeneration of final checksums/reports only after archival.

## Second-pass blocking findings

The following issues were found by independent read-only reviews after the
first lifecycle implementation.  Earlier issue-level passes remain useful
evidence for their narrower claims, but do not override these new blockers.

| Issue | Adversarial failure mode | Required resolution and mutation evidence | Status |
|---|---|---|---|
| TRAIN-07 | CICIDS2017 inverse-frequency weights span about 207,826:1 while Heartbleed has only 7/2/2 fit/validation/test rows in the rejected cache. A single validation Heartbleed decision changes macro recall by 3.33 percentage points, so checkpoint selection can be highly discrete even when the process is bit-deterministic. | Freeze a fit-only weighting and checkpoint policy before the corrected formal run; publish split supports and weight diagnostics; test rare-class, zero-count, and no-test-access cases. Do not select the policy from test performance. | PENDING |
| TRAIN-08 | The low-level runner still permits `--stage all` for an individual formal-shaped output. That job can evaluate test before the global 22-fit barrier, after which the suite may still pass because final verification does not require an unexposed manifest or an exact first-evaluation counter. | Bind formal jobs to a sealed plan and barrier capability; reject direct `all`/`evaluate` without the matching passed fit-verification artifact; require both primary/replica manifests to record no prior test exposure and exactly one authorized evaluation session. Attack-test a pre-evaluated single job followed by normal suite resume. | PENDING |
| ENV-06 | The live GPU reports a 190 W enforced power limit while the workstation safety profile declares 165 W. The non-formal r1 tail is drawing only about 52 W, but a fresh formal run could enter a different load regime. | Do not change the in-flight run. Before formal freeze, require an explicitly authorized/safe power setting and bind requested/enforced/default limits plus throttle reasons in the environment record. Launch must fail if the live value differs from the frozen value. | PENDING |
| ENV-07 | Full-run evidence currently lacks a sealed per-second PID/GPU/host resource trace; aggregate logs cannot prove absence of a transient restart, throttle, pressure event, or competing GPU workload. | Add a hashed raw trace and summary covering PID start/exit identity, GPU utilization/memory/power/temperature/clocks/P-state/throttle reasons, RAM/swap/PSI, run queue/I/O/disk, and job/seed/epoch markers. Fault-inject a child restart and monitor interruption. | PENDING |
| ENV-08 | Swap is effectively full. It is cold in the observed r1 tail, but leaves no safety margin for cache construction or many concurrent loaders. | Add preflight and runtime memory/PSI gates; never load the raw multi-million-row tables in concurrent workers. Cache once, benchmark corrected compact-cache concurrency, and abort a fresh run rather than silently reducing science parameters. | PENDING |
| TREE-02 | A valid NSL cache directory can be replaced by a valid UNSW cache (or vice versa) because the tree plan and its independent verifier do not all require the embedded cache dataset identity and exact neural-plan cross-binding. | Require `metadata.dataset == requested dataset` at freeze, load, verify, paper, package, and archive boundaries. Bind the neural plan and exact cache identities. Mutation: swap two valid cache directories and separately reseal one fingerprint; every downstream gate must reject. | PENDING |
| STATS-02 | The signed-rank test targets a symmetric location/pseudomedian null, while the paper table displays a mean difference and can imply that the p-value tests that mean. | Seal and state the estimand, symmetry assumption, zero/tie rules, descriptive mean, and Hodges--Lehmann/pseudomedian result. Independently reproduce ties and zeros without sharing the primary rank routine. | PENDING |
| STATS-03 | A single 1 percentage-point TOST margin across datasets and metrics lacks an operational justification and is especially fragile for a two-row rare class. | Either establish and freeze a domain rationale before the formal run or label the analysis only as a numerical-equivalence sensitivity analysis. Publish t-TOST and signed-rank-location robustness decisions and every discordance. | PENDING |
| STATS-04 | Three-decimal p-values can render values on opposite sides of alpha identically; four-decimal effects can render a nonzero effect as signed zero. | Use threshold-aware/high-precision formatting, state that decisions use full precision, and mutation-test alpha plus/minus epsilon, very small nonzero effects, and undefined values. | PENDING |
| EVIDENCE-01 | The first provenance fix records exact verifier source/runtime and bundles lifecycle tools, but independent red-team showed that its raw argv is self-asserted and accepts a wrong formal `--run-dir`; the archive fixture also monkeypatches away both core validators. | Validate canonical parsed/resolved inputs and exact invocation semantics, not only argv positions 0--1. Add real CLI/end-to-end tests with wrong, missing, and duplicate logical arguments; at least one archive fixture must execute both lifecycle and embedded-evidence validators. | FAIL |
| EXPORT-03 | Export thresholds, sample counts, row selection, and part of the QDQ recipe live in an unfrozen tool outside the neural source seal. They can be changed after seeing results without changing the neural plan SHA. | Before attempt 1, seal an `export_plan.json` containing the full 22-attempt matrix, thresholds, sample policy, QDQ recipe, tool/protocol hashes, environment, neural binding, and prior exposure. Bind every attempt, macro, paper check, and bundle to its SHA. Mutation: change any policy/tool byte after freeze. | PENDING |
| EXPORT-04 | A subprocess failure can be accepted from a return code and free-form failure file without replaying the same scientific failure; transient OOM/disk/kill can masquerade as a QDQ result. | Persist structured diagnostics before deciding failure, then replay the exact single attempt in a temporary output and require the same scientific identity/error/numeric value. Replay pass, different failure, or infrastructure failure must reject. | PENDING |
| PAPER-02 | The tracked `main.pdf`, legacy macro, BBL, and root README still publish obsolete leakage-era claims. A newer mtime or unrelated PDF currently satisfies the packaging freshness gate. The isolated double-builder is useful but is not consumed by package/archive. | Recoverably archive legacy outputs, perform two isolated no-shell-escape builds from an allowlisted source set, require identical PDF hashes, validate logs/FLS/BibTeX dependencies/citations/PDF metadata/text, and seal complete build provenance. Package only the exact sealed builder output. Mutations: touch/replace PDF, edit an input after build, inject an undefined citation. | FAIL |
| PAPER-03 | The manuscript scanner can omit the export macro, redefine protected macros across lines or through `csname`, and leave many literal protocol values stale. | Require exactly one literal input of each generated macro, protect both namespaces against all definition primitives, and semantically bind model/data/training/tree/export protocol values. Add multiline, fallback, duplicate-input, and missing-export attacks. | PENDING |
| BUNDLE-02 | After bundle creation, required all-seed neural/tree/export artifacts can be deleted while archival still claims that the complete evidence remains externally retained. | Add an external-retention manifest for every required scientific file, rehash it immediately before archive, and live-replay exact bundled verifiers. Mutation: delete a replica checkpoint, prediction NPZ, or tree model. | PENDING |
| BUNDLE-03 | Bundle paths use only the neural plan identity and package verification has a verify-then-copy race; independent red-team confirmed that neural checkpoints, tree models, cache files, paper inputs, and much evidence are copied without a previously validated source digest. | Use a composite bundle-input digest, hold all formal evidence locks through atomic rename, snapshot every source identity/hash, verify source before and after copy plus destination bytes, generate the manifest from staging, and revalidate staged scientific semantics. Mutate each source during a copy hook and require atomic failure with no target. | FAIL |
| BUNDLE-04 | The export payload currently accepts arbitrary extra files, and NOTICE/LICENSE/model-loading boundaries do not match the selected-weight bundle. | Require an exact derived export inventory, include the repository license, provide bundle-specific notices, and warn that PyTorch/joblib artifacts must not be loaded from untrusted sources. Mutation: inject an unplanned ONNX/core/log file. | PENDING |
| BUNDLE-05 | A coordinated reseal can replace bundled neural checkpoints, tree joblibs, RF ONNX, or FP32/QDQ ONNX, update the unkeyed inventory/selected hashes, and still satisfy the current archive gate. Payload hardlinks are also accepted, so an external inode can mutate the supposedly immutable bundle after validation. | Cross-bind neural checkpoint bytes to the independent neural report, tree joblibs/RF ONNX to the tree report, and every export payload through summary to runner-validation to export-report file hashes; compare to live formal sources before archival without loading untrusted bundle models. Reject `st_nlink != 1`. Add coordinated-reseal tests for every model type. A detached signature or signed release remains required for durable authenticity against replacement of the executing archive tool itself. | FAIL |
| PAPER-04 | `build_v5_paper.py` accepts arbitrary 64-hex plan labels, never validates the two macro provenance files, and its tests intentionally pass arbitrary macros that the body does not use. The FLS inventory omits BibTeX dependencies and wrapped/transcript-only warnings can evade scanning. | Accept actual sealed neural/tree/export plans; derive identities; validate and publish macro provenance and exact source snapshots; hash the exact `.bst` and require exactly the expected `.bib`; scan transcript/logs with wrapped whitespace; reject non-PDF output. Package/archive must consume the exact sealed build directory, not a live `main.pdf`. | FAIL |

These issues block their respective phase gates.  They are not waived by a
successful non-formal r1 run, by matching checksums among mutually dependent
files, or by the existence of tests that do not exercise the attacks above.

### Open issue PAPER-01 — export macro input was not a strict build gate

Adversarial inspection found that `check_paper_consistency.py` validates the
classification/statistics macro and its provenance, while the later bundle
tool validates export macros. The strict checker used immediately before
`latexmk` does not independently require the literal
`export_macros_v5.tex` input and its provenance. The current manuscript does
include that file, but the checker must reject its removal or substitution.

Status: **PENDING / blocks G7 and the final formal plan**. A candidate fix and
tests passed locally, but touching top-level package Python would invalidate
the in-flight r1 source contract. The candidate change was therefore reverted
immediately; source hashes for both r1 and r2 were rechecked with zero
mismatches. After r1 exits, the fix will be reapplied, tested, adversarially
reviewed, and frozen under a new formal run directory. r2 will not be promoted
or executed as the final plan.

### Resolved issue ARCHIVE-01 — incomplete self-consistent bundle could unlock archival

The original archival gate verified every file listed by the bundle manifest,
but it did not require the manifest to list the complete model/evidence set. A
resealed one-file bundle could therefore satisfy that local consistency check.
`tools/archive_pre_v5.py` now additionally requires the exact formal-run path,
the 11 unique seed-0 checkpoint identities and hashes, selected-state/cache
identities, the full formal-run retention policy, and a fixed set of neural,
tree, export, data-audit, paper-macro, and PDF evidence. Tests now show that a
valid-shaped bundle passes, a resealed missing-model bundle fails, and payload
tampering fails. `test_lifecycle_tools.py`: **5 passed** after the fix.

Status: **PASS at issue level**. G8 remains pending until the real formal
bundle exists and the complete dry-run/execute/post-move review is performed.

### Resolved issue REPO-01 — active citation metadata described obsolete v1/v3 claims

The root `CITATION.cff` attached DOI `10.5281/zenodo.18906060` to version
3.0.0 and repeated NPU, latency, and estimated-energy claims. The Zenodo API
identifies that DOI as the historical software record `v1.0.0`, published
2026-03-08; it is not a version-5 archive. The CFF now declares an unreleased
`5.0.0-dev` working tree, asks users to cite the exact revision or final
plan-addressed bundle, removes the mismatched DOI/preprint preference, and
states the evidence boundaries without result numbers. `cffconvert` validates
the revised file against CFF schema 1.2.0.

Status: **PASS at issue level**. A new Zenodo version DOI may be added only
after the final v5 revision and bundle are actually released.

### Resolved issue STATS-ORACLE-01 — final evidence lacked a separate full neural/statistics oracle

The built-in verification barrier recomputes saved predictions, but originally
used the same v5 metric implementation that generated the records. A new
`tools/verify_v5_neural.py` gate now reopens all 440 primary/replica prediction
artifacts, recomputes every scalar, per-class, confusion-matrix, and aggregate
quantity with sklearn/direct rates, and independently reconstructs the 14-test
difference family and 8-test equivalence family. Exact signed-rank p-values use
SciPy average ranks plus exhaustive NumPy sign enumeration; paired TOST and
Holm values are independently checked with statsmodels. Pair identities,
bootstrap intervals, zero-variance handling, strict alpha decisions, and both
full family sizes are fail-closed.

Adversarial performance testing rejected SciPy's direct exhaustive permutation
path for the formal n=20 workload (one test exceeded 45 seconds and about
1.5 GiB). The replacement enumerates the same complete sign space in bounded
chunks (about 1 second and 200 MiB in the n=20 benchmark) and agrees exactly
with SciPy exhaustive results on deterministic small cases with ties and
zeros. The packaging gate reruns both neural/statistics and tree independent
verification live instead of trusting a merely resealed report. Syntax,
correctness-focused Ruff, mypy, and `test_lifecycle_tools.py` all pass; the
lifecycle suite currently reports **15 passed**.

Status: **PASS at issue level**. G5 remains pending until the formal run exists
and this oracle passes against its real 440 artifacts and generated reports.

### Resolved issue TREE-ORACLE-01 — tree verification reused most v5 metric code

The first tree verifier independently checked confusion matrices, overall
accuracy, and macro-F1 with sklearn, but other paper-facing metrics and the
aggregate table still depended on `metrics.full_evaluate`. It now computes the
complete metric record with the separate sklearn/direct oracle, compares every
scalar and per-class field for every primary and replica model, and recomputes
all aggregates including singleton XGBoost standard-deviation semantics and
confusion-matrix summaries. The bundle builder also reruns this verifier live.
Adversarial tests include a known hand-calculated metric case, malformed
probabilities, singleton aggregation, and aggregate tampering. A second review
also fixed fail-open tree-plan edges: all hyperparameters are now exact, the RF
ONNX matrix must contain exactly one row per dataset, validation cannot be
silently reduced below the fixed 4,096-row cap, and graph paths, hashes, and
operators must match the fixed seed-0 contract. Duplicate ONNX rows and
hyperparameter drift are tested. The lifecycle suite reports **15 passed**.

Status: **PASS at issue level**. G4 remains pending until formal RF/XGBoost
artifacts, independent replicas, and RF ONNX outputs are produced and pass the
real-run verifier.

### Resolved issue EXPORT-01 — ORT parity was not a complete checkpoint/QDQ binding

The export wrapper originally reran FP32/QDQ graphs in a fresh CPU ONNX Runtime
session, but did not itself reconstruct the selected neural checkpoint. A
self-consistent graph plus stored reference logits could therefore pass without
an independent checkpoint-to-graph comparison. It also trusted the exporter's
operator list instead of independently proving that a purported QDQ graph had
Q/DQ nodes and integer tensors.

`tools/run_v5_exports.py` now reloads the sealed seed-0 best state, reconstructs
the model, requires exact equality with the stored PyTorch logits on all 1,024
fixed validation rows, checks the FP32 graph from that checkpoint, independently
runs `onnx.checker`, and requires QDQ graphs to contain both `QuantizeLinear`
and `DequantizeLinear` plus at least one INT8/UINT8 initializer. The evidence
records checkpoint-logit, graph-structure, and live ORT results. The packaging
gate now replays every passing validation and reproducible runner-validation
failure live; a formerly failed check that now passes is rejected as stale.
Static bundle checks also require the exact checkpoint gate and QDQ structure.
The lifecycle suite reports **15 passed**, focused ONNX/QDQ and tree tests report
**3 passed** (with two upstream Torch legacy-export deprecation warnings), and
syntax, correctness-focused Ruff, and mypy pass.

Status: **PASS at issue level**. G6 remains pending until all 22 attempts run
against the final formal checkpoints; every technical failure will be reviewed
and fixed where possible, while a genuine fixed-threshold QDQ failure must
remain reported as a failure rather than be tuned away.

### Open issue EXPORT-02 — export policy omits the full static-quantization recipe

The official ONNX Runtime quantization documentation confirms that static QDQ
uses calibration data and represents tensor quantization with
`QuantizeLinear`/`DequantizeLinear`; it also distinguishes QDQ representation
from proof of all-integer or accelerator execution. The current code follows
that boundary, but `export_policy.json` records only `int8: true`, not the
complete frozen recipe already present in code: signed activation/weight type,
per-channel setting, MinMax calibration, selected operator classes, and CPU
calibration provider. Those fields should be explicit evidence rather than
recoverable only from a source hash.

Status: **PENDING / blocks G6 and the final formal plan**. The policy and its
independent validation will be extended after r1 exits because
`export_verified.py` is part of the in-flight source seal. The fixed numerical
threshold and sample rows will not be changed.

### Resolved issue BUNDLE-01 — bundle hashes did not preserve exact executable source

The bundle plan recorded source SHA-256 values but initially omitted the source
bytes themselves. It now copies every frozen plan source under
`payload/source/spikeids_v5/`, verifies each byte against the plan before
packaging, and includes pinned requirements plus the v5 use/protocol notices.
This makes the selected checkpoints retain the exact training/evaluation loader
implementation rather than only an external hash promise.

The archival gate now cross-checks the embedded neural plan against the formal
run, all 440-artifact independent verification and both statistical reports,
tree plan/results/independent verification, the complete 22-attempt export
matrix, data-audit implementation hashes, paper checks, macro provenance, and
each selected seed-0 checkpoint's result metadata. It also requires the tree and
export formal directories to still exist before computing the preservation
plan. Missing frozen source and model/evidence tampering are adversarially
tested. Syntax, correctness-focused Ruff, mypy, and the **15-test** lifecycle
suite pass.

Status: **PASS at issue level**. G8 remains pending until the real bundle is
created, dry-run inventory is reviewed, reversible archival executes, every
moved byte is rehashed, and final active-tree checksums are regenerated.

## Out-of-scope physical claims

No physical N6, RA4E1, ESP32-S3, latency, or energy claim can pass without
explicit user authorization and a separate checkpoint-to-board evidence
chain. Until that exists, these are `OUT-OF-SCOPE` and must remain absent from
the paper; software export gates must not be renamed deployment validation.
