"""
Shared quantization utilities for all SNN-IDS ONNX quantization scripts.

Extracted from 6 files to eliminate duplication.
"""


class CalibrationDataReader:
    """Provides calibration data one sample at a time for INT8 quantization."""

    def __init__(self, data, input_name="input"):
        self.data = data
        self.input_name = input_name
        self.idx = 0

    def get_next(self):
        if self.idx >= len(self.data):
            return None
        sample = self.data[self.idx:self.idx + 1]
        self.idx += 1
        return {self.input_name: sample}

    def rewind(self):
        self.idx = 0
