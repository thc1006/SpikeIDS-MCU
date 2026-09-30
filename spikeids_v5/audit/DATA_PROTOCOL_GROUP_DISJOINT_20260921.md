# SpikeIDS v5 group-disjoint unique-pattern data protocol

Date: 2026-09-21

Status: **selected for implementation; not yet accepted**.  G2 remains FAIL
until two independently generated real caches and a separate verifier pass all
gates below.  No result from the rejected row-split caches is a formal result.

## Decision and estimand

The primary estimand is performance on **unique labelled model-input patterns**
under an exact-input-group-disjoint split.  It is not traffic-frequency
performance and it is not unseen-capture, unseen-device, or temporal
generalization.  Exact `(X, label)` repeats are deduplicated; rows with the same
`X` but different labels remain as explicit ambiguity, and the entire `X` group
is assigned to only one split.

NSL-KDD and UNSW-NB15 keep the publisher's train/test roles.  Fit and
validation are group-split inside official training data.  Official-test
patterns that occur in official training are excluded from the primary test,
then exact `(X, label)` repeats inside the remaining test are deduplicated.
The contaminated full official test retains an auditable ID/hash/count record,
but is not scored, used for selection, entered into a hypothesis family, or
reported as primary accuracy.

CICIDS2017 and IoT-23 use a fixed two-stage target-64/16/20
fit/validation/test split after deduplication, grouping by exact `X`.  Group
constraints make the realized fractions approximate.  They
remain row-derived benchmarks without reliable capture/device/time group IDs.

## Why the old protocol is rejected

The rejected cache had disjoint row IDs but not disjoint model inputs:

| Dataset | Fit to validation exact X | Train to test final-FP32 exact X |
|---|---:|---:|
| NSL-KDD | 7 / 25,195 | 664 / 22,544 (2.945%) |
| UNSW-NB15 | 16,427 / 35,069 (46.842%) | 8,563 / 82,332 (10.401%) |
| CICIDS2017 | 108,969 / 452,919 (24.059%) | 140,860 / 566,149 (24.880%) |
| IoT-23 | 870,534 / 967,460 (89.981%) | 1,093,943 / 1,209,325 (90.459%) |

Final-FP32 group counts also show that row counts greatly overstate independent
model patterns:

| Dataset | Rows | Exact-X groups | Mixed-label groups | Rows in mixed groups | Largest group |
|---|---:|---:|---:|---:|---:|
| NSL-KDD | 148,517 | 147,790 | 98 | 210 | 3 |
| UNSW-NB15 | 257,673 | 153,565 | 2,445 | 40,400 | 483 |
| CICIDS2017 | 2,830,743 | 2,199,140 | 311 | 83,116 | 9,329 |
| IoT-23 | 6,046,623 | 818,993 | 20 | 153,803 | 499,206 |

The largest IoT group is an identical Okiru pattern repeated 499,206 times and
split among all three old partitions.  A multiplicity-preserving group split
cannot simultaneously approach 64/16/20 because that single group alone is
larger than the desired validation partition.  That alternative is therefore
rejected as the primary protocol.

Raw equality alone is also insufficient.  Relative to canonical projected raw
features, final FP32 transformation introduced 22 additional UNSW test
collisions, 7,728 additional CIC collisions, and 3 additional IoT collisions.
The production protocol must converge on final model tensors, not merely raw
rows or hashes.

## Physical schema correction

Every one of the eight pinned CIC CSV headers contains `Fwd Header Length` at
zero-based physical positions 34 and 55.  Pandas had silently renamed the
second occurrence to `Fwd Header Length.1`; the two cache columns are bit-exact
equal.  The raw header must be parsed before pandas mangling, both physical
positions must be source-bound, equality must be verified in every chunk, and
only position 34 is retained.  The corrected CIC model has 76 features, not 77.

## Frozen construction algorithm

1. Verify source path, role, byte count, SHA-256, unmodified physical header,
   row count, label mapping, and feature order.  Reject any undeclared duplicate
   physical header.  Apply the declared CIC exception above and no fuzzy one.
