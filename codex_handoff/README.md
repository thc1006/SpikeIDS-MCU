# Codex Handoff — SpikeIDS-MCU GLOBECOM v4 (finish + review the paper to "airtight")

> **This folder is the complete, self-contained brief for a fresh Codex agent** with no prior
> conversation context. Read it top to bottom before touching anything. The code lives in the
> repo (paths in §2); this folder holds the orientation + the two top-level run scripts.

**Repo root (run everything from here):** `/home/thc1006/dev/SpikeIDS-MCU`
**Branch:** `v4`. **Date handed off:** 2026-09-20.

**This folder contains 10 files** (the ≤10 cap): 3 handoff/run files + 7 read-only code snapshots.

*Handoff docs / runners (authoritative — run these):*
1. `README.md` — this document (goal, repo map, experiments, the fix, re-run, prose reframe,
   per-file audit + review scope, pitfalls, checklist).
2. `run_v4_rerun.sh` — runs all 11 training jobs (calls the REPO `scripts/train_fast.py`).
3. `finalize_and_check.sh` — rebuilds macros + consistency check + PDF (calls REPO scripts).

*Code SNAPSHOTS (read-only reference — see caveat):*
4. `experiment_all.py` (complete-version SCAFFOLD, from `src/` — **the file to fill**, §12) · 5. `finalize_all_det.py` · 6. `assemble_nsl_legacy.py` ·
7. `assemble_cnn_legacy.py` · 8. `run_globecom_stats.py` · 9. `run_v4_equivalence.py` ·
10. `check_paper_consistency.py`

> **CAVEAT — snapshots vs authoritative.** Files 4–10 are point-in-time COPIES of
> `scripts/<same-name>.py` as of this handoff, put here so you can read the exact current code
> in one place. **The authoritative copies live in `scripts/` and are what actually runs**
> (they `sys.path`-import the science modules in `src/`). **Apply ALL edits to the `scripts/`
> copies, not these snapshots** — the snapshots go stale the moment you apply the §4 fix. The
> `src/` modules these scripts import (`models.py`, `data_loaders.py`, `metrics.py`,
> `stats_tests.py`, `quantize*.py`, `experiment_*.py` loaders, `train_utils.py`, `export_*.py`)
> do NOT fit the 10-file cap — they are annotated in §7 and reviewed **in place** in the repo.
> Run everything from the repo root: `/home/thc1006/dev/SpikeIDS-MCU`.

---

## 0. What this folder is for + how you (Codex) use it

**Purpose:** the v4 paper is NOT finished and NOT verified. A previous agent found ONE
confirmed, severe bug (test-set leakage) and did partial plumbing, but **most of the codebase
was never audited**. Your job is to (a) apply the confirmed methodology fix, (b) re-run all
experiments deterministically, (c) regenerate the paper's numbers, (d) rewrite the
data-dependent prose, and — most importantly — **(e) adversarially review every file listed
in §7 and fix it to correctness.** Treat nothing as "done". This is academic research.

**Workflow (do in order):**
1. Apply the val-selection fix to `scripts/train_fast.py` (§4) and verify (§4d).
2. Review + fix the Tier-1 files in §7 (data loaders, models/QCFS, metrics, stats) — these
   decide whether the numbers even mean anything.
3. `bash codex_handoff/run_v4_rerun.sh` (§5) — ~4–5 h, produces 11 result JSONs.
4. `bash codex_handoff/finalize_and_check.sh` (§6) — regenerates all LaTeX macros.
5. Rewrite the prose in `paper/globecom/main.tex` per the §6 catalog.
6. Review + fix Tier-2/3/4 files in §7; re-run `check_paper_consistency.py --strict` until
   clean; rebuild the PDF. Tick every box in §8.

**Workstation rules (obey):** use `.venv/bin/python` or `uv run`; **never `pip`** (use
`uv pip`/`uv add`). **Never add AI/Claude attribution to git commits.** Do not commit unless
the human asks. GPU is an RTX 4060 Ti; the trainer saturates at `--workers 2` (do not raise).

---

## 1. Goal + scientific context

