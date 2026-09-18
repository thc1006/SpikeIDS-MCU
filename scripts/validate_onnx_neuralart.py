"""Brute-force validate the IDS_MLP ONNX pipeline for Neural-ART (ST Edge AI Core).
Builds representative FP32 + INT8(QDQ) ONNX for the four v3 shapes and H=64, then:
 - onnx.checker.check_model (strict)
 - onnxruntime load + inference (numerical sanity)
 - operator inventory vs the Neural-ART support table (Gemm/Relu HW; QDQ ok)
 - shape/opset/initializer audit
No trained weights needed: random weights exercise the exact graph topology ST will compile.
"""
import sys, json, numpy as np, onnx, torch, torch.nn as nn
from pathlib import Path
import onnxruntime as ort
from onnxruntime.quantization import quantize_static, CalibrationDataReader, QuantType, QuantFormat

sys.path.insert(0, "src")
OUT = Path("results/onnx_neuralart_check")
OUT.mkdir(exist_ok=True)

# Neural-ART HW-mapped ops (from stneuralart_operator_support.html, fetched earlier)
HW_OK = {"Gemm", "MatMul", "Add", "Relu", "Clip", "QuantizeLinear", "DequantizeLinear", "Flatten", "Reshape"}
SW_FALLBACK = {"Floor", "Round", "Ceil"}  # would force CPU epochs

class MLP(nn.Module):
    def __init__(self, d, h, c):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(d, h), nn.ReLU(), nn.Linear(h, h), nn.ReLU(),
                                 nn.Linear(h, h // 2), nn.ReLU(), nn.Linear(h // 2, c))
    def forward(self, x): return self.net(x)

class RandReader(CalibrationDataReader):
    def __init__(self, d, n=64):
        self.data = iter([{"input": np.random.randn(1, d).astype(np.float32)} for _ in range(n)])
    def get_next(self): return next(self.data, None)

SHAPES = {"nslkdd": (41,256,5), "unsw": (34,256,10), "cicids": (78,256,15),
          "iot23": (23,256,5), "can_h64": (11,64,5)}
report = {}
allok = True
for name, (d, h, c) in SHAPES.items():
    r = {"shape": [d,h,c]}
    m = MLP(d, h, c).eval()
    fp = OUT / f"{name}_fp32.onnx"; q = OUT / f"{name}_int8.onnx"
    torch.onnx.export(m, torch.randn(1,d), str(fp), input_names=["input"], output_names=["output"],
                      dynamic_axes=None, opset_version=17)
    om = onnx.load(str(fp))
    try:
        onnx.checker.check_model(om, full_check=True); r["fp32_checker"]="PASS"
    except Exception as e:
        r["fp32_checker"]=f"FAIL {e}"; allok=False
    r["opset"] = om.opset_import[0].version
    # FP32 ORT inference
    try:
        s = ort.InferenceSession(str(fp), providers=["CPUExecutionProvider"])
        o = s.run(None, {"input": np.random.randn(1,d).astype(np.float32)})[0]
        r["fp32_ort_out_shape"] = list(o.shape); r["fp32_finite"]=bool(np.isfinite(o).all())
    except Exception as e:
        r["fp32_ort"]=f"FAIL {e}"; allok=False
    # INT8 static QDQ quantization (what ST Edge AI expects for NPU)
    try:
        quantize_static(str(fp), str(q), RandReader(d), quant_format=QuantFormat.QDQ,
                        activation_type=QuantType.QInt8, weight_type=QuantType.QInt8, per_channel=False)
        qm = onnx.load(str(q)); onnx.checker.check_model(qm, full_check=True)
        ops = sorted({n.op_type for n in qm.graph.node})
        r["int8_ops"] = ops
        r["int8_unsupported"] = [o for o in ops if o not in HW_OK and o not in SW_FALLBACK]
        r["int8_sw_fallback"] = [o for o in ops if o in SW_FALLBACK]
        s2 = ort.InferenceSession(str(q), providers=["CPUExecutionProvider"])
        o2 = s2.run(None, {"input": np.random.randn(1,d).astype(np.float32)})[0]
        r["int8_ort_out_shape"]=list(o2.shape); r["int8_finite"]=bool(np.isfinite(o2).all())
        r["int8_kb"]=round(q.stat().st_size/1024,1)
        r["int8_checker"]="PASS"
        if r["int8_unsupported"]: allok=False
    except Exception as e:
        r["int8"]=f"FAIL {type(e).__name__}: {e}"; allok=False
    report[name]=r

print(json.dumps(report, indent=1))
print("\nALL_OK:", allok)
print("onnx", onnx.__version__, "ort", ort.__version__)