2. Construct a canonical FP32 model-view matrix without the label, in the
   declared feature order.  Numeric values use the fixed strict parse and
   non-finite policy and canonicalize signed zero.  Categorical columns reject
   non-string non-null values, distinguish missing values from text, and use a
   deterministic global lexical identity dictionary whose integer IDs must be
   exactly representable in FP32.  This dictionary is used only to test raw
   token identity and is not the fit-only model encoder.  Groups are formed by
   exact equality of collision-free fixed-width row bytes (`np.unique` over
   `np.void` rows), not by probabilistic hash equality.  The ordered matrix has
   a SHA-256 fingerprint; dataset, policy version, implementation bytes, source
   bytes, and library versions are separately bound into the cache request.
3. Form immutable raw-identity groups, then deduplicate exact
   `(canonical-raw-X identity, label)` pairs, keeping the lowest original row
   ID as representative.  Preserve all excluded IDs, reason codes,
   multiplicities, label counts, and hashes.  Never collapse a mixed-label X
   identity to one label.
4. For NSL/UNSW, exact-X group-split only official training into fit/validation.
   Remove every official-test X group present anywhere in official training,
   then deduplicate the clean official test internally.  Official roles never
   move across their boundary.
5. For CIC/IoT, group-split raw-unique representatives in two stages with
   nominal 80/20 train/test and then 80/20 fit/validation targets, using frozen
   test seed 42 and validation seed 20260920.  Group constraints make realized
   fractions approximate.  Before each `StratifiedGroupKFold`, relabel arbitrary
   component IDs by first occurrence in the sorted local candidate population;
   this prevents test-only token changes from perturbing official-train splits.
   The implementation, fold rule, library versions, and input-order hash are
   part of the cache request and independent verifier.
6. Fit category vocabulary and scaler only on the selected canonical-raw-
   `(X,label)`-unique fit representatives.  Seal their exact IDs separately.
   Transform all raw-unique assigned representatives to the exact FP32 tensors
   consumed by models.
7. Maintain assignment components separately from immutable raw identities.
   If any equal final FP32 vector comes from different components, monotonically
   union those components, re-split, and refit preprocessing; a transient
   collision never deletes a raw pattern.  For official data, any final test
   component touching official training is excluded rather than reassigned.
   Terminate only on the first scan with zero new unions. With G0 initial
   identity groups, there can be at most G0-1 positive-union rounds plus one
   stable scan: every nonterminal round must strictly reduce component count.
   Fail closed on a non-coarsening transition, inconsistent union count or
   violation of this finite bound. The former arbitrary eight-round cutoff
   truncated real UNSW, whose nonformal diagnostic required 18 rounds; it is
   not a scientific convergence guarantee. The independent acceptance verifier
   must reconstruct the fixed folds and collision history from raw inputs,
   not merely validate a self-reported transition-count list.
8. Only after no new component union and zero cross-split final-X overlap,
   deduplicate exact stable `(final-FP32-X,label)` inside each split, keep the
   lowest raw ID, aggregate source multiplicities, and retain mixed-label final
   X as separate labelled patterns.  Do not refit preprocessing after this
   final dedup.  Thus preprocessing estimates the raw-unique fit population,
   while model loss/validation/test estimate the stable-final-unique
   population; final-collapsed fit vectors may have influenced preprocessing
   more than once.  This boundary must be disclosed, not described as pure
   final-pattern-weighted preprocessing.
9. Accept only if every declared class has positive support in each final
   split, all source rows reconcile through multiplicity plus declared official
   overlap exclusions, preprocessing-fit IDs and final-dedup mappings verify,
   fit/validation/test final-X intersections are empty, an independent raw-to-
   cache verifier passes, and a second clean cache build is byte-identical.

The final implementation must freeze the exact split objective and convergence
limit before real cache generation.  This document does not silently delegate
those choices to library defaults.

## Feasibility supports (not formal cache evidence)

These simulations establish feasibility.  NSL/UNSW used canonical projected
raw keys.  CIC/IoT used the rejected cache's final X and therefore must not be
presented as proof of the production fixed-point implementation.

### NSL-KDD