GLOBECOM 2026 **v4 resubmission**. Thesis: a tiny INT8 MLP intrusion detector whose **QCFS
(T=1 SNN) variant is statistically ≈ the ReLU MLP**, and which deploys on commodity MCU/NPU
silicon. The prior submission was rejected; reviewers flagged: limited novelty, **energy only
estimated**, not end-to-end, and **weak baselines**. v4 must answer these.

**"Airtight" means:** every reported number is (a) reproducible/deterministic, (b)
**leakage-free**, (c) computed by verified code, (d) internally consistent (paper prose =
tables = macros = result JSONs), and (e) backed by an **honest** claim (no overstatement).

**Key already-established truth (deterministic n=20):** on IoT-23 the QCFS arm is
*significantly better* than ReLU (OA 78.61 > 77.23). So the old paper claim "QCFS ≈ ReLU,
statistically indistinguishable on **all four** datasets" is **FALSE** and must be reframed to
an honest, bidirectional story (see §6).

---

## 2. Repo map — which folders/files are involved

| path | what it holds | your stance |
|---|---|---|
| `src/` | the science: `models.py` (MLP, **QCFS**, TinyCNN), `data_loaders.py` + `experiment_*.py` (dataset load/preprocess), `metrics.py`, `stats_tests.py` (TOST), `quantize*.py` (INT8), `export_*.py` (ONNX), `layerwise_analysis.py`, `tree_baseline.py` | **MOSTLY UNAUDITED — review per §7** |
| `scripts/` | `train_fast.py` (the trainer you fix in §4), `run_globecom_stats.py`, `run_v4_equivalence.py`, `finalize_all_det.py`, `assemble_{nsl,cnn}_legacy.py`, `check_paper_consistency.py`, `n6_*.py` (on-board latency) | mix of wrote-this-session + unaudited — §7 |
| `paper/globecom/` | `main.tex` (the paper), `result_macros.tex` (auto-generated numbers) | prose reframe in §6 |
| `data/` | `KDDTrain+.txt`/`KDDTest+.txt` (NSL, re-downloaded, md5 verified), `UNSW_NB15_*.parquet`, `cicids2017/`, `iot23/` | inputs; check preprocessing (§7) |
| `results/` | per-run metrics `*.json`, `stats_report_globecom.json`, `equivalence_v4.*` | outputs; will be overwritten by the re-run |
| `firmware/` + `results/three_platform_latency.md` | N6 on-board latency (3-platform table); a CPU-clock bug was caught here once | Tier-2 review (§7) |

**Do NOT touch / ignore:** the K8s cluster is intentionally stopped (unused). `src/__pycache__`.

---

## 3. The experiments (what is being run and measured)

**A. Classification accuracy + statistics (the core).** Four IDS datasets — NSL-KDD (5-cls),
UNSW-NB15 (10-cls), CICIDS2017 (15-cls), IoT-23 (5-cls) — each trained with three networks:
- **ReLU MLP** (`IDS_MLP`), **QCFS T=1 MLP** (`IDS_MLP_QCFS`, L=4), **TinyCNN** (`TinyCNN_IDS`,
  Conv2D 1×3, NPU-eligible baseline). Random Forest/XGBoost are non-NPU accuracy references only.
- 20 seeds each; report mean±std of overall accuracy + macro-F1 + per-class recall.
- **Paired stats:** ReLU-vs-QCFS **equivalence** (paired TOST, δ=1 pp, Holm) and Wilcoxon;
  ReLU-vs-TinyCNN Wilcoxon/Holm. All from `results/*.json` via `run_globecom_stats.py` +
  `run_v4_equivalence.py`.

**B. Deployment (INT8 / NPU / on-board).** Quantize to INT8, export to ONNX, measure latency
(and estimate energy) on N6 (M55 CPU vs Neural-ART NPU), RA4E1, ESP32-S3 → the 3-platform
table + width-sweep/NPU-crossover. Key prior result: on this workload the NPU is *slower* than
the M55 CPU INT8 path (see `results/three_platform_latency.md`).

**Budgets (must match within each ReLU-vs-QCFS pair):** iot23 = 40 epochs / batch 1024; all
others = 80 epochs / batch 512. TinyCNN now re-run at the MLP's 80 ep (it was confounded at
30/40 ep before). Standard Adam (lr 1e-3, wd 1e-5), cosine annealing.

