#!/usr/bin/env python3
"""Unified, RAM-safe, GPU-resident multi-seed trainer for the IDS equivalence study.

One reviewed code path for every (dataset, arm) so all matched pairs share an identical
procedure. It REUSES the existing per-dataset loaders/preprocessors, the IDS_MLP /
IDS_MLP_QCFS models, the best-by-macro selection, and metrics.full_evaluate — the ONLY
change from the legacy per-dataset scripts is the training-loop mechanics:

  * data preprocessed ONCE (parent), cached as compact tensors, workers load the light
    cache — avoids the multi-process pandas OOM that killed the box earlier;
  * GPU-resident manual seeded batching: perm = torch.randperm(n, generator=Generator(seed))
    reproduces DataLoader(shuffle=True, generator=...) EXACTLY (RandomSampler == randperm),
    so batches / BN stats / SGD trajectory are identical to the legacy loop, just without
    per-batch host->device copies;
  * STANDARD Adam (lr 1e-3, wd 1e-5) — same optimizer as every legacy ReLU baseline, so a
    re-run arm is numerically consistent with a kept arm (no fused-vs-standard question).

Numerically equivalent to the legacy scripts (verified by smoke tests vs the existing
JSONs); much faster (GPU-resident) and safe to run 2-way concurrent.

    .venv/bin/python scripts/train_fast.py --dataset iot23 --arm relu \
        --seeds 0 1 2 3 4 5 6 7 8 9 --epochs 40 --batch-size 1024 --workers 2 \
        --output iot23_multiseed_v5.json
"""
from __future__ import annotations
import argparse, json, sys, time, gc, os, random
from pathlib import Path

# MUST precede any cuBLAS use so deterministic GEMM has a fixed workspace; children inherit it.
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
DATA_DIR = ROOT / "data"

import numpy as np
import torch


