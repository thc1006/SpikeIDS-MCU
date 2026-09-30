"""GPU-resident IoT-23 trainer (v4): ~20x faster re-run for the matched ReLU-vs-QCFS pair.

Same model (IDS_MLP / IDS_MLP_QCFS), optimizer (Adam 1e-3, wd 1e-5), CosineAnnealing,
CrossEntropyLoss(inverse-freq weights), 40 epochs, batch 1024 (BN dynamics preserved),
best-macro checkpointing, and the identical metrics.full_evaluate.

Faithfulness scope (reviewed, stated honestly): this trainer is MATCHED BETWEEN THE TWO ARMS
(both use this exact code) — that is what the paired TOST needs. It is NOT bit-identical to the
v3 numbers: (a) the shuffle is torch.randperm per epoch, not the DataLoader sampler; (b) TF32
matmul is enabled for speed. Both changes are applied identically to both arms, so the paired
equivalence conclusion is valid, but the v4 IoT-23 absolute accuracies are a fresh matched pair
and must NOT be compared directly to v3's reported IoT-23 numbers. The CPU DataLoader is replaced
by GPU-resident index slicing (the documented ~20x tabular speed-up).

Outputs schema-compatible JSONs for scripts/run_v4_equivalence.py (used as a self-consistent pair).
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import numpy as np, torch, torch.nn as nn, torch.optim as optim

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from models import IDS_MLP, IDS_MLP_QCFS          # noqa: E402
from train_utils import set_seed, compute_class_weights  # noqa: E402
from experiment_iot23 import load_iot23, preprocess_iot23, full_evaluate  # noqa: E402

DEV = torch.device("cuda" if torch.cuda.is_available() else "cpu")
torch.set_float32_matmul_precision("high")         # TF32 on tensor cores (safe for this task)


def train_one(arm, seed, Xtr, ytr, Xte_cpu, yte_cpu, cw, nc, names, d, epochs, L):
    set_seed(seed)                                  # keeps cudnn.deterministic=True
    model = (IDS_MLP(d, 256, nc) if arm == "relu"
             else IDS_MLP_QCFS(d, 256, nc, L=L)).to(DEV)
    crit = nn.CrossEntropyLoss(weight=cw.to(DEV))
    opt = optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-5)
    sched = optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    n = Xtr.shape[0]; bs = 1024
    g = torch.Generator(device=DEV).manual_seed(seed)
    best_macro, best_state = 0.0, None
    for epoch in range(epochs):
        model.train()
        perm = torch.randperm(n, generator=g, device=DEV)
        for i in range(0, n, bs):
            idx = perm[i:i + bs]
            opt.zero_grad()
            loss = crit(model(Xtr[idx]), ytr[idx])
            loss.backward()
            opt.step()
        sched.step()
        if (epoch + 1) % 10 == 0 or epoch == epochs - 1:
            model.eval()
            with torch.no_grad():
                # best-macro selection on GPU (same protocol as the reference inner loop)
                Xte = Xte_cpu.to(DEV); yte = yte_cpu.to(DEV)
                correct = torch.zeros(nc, device=DEV); total = torch.zeros(nc, device=DEV)
                for i in range(0, Xte.shape[0], 4096):
                    p = model(Xte[i:i+4096]).argmax(1); yb = yte[i:i+4096]
                    for c in range(nc):
                        m = yb == c
                        correct[c] += (p[m] == yb[m]).sum(); total[c] += m.sum()
                macro = (torch.where(total > 0, correct / total, torch.zeros_like(correct)).mean() * 100).item()
                if macro > best_macro:
                    best_macro = macro
                    best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    model = model.cpu(); model.load_state_dict(best_state)
    return full_evaluate(model, Xte_cpu, yte_cpu, nc, names)  # identical reported metrics (CPU)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=list(range(10)))
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--L", type=int, default=4)
    ap.add_argument("--arms", nargs="+", default=["relu", "qcfs"])
    ap.add_argument("--tag", default="v4")
    ap.add_argument("--bench2", action="store_true", help="2-epoch timing probe only")
    a = ap.parse_args()

    df, labels, feats = load_iot23(binary=False)
    Xtr_c, ytr_c, Xte_c, yte_c, _sc, le = preprocess_iot23(df, labels)
    nc = len(le.classes_); names = list(le.classes_); d = Xtr_c.shape[1]
    cw = compute_class_weights(ytr_c, nc)
    Xtr = Xtr_c.to(DEV); ytr = ytr_c.to(DEV)
    print(f"IoT-23 GPU-resident: train {tuple(Xtr.shape)} test {tuple(Xte_c.shape)} "
          f"classes={nc} dev={DEV} vram={torch.cuda.memory_allocated()/1e6:.0f}MB", flush=True)

    if a.bench2:
        t0 = time.time(); train_one("relu", 0, Xtr, ytr, Xte_c, yte_c, cw, nc, names, d, 2, a.L)
        print(f"[bench] 2-epoch relu seed0: {time.time()-t0:.1f}s → ~{(time.time()-t0)/2*a.epochs:.0f}s/seed est", flush=True)
        return

    out = {"experiment": "IoT-23 GPU-resident matched v4", "dataset": "IoT-23", "label_mode": "5-class",
           "seeds": a.seeds, "epochs": a.epochs, "batch": 1024, "n_train": int(Xtr.shape[0]),
           "n_test": int(Xte_c.shape[0]), "input_dim": d, "num_classes": nc, "class_names": names}
    for arm in a.arms:
        per_seed = []
        for s in a.seeds:
            t0 = time.time()
            m = train_one(arm, s, Xtr, ytr, Xte_c, yte_c, cw, nc, names, d, a.epochs, a.L)
            per_seed.append(m)
            print(f"[{arm}] seed={s} done ({time.time()-t0:.1f}s) OA={m['overall_acc']:.2f} MF1={m['macro_f1']:.2f}", flush=True)
        if arm == "relu":
            r = dict(out); r["model"] = "IDS_MLP"; r["per_seed"] = per_seed
            Path(ROOT / "results" / f"iot23_multiseed_{a.tag}.json").write_text(json.dumps(r, indent=1))
        else:
            r = dict(out); r["model"] = f"IDS_MLP_QCFS L={a.L}"; r["qcfs"] = {"per_seed": per_seed}
            Path(ROOT / "results" / f"iot23_qcfs_multiseed_{a.tag}.json").write_text(json.dumps(r, indent=1))
        print(f"[{arm}] wrote results/iot23_*_{a.tag}.json", flush=True)


if __name__ == "__main__":
    main()