---

## 4. THE CRITICAL FIX — test-set leakage → validation-based selection (do this FIRST)

**Bug (confirmed):** `scripts/train_fast.py::_train_single` (and legacy
`src/experiment_multiseed.py`) selected the training epoch by **test-set** macro-accuracy and
reported that epoch's test metrics = **data leakage** → inflated, non-reproducible numbers.
Literature: test-set early stopping inflates ~76% of datasets. Measured NSL trajectory: test
macro-F1 **peaks at epoch ~20 (58.1) then overfits to 51.7 by epoch 80** — so the old "best"
numbers were the leaked peak.

**Fix = validation-based model selection (leakage-free, representative, standard).** Hold out a
fixed 15% stratified validation split from *train*; pick the epoch with best **validation**
macro-recall; report **test** at that epoch. (train_fast is currently in an interim
"last-epoch" state — no leakage but it reports the overfit model; you must upgrade it to the
val-selection code below.)

### 4a. Add to `scripts/train_fast.py` (module level, above `_train_single`)
```python
_VAL_FRAC = 0.15          # fraction of TRAIN held out for model selection
_VAL_SEED = 12345         # fixed: same val split for every seed AND both arms

def _split_train_val(y_train_cpu):
    from sklearn.model_selection import train_test_split
    import numpy as np
    y = y_train_cpu.numpy() if hasattr(y_train_cpu, "numpy") else np.asarray(y_train_cpu)
    idx = np.arange(len(y))
    tr, va = train_test_split(idx, test_size=_VAL_FRAC, stratify=y, random_state=_VAL_SEED)
    return np.sort(tr), np.sort(va)

def _val_macro_recall(model, Xva, yva, num_classes):
    model.eval()
    correct = torch.zeros(num_classes, device=Xva.device)
    total = torch.zeros(num_classes, device=Xva.device)
    with torch.no_grad():
        for j in range(0, Xva.shape[0], 8192):
            preds = model(Xva[j:j + 8192]).argmax(1)
            yb = yva[j:j + 8192]
            for c in range(num_classes):
                m = yb == c
                total[c] += m.sum()
                correct[c] += (preds[m] == c).sum()
    rec = torch.where(total > 0, correct / total, torch.zeros_like(correct))
    return float(rec.mean().item() * 100)
```

### 4b. Replace `_train_single` (new args `tr_idx, va_idx`)
```python
def _train_single(seed, arm, L, Xtr, ytr, Xte, yte, cw, num_classes, class_names,
                  input_dim, tr_idx, va_idx, epochs, batch_size):
    _make_deterministic(seed)
    dev = Xtr.device
    Xtr_, ytr_ = Xtr[tr_idx].contiguous(), ytr[tr_idx].contiguous()   # 85% train
    Xva, yva = Xtr[va_idx].contiguous(), ytr[va_idx].contiguous()     # 15% val (held out)
    model = _make_model(arm, input_dim, num_classes, L, dev)
    criterion = nn.CrossEntropyLoss(weight=cw)
    optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    n = Xtr_.shape[0]
    g = torch.Generator().manual_seed(seed)
    best_mr, best_state = -1.0, None
    for epoch in range(epochs):
        model.train()
        perm = torch.randperm(n, generator=g).to(dev)
        for i in range(0, n, batch_size):
            idx = perm[i:i + batch_size]
            optimizer.zero_grad()
            criterion(model(Xtr_[idx]), ytr_[idx]).backward()
            optimizer.step()
        scheduler.step()
        mr = _val_macro_recall(model, Xva, yva, num_classes)          # VALIDATION, not test
        if mr > best_mr:
            best_mr = mr
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    if best_state is not None:
        model.load_state_dict(best_state)
    return _evaluate(model, Xte, yte, num_classes, class_names)       # test @ best-VAL epoch
```

