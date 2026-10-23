#!/usr/bin/env bash
# Astra C-ZAP (A06–A07) — disposable authenticated ZAP AF wrapper.
#
# Mints a throwaway portal candidate (deployment profile `cloud_portal`:
# openfdd-web + openfdd-central + Timescale from GHCR, OPENFDD_MULTI_TENANT=1,
# per-run JWT secret, no open-bind escape hatch) through
# lib/portal_stack.sh, then delegates scan evaluation to
# scripts/qualification/zap/run_af_disposable.py (single evaluator).
# Compatibility entrypoint for Wave C / gate runners.
#
# Never activeScans live Railway or a site. Never persists JWT to artifact disk.
# No fallback crawl or warning soft-pass paths.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
# shellcheck source-path=SCRIPTDIR source=lib/portal_stack.sh
source "$ROOT/scripts/qualification/lib/portal_stack.sh"

portal_require_tag
portal_preflight

# Pin scanner digest (override only with another digest-pinned ref).
ZAP_IMAGE="${OPENFDD_ZAP_IMAGE:-ghcr.io/zaproxy/zaproxy@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef}"
if [[ "$ZAP_IMAGE" != *@sha256:* ]]; then
  echo "FAIL: OPENFDD_ZAP_IMAGE must be digest-pinned (@sha256:…); got: $ZAP_IMAGE" >&2
  exit 1
fi
ART="${ARTIFACT_DIR:-$ROOT/reports/waveC_zap_af_$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$ART"
ART="$(cd "$ART" && pwd)"
WRK="$ART/zap_wrk"
mkdir -p "$WRK"
# Restrict artifact tree (no JWT on disk). ZAP image often runs as uid 1000 —
# make wrk world-accessible for the mount only (plan/report; never secrets).
chmod 700 "$ART"
chmod 777 "$WRK"
cp "$ROOT/docs/openapi.yaml" "$WRK/openapi.yaml"

portal_stack_init zap
trap portal_stack_cleanup EXIT
# A07: scan through nginx+SPA (openfdd-web, compose service `web`), not bare
# central. The scanner joins this project's default network, where the
# compose service name `web` resolves; central and Timescale stay on the
# internal network and are not reachable from the scanner.
TARGET_ORIGIN="http://web:8080"
ZAP_NET="${PORTAL_PROJECT}_default"

echo "== Pull images and start the disposable portal candidate =="
docker pull "$ZAP_IMAGE" >/dev/null
portal_stack_up 240
echo "OK disposable portal candidate (web+central+timescale, project $PORTAL_PROJECT)"

portal_login admin admin || { echo "FAIL: could not mint admin JWT for ZAP context" >&2; exit 1; }
# UA-04: never persist JWT to artifact disk (env injection only).
rm -f "$ART/admin.jwt" "$WRK/admin.jwt" 2>/dev/null || true
echo "OK admin JWT minted (ephemeral env only)"

# Evaluator owns AF plan materialization + verdict; wrapper only mints candidate.
export OPENFDD_ZAP_AF_EXECUTE=1
export OPENFDD_ZAP_IMAGE="$ZAP_IMAGE"
export OPENFDD_ZAP_REQUIRE_DIGEST=1
export ZAP_TARGET_ORIGIN="$TARGET_ORIGIN"
ZAP_AUTH_HEADER_VALUE="Bearer $(cat "$PORTAL_PRIV/tok.admin")"
export ZAP_AUTH_HEADER_VALUE
export ZAP_AF_WORK_DIR="$WRK"
export ZAP_DOCKER_NETWORK="$ZAP_NET"
ZAP_AF_RUN_STARTED_EPOCH="$(date +%s)"
export ZAP_AF_RUN_STARTED_EPOCH
VERDICT_OUT="$ART/verdict.json"

set +e
python3 -B "$ROOT/scripts/qualification/zap/run_af_disposable.py" \
  --out "$VERDICT_OUT"
EVAL_RC=$?
set -e
unset ZAP_AUTH_HEADER_VALUE

chmod -R u+rwX,g+rwX,o-rwx "$WRK" 2>/dev/null || true
rm -f "$ART/admin.jwt" "$WRK/admin.jwt" 2>/dev/null || true
# Redact any accidental secret leakage from logs copied beside verdict.
while IFS= read -r -d '' f; do
  portal_redact_file "$f"
done < <(find "$ART" -type f \( -name '*.json' -o -name '*.log' -o -name '*.txt' -o -name '*.yaml' -o -name '*.html' \) -print0)

if [[ ! -f "$VERDICT_OUT" ]]; then
  echo "FAIL: evaluator wrote no verdict" >&2
  exit 1
fi

# Surface evaluator summary without secrets.
python3 -B - "$VERDICT_OUT" <<'PY'
import json, sys
from pathlib import Path
v = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(
    f"evaluator status={v.get('status')} high={v.get('high_alerts')} "
    f"medium={v.get('medium_alerts')} notes={v.get('notes')}"
)
PY

if [[ "$EVAL_RC" -ne 0 ]]; then
  echo "FAIL: isolated ZAP AF suite (evaluator rc=$EVAL_RC)" >&2
  exit "$EVAL_RC"
fi
echo "PASS: isolated ZAP AF (portal web via run_af_disposable.py) → $ART"
