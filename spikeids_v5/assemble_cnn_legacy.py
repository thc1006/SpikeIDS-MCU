"""TinyCNN compatibility view, checked by sample/preprocessing identity and actual seed IDs."""
from __future__ import annotations
import argparse
from pathlib import Path
from contracts import *
from evidence import verified_suite
from metrics import aggregate


def assemble(run_dir):
    plan,results=verified_suite(run_dir)
    obj={"schema":SCHEMA,"seeds":plan["seeds"],"source_plan_sha256":plan["content_sha256"],
         "budget_scope":"matched optimizer epochs/batches, NOT matched FLOPs, capacity, tuning effort, or energy"}
    for dataset in ("nslkdd","unsw","cicids2017"):
        cnn,relu=results[(dataset,"cnn")],results[(dataset,"relu")];same_pairing(cnn,relu)
        obj[dataset]={"per_seed":cnn["per_seed"],"aggregate":aggregate(cnn["per_seed"],cnn["class_names"]),
                      "n_train":cnn["counts"]["fit"],"n_validation":cnn["counts"]["validation"],
                      "n_test":cnn["counts"]["test"],"epochs":cnn["protocol"]["epochs"],
                      "model":"TinyCNN_IDS","data_fingerprint":cnn["data_fingerprint"],
                      "pairing_contract":cnn["pairing_contract"],"scientific_digest":cnn["scientific_digest"]}
    write_json(Path(run_dir)/"legacy"/"cnn_baseline_merged.json",seal(obj))
    write_json(Path(run_dir)/"legacy"/"cnn_baseline_cicids.json",seal({k:v for k,v in obj.items() if k not in ("nslkdd","unsw")}))
    return obj


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False);p.add_argument("--run-dir",required=True,type=Path)
    assemble(p.parse_args().run_dir)
if __name__=="__main__":main()
