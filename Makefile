# SNN-IDS: Reproducible Experiment Pipeline
# Usage: make all

PYTHON = python3
VENV = snn-ids-env
PIP = $(VENV)/bin/pip
PY = $(VENV)/bin/python3

.PHONY: all setup data train export quantize qcfs clean

all: setup data train export quantize qcfs

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -r requirements.txt

data:
	mkdir -p data
	@echo "Download NSL-KDD from https://www.unb.ca/cic/datasets/nsl.html"
	@echo "Place KDDTrain+.txt and KDDTest+.txt in data/"
	@test -f data/KDDTrain+.txt || (echo "ERROR: data/KDDTrain+.txt not found" && exit 1)

train:
	PYTHONUNBUFFERED=1 $(PY) src/train.py

export:
	PYTHONUNBUFFERED=1 $(PY) src/export_onnx.py

quantize:
	PYTHONUNBUFFERED=1 $(PY) src/quantize.py

qcfs:
	PYTHONUNBUFFERED=1 $(PY) src/train_qcfs.py
	PYTHONUNBUFFERED=1 $(PY) src/export_qcfs_onnx.py

clean:
	rm -rf models/*.pth models/*.onnx models/*.onnx.data
	rm -rf __pycache__ src/__pycache__