### 4c. In `_worker` (compute split once, pass in, record sizes)
Before `del d`, after tensors are on `dev`:
```python
    tr_np, va_np = _split_train_val(d["y_train"])
    tr_idx = torch.as_tensor(tr_np, dtype=torch.long, device=dev)
    va_idx = torch.as_tensor(va_np, dtype=torch.long, device=dev)
    meta = {"class_names": class_names, "num_classes": num_classes, "input_dim": input_dim,
            "n_train_official": d["n_train"], "n_train": int(len(tr_np)),
            "n_val": int(len(va_np)), "n_test": d["n_test"]}
```
and pass `tr_idx, va_idx` into the `_train_single(...)` call. In `main()`'s `common` dict add
`"n_train_official"`, `"n_val"`, and set `"n_train"` to the reduced value, plus
`"model_selection": "best validation macro-recall (leakage-free); 15% stratified val holdout"`.
Then update the adapters: `assemble_nsl_legacy.py` — drop the hardcoded `n_train==125973`
assert; instead assert `relu["n_train"]==qcfs["n_train"]` and `n_train_official==125973` and
`n_test==22544`. `assemble_cnn_legacy.py` already cross-checks `cnn n_train == relu n_train`.

### 4d. VERIFY before the 5-hour run (must pass)
```bash
cd /home/thc1006/dev/SpikeIDS-MCU; PY=.venv/bin/python
CUDA_VISIBLE_DEVICES=0 $PY scripts/train_fast.py --dataset nslkdd --arm relu --seeds 0 \
  --epochs 80 --batch-size 512 --workers 1 --output nsl_check.json
$PY - <<'EOF'
import json; r=json.load(open("results/nsl_check.json"))["per_seed"][0]
print("OA=%.2f macroF1=%.2f  (expect OA~77-79, macroF1~55-58, NOT ~51)" % (r["overall_acc"], r["macro_f1"]))
import os; os.remove("results/nsl_check.json")
EOF
```
Run it twice → the two OA must be **bit-identical** (determinism). macro-F1 ≈ 55–58 confirms
selection recovers the peak (≈51 would mean selection is not working).

---

## 5. Re-run all 11 jobs — `bash codex_handoff/run_v4_rerun.sh`

8 MLP (ReLU/QCFS × 4 datasets) + 3 TinyCNN (nsl/unsw/cicids), 20 seeds each. **~4–5 hours.**
Outputs 11 files under `results/` (see the script). Run under `nohup`; it stops on the first
failure (`FAILED rc=`). Do NOT proceed until all 11 exist with 20 seeds each. Sanity: the
first job (iot23 relu) mean OA should be ~76–79.

Per-job rough time: iot23 relu/qcfs ~35/~55 min; cicids relu/qcfs/cnn ~32/~52/~32 min; unsw &
nsl (MLP + cnn) minutes each.

---

## 6. Regenerate numbers + reframe prose

**6a.** `bash codex_handoff/finalize_and_check.sh` → runs the adapters, `run_globecom_stats.py`,
`run_v4_equivalence.py`, rewrites `paper/globecom/result_macros.tex` (all macros), then the
consistency checker + PDF build. **Read the printed p/dz/reject verdicts** — you need them below.

**6b. Rewrite the data-dependent PROSE in `paper/globecom/main.tex`** (finalize fixes numeric
macros, not claims). `python scripts/check_paper_consistency.py` lists live hardcoded sites.
Known edits (search the text; line numbers drift):
- Abstract + Results "indistinguishable on **all four** datasets ($p\geq0.227$)" → honest
  bidirectional; **IoT-23 QCFS is significantly better** (reject), not equivalent.
- `tab:stats`: change every `$n{=}10$`/`$n{=}5$` → `$n{=}20$`.
- Stats-methodology paragraph: delete the obsolete "signed-rank floor / smallest attainable
  $p=0.0625$ / still at $n{=}5$ / all five seeds" argument (moot at n=20); macro-ize the
  hardcoded `$d_z{=}{+}0.20$`.
- TinyCNN prose (hardcoded `p{=}0.002`, `d_z{=}2.06`, `d_z{=}{-}0.97`, `p{=}0.063`,
  `d_z{=}{+}1.32`) → new macros (`\unswpcnn`,`\unswdzcnn`,`\nsldzcnn`,`\cicpcnn`,`\cicdzcnn`);
  update "significantly outperforms / trends higher" to the new verdicts.
- Conclusion "(NSL-KDD $p{=}0.227$, UNSW $p{=}0.846$, **CICIDS $p{=}0.312$**, IoT-23
  $p{=}0.438$)" — the `0.312` is STALE (macro is 0.770). Macro-ize all four; rewrite the claim.