- Official train: 125,973 rows to 125,964 unique labelled patterns.
- Fit: 100,771: DoS 36,741; Probe 9,317; R2L 796; U2R 42; normal 53,875.
- Validation: 25,193: 9,186; 2,330; 199; 10; 13,468.
- Official test: exclude 664 training-X rows and 3 internal labelled repeats.
- Primary clean test: 21,877 (97.041% retained): 7,058; 2,288; 2,725;
  200; 9,606.

### UNSW-NB15

- Official train: 175,341 rows to 107,740 unique labelled patterns.
- Fit: 86,191: Analysis 1,275; Backdoor 1,228; DoS 3,044; Exploits 15,875;
  Fuzzers 12,920; Generic 3,345; Normal 41,512; Reconnaissance 6,017;
  Shellcode 873; Worms 102.
- Validation: 21,549: 319; 307; 762; 3,969; 3,230; 836; 10,378; 1,505;
  218; 25.
- Official test: exclude 8,541 training-X rows and 19,876 internal labelled
  repeats.
- Primary clean test: 53,915 (65.485% retained): 328; 345; 1,481; 7,391;
  4,625; 3,393; 33,666; 2,277; 365; 44.

### CICIDS2017 dry simulation

There are 2,199,451 unique labelled final-X patterns.  The simulated split is:

- Fit 1,407,648: BENIGN 1,192,339; Bot 923; DDoS 81,930; GoldenEye 6,580;
  Hulk 110,585; Slowhttptest 3,345; slowloris 3,436; FTP-Patator 3,796;
  Heartbleed 7; Infiltration 23; PortScan 1,253; SSH-Patator 2,060;
  Web Brute Force 941; SQL Injection 13; XSS 417.
- Validation 351,912: 298,085; 230; 20,482; 1,644; 27,646; 837; 859;
  950; 2; 6; 313; 515; 235; 3; 105.
- Test 439,891: 372,605; 288; 25,604; 2,056; 34,558; 1,045; 1,074;
  1,187; 2; 7; 392; 644; 294; 5; 130.

PortScan falls from 158,930 rows to 1,958 unique labelled patterns.
Heartbleed, SQL Injection, and Infiltration still have only 11, 21, and 36
total observations.  Deduplication cannot manufacture rare-class evidence.

### IoT-23 dry simulation

There are 819,013 unique labelled final-X patterns.

- Fit 524,168: Benign 176,813; C&C 8,354; DDoS 41,321; Okiru 568;
  PortScan 297,112.
- Validation 131,042: 44,203; 2,089; 10,330; 142; 74,278.
- Test 163,803: 55,254; 2,611; 12,913; 177; 92,848.

The original 1,313,015 Okiru rows reduce to 887 unique labelled patterns.

## Consequences for training and claims

- The old exact inverse-frequency loss and validation-macro-recall checkpoint
  selection are separately blocked.  The corrected supports must be recomputed
  before a fit-only weighting policy is frozen.  The leading policy candidate
  is square-root inverse frequency with a fixed final-epoch checkpoint, because
  it has no dataset-specific cap/beta and does not let two Heartbleed validation
  rows select an epoch.  This is not accepted until its own tests/review pass.
- CIC's 15-class aggregate may be retained only as a fixed-pattern descriptive
  benchmark.  Twenty training seeds measure optimization variability, not
  population or rare-attack sampling uncertainty.  No claim of reliable
  Heartbleed, SQL-injection, or Infiltration detection is permitted.
- The old IoT/CIC row-frequency results, all r1/r2-derived outputs, and all
  legacy leakage-era results are non-formal engineering/history artifacts.
- Historical test exposure is disclosed.  This protocol is a prospective
  correction frozen before its own models are trained, not a claim of original
  preregistration.

## G2 acceptance evidence

- raw-header and duplicate-column mutation tests;
- exact canonicalization tests including signed zero, non-finite policy,
  Unicode/missing categorical tokens, and FP32 collisions;
- mixed-label group and giant-group synthetic attacks;
- official-role, overlap-exclusion, dedup-reason, and all-row accounting tests;
- post-transform collision fixed-point tests, including unknown categories;
- exact zero final-X overlap independently recomputed without loader helpers;
- all per-class supports and multiplicities sealed;
- two clean real-cache generations with identical inventories and bytes;
- audit-to-cache/source/tool hash binding and a fresh issue-level adversarial
  review before G2 can change from FAIL to PASS.
