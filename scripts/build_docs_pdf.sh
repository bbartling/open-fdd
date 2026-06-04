#!/usr/bin/env bash
# Build pdf/open-fdd-docs.pdf (+ .txt). Requires system pandoc; installs weasyprint if missing.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi
if ! command -v pandoc >/dev/null 2>&1; then
  echo "Install pandoc first: https://pandoc.org/installing.html" >&2
  exit 1
fi
if ! "$PY" -c "import weasyprint" 2>/dev/null; then
  echo "Installing weasyprint into $(dirname "$PY")…" >&2
  "$PY" -m pip install -q weasyprint pyyaml
fi
exec "$PY" "${ROOT}/scripts/build_docs_pdf.py" "$@"
