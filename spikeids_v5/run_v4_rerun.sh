#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Activate the intended uv environment first, or pass PYTHON=/absolute/path/to/python.
# A frozen plan is mandatory. No train_fast.py path, parallel GPU workers, or silent fallbacks.
exec "${PYTHON:-python}" "$HERE/suite.py" run "$@"
