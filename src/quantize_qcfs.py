"""
SNN-IDS: INT8 Post-Training Quantization for QCFS Models
Quantize FP32 QCFS ONNX → INT8 ONNX for Neural-ART NPU deployment.
Goal: Determine if Floor/Clip operators survive quantization and map to NPU.
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
    """Provides calibration data one sample at a time for INT8 quantization."""

    def __init__(self, calibration_data, input_name="input"):
        self.data = calibration_data
        self.input_name = input_name
        self.idx = 0

    def get_next(self):
        if self.idx >= len(self.data):
            return None
        sample = self.data[self.idx : self.idx + 1]
        self.idx += 1
        return {self.input_name: sample}

    def rewind(self):
        self.idx = 0


def load_calibration_data(n_samples=1000):
    """Load a subset of training data for calibration."""
    metadata = torch.load(MODEL_DIR / "ids_metadata.pth", weights_only=False)

    df = pd.read_csv(DATA_DIR / "KDDTrain+.txt", header=None, names=COL_NAMES)
    df.drop(columns=["difficulty"], inplace=True)
    df["label"] = df["label"].map(ATTACK_MAP).fillna("unknown")
    df = df[df["label"] != "unknown"]

    cat_cols = ["protocol_type", "service", "flag"]
    for col in cat_cols:
        le = LabelEncoder()
        le.fit(df[col])
        df[col] = le.transform(df[col])

    X = df.drop(columns=["label"]).values.astype(np.float32)

    scaler = StandardScaler()
    scaler.mean_ = np.array(metadata["scaler_mean"])
    scaler.scale_ = np.array(metadata["scaler_scale"])
    scaler.var_ = scaler.scale_ ** 2
    scaler.n_features_in_ = len(scaler.mean_)
    X = scaler.transform(X)

    rng = np.random.RandomState(42)
    indices = rng.choice(len(X), size=min(n_samples, len(X)), replace=False)
    return X[indices].astype(np.float32)


def load_test_data():
    """Load full test set for accuracy evaluation."""
    metadata = torch.load(MODEL_DIR / "ids_metadata.pth", weights_only=False)

    test_df = pd.read_csv(DATA_DIR / "KDDTest+.txt", header=None, names=COL_NAMES)
    test_df.drop(columns=["difficulty"], inplace=True)
    test_df["label"] = test_df["label"].map(ATTACK_MAP).fillna("unknown")
    test_df = test_df[test_df["label"] != "unknown"]

    train_df = pd.read_csv(DATA_DIR / "KDDTrain+.txt", header=None, names=COL_NAMES)
    train_df.drop(columns=["difficulty"], inplace=True)
    train_df["label"] = train_df["label"].map(ATTACK_MAP).fillna("unknown")
    train_df = train_df[train_df["label"] != "unknown"]

    cat_cols = ["protocol_type", "service", "flag"]
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

    return X_test.astype(np.float32), test_labels, label_enc


def quantize_qcfs(L=4):
    from onnxruntime.quantization import quantize_static, QuantType, CalibrationMethod
    import onnxruntime as ort
    import onnx

    fp32_path = MODEL_DIR / f"ids_qcfs_L{L}.onnx"
    int8_path = MODEL_DIR / f"ids_qcfs_L{L}_int8.onnx"

    if not fp32_path.exists():
        print(f"ERROR: {fp32_path} not found. Run export_qcfs_onnx.py first.")
        return

    print("=" * 60)
    print(f"SNN-IDS: INT8 PTQ for QCFS L={L}")
    print("=" * 60)

    # Detect input name from ONNX model
    fp32_model = onnx.load(str(fp32_path))
    input_name = fp32_model.graph.input[0].name
    print(f"\n  Input name: {input_name}")

    # Show FP32 operators
    fp32_ops = set()
    for node in fp32_model.graph.node:
        fp32_ops.add(node.op_type)
    print(f"  FP32 operators: {sorted(fp32_ops)}")

    print(f"\n[1/3] Loading calibration data...")
    cal_data = load_calibration_data(n_samples=1000)
    print(f"  Calibration samples: {len(cal_data)}")

    print(f"\n[2/3] Running INT8 quantization...")
    reader = CalibrationDataReader(cal_data, input_name=input_name)
    quantize_static(
        model_input=str(fp32_path),
        model_output=str(int8_path),
        calibration_data_reader=reader,
        quant_format=QuantType.QInt8,
        calibrate_method=CalibrationMethod.MinMax,
        per_channel=False,
        weight_type=QuantType.QInt8,
        activation_type=QuantType.QInt8,
    )

    # Ensure weights are embedded (not external data file)
    int8_model = onnx.load(str(int8_path))
    onnx.save(int8_model, str(int8_path), save_as_external_data=False)

    print(f"  INT8 model saved: {int8_path}")
    print(f"  INT8 size: {int8_path.stat().st_size / 1024:.1f} KB")
    print(f"  FP32 size: {fp32_path.stat().st_size / 1024:.1f} KB")

    # Analyze INT8 operators
    int8_model = onnx.load(str(int8_path))
    int8_ops = set()
    for node in int8_model.graph.node:
        int8_ops.add(node.op_type)
    print(f"\n  INT8 operators: {sorted(int8_ops)}")

    new_ops = int8_ops - fp32_ops
    removed_ops = fp32_ops - int8_ops
    if new_ops:
        print(f"  New operators (from quantization): {sorted(new_ops)}")
    if removed_ops:
        print(f"  Removed operators: {sorted(removed_ops)}")

    # Check if Floor survived quantization
    floor_survived = "Floor" in int8_ops
    print(f"\n  Floor operator survived INT8 PTQ: {'YES' if floor_survived else 'NO'}")
    if floor_survived:
        print(f"  → Floor still present. NPU may or may not support it in INT8 mode.")
        print(f"  → Upload to ST Cloud to verify NPU/CPU mapping.")
    else:
        print(f"  → Floor was removed/folded during quantization.")
        print(f"  → Model may now be fully NPU-compatible (like ReLU INT8).")

    print(f"\n[3/3] Accuracy verification (FP32 vs INT8)...")
    X_test, test_labels, label_enc = load_test_data()

    # FP32 inference
    fp32_sess = ort.InferenceSession(str(fp32_path))
    fp32_correct = 0
    for i in range(len(X_test)):
        x = X_test[i:i+1].astype(np.float32)
        out = fp32_sess.run(None, {input_name: x})[0]
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

    print(f"\n  QCFS L={L} FP32 accuracy: {fp32_acc:.2f}%")
    print(f"  QCFS L={L} INT8 accuracy: {int8_acc:.2f}%")
    print(f"  Accuracy drop: {fp32_acc - int8_acc:.2f}%")

    go = (fp32_acc - int8_acc) < 5.0
    print(f"\n  Go/No-Go: INT8 accuracy drop < 5%? {'GO' if go else 'REVIEW NEEDED'}")
    print(f"\n  Next step: Upload {int8_path.name} to stedgeai-dc.st.com")
    print(f"  → Select target: STM32N6570-DK → Benchmark")
    print(f"  → Compare epochs_hw count vs FP32 (which had 0 HW epochs)")


if __name__ == "__main__":
    import sys
    L = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    quantize_qcfs(L)
