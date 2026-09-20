"""Bounded-chunk, fit-only preparation for four declared benchmark tasks.

No legacy preprocessed loader is imported. Raw files are read in stable order;
labels determine a fixed split, then categorical vocabularies and StandardScaler
are fitted exclusively on fit rows. The processed cache is immutable and hashed.
The row-split IoT/CIC protocols are NOT held-out-device/capture evaluations.
"""
from __future__ import annotations
import argparse
import gc
import os
from pathlib import Path
import shutil
import tempfile
from typing import Iterator
import numpy as np
import pandas as pd
import sklearn
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from contracts import SCHEMA, ContractError, require, digest, sha256, write_json, load_json, file_lock, seal, check_seal

NSL_FEATURES = [
    "duration", "protocol_type", "service", "flag", "src_bytes", "dst_bytes", "land", "wrong_fragment",
    "urgent", "hot", "num_failed_logins", "logged_in", "num_compromised", "root_shell", "su_attempted",
    "num_root", "num_file_creations", "num_shells", "num_access_files", "num_outbound_cmds", "is_host_login",
    "is_guest_login", "count", "srv_count", "serror_rate", "srv_serror_rate", "rerror_rate", "srv_rerror_rate",
    "same_srv_rate", "diff_srv_rate", "srv_diff_host_rate", "dst_host_count", "dst_host_srv_count",
    "dst_host_same_srv_rate", "dst_host_diff_srv_rate", "dst_host_same_src_port_rate", "dst_host_srv_diff_host_rate",
    "dst_host_serror_rate", "dst_host_srv_serror_rate", "dst_host_rerror_rate", "dst_host_srv_rerror_rate"]
NSL_MAP = {"normal": "normal"}
for _group, _attacks in {
    "DoS": "back land neptune pod smurf teardrop mailbomb apache2 processtable udpstorm",
    "Probe": "ipsweep nmap portsweep satan mscan saint",
    "R2L": "ftp_write guess_passwd imap multihop phf spy warezclient warezmaster sendmail named snmpgetattack snmpguess xlock xsnoop worm",
    "U2R": "buffer_overflow loadmodule perl rootkit httptunnel ps sqlattack xterm",
}.items():
    NSL_MAP.update({x: _group for x in _attacks.split()})
IOT_NUM = ["id.orig_p", "id.resp_p", "duration", "orig_bytes", "resp_bytes", "missed_bytes",
           "orig_pkts", "orig_ip_bytes", "resp_pkts", "resp_ip_bytes"]
CATS = {"nslkdd": ["protocol_type", "service", "flag"], "unsw": ["proto", "service", "state"],
        "cicids2017": [], "iot23": ["proto", "service", "conn_state"]}
CLASSES = {
    "nslkdd": ["DoS", "Probe", "R2L", "U2R", "normal"],
    "unsw": ["Analysis", "Backdoor", "DoS", "Exploits", "Fuzzers", "Generic", "Normal", "Reconnaissance", "Shellcode", "Worms"],
    "cicids2017": sorted(["BENIGN", "Bot", "DDoS", "DoS GoldenEye", "DoS Hulk", "DoS Slowhttptest", "DoS slowloris",
                          "FTP-Patator", "Heartbleed", "Infiltration", "PortScan", "SSH-Patator",
                          "Web Attack - Brute Force", "Web Attack - Sql Injection", "Web Attack - XSS"]),
    "iot23": ["Benign", "C&C", "DDoS", "Okiru", "PortScan"],
}
IOT_MAP = {"Benign": "Benign", "DDoS": "DDoS", "Okiru": "Okiru", "Okiru-Attack": "Okiru",
           "PartOfAHorizontalPortScan": "PortScan", **{x: "C&C" for x in
             ("C&C", "C&C-HeartBeat", "Attack", "C&C-FileDownload", "C&C-Torii", "FileDownload",
              "C&C-HeartBeat-FileDownload", "C&C-Mirai")}}
