"""
Tree-based baseline comparison for SNN-IDS paper.
Trains Random Forest and XGBoost on NSL-KDD and UNSW-NB15,
exports to ONNX for ST Cloud CPU-only benchmark comparison.

Purpose: Compare MLP (NPU-accelerated) vs tree models (CPU-only)
to demonstrate NPU advantage for neural network architectures.

Usage:
    python src/tree_baseline.py
"""

import json
import time
import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (confusion_matrix, precision_recall_fscore_support,
                             accuracy_score)
import xgboost as xgb
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
MODEL_DIR = BASE_DIR / "models"
RESULTS_DIR = BASE_DIR / "results"
MODEL_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

# ── NSL-KDD loading ──

COL_NAMES = [
    "duration", "protocol_type", "service", "flag", "src_bytes", "dst_bytes",
    "land", "wrong_fragment", "urgent", "hot", "num_failed_logins", "logged_in",
    "num_compromised", "root_shell", "su_attempted", "num_root",
    "num_file_creations", "num_shells", "num_access_files", "num_outbound_cmds",
    "is_host_login", "is_guest_login", "count", "srv_count", "serror_rate",
    "srv_serror_rate", "rerror_rate", "srv_rerror_rate", "same_srv_rate",
    "diff_srv_rate", "srv_diff_host_rate", "dst_host_count", "dst_host_srv_count",
    "dst_host_same_srv_rate", "dst_host_diff_srv_rate",
    "dst_host_same_src_port_rate", "dst_host_srv_diff_host_rate",
    "dst_host_serror_rate", "dst_host_srv_serror_rate", "dst_host_rerror_rate",
    "dst_host_srv_rerror_rate", "label", "difficulty"
]

ATTACK_MAP = {
    'normal': 'normal',
    'back': 'DoS', 'land': 'DoS', 'neptune': 'DoS', 'pod': 'DoS',
    'smurf': 'DoS', 'teardrop': 'DoS', 'mailbomb': 'DoS', 'apache2': 'DoS',
    'processtable': 'DoS', 'udpstorm': 'DoS',
    'ipsweep': 'Probe', 'nmap': 'Probe', 'portsweep': 'Probe',
    'satan': 'Probe', 'mscan': 'Probe', 'saint': 'Probe',
    'ftp_write': 'R2L', 'guess_passwd': 'R2L', 'imap': 'R2L',
    'multihop': 'R2L', 'phf': 'R2L', 'spy': 'R2L', 'warezclient': 'R2L',
    'warezmaster': 'R2L', 'sendmail': 'R2L', 'named': 'R2L',
    'snmpgetattack': 'R2L', 'snmpguess': 'R2L', 'xlock': 'R2L',
    'xsnoop': 'R2L', 'worm': 'R2L',
    'buffer_overflow': 'U2R', 'loadmodule': 'U2R', 'perl': 'U2R',
    'rootkit': 'U2R', 'httptunnel': 'U2R', 'ps': 'U2R',
    'sqlattack': 'U2R', 'xterm': 'U2R',
}


def load_nslkdd():
    train_df = pd.read_csv(DATA_DIR / "KDDTrain+.txt", header=None, names=COL_NAMES)
    test_df = pd.read_csv(DATA_DIR / "KDDTest+.txt", header=None, names=COL_NAMES)
    for df in [train_df, test_df]:
        df.drop(columns=["difficulty"], inplace=True)
        df["label"] = df["label"].map(ATTACK_MAP).fillna("unknown")
        df.drop(df[df["label"] == "unknown"].index, inplace=True)

    cat_cols = ["protocol_type", "service", "flag"]
    for col in cat_cols:
        le = LabelEncoder()
        combined = pd.concat([train_df[col], test_df[col]])
        le.fit(combined)
        train_df[col] = le.transform(train_df[col])
        test_df[col] = le.transform(test_df[col])

    label_enc = LabelEncoder()
    label_enc.fit(["DoS", "Probe", "R2L", "U2R", "normal"])
    y_train = label_enc.transform(train_df["label"])
    y_test = label_enc.transform(test_df["label"])

    X_train = train_df.drop(columns=["label"]).values.astype(np.float32)
    X_test = test_df.drop(columns=["label"]).values.astype(np.float32)

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)

    return X_train, y_train, X_test, y_test, label_enc, list(train_df.drop(columns=["label"]).columns)


