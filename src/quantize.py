"""
SNN-IDS: INT8 Post-Training Quantization (PTQ)
Uses ONNX Runtime quantization → ready for ST Edge AI Developer Cloud upload.
Math basis: INT8 quantized ANN ≡ T=1 SNN (Bu CVPR'25, Jiang ICML'23)
"""

import numpy as np
from pathlib import Path
from quantize_utils import CalibrationDataReader
from data_loaders import load_nslkdd

MODEL_DIR = Path(__file__).parent.parent / "models"
DATA_DIR = Path(__file__).parent.parent / "data"


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

    print("\n[1/3] Loading data...")
    X_train, _, X_test, y_test, _, label_enc = load_nslkdd(DATA_DIR)
    rng = np.random.RandomState(42)
    idx = rng.choice(len(X_train), 1000, replace=False)
    cal_data = X_train[idx]
    test_labels = y_test
    print(f"  Calibration samples: {len(cal_data)}")
    print(f"  Shape: {cal_data.shape}")

    # Detect input name from ONNX model
    import onnxruntime as _ort
    _sess = _ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_name = _sess.get_inputs()[0].name
    del _sess
    print(f"  Input name: {input_name}")

    print("\n[2/3] Running INT8 quantization...")
    reader = CalibrationDataReader(cal_data, input_name=input_name)
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

    # FP32 inference
    fp32_sess = ort.InferenceSession(str(onnx_path))
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

    print(f"\n  FP32 accuracy: {fp32_acc:.2f}%")
    print(f"  INT8 accuracy: {int8_acc:.2f}%")
    print(f"  Accuracy drop: {fp32_acc - int8_acc:.2f}%")

    go = (fp32_acc - int8_acc) < 3.0
    print(f"\n  Go/No-Go: INT8 accuracy drop < 3%? {'GO' if go else 'REVIEW NEEDED'}")
    print(f"\n  Next step: Upload {int8_path.name} to stedgeai-dc.st.com")
    print(f"  → Validate for STM32N6 Neural-ART NPU")


if __name__ == "__main__":
    quantize()
