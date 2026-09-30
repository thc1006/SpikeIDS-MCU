"""Read current run artifacts and recompute metrics before consuming claims."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from contracts import *
from metrics import full_evaluate, aggregate


def read_plan(run_dir: Path) -> dict:
    plan = load_json(Path(run_dir)/"plan.json"); check_seal(plan)
    require(plan["schema"] == SCHEMA, "Unsupported plan schema")
    require(plan["sources"] == sources(), "Code changed after the protocol was frozen; create a new run directory")
    ids = [j["id"] for j in plan["jobs"]]
    expected={d+"_"+a for d in DATASETS for a in ARMS[d]}
    require(len(ids)==len(set(ids)) and set(ids)==expected,"The full 11-job suite must be declared")
    for j in plan["jobs"]:
        require(j["id"]==j["dataset"]+"_"+j["model"],"Job ID mismatch")
    require(plan["difference_family"]==[f"{d}:relu_vs_{a}:{m}" for d in DATASETS for a in ARMS[d] if a!="relu" for m in METRICS],"Difference family changed")
    require(plan["equivalence_family"]==[f"{d}:{m}" for d in DATASETS for m in METRICS],"Equivalence family changed")
    return plan


def load_fit(path: Path, job: dict | None = None, plan: dict | None = None) -> dict:
    record=load_json(path); check_seal(record)
    require(record["schema"]==SCHEMA and record["status"] in ("fit_complete","evaluating","complete"), "Incomplete/legacy training record")
    manifest=load_json(Path(path).with_suffix("")/"manifest.json");check_seal(manifest)
    binding=manifest["binding"]
    require(manifest["fingerprint"]==record["fingerprint"]==digest(binding),"Run fingerprint/binding mismatch")
    require(binding["protocol"]==record["protocol"] and binding["environment"]==record["environment"] and
            binding["data_fingerprint"]==record["data_fingerprint"],"Run JSON does not match its immutable binding")
    require(binding["sources"]==sources(),"Current source differs from the source used for training")
    if plan is not None:require(binding["sources"]==plan["sources"],"Training source differs from frozen plan")
    require(record["dataset"]==record["protocol"]["dataset"] and record["kind"]==record["protocol"]["model"],
            "Run identity differs from protocol")
    rows=seed_rows(record["fit_runs"],record["protocol"]["seeds"])
    for row in rows.values():
        stable={k:v for k,v in row.items() if k not in ("training_reproducibility_sha256","elapsed_seconds","fit_complete")}
        require(digest(stable)==row["training_reproducibility_sha256"],"Training history/state digest invalid")
        require([h["epoch"] for h in row["history"]]==list(range(1,record["protocol"]["epochs"]+1)),"Epoch history incomplete")
        candidates=[h for h in row["history"] if h["validation_macro_recall_pct"] is not None]
        require(candidates, "No validation checkpoint exists")
        best=max(candidates,key=lambda h:h["validation_macro_recall_pct"])
        require(row["best_epoch"]==best["epoch"] and
                row["best_validation_macro_recall_pct"]==best["validation_macro_recall_pct"],
                "Selected epoch does not match earliest maximum validation score")
    require(all(r.get("fit_complete") for r in rows.values()), "An individual fit is incomplete")
    require(record["training_digest"]==digest([rows[s]["training_reproducibility_sha256"] for s in sorted(rows)]), "Training digest mismatch")
    if plan is not None:
        require(record["environment"]==plan["environment"], "Run environment does not match frozen plan")
        require(record["protocol"]["seeds"]==plan["seeds"], "Run seed set differs from plan")
    if job is not None:
        require(record["dataset"]==job["dataset"] and record["kind"]==job["model"], "Wrong job output")
        for key,value in job["hyperparameters"].items():
            require(record["protocol"].get(key)==value, f"Frozen job parameter changed: {key}")
        require(record["data_fingerprint"]==job["data_fingerprint"], "Job used a different prepared dataset")
    # Independently bind every selected/final state, optimizer and RNG payload.
    from experiment_all import load_checkpoint, tree_digest
    for seed,row in rows.items():
        checkpoint=Path(path).with_suffix("")/"runs"/f"{record['kind']}_seed_{seed}.pt"
        state=load_checkpoint(checkpoint,record["fingerprint"])
        require(state["epoch"]==record["protocol"]["epochs"] and state["seed"]==seed and state["kind"]==record["kind"], "Checkpoint identity/budget mismatch")
        require(state["fit_result"]==row, "JSON fit result differs from checkpoint")
        for key,hash_key in (("best_model","best_state_sha256"),("model","final_state_sha256"),
                             ("optimizer","optimizer_state_sha256"),("scheduler","scheduler_state_sha256"),("rng","rng_state_sha256")):
            require(tree_digest(state[key])==row[hash_key], f"Checkpoint {key} does not match recorded content")
    return record


def load_result(path: Path, job: dict | None = None, plan: dict | None = None) -> dict:
    r=load_fit(path,job,plan)
    require(r["status"]=="complete", f"Test evaluation incomplete: {path}")
    from data_loaders import open_cache
    meta,prepared=open_cache(Path(r["cache_path"]))
    require(meta["data_fingerprint"]==r["data_fingerprint"] and meta["class_names"]==r["class_names"],"Prepared-data identity differs")
    require(r["counts"]==meta["counts"],"Result counts differ from prepared partitions")
    pairing={"ids_sha256":{s:meta["files_sha256"][f"ids_{s}.npy"] for s in ("fit","validation","test")},
             "preprocessor_sha256":meta["preprocessor_sha256"],"raw_binding_sha256":digest(meta["raw_binding"])}
    require(r["pairing_contract"]==pairing,"Pairing contract differs from the actual prepared rows")
    rows=seed_rows(r["per_seed"],r["protocol"]["seeds"])
    fit=seed_rows(r["fit_runs"],r["protocol"]["seeds"])
    from experiment_all import array_sha256
    for seed,row in rows.items():
        require(row["kind"]==r["kind"] and row["test_evaluated"], "Wrong prediction arm")
        require(row["best_state_sha256"]==fit[seed]["best_state_sha256"] and row["best_epoch"]==fit[seed]["best_epoch"], "Selected checkpoint mismatch")
        require(row["batch_order_sha256"]==digest([h["order_sha256"] for h in fit[seed]["history"]]),
                "Reported batch order differs from the training history")
        artifact=Path(path).with_suffix("")/"runs"/row["artifact"]["filename"]
        require(artifact.name==row["artifact"]["filename"], "Artifact filename must be local (no traversal)")
        require(sha256(artifact)==row["artifact"]["sha256"], "Prediction artifact changed")
        with np.load(artifact,allow_pickle=False) as a:
            require(set(a.files)=={"logits","probabilities","y_true","y_pred"}, "Unexpected prediction fields")
            logits,prob,y,pred=(a[k] for k in ("logits","probabilities","y_true","y_pred"))
            require(np.array_equal(y,prepared["y_test"]),"Predictions used labels/order different from the frozen test partition")
            require(np.isfinite(logits).all() and np.array_equal(logits.argmax(1),pred), "Invalid logit/prediction correspondence")
            # Softmax numerical tolerance is explicit; this is a sanity check, not a substitute for hashes.
            exp=np.exp(logits.astype(np.float64)-logits.max(1,keepdims=True))
            require(np.allclose(exp/exp.sum(1,keepdims=True),prob,atol=1e-6,rtol=1e-5), "Stored probabilities do not match logits")
            calculated=full_evaluate(y,pred,prob,len(r["class_names"]),r["class_names"])
            for k,value in calculated.items(): require(row.get(k)==value, f"Metric differs from independent artifact recomputation: {k}")
            for key,value in (("logits_sha256",logits),("probabilities_sha256",prob),("predictions_sha256",pred),("labels_sha256",y)):
                require(row["reproducibility"][key]==array_sha256(value),f"Semantic {key} mismatch")
            require(row["reproducibility"]["metrics_sha256"]==digest(calculated),"Metric digest mismatch")
        require(row["reproducibility"]["training_sha256"]==fit[seed]["training_reproducibility_sha256"], "Prediction linked to another training run")
    ordered=[rows[s] for s in sorted(rows)]
    require(r["aggregate"]==aggregate(ordered,r["class_names"]), "Stale/incorrect aggregate")
    require(r["scientific_digest"]==digest({"training":r["training_digest"],"predictions":[row["reproducibility"] for row in ordered]}), "Scientific digest mismatch")
    return r


def verified_suite(run_dir: Path):
    run_dir=Path(run_dir); plan=read_plan(run_dir)
    report=load_json(run_dir/"verification_evaluate.json"); check_seal(report)
    require(report["plan_sha256"]==plan["content_sha256"] and report["passed"] is True, "Missing/pending/failed full repeat verification")
    results={}
    for job in plan["jobs"]:
        r=load_result(run_dir/"results"/f"{job['id']}.json",job,plan)
        require(report["jobs"][job["id"]]==r["scientific_digest"],"Verification is stale")
        replica=load_result(run_dir/"replicas"/f"{job['id']}.json",job,plan)
        require(replica["fingerprint"]==r["fingerprint"] and replica["scientific_digest"]==r["scientific_digest"],
                "Independent replica artifacts no longer match; verification is stale")
        results[(job["dataset"],job["model"])]=r
    return plan,results