- `n_train` in dataset descriptions + "5--20 seeds" → "20 seeds" and the **reduced** train
  counts after the 15% val holdout; add ONE methods sentence: *"For each run we hold out a
  fixed 15% stratified validation split and report test metrics at the epoch with the best
  validation macro-recall (the test set is never used for model selection)."* — this sentence
  is what makes the protocol airtight; it MUST be present.
- `layerwise_analysis.py` figure uses an OLD UNSW model (~75.2%) — re-run against the new
  checkpoint and update the figure.

Loop `python scripts/check_paper_consistency.py --strict` (exit 0) + `latexmk` until clean.

---

## 7. COMPLETE file audit inventory + review mandate (the point of this handoff)

**Only two things were deep-audited before handoff: (a) train_fast determinism, (b) the
leakage bug.** Everything below marked `👁️`/`❓` is UNVERIFIED — assume it may be wrong
(leakage, wrong metric/stat/quantization, train↔export mismatch) until you read it and
re-derive it. `✍️` = written this session (review it too — not infallible).

### Tier 1 — produces the headline accuracy + statistics (review first)
- `scripts/train_fast.py` ✍️ — after §4, re-derive determinism, class-weights, per-arm parity.
- `src/data_loaders.py` 👁️ — **LEAK LEAD:** categorical `LabelEncoder.fit(pd.concat([train,test]))`
  for NSL (L44) + UNSW (L108) → test vocabulary leaks. Refit train-only (handle unseen) or
  justify. Confirm `StandardScaler` is train-only (looks OK). Audit UNSW NaN/feature/label.
- `src/experiment_iot23.py` ❓ — **LEAK LEAD:** L128 `enc.fit(df[col])` — is `df` train-only or
  train+test? Audit iot23 features(13)/classes(5)/scaler. train_fast imports its loaders.
- `src/experiment_cicids2017.py` ❓ — audit 15-cls mapping, 69 features, Inf/NaN, scaler
  train-only, split logic. train_fast imports its loaders.
- `src/experiment_unsw.py`/`experiment_unsw_qcfs.py` ❓ — verify the train/test parquet swap
  (training-set=175341 / testing-set=82332) and labels.
- `src/models.py` 👁️ (only TinyCNN seen) — **THESIS CRUX:** deep-audit `IDS_MLP_QCFS` + QCFS
  layers (Floor/Clip/Shift, threshold, T=1 inference) and BatchNorm folding: is this a *valid*
  ANN→SNN conversion, or just an ANN? If wrong, the whole "T=1 SNN ≈ ReLU" claim is void.
- `src/metrics.py` ❓ — every metric flows through `full_evaluate`: macro-F1, multiclass
  ROC-AUC (averaging?), per-class recall, MCC, confusion. One wrong average corrupts all tables.
- `src/train_utils.py` ❓ — `set_seed`, `compute_class_weights` (inverse-freq?).
- `src/stats_tests.py` ❓ — `run_equivalence_analysis`: re-derive paired TOST, Wilcoxon-TOST,
  Holm, δ_min, power/`n*`. The equivalence claims live or die here.
- `scripts/run_globecom_stats.py` 👁️ — Wilcoxon ties/zero-method, Holm impl, bootstrap seed,
  the pairing-by-seed-index assumption.
- `scripts/run_v4_equivalence.py` 👁️ — `TRAIN_BATCH` names stale scripts (values OK); prefer
  reading epochs/batch from JSON; verify `pair_validity` + Holm family.

### Tier 2 — deployment / latency / energy claims
- `src/quantize_qcfs.py`,`quantize.py`,`quantize_utils.py`,`quantize_ablation.py` ❓ — INT8
  correctness; calibration leakage; does the quantized model equal what is exported/deployed?
- `src/export_qcfs_onnx.py`,`export_onnx.py`,`export_{cicids,iot23,unsw,baselines}_onnx.py` ❓ —
  **train/export parity**: exported ONNX == trained checkpoint (BN folded, QCFS→graph)?
- `scripts/gen_width_onnx.py`,`validate_onnx_neuralart.py` ❓ — width-sweep/NPU validation
  match the on-board runs?
