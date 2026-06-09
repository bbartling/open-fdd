#!/usr/bin/env bash
# Central portfolio Plotly Dash (benserver / analyst workstation — not edge).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
pip install -q -r portfolio/requirements.txt
exec python portfolio/dash/app.py