def load_unsw_nb15():
    train_df = pd.read_parquet(DATA_DIR / "UNSW_NB15_training-set.parquet")
    test_df = pd.read_parquet(DATA_DIR / "UNSW_NB15_testing-set.parquet")

    for col in ["id"]:
        if col in train_df.columns:
            train_df = train_df.drop(columns=[col])
            test_df = test_df.drop(columns=[col])

    train_labels = train_df["attack_cat"].astype(str).str.strip()
    test_labels = test_df["attack_cat"].astype(str).str.strip()
    train_df = train_df.drop(columns=["attack_cat", "label"])
    test_df = test_df.drop(columns=["attack_cat", "label"])

    cat_cols = train_df.select_dtypes(include=["object", "category"]).columns.tolist()
    for col in cat_cols:
        le = LabelEncoder()
        combined = pd.concat([train_df[col].astype(str), test_df[col].astype(str)])
        le.fit(combined)
        train_df[col] = le.transform(train_df[col].astype(str))
        test_df[col] = le.transform(test_df[col].astype(str))

    all_classes = sorted(set(train_labels.unique()) | set(test_labels.unique()))
    label_enc = LabelEncoder()
    label_enc.fit(all_classes)
    y_train = label_enc.transform(train_labels)
    y_test = label_enc.transform(test_labels)

    X_train = train_df.values.astype(np.float32)
    X_test = test_df.values.astype(np.float32)
    X_train = np.nan_to_num(X_train, nan=0.0, posinf=1e6, neginf=-1e6)
    X_test = np.nan_to_num(X_test, nan=0.0, posinf=1e6, neginf=-1e6)

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)

    return X_train, y_train, X_test, y_test, label_enc, list(train_df.columns)


def evaluate_model(y_true, y_pred, class_names, num_classes):
    """Compute full evaluation metrics."""
    cm = confusion_matrix(y_true, y_pred, labels=list(range(num_classes)))
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=list(range(num_classes)), zero_division=0
    )
    per_class_acc = cm.diagonal() / np.maximum(cm.sum(axis=1), 1)
    overall_acc = accuracy_score(y_true, y_pred) * 100
    macro_acc = per_class_acc.mean() * 100

    w_precision, w_recall, w_f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average='weighted', zero_division=0
    )

    return {
        "overall_acc": float(overall_acc),
        "macro_acc": float(macro_acc),
        "macro_precision": float(np.mean(precision) * 100),
        "macro_recall": float(np.mean(recall) * 100),
        "macro_f1": float(np.mean(f1) * 100),
        "weighted_f1": float(w_f1 * 100),
        "per_class": {
            class_names[i]: {
                "accuracy": float(per_class_acc[i] * 100),
                "precision": float(precision[i] * 100),
                "recall": float(recall[i] * 100),
                "f1": float(f1[i] * 100),
                "support": int(support[i]),
            }
            for i in range(num_classes)
        },
        "confusion_matrix": cm.tolist(),
    }