- `scripts/n6_bench.py`,`n6_bench_report.py`,`n6_cpu_run.py`,`n6_validate_pathB.py`,`n6b_run.py`
  + `firmware/` ❓ — 3-platform latency; re-verify clocks/timing (a CPU-clock bug was caught once).

### Tier 3 — paper generation (wrote this session; still review)
- `scripts/finalize_all_det.py` ✍️ — macro-map completeness, regex safety, comparison keys.
- `scripts/assemble_nsl_legacy.py` ✍️ — apply §4c n_train change; schema matches stats scripts.
- `scripts/assemble_cnn_legacy.py` ✍️ — split cross-check; file shapes.
- `scripts/check_paper_consistency.py` ✍️ — its macro list must match `main.tex`; extend for
  ROC-AUC/weighted-F1 if the paper cites them.
- `scripts/emit_paper_macros.py` 👁️ — **do NOT run for the final** (full-regen drops hand-macros).
- `paper/globecom/main.tex`+`result_macros.tex` ✍️(macros only) — audit every table number vs
  the JSONs, not just the macros touched.

### Tier 4 — superseded / auxiliary (verify they do not silently feed the paper)
- `src/experiment_multiseed.py` 👁️, `experiment_cnn_baseline.py` 👁️ — legacy (leakage /
  confound); superseded by train_fast; their loaders may still be imported.
- `src/experiment_qcfs_lsweep.py` ❓ — the **L-sweep table** (`tab:lsweep`) comes from here; audit.
- `src/layerwise_analysis.py` ❓ — stale UNSW model; re-run + audit.
- `src/tree_baseline.py` ❓ — RF/XGBoost (`tab:accuracy` RF row); determinism + non-NPU framing.
- `src/experiment_baselines.py`,`experiment_focal.py`,`train.py`,`train_qcfs.py` ❓ — determine
  if any paper number derives from these; audit or mark unused.
- `scripts/finalize_globecom.py`,`finalize_cicids_qcfs.py`,`run_cicids_qcfs_parallel.py`,
  `train_iot23_gpu.py`,`iot23_equivalence_test.py`,`run_*.sh` ❓ — dead vs live; live ones must
  agree with train_fast + finalize_all_det.

### Global checks (run once)
- Leakage sweep: `rg -n "concat\(\[.*test|fit_transform|\.fit\(" src/` — audit every fit.
- Metric parity: paper macros == fresh independent recompute from `results/*.json`.
- Model parity: trained checkpoint ↔ exported ONNX ↔ on-board binary are the same network.
- Determinism: every trainer used for a paper number sets `use_deterministic_algorithms` +
  `CUBLAS_WORKSPACE_CONFIG` (only train_fast does today).

---

## 8. Verification checklist (definition of done)
- [ ] `train_fast.py` selects on validation; §4d smoke bit-identical + macro-F1 ~55–58 on NSL.
- [ ] Tier-1 files (§7) reviewed + fixed (esp. preprocessing leakage, QCFS validity, metrics, TOST).
- [ ] All 11 `results/*.json` exist, 20 seeds each, `model_selection` field present.
- [ ] `finalize_and_check.sh` runs clean; `result_macros.tex` regenerated.
- [ ] `check_paper_consistency.py --strict` exits 0 (no stale macro, no hardcoded stat prose).
- [ ] `main.tex`: no "all four indistinguishable"; IoT-23 = QCFS-better; n=20 everywhere;
      val-holdout methods sentence present; n_train updated; layerwise figure refreshed.
- [ ] Tier-2/3/4 files reviewed (deployment parity, L-sweep, RF, dead-code marked).
- [ ] `latexmk` builds `main.pdf`, 0 errors / 0 undefined control sequences.
- [ ] `tests/test_v4_equivalence.py` passes (expects n=20 all four).

---

## 9. Pitfalls (learned the hard way)
- `pkill -f <pat>` **self-matches** the shell if `<pat>` is in your command line (killed the
  shell, exit 144). Kill by explicit PID, or via `nvidia-smi --query-compute-apps=pid`.
- **spawn workers are invisible to `pgrep -f train_fast`** (cmdline is `python -c ...`). To stop
  training, kill the runner + the PIDs from `nvidia-smi --query-compute-apps=pid --format=csv,noheader`.
