#!/usr/bin/env bash
# Live Acme post-deploy validation after GHCR image updates (read-only by default).
#
#   OPENFDD_IMAGE_TAG=v3.0.32 ./scripts/acme_post_deploy_validate.sh --limit acme_vm_bbartling --full
#   OPENFDD_IMAGE_TAG=latest ./scripts/acme_post_deploy_validate.sh --base http://100.x.x.x --quick
#   ./scripts/acme_post_deploy_validate.sh --limit acme_vm_bbartling --full --json-out reports/acme-validate.json
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LIMIT=""
BASE=""
SITE_ID="${ACME_SITE_ID:-acme}"
BUILDING_ID="${ACME_BUILDING_ID:-vm-bbartling}"
MODE="quick"
JSON_OUT=""
JUNIT_OUT=""
MARKDOWN_OUT=""
PROFILE=""
REMOTE_JSON=""
SKIP_UI=0
SKIP_BACNET=0
SKIP_FDD=0
SKIP_RULELAB=0
SKIP_LOGS=0
NO_ANSIBLE=0
FAIL_FAST=0
ALLOW_WRITE=0
TIMEOUT_SECONDS="${ACME_VALIDATE_TIMEOUT:-600}"
EXTRA_PY=()

usage() {
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options:
  --limit <ansible-host>     Acme inventory limit (preferred)
  --base <url>               Direct bridge URL (skip inventory resolution)
  --site-id <id>             Default: acme
  --building-id <id>         Default: vm-bbartling
  --quick | --full | --long  Validation depth (default: --quick)
  --profile <json>           Threshold profile JSON
  --json-out <path>          Machine-readable report
  --junit-out <path>         JUnit XML report
  --markdown-out <path>      Markdown summary
  --skip-ui | --skip-bacnet | --skip-fdd | --skip-rulelab | --skip-logs
  --no-ansible               Skip remote host/container probes
  --fail-fast                Stop Python validator on first failure
  --timeout-seconds <n>      Remote probe timeout (default 600)
  --allow-write              Not supported (validation is read-only)

Reuses: stack_health_check.sh, acme_validate_fdd_bundle.py, validate_acme_rules_pypi.py,
        infra/ansible/scripts/http_probes.py, acme_operational_verify.sh (optional).
EOF
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --limit) LIMIT="$2"; shift 2 ;;
    --base) BASE="$2"; shift 2 ;;
    --site-id) SITE_ID="$2"; shift 2 ;;
    --building-id) BUILDING_ID="$2"; shift 2 ;;
    --quick) MODE="quick"; shift ;;
    --full) MODE="full"; shift ;;
    --long) MODE="long"; shift ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --json-out) JSON_OUT="$2"; shift 2 ;;
    --junit-out) JUNIT_OUT="$2"; shift 2 ;;
    --markdown-out) MARKDOWN_OUT="$2"; shift 2 ;;
    --skip-ui) SKIP_UI=1; shift ;;
    --skip-bacnet) SKIP_BACNET=1; shift ;;
    --skip-fdd) SKIP_FDD=1; shift ;;
    --skip-rulelab) SKIP_RULELAB=1; shift ;;
    --skip-logs) SKIP_LOGS=1; shift ;;
    --no-ansible) NO_ANSIBLE=1; shift ;;
    --fail-fast) FAIL_FAST=1; shift ;;
    --timeout-seconds) TIMEOUT_SECONDS="$2"; shift 2 ;;
    --allow-write) ALLOW_WRITE=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown: $1" >&2; usage 1 ;;
  esac
done

if [[ "$ALLOW_WRITE" == "1" ]]; then
  echo "error: --allow-write is not supported for live Acme validation" >&2
  exit 2
fi

if [[ -z "$BASE" && -z "$LIMIT" ]]; then
  echo "error: provide --base <url> or --limit <inventory_host>" >&2
  usage 1
fi

TAG="${OPENFDD_IMAGE_TAG:-}"
if [[ -n "$TAG" ]]; then
  # shellcheck source=scripts/openfdd_normalize_image_tag.sh
  source "${ROOT}/scripts/openfdd_normalize_image_tag.sh"
  TAG="$(normalize_openfdd_image_tag "$TAG")"
  export OPENFDD_IMAGE_TAG="$TAG"
fi
if [[ -z "$TAG" ]]; then
  echo "warn: OPENFDD_IMAGE_TAG not set — Docker image tag checks are best-effort" >&2