def train_and_export(dataset_name, X_train, y_train, X_test, y_test,
                     label_enc, feature_names, n_seeds=10):
    """Train RF and XGBoost, evaluate, export ONNX."""
    num_classes = len(label_enc.classes_)
    class_names = list(label_enc.classes_)
    input_dim = X_train.shape[1]

    results = {
        "dataset": dataset_name,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "input_dim": input_dim,
        "num_classes": num_classes,
        "class_names": class_names,
    }

    # ── Random Forest ──
    print(f"\n  [RF] Training Random Forest (n_seeds={n_seeds})...")
    rf_seed_results = []
    for seed in range(n_seeds):
        t0 = time.time()
        rf = RandomForestClassifier(
            n_estimators=100,
            max_depth=20,
            random_state=seed,
            class_weight="balanced",
            n_jobs=-1,
        )
        rf.fit(X_train, y_train)
        y_pred = rf.predict(X_test)
        metrics = evaluate_model(y_test, y_pred, class_names, num_classes)
        elapsed = time.time() - t0
        rf_seed_results.append(metrics)
        print(f"    Seed {seed}: OA={metrics['overall_acc']:.2f}% "
              f"MF1={metrics['macro_f1']:.2f}% ({elapsed:.1f}s)")

    # Export best RF to ONNX (seed 0)
    rf_best = RandomForestClassifier(
        n_estimators=100, max_depth=20, random_state=0,
        class_weight="balanced", n_jobs=-1
    )
    rf_best.fit(X_train, y_train)
    onnx_suffix = "nslkdd" if "NSL" in dataset_name else "unsw"
    try:
        initial_type = [("float_input", FloatTensorType([None, input_dim]))]
        rf_onnx = convert_sklearn(rf_best, initial_types=initial_type,
                                  target_opset=13)
        rf_onnx_path = MODEL_DIR / f"rf_{onnx_suffix}.onnx"
        with open(rf_onnx_path, "wb") as f:
            f.write(rf_onnx.SerializeToString())
        print(f"    ONNX exported: {rf_onnx_path} ({rf_onnx_path.stat().st_size / 1024:.0f} KB)")
    except Exception as e:
        print(f"    ONNX export failed: {e}")

    # Aggregate RF
    rf_agg = _aggregate(rf_seed_results, class_names)
    results["random_forest"] = {
        "per_seed": rf_seed_results,
        "aggregate": rf_agg,
        "model_params": {"n_estimators": 100, "max_depth": 20, "class_weight": "balanced"},
    }

    # ── XGBoost ──
    print(f"\n  [XGB] Training XGBoost (n_seeds={n_seeds})...")
    xgb_seed_results = []
    for seed in range(n_seeds):
        t0 = time.time()
        # Compute sample weights for balanced classes
        class_counts = np.bincount(y_train, minlength=num_classes).astype(np.float32)
        class_counts = np.maximum(class_counts, 1.0)
        sample_weights = 1.0 / class_counts[y_train]
        sample_weights = sample_weights / sample_weights.sum() * len(y_train)

        xgb_model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            random_state=seed,
            eval_metric="mlogloss",
            tree_method="hist",
            device="cpu",
            verbosity=0,
        )
        xgb_model.fit(X_train, y_train, sample_weight=sample_weights)
        y_pred = xgb_model.predict(X_test)
        metrics = evaluate_model(y_test, y_pred, class_names, num_classes)
        elapsed = time.time() - t0
        xgb_seed_results.append(metrics)
        print(f"    Seed {seed}: OA={metrics['overall_acc']:.2f}% "
              f"MF1={metrics['macro_f1']:.2f}% ({elapsed:.1f}s)")

    # Export best XGBoost to ONNX (seed 0)
    xgb_best = xgb.XGBClassifier(
        n_estimators=100, max_depth=6, learning_rate=0.1,
        random_state=0, eval_metric="mlogloss", tree_method="hist",
        device="cpu", verbosity=0,
    )
    class_counts = np.bincount(y_train, minlength=num_classes).astype(np.float32)
    class_counts = np.maximum(class_counts, 1.0)
    sw = 1.0 / class_counts[y_train]
    sw = sw / sw.sum() * len(y_train)
    xgb_best.fit(X_train, y_train, sample_weight=sw)
    try:
        initial_type = [("float_input", FloatTensorType([None, input_dim]))]
        xgb_onnx = convert_sklearn(xgb_best, initial_types=initial_type,
                                   target_opset=13)
        xgb_onnx_path = MODEL_DIR / f"xgb_{onnx_suffix}.onnx"
        with open(xgb_onnx_path, "wb") as f:
            f.write(xgb_onnx.SerializeToString())
        print(f"    ONNX exported: {xgb_onnx_path} ({xgb_onnx_path.stat().st_size / 1024:.0f} KB)")
    except Exception as e:
        print(f"    ONNX export failed: {e}")

    # Aggregate XGBoost
    xgb_agg = _aggregate(xgb_seed_results, class_names)
    results["xgboost"] = {
        "per_seed": xgb_seed_results,
        "aggregate": xgb_agg,
        "model_params": {"n_estimators": 100, "max_depth": 6, "lr": 0.1},
    }

    return results


