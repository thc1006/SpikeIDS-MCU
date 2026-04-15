"""
Quantization ablation study for SNN-IDS paper.
Tests different calibration methods, per-tensor vs per-channel,
and calibration sample sizes on both NSL-KDD and UNSW-NB15.

Expected result: small model (111K params) should show minimal variation,
supporting T=1 robustness claim.

Usage:
    python src/quantize_ablation.py
"""

import json
import time
import numpy as np
import onnx
import onnxruntime as ort
from pathlib import Path
from sklearn.metrics import accuracy_score
from onnxruntime.quantization import (
    quantize_static, QuantType, CalibrationMethod
)
from data_loaders import load_nslkdd, load_unsw
from quantize_utils import CalibrationDataReader

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
MODEL_DIR = BASE_DIR / "models"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)


def evaluate_onnx(model_path, X_test, y_test):
    """Evaluate ONNX model accuracy."""
    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name

    # Check if batch supported
    input_shape = sess.get_inputs()[0].shape
    if input_shape[0] == 1:
        # Fixed batch=1, iterate
        preds = []
        for i in range(len(X_test)):
            out = sess.run(None, {input_name: X_test[i:i+1]})[0]
            preds.append(out.argmax())
        preds = np.array(preds)
    else:
        out = sess.run(None, {input_name: X_test})[0]
        preds = out.argmax(axis=1)

    overall_acc = accuracy_score(y_test, preds) * 100
    return overall_acc


def run_ablation(onnx_path, X_train, X_test, y_test, dataset_name):
    """Run quantization ablation across calibration methods, per-channel, sample sizes."""
    print(f"\n  FP32 baseline...")
    fp32_acc = evaluate_onnx(onnx_path, X_test, y_test)
    print(f"    FP32 accuracy: {fp32_acc:.2f}%")

    # Get input name from model
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name
    del sess

    # Ablation configurations
    calibration_methods = {
        "MinMax": CalibrationMethod.MinMax,
        "Entropy": CalibrationMethod.Entropy,
        "Percentile": CalibrationMethod.Percentile,
    }
    per_channel_options = [False, True]
    sample_sizes = [100, 500, 1000, 5000]

    results = {
        "dataset": dataset_name,
        "fp32_accuracy": fp32_acc,
        "ablations": [],
    }

    for method_name, method in calibration_methods.items():
        for per_channel in per_channel_options:
            for n_samples in sample_sizes:
                config_name = f"{method_name}_{'perCh' if per_channel else 'perT'}_{n_samples}"
                print(f"    {config_name}...", end=" ", flush=True)

                # Sample calibration data
                rng = np.random.RandomState(42)
                cal_idx = rng.choice(len(X_train),
                                     size=min(n_samples, len(X_train)),
                                     replace=False)
                cal_data = X_train[cal_idx].astype(np.float32)

                # Output path
                out_path = MODEL_DIR / f"ablation_{dataset_name}_{config_name}.onnx"

                try:
                    t0 = time.time()
                    reader = CalibrationDataReader(cal_data, input_name=input_name)

                    quantize_static(
                        model_input=str(onnx_path),
                        model_output=str(out_path),
                        calibration_data_reader=reader,
                        quant_format=QuantType.QInt8,
                        calibrate_method=method,
                        per_channel=per_channel,
                        weight_type=QuantType.QInt8,
                        activation_type=QuantType.QInt8,
                    )

                    int8_acc = evaluate_onnx(out_path, X_test, y_test)
                    elapsed = time.time() - t0
                    drop = fp32_acc - int8_acc
                    file_size = out_path.stat().st_size / 1024

                    print(f"INT8={int8_acc:.2f}% (drop={drop:.2f}%) [{elapsed:.1f}s]")

                    results["ablations"].append({
                        "calibration_method": method_name,
                        "per_channel": per_channel,
                        "n_calibration_samples": n_samples,
                        "int8_accuracy": float(int8_acc),
                        "accuracy_drop": float(drop),
                        "file_size_kb": float(file_size),
                        "time_s": float(elapsed),
                    })

                    # Clean up ablation model (keep disk clean)
                    out_path.unlink()

                except Exception as e:
                    print(f"FAILED: {e}")
                    results["ablations"].append({
                        "calibration_method": method_name,
                        "per_channel": per_channel,
                        "n_calibration_samples": n_samples,
                        "error": str(e),
                    })
                    if out_path.exists():
                        out_path.unlink()

    return results


def main():
    print("=" * 70)
    print("Quantization Ablation Study for SNN-IDS")
    print("  Calibration methods: MinMax, Entropy, Percentile")
    print("  Granularity: per-tensor, per-channel")
    print("  Sample sizes: 100, 500, 1000, 5000")
    print("=" * 70)

    all_results = {}

    # NSL-KDD
    onnx_path = MODEL_DIR / "ids_model.onnx"
    if onnx_path.exists():
        print(f"\n{'='*70}")
        print("Dataset: NSL-KDD")
        print(f"{'='*70}")
        X_train, _, X_test, y_test, _, le = load_nslkdd(DATA_DIR)
        nslkdd_results = run_ablation(onnx_path, X_train, X_test, y_test, "nslkdd")
        all_results["nslkdd"] = nslkdd_results
    else:
        print(f"WARNING: {onnx_path} not found, skipping NSL-KDD")

    # UNSW-NB15
    unsw_onnx_path = MODEL_DIR / "unsw_model.onnx"
    if unsw_onnx_path.exists():
        print(f"\n{'='*70}")
        print("Dataset: UNSW-NB15")
        print(f"{'='*70}")
        X_train, _, X_test, y_test, _, le, _ = load_unsw(DATA_DIR)
        unsw_results = run_ablation(unsw_onnx_path, X_train, X_test, y_test, "unsw")
        all_results["unsw"] = unsw_results
    else:
        print(f"WARNING: {unsw_onnx_path} not found, skipping UNSW-NB15")

    # Save results
    out_path = RESULTS_DIR / "quantize_ablation.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nResults saved to {out_path}")

    # Summary table
    print(f"\n{'='*70}")
    print("Summary Table (for paper)")
    print(f"{'='*70}")
    for ds_name, ds_results in all_results.items():
        print(f"\n  Dataset: {ds_name} (FP32: {ds_results['fp32_accuracy']:.2f}%)")
        print(f"  {'Method':<14} {'Granularity':<12} {'Samples':<8} {'INT8 Acc%':<12} {'Drop%':<8}")
        print(f"  {'-'*54}")
        for a in ds_results["ablations"]:
            if "error" in a:
                continue
            gran = "per-ch" if a["per_channel"] else "per-t"
            print(f"  {a['calibration_method']:<14} {gran:<12} {a['n_calibration_samples']:<8} "
                  f"{a['int8_accuracy']:<12.2f} {a['accuracy_drop']:<8.2f}")

    # Key finding (per-dataset)
    for ds_name, ds_results in all_results.items():
        drops = [a["accuracy_drop"] for a in ds_results["ablations"] if "error" not in a]
        if drops:
            print(f"\n  {ds_name}: accuracy drop range = [{min(drops):.2f}%, {max(drops):.2f}%]")
            if max(abs(d) for d in drops) < 3.0:
                print(f"    All drops < 3% → robust to quantization choices")
            else:
                print(f"    WARNING: max drop {max(drops):.2f}% exceeds 3% threshold")


if __name__ == "__main__":
    main()
