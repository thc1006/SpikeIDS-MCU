#!/usr/bin/env bash
# Gate 7 reviewer-lens helper: compile paper, emit page + warning summary.
set -euo pipefail
cd "$(dirname "$0")/../paper/globecom"
pdflatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null 2>&1 || true
bibtex main >/dev/null 2>&1 || true
pdflatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null 2>&1 || true
pdflatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null 2>&1 || true

echo "=== Pages ==="
pdfinfo main.pdf | grep -E "Pages|Page size"

echo
echo "=== Undefined refs / warnings ==="
grep -iE "undefined|multiply.defined|latex warning" main.log || echo "none"

echo
echo "=== Overfull/Underfull boxes (count) ==="
grep -cE "Overfull|Underfull" main.log || true

echo
echo "=== Bibliography warnings ==="
grep -i "warning" main.blg || echo "none"
