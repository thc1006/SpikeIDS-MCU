#!/usr/bin/env python3
"""RAM-safe, GPU-saturating driver for the CICIDS2017 QCFS multi-seed re-run.

Two problems this solves:
  * Speed: the matched-budget run (batch 512, 80 ep, 10 seeds) is launch-bound on a tiny
    MLP; one seed leaves the RTX 4060 Ti ~44% idle. Running a few seeds concurrently fills
    it (~1.4x; measured 865 -> ~1220 steps/s). torch.compile was SLOWER (0.67x, FloorSTE
    graph-breaks); a vmap ensemble was rejected as too risky for BatchNorm correctness.
  * RAM: this box also runs a single-node k8s dev cluster; free RAM is tight and swap runs
    near-full. Loading the full 2.83M-row CICIDS DataFrame *per worker* (pandas+scaler+split,
    ~4-6 GB each) once triggered a global OOM that took out the tmux session and k8s pods.
    Fix: preprocess ONCE in the parent, cache the ready float32 tensors (~0.8 GB), free the
    DataFrame, then let each worker mmap-load the light cache (~0.8 GB) instead of pandas.

Per-seed numerics are identical to a sequential run (same verified `_train_single`; the split
is fixed at random_state=42 so every seed/worker sees the same train/test data). A shared
queue balances seeds; results merge via the script's own `_aggregate`; top-level metadata is
filled exactly as the single-process script would, so run_v4_equivalence.py's pair_validity
sees matched budgets.

    .venv/bin/python scripts/run_cicids_qcfs_parallel.py --workers 2 --epochs 80 \
        --batch-size 512 --L 4 --output cicids_qcfs_multiseed.json
"""
from __future__ import annotations
import argparse, json, sys, time, gc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import torch
import torch.multiprocessing as mp

CACHE = Path("/tmp/claude-1000/-home-thc1006-dev-SpikeIDS-MCU/"
             "e287e8df-b593-44ae-b9b0-05620b77d9a7/scratchpad/cicids_preproc.pt")


