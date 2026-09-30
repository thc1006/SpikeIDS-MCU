"""Explicit, evidence-preserving NSL compatibility view; never trusts old aggregates."""
from __future__ import annotations
import argparse
from pathlib import Path
from contracts import *
from evidence import verified_suite
from metrics import aggregate


def assemble(run_dir):
    plan,results=verified_suite(run_dir)
    a,b=results[("nslkdd","relu")],results[("nslkdd","qcfs")];same_pairing(a,b)
    obj={"schema":SCHEMA,"dataset":"nslkdd","seeds":plan["seeds"],"n_train":a["counts"]["fit"],
         "n_validation":a["counts"]["validation"],"n_test":a["counts"]["test"],
         "official_train_raw_rows":a["official_train_raw_rows"],
         "n_train_validation_patterns":a["n_train_validation_patterns"],
         "class_names":a["class_names"],
         "epochs":a["protocol"]["epochs"],"batch_size":a["protocol"]["batch_size"],
         "data_fingerprint":a["data_fingerprint"],"pairing_contract":a["pairing_contract"],
         "source_plan_sha256":plan["content_sha256"],"source_results":{"relu":a["scientific_digest"],"qcfs":b["scientific_digest"]},
         "legacy_warning":"Format view only; not permission to merge with old results; qcfs_L4 is shifted_v1 ANN, not a claimed T=1 SNN",
         "relu":{"per_seed":a["per_seed"],"aggregate":aggregate(a["per_seed"],a["class_names"])},
         "qcfs_L4":{"per_seed":b["per_seed"],"aggregate":aggregate(b["per_seed"],b["class_names"])}}
    write_json(Path(run_dir)/"legacy"/"multiseed_20.json",seal(obj));return obj


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False);p.add_argument("--run-dir",required=True,type=Path)
    assemble(p.parse_args().run_dir)
if __name__=="__main__":main()