CIC_FILES = ["Monday-WorkingHours.pcap_ISCX.csv", "Tuesday-WorkingHours.pcap_ISCX.csv",
             "Wednesday-workingHours.pcap_ISCX.csv", "Thursday-WorkingHours-Morning-WebAttacks.pcap_ISCX.csv",
             "Thursday-WorkingHours-Afternoon-Infilteration.pcap_ISCX.csv", "Friday-WorkingHours-Morning.pcap_ISCX.csv",
             "Friday-WorkingHours-Afternoon-PortScan.pcap_ISCX.csv", "Friday-WorkingHours-Afternoon-DDos.pcap_ISCX.csv"]
DROP_CIC = {"flow id", "source ip", "destination ip", "source port", "destination port", "timestamp"}
SPLITS = ("fit", "validation", "test")


def source_files(dataset: str, root: Path, spec_path: Path | None = None) -> list[tuple[Path, str]]:
    require(dataset in CLASSES, f"Unknown dataset {dataset}")
    if spec_path:
        spec = load_json(spec_path)
        require(spec.get("dataset") == dataset, "Raw-source manifest dataset mismatch")
        items = [(root / row["path"], row["role"]) for row in spec["files"]]
        require(bool(spec.get("provenance_note")), "Raw-source manifest needs a provenance_note")
    elif dataset == "nslkdd":
        items = [(root / "KDDTrain+.txt", "train"), (root / "KDDTest+.txt", "test")]
    elif dataset == "unsw":
        extension = ".parquet" if (root / "UNSW_NB15_training-set.parquet").exists() else ".csv"
        items = [(root / (f"UNSW_NB15_{role}ing-set" + extension), role) for role in ("train", "test")]
    else:
        directory = root / ("cicids2017" if dataset == "cicids2017" else "iot23")
        base = "cicids2017_combined" if dataset == "cicids2017" else "iot23_combined"
        if (directory / (base + ".parquet")).exists():
            items = [(directory / (base + ".parquet"), "combined")]
        elif (directory / (base + ".csv")).exists():
            items = [(directory / (base + ".csv"), "combined")]
        elif dataset == "cicids2017":
            items = [(directory / name, "combined") for name in CIC_FILES]
        else:
            raise FileNotFoundError(f"Missing raw IoT table under {directory}; automatic downloads are disabled")
    require(items and len({str(p.resolve()) for p, _ in items}) == len(items), "Duplicate/empty raw source set")
    roles = {r for _, r in items}
    require(roles == ({"train", "test"} if dataset in ("nslkdd", "unsw") else {"combined"}), "Invalid file roles")
    # A deterministic role order makes official-train rows a contiguous prefix.
    items.sort(key=lambda item: ({"train": 0, "test": 1, "combined": 0}[item[1]], item[0].as_posix()))
    for p, _ in items:
        require(p.is_file(), f"Required raw shard missing: {p}; no shards are silently skipped")
    return items


def _batches(items, dataset, chunksize) -> Iterator[tuple[pd.DataFrame, str]]:
    for path, role in items:
        if path.suffix.lower() == ".parquet":
            try:
                import pyarrow.parquet as pq
            except ImportError as exc:
                raise RuntimeError("Parquet input requires pyarrow. Install it in the selected uv environment.") from exc
            parquet = pq.ParquetFile(path)
            columns = IOT_NUM + CATS[dataset] + ["label"] if dataset == "iot23" else None
            iterator = (batch.to_pandas() for batch in parquet.iter_batches(batch_size=chunksize,
                         columns=columns, use_threads=False))
        else:
            iterator = pd.read_csv(path, header=None if dataset == "nslkdd" else "infer",
                                   chunksize=chunksize, dtype=str, keep_default_na=False,
                                   encoding="utf-8", encoding_errors="strict")
        for frame in iterator:
            if dataset == "nslkdd":
                require(frame.shape[1] == 43, f"NSL requires 43 columns, found {frame.shape[1]}")
                frame.columns = NSL_FEATURES + ["label", "difficulty"]
            else:
                frame.columns = [str(c).strip() for c in frame.columns]
            require(len(set(frame.columns)) == len(frame.columns), "Column collision after whitespace normalization")
            require(len(frame) > 0, "Unexpected empty raw chunk")
            yield frame, role


