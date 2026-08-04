#!/usr/bin/env bash
# Legacy Streamlit UI dev helper — product UI is React (`frontend/web`).
set -euo pipefail
echo "openfdd_ui_dev.sh removed: Streamlit product UI is deleted." >&2
echo "Use: cd frontend/web && npm run dev" >&2
echo "Or:  OPENFDD_REACT_UI=1 ./scripts/openfdd_stack_up.sh react-ot" >&2
exit 1
