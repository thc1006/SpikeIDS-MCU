"""
SNN-IDS: INT8 Post-Training Quantization (PTQ)
Uses ONNX Runtime quantization → ready for ST Edge AI Developer Cloud upload.
Math basis: INT8 quantized ANN ≡ T=1 SNN (arXiv:2510.23383)
"""

import numpy as np
import torch
from pathlib import Path
from sklearn.preprocessing import LabelEncoder, StandardScaler
import pandas as pd

MODEL_DIR = Path(__file__).parent.parent / "models"
DATA_DIR = Path(__file__).parent.parent / "data"

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


class CalibrationDataReader:
    """Provides calibration data for INT8 quantization."""

    def __init__(self, calibration_data, batch_size=64):
        self.data = calibration_data
        self.batch_size = batch_size
        self.idx = 0

    def get_next(self):
        if self.idx >= len(self.data):
            return None
        sample = self.data[self.idx : self.idx + 1]
        self.idx += 1
        return {"input": sample}

    def rewind(self):
        self.idx = 0


def load_calibration_data(n_samples=1000):
    """Load a subset of training data for calibration."""
    metadata = torch.load(MODEL_DIR / "ids_metadata.pth", weights_only=False)

    df = pd.read_csv(DATA_DIR / "KDDTrain+.txt", header=None, names=COL_NAMES)
    df.drop(columns=["difficulty"], inplace=True)
    df["label"] = df["label"].map(ATTACK_MAP).fillna("unknown")
    df = df[df["label"] != "unknown"]

    # Load test data too for combined LabelEncoder fit (must match training pipeline)
    test_df = pd.read_csv(DATA_DIR / "KDDTest+.txt", header=None, names=COL_NAMES)
    test_df.drop(columns=["difficulty"], inplace=True)

    cat_cols = ["protocol_type", "service", "flag"]
    for col in cat_cols:
        le = LabelEncoder()
        combined = pd.concat([df[col], test_df[col]])
        le.fit(combined)
        df[col] = le.transform(df[col])

    X = df.drop(columns=["label"]).values.astype(np.float32)

    scaler = StandardScaler()
    scaler.mean_ = np.array(metadata["scaler_mean"])
    scaler.scale_ = np.array(metadata["scaler_scale"])
    scaler.var_ = scaler.scale_ ** 2
    scaler.n_features_in_ = len(scaler.mean_)
    X = scaler.transform(X)

    # Random sampling from training set
    rng = np.random.RandomState(42)
    indices = rng.choice(len(X), size=min(n_samples, len(X)), replace=False)
    return X[indices].astype(np.float32)


def quantize():
    from onnxruntime.quantization import quantize_static, QuantType, CalibrationMethod

    onnx_path = MODEL_DIR / "ids_model.onnx"
    int8_path = MODEL_DIR / "ids_model_int8.onnx"

    if not onnx_path.exists():
        print("ERROR: ONNX model not found. Run export_onnx.py first.")
        return

    print("=" * 60)
    print("SNN-IDS: INT8 Post-Training Quantization")
    print("=" * 60)

    print("\n[1/3] Loading calibration data...")
    cal_data = load_calibration_data(n_samples=1000)
    print(f"  Calibration samples: {len(cal_data)}")
    print(f"  Shape: {cal_data.shape}")

    print("\n[2/3] Running INT8 quantization...")
    reader = CalibrationDataReader(cal_data, batch_size=64)
    quantize_static(
        model_input=str(onnx_path),
        model_output=str(int8_path),
        calibration_data_reader=reader,
        quant_format=QuantType.QInt8,
        calibrate_method=CalibrationMethod.MinMax,
        per_channel=False,
        weight_type=QuantType.QInt8,
        activation_type=QuantType.QInt8,
    )
    print(f"  INT8 model saved: {int8_path}")
    print(f"  File size: {int8_path.stat().st_size / 1024:.1f} KB")
    print(f"  FP32 size: {onnx_path.stat().st_size / 1024:.1f} KB")
    ratio = int8_path.stat().st_size / onnx_path.stat().st_size
    print(f"  Compression: {ratio:.2f}x")

    print("\n[3/3] Accuracy verification (INT8 vs FP32)...")
    import onnxruntime as ort
    import onnx

    # Print INT8 operators
    int8_model = onnx.load(str(int8_path))
    ops = set()
    for node in int8_model.graph.node:
        ops.add(node.op_type)
    print(f"  INT8 operators: {sorted(ops)}")

    # Load test data for accuracy comparison
    test_df = pd.read_csv(DATA_DIR / "KDDTest+.txt", header=None, names=COL_NAMES)
    test_df.drop(columns=["difficulty"], inplace=True)
    test_df["label"] = test_df["label"].map(ATTACK_MAP).fillna("unknown")
    test_df = test_df[test_df["label"] != "unknown"]

    metadata = torch.load(MODEL_DIR / "ids_metadata.pth", weights_only=False)

    cat_cols = ["protocol_type", "service", "flag"]
    train_df = pd.read_csv(DATA_DIR / "KDDTrain+.txt", header=None, names=COL_NAMES)
    train_df.drop(columns=["difficulty"], inplace=True)
    train_df["label"] = train_df["label"].map(ATTACK_MAP).fillna("unknown")
    train_df = train_df[train_df["label"] != "unknown"]

    for col in cat_cols:
        le = LabelEncoder()
        combined = pd.concat([train_df[col], test_df[col]])
        le.fit(combined)
        test_df[col] = le.transform(test_df[col])

    label_enc = LabelEncoder()
    label_enc.fit(["normal", "DoS", "Probe", "R2L", "U2R"])
    test_labels = label_enc.transform(test_df["label"])

    X_test = test_df.drop(columns=["label"]).values.astype(np.float32)
    scaler = StandardScaler()
    scaler.mean_ = np.array(metadata["scaler_mean"])
    scaler.scale_ = np.array(metadata["scaler_scale"])
    scaler.var_ = scaler.scale_ ** 2
    scaler.n_features_in_ = len(scaler.mean_)
    X_test = scaler.transform(X_test)

    # FP32 inference
    fp32_sess = ort.InferenceSession(str(onnx_path))
    fp32_correct = 0
    for i in range(len(X_test)):
        x = X_test[i:i+1].astype(np.float32)
        out = fp32_sess.run(None, {"input": x})[0]
        if out.argmax() == test_labels[i]:
            fp32_correct += 1
    fp32_acc = fp32_correct / len(X_test) * 100

    # INT8 inference
    int8_sess = ort.InferenceSession(str(int8_path))
    int8_input_name = int8_sess.get_inputs()[0].name
    int8_correct = 0
    for i in range(len(X_test)):
        x = X_test[i:i+1].astype(np.float32)
        out = int8_sess.run(None, {int8_input_name: x})[0]
        if out.argmax() == test_labels[i]:
            int8_correct += 1
    int8_acc = int8_correct / len(X_test) * 100

    print(f"\n  FP32 accuracy: {fp32_acc:.2f}%")
    print(f"  INT8 accuracy: {int8_acc:.2f}%")
    print(f"  Accuracy drop: {fp32_acc - int8_acc:.2f}%")

    go = (fp32_acc - int8_acc) < 3.0
    print(f"\n  Go/No-Go: INT8 accuracy drop < 3%? {'GO' if go else 'REVIEW NEEDED'}")
    print(f"\n  Next step: Upload {int8_path.name} to stedgeai-dc.st.com")
    print(f"  → Validate for STM32N6 Neural-ART NPU")


if __name__ == "__main__":
    quantize()