def _labels_and_features(frame, dataset):
    label_col = "attack_cat" if dataset == "unsw" else ("Label" if dataset == "cicids2017" and "Label" in frame else "label")
    require(label_col in frame, f"Missing label column {label_col}")
    require(not frame[label_col].isna().any(), "Null labels cannot be mapped to a class")
    if dataset == "cicids2017":
        require(not ("Label" in frame and "label" in frame), "Ambiguous duplicate label columns")
    raw = frame[label_col].astype(str).str.strip()
    if dataset == "nslkdd":
        labels, features = raw.map(NSL_MAP), NSL_FEATURES
    elif dataset == "iot23":
        labels, features = raw.map(IOT_MAP), IOT_NUM + CATS[dataset]
    elif dataset == "unsw":
        labels = raw.replace({"Backdoors": "Backdoor"})
        require("label" in frame and "id" in frame, "Expected official UNSW split with id and binary label columns")
        features = [c for c in frame if c not in ("attack_cat", "label", "id")]
        # The binary target is a redundant label, never a model input.
        binary = pd.to_numeric(frame["label"], errors="raise").to_numpy()
        require(np.array_equal(binary, (labels != "Normal").to_numpy().astype(int)), "UNSW label/attack_cat conflict")
    else:
        labels = raw.str.replace("\x96", "-", regex=False).str.replace("–", "-", regex=False)
        features = [c for c in frame if c not in ("Label", "label") and c.lower() not in DROP_CIC]
    require(labels.notna().all(), f"Unmapped labels: {sorted(raw[labels.isna()].unique().tolist())}")
    mapping = {name: i for i, name in enumerate(CLASSES[dataset])}
    y = labels.map(mapping)
    require(y.notna().all(), f"Labels outside fixed task: {sorted(labels[y.isna()].unique().tolist())}")
    require(features and len(features) <= 512 and all(c in frame for c in features),
            "Missing feature or unexpectedly wide schema (>512); inspect the raw data contract")
    require(all(c in features for c in CATS[dataset]), "Required categorical feature missing")
    # Reject pre-encoded categorical parquet columns: these have unknown fit provenance.
    for col in CATS[dataset]:
        require(not pd.api.types.is_numeric_dtype(frame[col].dtype),
                f"{col} is already numeric/encoded; raw category tokens with fit provenance are required")
        tokens = frame[col].dropna().astype(str)
        require(not (len(tokens) and tokens.str.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)").all()),
                f"{col} contains only numeric category codes; verify raw-token provenance")
    return y.to_numpy(dtype=np.int64), features


def _tokens(series: pd.Series) -> pd.Series:
    # Prefix non-null strings so an actual '<missing>' value cannot alias null.
    return series.astype(object).map(lambda v: "M:" if pd.isna(v) else "V:" + str(v))


def _encode(frame, features, dataset, categories, diagnostics):
    x = np.empty((len(frame), len(features)), dtype=np.float32)
    for j, col in enumerate(features):
        if col in CATS[dataset]:
            tokens = _tokens(frame[col])
            x[:, j] = tokens.map({v: i for i, v in enumerate(categories[col])}).fillna(-1).to_numpy(dtype=np.float32)
        else:
            values = frame[col]
            # Missing-value policy is fixed before seeing any outcome. Arbitrary text is not silently zeroed.
            cleaned = values.replace({"-": np.nan, "": np.nan, "NaN": np.nan, "nan": np.nan,
                                      "Infinity": np.inf, "-Infinity": -np.inf})
            numeric = pd.to_numeric(cleaned, errors="raise").to_numpy(dtype=np.float64)
            bad = ~np.isfinite(numeric)
            diagnostics[col] = diagnostics.get(col, 0) + int(bad.sum())
            if dataset == "nslkdd":
                require(not bad.any(), f"NSL non-finite/missing feature: {col}")
            else:
                numeric[bad] = 0.0
            # Keep measured negative values. Do not infer a data-cleaning policy from test minima.
            require((np.abs(numeric) <= np.finfo(np.float32).max).all(), f"FP32 overflow in {col}")
            x[:, j] = numeric
    return x


