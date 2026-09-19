#!/usr/bin/env python3
"""Generate INT8 QDQ ONNX of the CAN-IDS MLP at a chosen hidden width, for the
latency-vs-model-size sweep (11 -> W -> W -> W/2 -> 5, same family as SpikeIDS-RA4E1's
deploy_h64 and the paper's d->256->256->128->C).

Latency of dense INT8 fully-connected kernels is weight-value-independent, so random
init + random calibration is sufficient for the LATENCY sweep; per-width accuracy is
taken from the SpikeIDS-RA4E1 real-data ablation (platform-independent). Produces the
same per-tensor QDQ Gemm graph that stedgeai and onnx_to_cmsis consume.

    uv run --with torch --with onnx --with onnxruntime python scripts/gen_width_onnx.py --width 128 --out /tmp/w128.onnx
"""
import argparse, tempfile, os
import numpy as np
import torch, torch.nn as nn


class MLP(nn.Module):
    def __init__(self, w, d=11, c=5):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(d, w), nn.ReLU(),
            nn.Linear(w, w), nn.ReLU(),
            nn.Linear(w, w // 2), nn.ReLU(),
            nn.Linear(w // 2, c),
        )
    def forward(self, x): return self.net(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, required=True)
    ap.add_argument("--din", type=int, default=11)
    ap.add_argument("--classes", type=int, default=5)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    torch.manual_seed(a.seed); np.random.seed(a.seed)

    m = MLP(a.width, a.din, a.classes).eval()
    dummy = torch.randn(1, a.din)
    fp32 = a.out + ".fp32.onnx"
    torch.onnx.export(m, dummy, fp32, input_names=["input"], output_names=["output"],
                      opset_version=13, dynamic_axes=None)

    from onnxruntime.quantization import quantize_static, CalibrationDataReader, QuantType, QuantFormat

    class RandReader(CalibrationDataReader):
        def __init__(self, n=128, d=a.din):
            # spread of typical normalized CAN features
            self.data = [{"input": np.random.randn(1, d).astype(np.float32)} for _ in range(n)]
            self.i = iter(self.data)
        def get_next(self): return next(self.i, None)

    quantize_static(fp32, a.out, RandReader(), quant_format=QuantFormat.QDQ,
                    per_channel=False, activation_type=QuantType.QInt8, weight_type=QuantType.QInt8)
    os.remove(fp32)
    macs = a.din * a.width + a.width * a.width + a.width * (a.width // 2) + (a.width // 2) * a.classes
    print(f"width={a.width}  arch={a.din}->{a.width}->{a.width}->{a.width//2}->{a.classes}  MACs={macs}  -> {a.out}")


if __name__ == "__main__":
    main()
