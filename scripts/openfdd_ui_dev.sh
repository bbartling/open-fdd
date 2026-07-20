#!/usr/bin/env bash
# Local Streamlit vibe19 UI — hot reload against central :8080.
#
#   ./scripts/openfdd_ui_dev.sh              # localhost:8501
#   ./scripts/openfdd_ui_dev.sh --lan        # 0.0.0.0:8501 for remote browser on LAN
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

LAN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lan) LAN=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: scripts/openfdd_ui_dev.sh [--lan]

  --lan  Bind Streamlit to 0.0.0.0:8501
EOF
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

cd "$ROOT/services/ui"
python3 -m pip install -q -r requirements.txt

export OPENFDD_API_BASE="${OPENFDD_API_BASE:-http://127.0.0.1:8080}"
ADDR="127.0.0.1"
[[ "$LAN" -eq 1 ]] && ADDR="0.0.0.0"
echo "==> Streamlit on http://${ADDR}:8501 (OPENFDD_API_BASE=${OPENFDD_API_BASE})"
echo "    Start central first: ./scripts/openfdd_stack_up.sh csv"
exec streamlit run streamlit_app.py --server.port=8501 --server.address="$ADDR"