- **cwd drifts** across Bash calls after a `cd`; use absolute paths or `cd` every time.
  `.venv/bin/python: not found` (exit 127) = wrong directory.
- `CUBLAS_WORKSPACE_CONFIG` must be set **before** `import torch` (train_fast does it at module
  top; spawn workers re-import so it holds). Keep it. Keep standard (not fused) Adam.
- Determinism costs ~5–15%; do not "optimize" it away.
- Full session transcript (if you want the reasoning trail):
  `~/.claude/projects/-home-thc1006-dev-SpikeIDS-MCU/e287e8df-b593-44ae-b9b0-05620b77d9a7.jsonl`

---

## 12. PREFERRED BASE — `src/experiment_multiseed(1).py` (supersedes train_fast) + how to complete it

A newer, **more rigorous** trainer exists: `src/experiment_multiseed(1).py` (1021 lines,
"Leakage-safe, audited"). It was smoke-verified this session and is **strictly better** than
`scripts/train_fast.py`:
- fit/val/test split with **fit-only preprocessing** (`TrainOnlyPreprocessor().fit(train.iloc[fit])`)
  — fixes the categorical-encoder-on-test leakage that `data_loaders.py` still has;
- validation-based epoch selection (val macro-recall) — the §4 fix, already done correctly;
- full determinism (env set before torch import), SHA256 fingerprints, `--resume` checkpoints,
  QCFS threshold health checks, fit-then-evaluate (test touched only after all fits).

**So §4 (patching train_fast) is MOOT if you adopt this file** — prefer this file. **A 20-seed
NSL run using it is already in progress** (`results/nsl_leakagesafe_multiseed.json`, per-fit
checkpoints under `results/nsl_leakagesafe_multiseed/runs/`; resume with the same command +
`--resume`). Its output is a **rich custom schema** (not `multiseed_20.json`).