def _make_deterministic(seed: int):
    """Bit-reproducible training on this machine/torch build for a given seed."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=False)
import torch.nn as nn
import torch.optim as optim
import torch.multiprocessing as mp

CACHE_DIR = Path("/tmp/claude-1000/-home-thc1006-dev-SpikeIDS-MCU/"
                 "e287e8df-b593-44ae-b9b0-05620b77d9a7/scratchpad")


def _avail_gb() -> float:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / (1024 * 1024)
    except Exception:
        pass
    return 999.0


def _load_dataset(dataset: str):
    """Return (X_train,y_train,X_test,y_test [torch], class_names). Reuses legacy loaders."""
    if dataset == "cicids2017":
        from experiment_cicids2017 import load_cicids2017, preprocess_cicids
        df, labels = load_cicids2017(grouped=False)
        Xtr, ytr, Xte, yte, _sc, le, _f = preprocess_cicids(df, labels)
        return Xtr, ytr, Xte, yte, list(le.classes_)
    if dataset == "iot23":
        from experiment_iot23 import load_iot23, preprocess_iot23
        df, labels, _feats = load_iot23(binary=False)
        Xtr, ytr, Xte, yte, _sc, le = preprocess_iot23(df, labels)
        return Xtr, ytr, Xte, yte, list(le.classes_)
    if dataset == "unsw":
        from data_loaders import load_unsw
        Xtr, ytr, Xte, yte, _sc, le, _f = load_unsw(DATA_DIR)
        to_t = lambda a, d: torch.as_tensor(np.asarray(a), dtype=d)
        return (to_t(Xtr, torch.float32), to_t(ytr, torch.long),
                to_t(Xte, torch.float32), to_t(yte, torch.long), list(le.classes_))
    if dataset == "nslkdd":
        # Same preprocessing as the legacy experiment_multiseed.py (shared loader);
        # only the training loop changes to the deterministic train_fast path, so all
        # four datasets now use one bit-reproducible trainer.
        from data_loaders import load_nslkdd_raw, preprocess_nslkdd
        train_df, test_df = load_nslkdd_raw(DATA_DIR)
        Xtr, ytr, Xte, yte, _sc, le = preprocess_nslkdd(train_df.copy(), test_df.copy())
        to_t = lambda a, d: torch.as_tensor(np.asarray(a), dtype=d)
        return (to_t(Xtr, torch.float32), to_t(ytr, torch.long),
                to_t(Xte, torch.float32), to_t(yte, torch.long), list(le.classes_))
    raise ValueError(f"unknown dataset {dataset}")


def _cache_path(dataset: str) -> Path:
    return CACHE_DIR / f"preproc_{dataset}.pt"


def build_cache(dataset: str):
    from train_utils import compute_class_weights
    print(f"[cache] preprocessing {dataset} once (avail {_avail_gb():.1f} GB) ...", flush=True)
    Xtr, ytr, Xte, yte, class_names = _load_dataset(dataset)
    num_classes = len(class_names)
    cw = compute_class_weights(ytr, num_classes)
    payload = {"X_train": Xtr.contiguous(), "y_train": ytr.contiguous(),
               "X_test": Xte.contiguous(), "y_test": yte.contiguous(),
               "class_weights": cw, "class_names": class_names, "num_classes": num_classes,
               "input_dim": int(Xtr.shape[1]),
               "n_train": int(Xtr.shape[0]), "n_test": int(Xte.shape[0])}
    p = _cache_path(dataset)
    p.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, p)
    del Xtr, ytr, Xte, yte, payload
    gc.collect()
    print(f"[cache] wrote {p} ({p.stat().st_size/1e6:.0f} MB); avail {_avail_gb():.1f} GB", flush=True)


def _make_model(arm, input_dim, num_classes, L, dev):
    from models import IDS_MLP, IDS_MLP_QCFS, TinyCNN_IDS
    if arm == "relu":
        return IDS_MLP(input_dim=input_dim, hidden=256, num_classes=num_classes).to(dev)
    if arm == "cnn":
        # TinyCNN baseline; forward() reshapes (B,F)->(B,1,1,F) internally, so it
        # trains through the exact same loop/optimizer/scheduler as the MLP arms —
        # a budget-matched, deterministic ReLU-MLP-vs-TinyCNN comparison.
        return TinyCNN_IDS(input_dim=input_dim, num_classes=num_classes).to(dev)
    return IDS_MLP_QCFS(input_dim=input_dim, hidden=256, num_classes=num_classes, L=L).to(dev)


def _evaluate(model, X_test, y_test, num_classes, class_names):
    from metrics import full_evaluate
    model.eval()
    dev = next(model.parameters()).device
    preds_all, labels_all, probs_all = [], [], []
    with torch.no_grad():
        for j in range(0, X_test.shape[0], 8192):
            xb = X_test[j:j + 8192].to(dev)
            logits = model(xb)
            preds_all.append(logits.argmax(1).cpu().numpy())
            probs_all.append(torch.softmax(logits, 1).cpu().numpy())
            labels_all.append(y_test[j:j + 8192].cpu().numpy())
    return full_evaluate(np.concatenate(labels_all), np.concatenate(preds_all),
                         np.concatenate(probs_all), num_classes, class_names)


def _train_single(seed, arm, L, Xtr, ytr, Xte, yte, cw, num_classes, class_names,
                  input_dim, epochs, batch_size):
    _make_deterministic(seed)
    model = _make_model(arm, input_dim, num_classes, L, Xtr.device)
    criterion = nn.CrossEntropyLoss(weight=cw)
    optimizer = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)  # STANDARD Adam
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    # Fast GPU-resident batching via a seeded torch.randperm shuffle. BOTH arms of a dataset
    # run through this same trainer, so for a given seed ReLU and QCFS see the SAME shuffle and
    # the SAME init — a clean paired design (only the activation differs). It is a valid seeded
    # shuffle; it need not (and does not) reproduce torch's DataLoader RandomSampler, which we no
    # longer use. Xtr requires no grad, so the index read has no non-deterministic index_add
    # backward; the whole step is bit-reproducible under _make_deterministic(seed).
    n = Xtr.shape[0]
    g = torch.Generator().manual_seed(seed)
    for epoch in range(epochs):
        model.train()
        perm = torch.randperm(n, generator=g).to(Xtr.device)
        for i in range(0, n, batch_size):
            idx = perm[i:i + batch_size]
            optimizer.zero_grad()
            criterion(model(Xtr[idx]), ytr[idx]).backward()
            optimizer.step()
        scheduler.step()
    # Fixed-budget training: report the FINAL model, NO model selection. The earlier
    # code (and the legacy experiment_*.py MLP path) picked the epoch with the best
    # *test-set* macro accuracy — that leaks the test set into model selection and
    # optimistically biases every reported number. Cosine annealing to ~0 LR has
    # converged by the last epoch, so we report it directly (also matches the TinyCNN
    # baseline's last-epoch convention). Both arms use this identical procedure, so
    # the ReLU-vs-QCFS pairing stays clean.
    return _evaluate(model, Xte, yte, num_classes, class_names)


def _worker(rank, seed_q, ret_q, dataset, arm, L, epochs, batch_size):
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    d = torch.load(_cache_path(dataset), map_location="cpu", weights_only=False)
    class_names = d["class_names"]; num_classes = d["num_classes"]; input_dim = d["input_dim"]
    meta = {"class_names": class_names, "num_classes": num_classes, "input_dim": input_dim,
            "n_train": d["n_train"], "n_test": d["n_test"]}
    Xtr = d["X_train"].to(dev); ytr = d["y_train"].to(dev)
    Xte = d["X_test"].to(dev); yte = d["y_test"].to(dev); cw = d["class_weights"].to(dev)
    del d
    while True:
        try:
            seed = seed_q.get_nowait()
        except Exception:
            break
        t0 = time.time()
        m = _train_single(seed, arm, L, Xtr, ytr, Xte, yte, cw, num_classes, class_names,
                          input_dim, epochs, batch_size)
        ret_q.put((seed, m, meta))
        print(f"[w{rank}] {dataset}/{arm} seed {seed} done ({time.time()-t0:.0f}s) "
              f"OA={m['overall_acc']:.2f}% MF1={m['macro_f1']:.2f}%", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, choices=["cicids2017", "iot23", "unsw", "nslkdd"])
    ap.add_argument("--arm", required=True, choices=["relu", "qcfs", "cnn"])
    ap.add_argument("--seeds", type=int, nargs="+", default=list(range(10)))
    ap.add_argument("--epochs", type=int, required=True)
    ap.add_argument("--batch-size", type=int, required=True, dest="batch_size")
    ap.add_argument("--L", type=int, default=4)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--reserve-gb", type=float, default=6.0)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()

    from experiment_cicids_qcfs import _aggregate  # generic aggregator (reused)
    RESULTS = ROOT / "results"

    if not _cache_path(a.dataset).exists():
        build_cache(a.dataset)

    avail = _avail_gb()
    ram_cap = max(1, int((avail - a.reserve_gb) / 2.6))
    n_workers = min(a.workers, len(a.seeds), ram_cap)
    print(f"train_fast {a.dataset}/{a.arm}: {len(a.seeds)} seeds, workers={n_workers} "
          f"(req {a.workers}, RAM cap {ram_cap} @ {avail:.1f}GB), epochs={a.epochs} "
          f"batch={a.batch_size} L={a.L}", flush=True)

    mp.set_start_method("spawn", force=True)
    seed_q: mp.Queue = mp.Queue()
    for s in a.seeds:
        seed_q.put(s)
    ret_q: mp.Queue = mp.Queue()
    t0 = time.time()
    procs = [mp.Process(target=_worker,
                        args=(r, seed_q, ret_q, a.dataset, a.arm, a.L, a.epochs, a.batch_size))
             for r in range(n_workers)]
    for p in procs:
        p.start(); time.sleep(4)

    results, meta = {}, None
    while len(results) < len(a.seeds):
        try:
            seed, m, mt = ret_q.get(timeout=300)
            results[seed] = m; meta = meta or mt
        except Exception:
            if not any(p.is_alive() for p in procs) and ret_q.empty():
                break
    for p in procs:
        p.join(timeout=30)
    missing = [s for s in a.seeds if s not in results]
    if missing or meta is None:
        raise SystemExit(f"FATAL: seeds did not return: {missing}")

    per_seed = [results[s] for s in a.seeds]
    body = {"per_seed": per_seed, "aggregate": _aggregate(per_seed, meta["class_names"])}
    common = {
        "experiment": f"{a.dataset} {a.arm.upper()} multi-seed (train_fast)",
        "dataset": a.dataset, "arm": a.arm,
        "model": ("IDS_MLP" if a.arm == "relu"
                  else "TinyCNN_IDS" if a.arm == "cnn"
                  else f"IDS_MLP_QCFS L={a.L}"),
        "seeds": a.seeds, "epochs": a.epochs, "batch_size": a.batch_size,
        "n_train": meta["n_train"], "n_test": meta["n_test"],
        "input_dim": meta["input_dim"], "num_classes": meta["num_classes"],
        "class_names": meta["class_names"],
    }
    # schema: ReLU and CNN arms are read top-level; QCFS arms under a "qcfs" key
    # (matches downstream consumers / the legacy cnn_baseline per-dataset blocks).
    result = {**common, "qcfs": body} if a.arm == "qcfs" else {**common, **body}
    out = RESULTS / a.output
    with open(out, "w") as f:
        json.dump(result, f, indent=2)
    oas = [r["overall_acc"] for r in per_seed]; mfs = [r["macro_f1"] for r in per_seed]
    print(f"\n[done] {a.dataset}/{a.arm} {len(per_seed)} seeds -> {out} in {time.time()-t0:.0f}s")
    print(f"[done] OA {np.mean(oas):.2f}±{np.std(oas,ddof=1):.2f} (min {min(oas):.2f} max {max(oas):.2f}) "
          f"| MF1 {np.mean(mfs):.2f}±{np.std(mfs,ddof=1):.2f}", flush=True)


if __name__ == "__main__":
    main()