def _aggregate(seed_results, class_names):
    """Aggregate multi-seed results."""
    n = len(seed_results)
    agg = {}
    for key in ["overall_acc", "macro_acc", "macro_precision",
                "macro_recall", "macro_f1", "weighted_f1"]:
        values = [r[key] for r in seed_results]
        agg[key] = {
            "mean": float(np.mean(values)),
            "std": float(np.std(values, ddof=1)) if n > 1 else 0.0,
            "values": values,
        }
    agg["per_class"] = {}
    for cls in class_names:
        agg["per_class"][cls] = {}
        for metric in ["accuracy", "precision", "recall", "f1"]:
            values = [r["per_class"][cls][metric] for r in seed_results]
            agg["per_class"][cls][metric] = {
                "mean": float(np.mean(values)),
                "std": float(np.std(values, ddof=1)) if n > 1 else 0.0,
            }
    return agg


def main():
    print("=" * 70)
    print("Tree-Based Baseline Comparison for SNN-IDS")
    print("  Random Forest + XGBoost on NSL-KDD and UNSW-NB15")
    print("  ONNX export for ST Cloud benchmark (CPU-only, no NPU)")
    print("=" * 70)

    all_results = {}

    # NSL-KDD
    print("\n" + "=" * 70)
    print("Dataset: NSL-KDD")
    print("=" * 70)
    X_tr, y_tr, X_te, y_te, le, fn = load_nslkdd()
    print(f"  Train: {len(X_tr)}, Test: {len(X_te)}, Features: {X_tr.shape[1]}")
    nslkdd_results = train_and_export("NSL-KDD", X_tr, y_tr, X_te, y_te, le, fn)
    all_results["nslkdd"] = nslkdd_results

    # Print comparison header
    print(f"\n  NSL-KDD Summary:")
    for model_name in ["random_forest", "xgboost"]:
        a = nslkdd_results[model_name]["aggregate"]
        print(f"    {model_name:>15s}: OA={a['overall_acc']['mean']:.2f}+/-{a['overall_acc']['std']:.2f}%  "
              f"MF1={a['macro_f1']['mean']:.2f}+/-{a['macro_f1']['std']:.2f}%")

    # UNSW-NB15
    print("\n" + "=" * 70)
    print("Dataset: UNSW-NB15")
    print("=" * 70)
    X_tr, y_tr, X_te, y_te, le, fn = load_unsw_nb15()
    print(f"  Train: {len(X_tr)}, Test: {len(X_te)}, Features: {X_tr.shape[1]}")
    unsw_results = train_and_export("UNSW-NB15", X_tr, y_tr, X_te, y_te, le, fn)
    all_results["unsw_nb15"] = unsw_results

    print(f"\n  UNSW-NB15 Summary:")
    for model_name in ["random_forest", "xgboost"]:
        a = unsw_results[model_name]["aggregate"]
        print(f"    {model_name:>15s}: OA={a['overall_acc']['mean']:.2f}+/-{a['overall_acc']['std']:.2f}%  "
              f"MF1={a['macro_f1']['mean']:.2f}+/-{a['macro_f1']['std']:.2f}%")

    # Save
    out_path = RESULTS_DIR / "tree_baseline.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nResults saved to {out_path}")

    # Final comparison table
    print("\n" + "=" * 70)
    print("Cross-Model Comparison (for paper Table X)")
    print("=" * 70)
    print(f"{'Dataset':<12} {'Model':<16} {'OA%':<18} {'Macro F1%':<18} {'NPU?':<6}")
    print("-" * 70)
    for ds_key, ds_name in [("nslkdd", "NSL-KDD"), ("unsw_nb15", "UNSW-NB15")]:
        for model_name in ["random_forest", "xgboost"]:
            a = all_results[ds_key][model_name]["aggregate"]
            oa = f"{a['overall_acc']['mean']:.2f}+/-{a['overall_acc']['std']:.2f}"
            mf = f"{a['macro_f1']['mean']:.2f}+/-{a['macro_f1']['std']:.2f}"
            print(f"{ds_name:<12} {model_name:<16} {oa:<18} {mf:<18} {'No':<6}")
    print("-" * 70)
    print("Note: MLP results from multiseed experiments. Tree models run on CPU only.")
    print("      Upload RF/XGB ONNX models to ST Cloud for Cortex-M55 CPU benchmark.")


if __name__ == "__main__":
    main()
