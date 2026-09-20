#!/usr/bin/env bash
# Post-re-run: rebuild every LaTeX macro from the fresh results/*.json, run the consistency
# checker, and rebuild the PDF. Run AFTER run_v4_rerun.sh finishes (all 11 JSONs exist).
# The --strict check will only pass once the README.md §6 prose reframe is also done.
set -u
cd /home/thc1006/dev/SpikeIDS-MCU || { echo "repo not found"; exit 1; }
PY=.venv/bin/python

echo "== [1/3] finalize: adapters + run_globecom_stats + run_v4_equivalence + rewrite result_macros.tex =="
$PY scripts/finalize_all_det.py 2>&1 | tee results/finalize_v4.log

echo "== [2/3] consistency check (macro-vs-JSON + hardcoded-prose scan) =="
$PY scripts/check_paper_consistency.py --strict \
  || echo "  ^ NOT clean yet — finish the README §6 prose reframe, then re-run this script"

echo "== [3/3] rebuild PDF =="
latexmk -pdf -interaction=nonstopmode -halt-on-error -cd paper/globecom/main.tex

echo "== done -> paper/globecom/main.pdf =="
