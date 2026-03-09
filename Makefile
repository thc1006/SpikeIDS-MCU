# SNN-IDS: Reproducible Experiment Pipeline
# Usage: make all

PYTHON = python3
VENV = snn-ids-env
PIP = $(VENV)/bin/pip
PY = $(VENV)/bin/python3

.PHONY: all setup data train export quantize qcfs quantize-qcfs \
        multiseed unsw unsw-export tree-baseline layerwise quant-ablation \
        paper clean

all: setup data train export quantize qcfs quantize-qcfs

setup:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -r requirements.txt

data:
	mkdir -p data
	@echo "Download NSL-KDD from https://www.unb.ca/cic/datasets/nsl.html"
	@echo "Place KDDTrain+.txt and KDDTest+.txt in data/"
	@test -f data/KDDTrain+.txt || (echo "ERROR: data/KDDTrain+.txt not found" && exit 1)

# --- NSL-KDD Pipeline ---
train:
	PYTHONUNBUFFERED=1 $(PY) src/train.py

export:
	PYTHONUNBUFFERED=1 $(PY) src/export_onnx.py

quantize:
	PYTHONUNBUFFERED=1 $(PY) src/quantize.py

qcfs:
	PYTHONUNBUFFERED=1 $(PY) src/train_qcfs.py
	PYTHONUNBUFFERED=1 $(PY) src/export_qcfs_onnx.py

quantize-qcfs:
	PYTHONUNBUFFERED=1 $(PY) src/quantize_qcfs.py 4

# --- Multi-seed & Cross-dataset ---
multiseed:
	PYTHONUNBUFFERED=1 $(PY) src/experiment_multiseed.py

unsw:
	PYTHONUNBUFFERED=1 $(PY) src/experiment_unsw.py

unsw-export:
	PYTHONUNBUFFERED=1 $(PY) src/export_unsw_onnx.py

# --- Analysis & Baselines ---
tree-baseline:
	PYTHONUNBUFFERED=1 $(PY) src/tree_baseline.py

layerwise:
	PYTHONUNBUFFERED=1 $(PY) src/layerwise_analysis.py

quant-ablation:
	PYTHONUNBUFFERED=1 $(PY) src/quantize_ablation.py

# --- Paper ---
paper:
	cd paper && pdflatex main && bibtex main && pdflatex main && pdflatex main

clean:
	rm -rf models/*.pth models/*.onnx models/*.onnx.data
	rm -rf __pycache__ src/__pycache__