def _partition(y: np.ndarray, n_official_train: int | None, classes: int, val_fraction, split_seed, test_seed):
    all_indices = np.arange(len(y), dtype=np.int64)
    if n_official_train is None:
        tr, te = train_test_split(all_indices, test_size=.2, random_state=test_seed, stratify=y)
    else:
        tr, te = all_indices[:n_official_train], all_indices[n_official_train:]
    require(len(tr) > 0 and len(te) > 0, "Empty train/test split")
    support = np.bincount(y[tr], minlength=classes)
    require((support >= 2).all(), "Each training class needs >=2 rows for stratified validation")
    fit, val = train_test_split(tr, test_size=val_fraction, random_state=split_seed, stratify=y[tr])
    indices = {"fit": np.sort(fit), "validation": np.sort(val), "test": np.sort(te)}
    for key, idx in indices.items():
        require((np.bincount(y[idx], minlength=classes) > 0).all(), f"{key} lacks a declared class; change the declared task/split, not silently drop it")
    return indices, len(tr)


def open_cache(path: Path, verify: bool = True):
    path = Path(path)
    metadata = load_json(path / "metadata.json")
    check_seal(metadata)
    require(metadata["schema"] == SCHEMA, "Cache schema mismatch")
    require(metadata["data_fingerprint"] == digest({k:v for k,v in metadata.items()
             if k not in ("content_sha256","data_fingerprint")}), "Cache semantic fingerprint invalid")
    require(metadata["request_sha256"] == digest(metadata["raw_binding"]), "Cache request binding invalid")
    require(metadata["raw_binding"]["implementation_sha256"] == sha256(Path(__file__)) and
            metadata["raw_binding"]["contracts_sha256"] == sha256(Path(__file__).with_name("contracts.py")),
            "Preprocessor code changed; rebuild into a fresh cache directory")
    expected={f"{p}_{s}.npy" for s in SPLITS for p in ("x","y","ids")} | {"preprocessing.json"}
    require(set(metadata["files_sha256"]) == expected, "Incomplete/unexpected cache file inventory")
    if verify:
        for name, expected in metadata["files_sha256"].items():
            require(sha256(path / name) == expected, f"Cache file changed: {name}")
    arrays = {name: np.load(path / (name + ".npy"), mmap_mode="c", allow_pickle=False)
              for name in (f"{prefix}_{split}" for split in SPLITS for prefix in ("x", "y", "ids"))}
    for split in SPLITS:
        n, d = metadata["counts"][split], len(metadata["features"])
        require(arrays[f"x_{split}"].shape == (n, d) and arrays[f"x_{split}"].dtype == np.float32, "Cache feature shape/dtype invalid")
        require(arrays[f"y_{split}"].shape == arrays[f"ids_{split}"].shape == (n,), "Cache label/id shape invalid")
        require(arrays[f"y_{split}"].dtype == arrays[f"ids_{split}"].dtype == np.int64, "Cache labels/IDs must be int64")
    n=sum(metadata["counts"].values())
    require(metadata["n_official_train"] == metadata["counts"]["fit"]+metadata["counts"]["validation"],
            "Training/validation counts do not reconcile")
    seen=np.zeros(n,dtype=bool)
    for split in SPLITS:
        ids=arrays[f"ids_{split}"];y=arrays[f"y_{split}"]
        require(len(ids)>0 and ids[0]>=0 and ids[-1]<n and (np.diff(ids)>0).all(), "Invalid/duplicate/unsorted row IDs")
        require(not seen[ids].any(), "Row identity occurs in more than one split")
        seen[ids]=True
        require((y>=0).all() and (y<len(metadata["class_names"])).all(), "Label outside cached class schema")
    require(seen.all(), "Unassigned rows in cache")
    prep=load_json(path/"preprocessing.json")
    semantic={k:v for k,v in prep.items() if k not in ("nonfinite_replacements","unknown_categories")}
    require(metadata["preprocessor_sha256"]==digest(semantic), "Preprocessor semantic digest invalid")
    return metadata, arrays


