#!/usr/bin/env bash
# Wave U U5 — disposable authenticated ZAP AF entrypoint.
# Secrets: ZAP_AUTH_HEADER_VALUE via env only (never argv).
# Soft-OPEN until a real scan writes PASS with High=0.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec python3 -B "$ROOT/scripts/qualification/zap/run_af_disposable.py" "$@"