def _avail_gb() -> float:
    """Available RAM in GB from /proc/meminfo (reclaimable cache counts as available)."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / (1024 * 1024)
    except Exception:
        pass
    return 999.0


def build_cache(grouped: bool):
    """Preprocess CICIDS once (pandas), save compact tensors, free the DataFrame."""
    from experiment_cicids2017 import load_cicids2017, preprocess_cicids
    from train_utils import compute_class_weights
    print(f"[cache] preprocessing once (avail {_avail_gb():.1f} GB) ...", flush=True)
    df, labels = load_cicids2017(grouped=grouped)
    X_train, y_train, X_test, y_test, _sc, label_enc, _f = preprocess_cicids(df, labels)
    class_names = list(label_enc.classes_)
    num_classes = len(class_names)
    cw = compute_class_weights(y_train, num_classes)
    payload = {
        "X_train": X_train.contiguous(), "y_train": y_train.contiguous(),
        "X_test": X_test.contiguous(), "y_test": y_test.contiguous(),
        "class_weights": cw, "class_names": class_names, "num_classes": num_classes,
        "input_dim": int(X_train.shape[1]),
        "n_train": int(X_train.shape[0]), "n_test": int(X_test.shape[0]),
    }
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, CACHE)
    del df, labels, X_train, y_train, X_test, y_test, payload
    gc.collect()
    print(f"[cache] wrote {CACHE} ({CACHE.stat().st_size/1e6:.0f} MB); "
          f"DataFrame freed (avail {_avail_gb():.1f} GB)", flush=True)


def _worker(rank, seed_q, ret_q, L, epochs, batch_size):
    from experiment_cicids_qcfs import _train_single, DEVICE
    d = torch.load(CACHE, map_location="cpu", weights_only=False)
    class_names = d["class_names"]; num_classes = d["num_classes"]; input_dim = d["input_dim"]
    meta = {"class_names": class_names, "num_classes": num_classes, "input_dim": input_dim,
            "n_train": d["n_train"], "n_test": d["n_test"]}
    X_train = d["X_train"].to(DEVICE); y_train = d["y_train"].to(DEVICE)
    X_test = d["X_test"].to(DEVICE); y_test = d["y_test"].to(DEVICE)
    cw = d["class_weights"].to(DEVICE)
    del d
    if DEVICE.type == "cuda":
        torch.backends.cudnn.benchmark = True
    while True:
        try:
            seed = seed_q.get_nowait()
        except Exception:
            break
        t0 = time.time()
        m = _train_single(seed, L, X_train, y_train, X_test, y_test,
                          cw, num_classes, class_names, input_dim, epochs, batch_size)
        ret_q.put((seed, m, meta))
        print(f"[w{rank}] seed {seed} done ({time.time()-t0:.0f}s) "
              f"OA={m['overall_acc']:.2f}% MF1={m['macro_f1']:.2f}%", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2,
                    help="concurrent seeds; keep low — each holds ~2.3 GB RAM. RAM-guarded.")
    ap.add_argument("--seeds", type=int, nargs="+", default=list(range(10)))
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--batch-size", type=int, default=512, dest="batch_size")
    ap.add_argument("--L", type=int, default=4)
    ap.add_argument("--grouped", action="store_true")
    ap.add_argument("--reserve-gb", type=float, default=6.0,
                    help="keep at least this much RAM free; cap workers to respect it")
    ap.add_argument("--build-only", action="store_true",
                    help="only preprocess+cache the tensors, then exit (heavy pandas load "
                         "isolated in its own process so its RAM is fully reclaimed)")
    ap.add_argument("--output", type=str, default="cicids_qcfs_multiseed.json")
    a = ap.parse_args()

    from experiment_cicids_qcfs import _aggregate, RESULTS_DIR

    if a.build_only:
        if CACHE.exists():
            print(f"[cache] already present: {CACHE} ({CACHE.stat().st_size/1e6:.0f} MB)")
        else:
            build_cache(a.grouped)
        return
    if not CACHE.exists():
        build_cache(a.grouped)

    # RAM guard: ~2.3 GB/worker; never exceed (avail - reserve)/2.3, and cap at seeds.
    avail = _avail_gb()
    ram_cap = max(1, int((avail - a.reserve_gb) / 2.3))
    n_workers = min(a.workers, len(a.seeds), ram_cap)
    print(f"CICIDS2017 QCFS parallel: {len(a.seeds)} seeds, workers={n_workers} "
          f"(requested {a.workers}, RAM cap {ram_cap} @ {avail:.1f} GB avail), "
          f"L={a.L} epochs={a.epochs} batch={a.batch_size}", flush=True)

    mp.set_start_method("spawn", force=True)
    seed_q: mp.Queue = mp.Queue()
    for s in a.seeds:
        seed_q.put(s)
    ret_q: mp.Queue = mp.Queue()

    t0 = time.time()
    procs = [mp.Process(target=_worker, args=(r, seed_q, ret_q, a.L, a.epochs, a.batch_size))
             for r in range(n_workers)]
    for p in procs:
        p.start()
        time.sleep(4)  # stagger the ~0.8 GB cache loads

    results, meta = {}, None
    while len(results) < len(a.seeds):
        try:
            seed, m, mt = ret_q.get(timeout=180)
            results[seed] = m
            meta = meta or mt
        except Exception:
            if not any(p.is_alive() for p in procs) and ret_q.empty():
                break
    for p in procs:
        p.join(timeout=30)

    missing = [s for s in a.seeds if s not in results]
    if missing or meta is None:
        raise SystemExit(f"FATAL: seeds did not return: {missing} (meta={'ok' if meta else 'MISSING'})")

    per_seed = [results[s] for s in a.seeds]
    result = {
        "experiment": f"CICIDS2017 QCFS L={a.L} multi-seed (parallel)",
        "dataset": "cicids2017", "model": f"IDS_MLP_QCFS L={a.L}",
        "label_mode": "7-class grouped" if a.grouped else "15-class",
        "seeds": a.seeds, "epochs": a.epochs, "batch_size": a.batch_size,
        "n_train": meta["n_train"], "n_test": meta["n_test"],
        "input_dim": meta["input_dim"], "num_classes": meta["num_classes"],
        "class_names": meta["class_names"],
        "qcfs": {"per_seed": per_seed, "aggregate": _aggregate(per_seed, meta["class_names"])},
    }
    out_path = RESULTS_DIR / a.output
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    oas = [r["overall_acc"] for r in per_seed]; mfs = [r["macro_f1"] for r in per_seed]
    print(f"\n[merged] {len(per_seed)} seeds -> {out_path} in {time.time()-t0:.0f}s", flush=True)
    print(f"[merged] OA {sum(oas)/len(oas):.2f}% (min {min(oas):.2f} max {max(oas):.2f}) | "
          f"MF1 {sum(mfs)/len(mfs):.2f}%", flush=True)


if __name__ == "__main__":
    main()