def prepare(dataset: str, data_dir: Path, cache: Path, *, val_fraction=.2, split_seed=20260920,
            test_seed=42, chunksize=65536, source_spec: Path | None = None):
    require(0 < val_fraction < 1 and chunksize >= 2, "Invalid preparation parameters")
    require(type(split_seed) is int and type(test_seed) is int and 0 <= split_seed < 2**32 and 0 <= test_seed < 2**32, "Invalid split seeds")
    data_dir, cache = Path(data_dir).resolve(), Path(cache).resolve()
    items = source_files(dataset, data_dir, source_spec)
    binding = {"schema": SCHEMA, "dataset": dataset,
               "files": [{"path": p.relative_to(data_dir).as_posix(), "role": role, "sha256": sha256(p)} for p, role in items],
               "val_fraction": val_fraction, "split_seed": split_seed, "test_seed": test_seed,
               "chunksize": chunksize, "implementation_sha256": sha256(Path(__file__)),
               "contracts_sha256": sha256(Path(__file__).with_name("contracts.py")),
               "numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__,
               "source_spec": load_json(source_spec) if source_spec else None,
               "policy": "fit_only_ordinal_minus1; fit_only_incremental_standard_scaler; retain_constants; missing_nonNSL=0; keep_negative"}
    if any(p.suffix == ".parquet" for p, _ in items):
        import pyarrow
        binding["pyarrow"] = pyarrow.__version__
    request_hash = digest(binding)
    with file_lock(cache.with_name(cache.name + ".lock")):
        if cache.exists():
            meta, arrays = open_cache(cache)
            require(meta["request_sha256"] == request_hash, "Existing cache belongs to another raw input/protocol/software version")
            return meta, arrays
        cache.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=cache.name + ".tmp-", dir=cache.parent))
        try:
            n, official_n, features = 0, 0, None
            with (staging / "labels.raw").open("wb") as f:
                for frame, role in _batches(items, dataset, chunksize):
                    y_chunk, fcols = _labels_and_features(frame, dataset)
                    if features is None: features = fcols
                    require(features == fcols, "Raw feature schema/order differs between chunks/shards")
                    y_chunk.tofile(f); n += len(frame)
                    if role == "train": official_n += len(frame)
            require(n > 0, "Empty dataset")
            y_all = np.memmap(staging / "labels.raw", mode="r", dtype=np.int64, shape=(n,))
            indices, train_total = _partition(y_all, official_n if dataset in ("nslkdd", "unsw") else None,
                                             len(CLASSES[dataset]), val_fraction, split_seed, test_seed)
            assignment = np.empty(n, dtype=np.uint8)
            for code, split in enumerate(SPLITS): assignment[indices[split]] = code
            vocab = {c: set() for c in CATS[dataset]}
            offset = 0
            for frame, _ in _batches(items, dataset, chunksize):
                keep = assignment[offset:offset + len(frame)] == 0
                for col in vocab:
                    vocab[col].update(_tokens(frame.loc[keep, col]).tolist())
                    require(len(vocab[col]) <= 100000, f"Unexpected high-cardinality field {col}")
                offset += len(frame)
            categories = {c: sorted(v) for c, v in vocab.items()}
            scaler = StandardScaler()
            raw_x = np.lib.format.open_memmap(staging / "unscaled.npy", mode="w+", dtype=np.float32, shape=(n, len(features)))
            offset, diagnostics = 0, {}
            for frame, _ in _batches(items, dataset, chunksize):
                x = _encode(frame, features, dataset, categories, diagnostics)
                raw_x[offset:offset + len(x)] = x
                keep = assignment[offset:offset + len(x)] == 0
                if keep.any(): scaler.partial_fit(x[keep])
                offset += len(x)
            raw_x.flush()
            outputs, positions = {}, {s: 0 for s in SPLITS}
            for split in SPLITS:
                idx = indices[split]
                np.save(staging / f"ids_{split}.npy", idx, allow_pickle=False)
                np.save(staging / f"y_{split}.npy", np.asarray(y_all[idx]), allow_pickle=False)
                outputs[split] = np.lib.format.open_memmap(staging / f"x_{split}.npy", mode="w+", dtype=np.float32,
                                                          shape=(len(idx), len(features)))
            unknown_counts = {s: {c: 0 for c in CATS[dataset]} for s in SPLITS}
            for a in range(0, n, chunksize):
                b = min(n, a + chunksize)
                x = np.ascontiguousarray(scaler.transform(raw_x[a:b]), dtype=np.float32)
                require(np.isfinite(x).all(), "Non-finite scaled feature")
                for code, split in enumerate(SPLITS):
                    keep = assignment[a:b] == code
                    k = int(keep.sum()); start = positions[split]
                    outputs[split][start:start+k] = x[keep]
                    positions[split] += k
                    for c in CATS[dataset]:
                        unknown_counts[split][c] += int((raw_x[a:b, features.index(c)][keep] == -1).sum())
            for out in outputs.values(): out.flush()
            del outputs, out, raw_x, y_all
            gc.collect()
            (staging / "labels.raw").unlink(); (staging / "unscaled.npy").unlink()
            preprocessor = {"feature_columns": features, "categorical_columns": CATS[dataset],
                            "categories": categories, "mean": scaler.mean_.tolist(), "var": scaler.var_.tolist(),
                            "scale": scaler.scale_.tolist(), "n_fit": int(scaler.n_samples_seen_),
                            "class_names": CLASSES[dataset], "class_grouping": IOT_MAP if dataset == "iot23" else None,
                            "grouping_note": "C&C is the historical aggregate including Attack/FileDownload, not a pure C&C taxonomy" if dataset == "iot23" else None,
                            "nonfinite_replacements": diagnostics, "unknown_categories": unknown_counts}
            write_json(staging / "preprocessing.json", preprocessor)
            files = {p.name: sha256(p) for p in sorted(staging.glob("*")) if p.is_file()}
            metadata = {"schema": SCHEMA, "dataset": dataset, "request_sha256": request_hash,
                        "raw_binding": binding, "features": features, "class_names": CLASSES[dataset],
                        "counts": {s: len(indices[s]) for s in SPLITS}, "n_official_train": train_total,
                        "files_sha256": files,
                        "scope": "official file-role split" if dataset in ("nslkdd", "unsw") else "stratified row benchmark; NOT capture/device/time holdout",
                        "upstream_preprocessing_verified": False,
                        "duplicate_or_group_leakage_excluded": False,
                        "preprocessor_sha256": digest({k: v for k, v in preprocessor.items()
                                                       if k not in ("nonfinite_replacements", "unknown_categories")})}
            metadata["data_fingerprint"] = digest(metadata)
            write_json(staging / "metadata.json", seal(metadata))
            # Detect input modification across multi-pass preparation.
            for (path, _), record in zip(items, binding["files"]):
                require(sha256(path) == record["sha256"], f"Raw source changed during preparation: {path}")
            os.replace(staging, cache)
        finally:
            if staging.exists(): shutil.rmtree(staging)
    return open_cache(cache)


def main():
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--dataset", required=True, choices=tuple(CLASSES))
    p.add_argument("--data-dir", required=True, type=Path)
    p.add_argument("--cache", required=True, type=Path)
    p.add_argument("--source-spec", type=Path)
    p.add_argument("--chunksize", type=int, default=65536)
    a = p.parse_args()
    meta, _ = prepare(a.dataset, a.data_dir, a.cache, source_spec=a.source_spec, chunksize=a.chunksize)
    print(meta["data_fingerprint"], meta["counts"], len(meta["features"]))

if __name__ == "__main__": main()