### 12a. Complete the SCAFFOLD `src/experiment_all.py` (ALREADY CREATED — just fill it)
`src/experiment_all.py` **already exists** (also snapshot #4 in this folder): a copy of
`experiment_multiseed(1).py` with the full leakage-safe machinery, the **NSL-KDD path working**,
and **`--model cnn` (TinyCNN) already wired into `build_model`**. UNSW / CICIDS2017 / IoT-23 are
placeholders — `prepare_data` raises `NotImplementedError` carrying the exact per-dataset
requirement + a 7-step blueprint (see the `_DATASET_SPECS` dict). Verified: it compiles,
`--dataset nslkdd` runs, and `--dataset unsw|cicids2017|iot23` prints its precise TODO.
**Do NOT edit `experiment_multiseed(1).py`** (its in-flight NSL run needs `--resume`
source-hash stability). Fill each placeholder in `experiment_all.py`:
1. Add `--dataset {nslkdd,unsw,cicids2017,iot23}`; dispatch in `prepare_data`. Reuse the RAW
   loaders (`data_loaders.load_nslkdd_raw`/`load_unsw_raw`, `experiment_iot23.load_iot23`,
   `experiment_cicids2017.load_cicids2017`) to get train/test DataFrames, **but do the
   preprocessing fit-only** via the `TrainOnlyPreprocessor` pattern (fit on `train.iloc[fit]`).
2. Parameterize `CAT_COLS` per dataset — take the exact categorical/numeric column lists from
   the existing preprocessors: NSL = protocol_type/service/flag; UNSW = proto/service/state
   (see `data_loaders.preprocess_unsw`); CICIDS = numeric-only + Inf/NaN handling (see
   `experiment_cicids2017.preprocess_cicids`); IoT-23 = per `experiment_iot23.preprocess_iot23`
   (audit its `enc.fit(df[col])` — must be fit-split only). **Verify no scaler/encoder ever
   sees val or test.**
3. Add `cnn` to `build_model` (`models.TinyCNN_IDS(input_dim, num_classes)`) and to `--model`
   choices; TinyCNN runs only nslkdd/unsw/cicids2017.
4. Budgets are CLI, not code: iot23 = `--epochs 40 --batch-size 1024`; all others =
   `--epochs 80 --batch-size 512`. The runner script sets them per dataset.
5. **Smoke EACH dataset** (`--seeds 0 --model relu --epochs 3`) before any full run — confirm
   it loads, preprocesses fit-only, and the val path works. This is where per-dataset bugs hide.

### 12b. Output adapter (so the pipeline can consume it)
Write `scripts/assemble_from_leakagesafe.py`: read each dataset's rich-schema output
(`fit_runs`/per-seed test metrics) and emit the schema the existing stats scripts expect
(`results/multiseed_20.json` with `relu`/`qcfs_L4` `per_seed`; `unsw_multiseed_20.json` +
`unsw_qcfs_multiseed.json`; `cicids2017_*`; `iot23_*`; `cnn_baseline_merged.json`). Then §6
(finalize) and §7 review proceed unchanged. Record the reduced `n_train` (= n_fit) + `n_val` +
the val-holdout methods sentence in the paper (§6).

---

---

## 13. COMPLETE RUN MANIFEST — everything that must be executed ("what to run")

**Single source of truth for the runs** (supersedes the scattered mentions in §3/§5/§7). Every
model result must be produced by the leakage-safe, deterministic, val-selection protocol
(§12). Tick each as you finish it.

### A. Model training — 11 runs, 20 seeds each, val-selection, deterministic
| # | dataset | arm(s) | budget | how | status |
|---|---|---|---|---|---|
| A1 | NSL-KDD | ReLU + QCFS | 80ep / 512 | `experiment_multiseed(1).py` | **IN PROGRESS** |
| A2 | UNSW-NB15 | ReLU + QCFS | 80ep / 512 | extend (1) → `experiment_all.py` (§12a) | TODO |
| A3 | CICIDS2017 | ReLU + QCFS | 80ep / 512 | " | TODO |
| A4 | IoT-23 | ReLU + QCFS | **40ep / 1024** | " | TODO |
| A5 | NSL-KDD, UNSW, CICIDS2017 | TinyCNN | 80ep / 512 | " (add `cnn` kind) | TODO |

### B. Non-NN baselines
| B1 | NSL-KDD, UNSW | RandomForest + XGBoost | `src/tree_baseline.py` — verify `random_state` determinism; feeds `tab:accuracy` RF row | TODO/verify |

### C. Ablations / secondary tables
| C1 | NSL-KDD | QCFS L∈{1,2,4,8} | `src/experiment_qcfs_lsweep.py` — feeds `tab:lsweep`; audit for the same leakage + re-run leakage-safe if it feeds the paper | TODO/verify |
| C2 | UNSW | layerwise analysis | `src/layerwise_analysis.py` — **stale (old 75.2% model); re-run on the NEW checkpoint** | TODO |

### D. Statistics (consume A/B/C outputs)
| D1 | `scripts/run_globecom_stats.py` → paired Wilcoxon + Holm + TOST + bootstrap | TODO (after A) |
| D2 | `scripts/run_v4_equivalence.py` → TOST equivalence family | TODO (after A) |

### E. Deployment tables (INT8 / latency / energy)
| E1 | INT8 quantize + ONNX export | `src/quantize*.py` + `src/export_*.py` — must match the RE-TRAINED weights; audit train↔export parity | TODO/verify |
| E2 | on-board 3-platform latency (N6 CPU/NPU, RA4E1, ESP32-S3) | `scripts/n6_*.py` + `firmware/` — re-confirm the deployed net == the re-trained one; a CPU-clock bug was caught here once | verify |

### F. Paper assembly (after A–E)
| F1 | schema adapter + finalize | `scripts/assemble_from_leakagesafe.py` (§12b) + `scripts/finalize_all_det.py` | TODO |
| F2 | prose reframe | `paper/globecom/main.tex` (§6 catalog: "all four indistinguishable"→honest, n→20, TinyCNN, conclusion, val-holdout methods sentence) | TODO |
| F3 | consistency + build | `scripts/check_paper_consistency.py --strict` (exit 0) + `latexmk` | TODO |

**Order:** §12a (extend + smoke EACH dataset) → A2–A5 → B/C → D → E → F. A2–A5 are the bulk of
the work and all depend on §12a. Nothing is "done" — every file is "ready to be reviewed to
correctness" (§7). If you adopt §12's file, start there; otherwise start at §4 then §7.
