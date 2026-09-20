#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# --build performs the strict consistency check BEFORE latexmk. Any failure propagates.
exec "${PYTHON:-python}" "$HERE/finalize_all_det.py" --build "$@"