fi

REMOTE_JSON="$(mktemp)"
trap 'rm -f "$REMOTE_JSON"' EXIT

if [[ "$NO_ANSIBLE" == "0" && -n "$LIMIT" ]]; then
  echo "==> Remote host probe (--limit ${LIMIT})"
  if ! timeout "${TIMEOUT_SECONDS}" "${ROOT}/infra/ansible/scripts/acme_remote_host_probe.sh" \
    --limit "$LIMIT" --json-out "$REMOTE_JSON"; then
    echo "warn: remote host probe failed (continuing with API-only checks)" >&2
    echo '{}' >"$REMOTE_JSON"
  fi
else
  echo '{}' >"$REMOTE_JSON"
fi

PY_ARGS=(
  python3 "${ROOT}/scripts/acme_live_validate.py"
  --site-id "$SITE_ID"
  --building-id "$BUILDING_ID"
  --expected-image-tag "$TAG"
  --auth-env "${ROOT}/workspace/auth.env.local"
  --acme-secrets "${ROOT}/infra/ansible/secrets/acme.env.local"
  --remote-host-json "$REMOTE_JSON"
  "--${MODE}"
)
[[ -n "$BASE" ]] && PY_ARGS+=(--base "$BASE")
[[ -z "$BASE" && -n "$LIMIT" ]] && PY_ARGS+=(--limit "$LIMIT")
[[ -n "$PROFILE" ]] && PY_ARGS+=(--profile "$PROFILE")
[[ -n "$JSON_OUT" ]] && PY_ARGS+=(--json-out "$JSON_OUT")
[[ -n "$JUNIT_OUT" ]] && PY_ARGS+=(--junit-out "$JUNIT_OUT")
[[ -n "$MARKDOWN_OUT" ]] && PY_ARGS+=(--markdown-out "$MARKDOWN_OUT")
[[ "$SKIP_UI" == "1" ]] && PY_ARGS+=(--skip-ui)
[[ "$SKIP_BACNET" == "1" ]] && PY_ARGS+=(--skip-bacnet)
[[ "$SKIP_FDD" == "1" ]] && PY_ARGS+=(--skip-fdd)
[[ "$SKIP_RULELAB" == "1" ]] && PY_ARGS+=(--skip-rulelab)
[[ "$SKIP_LOGS" == "1" ]] && PY_ARGS+=(--skip-logs)
[[ "$FAIL_FAST" == "1" ]] && PY_ARGS+=(--fail-fast)

echo "==> Acme live API validation (${MODE})"
FAIL=0
if ! "${PY_ARGS[@]}"; then
  FAIL=1
fi

# stack_health_check.sh targets local compose.dev.yml and requires MCP — skip on remote edge (--limit).
if [[ "$MODE" != "quick" && "$FAIL" == "0" && -z "$LIMIT" && -f "${ROOT}/scripts/stack_health_check.sh" ]]; then
  echo "==> stack_health_check.sh (supplemental, local dev stack only)"
  RESOLVED_BASE="$BASE"
  if [[ -z "$RESOLVED_BASE" && -n "$LIMIT" ]]; then
    RESOLVED_BASE="$(python3 -c "
from pathlib import Path
import re, sys
sys.path.insert(0, '${ROOT}')
from scripts.acme_live_validate import resolve_base_from_ansible
print(resolve_base_from_ansible('${LIMIT}'))
" 2>/dev/null || true)"
  fi
  if [[ -n "$RESOLVED_BASE" ]]; then
    OPENFDD_BASE_URL="$RESOLVED_BASE" OPENFDD_HEALTH_MIN_MODEL_EQUIPMENT="${ACME_MIN_EQUIPMENT:-10}" \
      OPENFDD_HEALTH_MIN_MODEL_POINTS="${ACME_MIN_POINTS:-50}" \
      ./scripts/stack_health_check.sh --base "$RESOLVED_BASE" || FAIL=1
  fi
fi

if [[ "$FAIL" == "1" ]]; then
  echo ""
  echo "ACME POST-DEPLOY VALIDATION — FAIL"
  echo "See report above. For UI bundle staleness, run: OPENFDD_IMAGE_TAG=${TAG:-latest} ./scripts/upgrade_edge_full.sh --limit ${LIMIT:-<host>}"
  exit 1
fi

echo ""
echo "ACME POST-DEPLOY VALIDATION — PASS"
exit 0
