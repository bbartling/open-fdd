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
# Never activeScans live Railway or a site. Never persists JWT to the artifact dir.
# The scanner credential is handed to the evaluator through a private 0600 file
# outside the artifact dir. A negative control (broken scanner credential)
# must be rejected before the real scan runs.
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
# UA-04: token stays in the private dir, never in the artifact tree or argv.
AUTH_FILE="$PORTAL_PRIV/scanner_auth_header"
printf 'Bearer %s' "$(cat "$PORTAL_PRIV/tok.admin")" >"$AUTH_FILE"
chmod 600 "$AUTH_FILE"
if [[ "$(wc -c <"$AUTH_FILE")" -lt 20 ]]; then
  echo "FAIL: could not mint admin JWT for ZAP context" >&2
  exit 1
fi
rm -f "$ART/admin.jwt" "$WRK/admin.jwt" 2>/dev/null || true
echo "OK admin JWT minted (ephemeral env only; private file outside artifacts)"

# Evaluator owns AF plan materialization + verdict; wrapper only mints candidate.
export OPENFDD_ZAP_AF_EXECUTE=1
export OPENFDD_ZAP_IMAGE="$ZAP_IMAGE"
export OPENFDD_ZAP_REQUIRE_DIGEST=1
export ZAP_TARGET_ORIGIN="$TARGET_ORIGIN"
export ZAP_AUTH_HEADER_FILE="$AUTH_FILE"
export OPENFDD_ZAP_EXPECTED_USERNAME="admin"
export ZAP_DOCKER_NETWORK="$ZAP_NET"
unset OPENFDD_ADMIN_PASSWORD OPENFDD_JWT_SECRET
VERDICT_OUT="$ART/verdict.json"

NEG_WRK="$ART/zap_wrk_negative"
mkdir -p "$NEG_WRK"
chmod 777 "$NEG_WRK"
cp "$WRK/openapi.yaml" "$NEG_WRK/openapi.yaml"
set +e
ZAP_AF_WORK_DIR="$NEG_WRK" OPENFDD_ZAP_AF_ACTIVE=0 \
  python3 -B "$ROOT/scripts/qualification/zap/run_af_disposable.py" \
  --negative-control --out "$ART/negative_control_verdict.json" \
  >"$PORTAL_PRIV/zap-negative.stdout" 2>"$PORTAL_PRIV/zap-negative.stderr"
NEG_RC=$?
set -e
if [[ "$NEG_RC" -ne 0 ]]; then
  echo "FAIL: negative control did not reject a broken scanner credential (rc=$NEG_RC)" >&2
  exit 1
fi

export ZAP_AF_WORK_DIR="$WRK"
set +e
python3 -B "$ROOT/scripts/qualification/zap/run_af_disposable.py" \
  --out "$VERDICT_OUT" \
  >"$PORTAL_PRIV/zap-evaluator.stdout" 2>"$PORTAL_PRIV/zap-evaluator.stderr"
EVAL_RC=$?
set -e

# Buffer evaluator output until cleanup has verified that its hashed evidence
# is unchanged. Redaction must never silently turn altered evidence into PASS.
INTEGRITY=(python3 -B "$ROOT/scripts/qualification/zap/artifact_integrity.py"
  --root "$ART" --state "$PORTAL_PRIV/zap-artifacts-before.json"
  --report "$ART/artifact_integrity.json" --verdict "$VERDICT_OUT"
  --verdict "$ART/negative_control_verdict.json")
if ! "${INTEGRITY[@]}" snapshot; then
  echo "FAIL: could not snapshot evaluated ZAP evidence; qualification invalid" >&2
  exit 1
fi
REDACTION_FAILED=0
chmod -R u+rwX,g+rwX,o-rwx "$WRK" 2>/dev/null || REDACTION_FAILED=1
rm -f "$ART/admin.jwt" "$WRK/admin.jwt" 2>/dev/null || REDACTION_FAILED=1
if ! find "$ART" -type f \( -name '*.json' -o -name '*.log' -o -name '*.txt' -o -name '*.yaml' -o -name '*.html' \) -print0 \
  >"$PORTAL_PRIV/zap-redaction-files"; then
  REDACTION_FAILED=1
fi
while IFS= read -r -d '' f; do
  portal_redact_file "$f" || REDACTION_FAILED=1
done <"$PORTAL_PRIV/zap-redaction-files"
INTEGRITY_FLAGS=()
if [[ "$REDACTION_FAILED" -ne 0 ]]; then
  INTEGRITY_FLAGS+=(--redaction-failed)
fi
if ! "${INTEGRITY[@]}" verify "${INTEGRITY_FLAGS[@]}"; then
  echo "FAIL: cleanup changed evaluated ZAP evidence; qualification invalid" >&2
  exit 1
fi

if [[ ! -f "$VERDICT_OUT" ]]; then
  echo "FAIL: evaluator wrote no verdict" >&2
  exit 1
fi

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
