#!/usr/bin/env bash
# Wave M D5 - one dependable Railway release orchestrator (agents + humans).
#
# Dry-run / preflight by default. Mutation requires OPENFDD_RELEASE_EXECUTE=1.
# Never prints tokens, PEMs, or full Railway variable dumps.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

UTC="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_ROOT="${OPENFDD_RELEASE_OUT:-$HOME/openfdd-releases/${UTC}}"
PROJECT="${OPENFDD_RAILWAY_PROJECT:-gleaming-cooperation}"
ENV_NAME="${OPENFDD_RAILWAY_ENV:-production}"
CENTRAL_SVC="${OPENFDD_RAILWAY_CENTRAL_SVC:-openfdd-central-cQ-F}"
WEB_SVC="${OPENFDD_RAILWAY_WEB_SVC:-openfdd-web}"
MQTT_SVC="${OPENFDD_RAILWAY_MQTT_SVC:-openfdd-mqtt}"
EXECUTE="${OPENFDD_RELEASE_EXECUTE:-0}"
LOCK_FILE="${OPENFDD_RELEASE_LOCK:-/tmp/openfdd-railway-release.lock}"
HUB_BASE="${OPENFDD_API_BASE:-https://openfdd-web-production-af99.up.railway.app}"
SOURCE_SHA="${OPENFDD_RELEASE_SOURCE_SHA:-$(git rev-parse HEAD)}"
SHORT_SHA="$(git rev-parse --short=7 "$SOURCE_SHA")"
TAG="sha-${SHORT_SHA}"
TIMEOUT_SECS="${OPENFDD_RELEASE_TIMEOUT_SECS:-900}"

mkdir -p "$OUT_ROOT"
MANIFEST="$OUT_ROOT/release_manifest.json"
LOG="$OUT_ROOT/release.log"
exec > >(tee -a "$LOG") 2>&1

redact() {
  sed -E \
    -e 's/(Bearer )[A-Za-z0-9._-]+/\1REDACTED/g' \
    -e 's/(password|token|secret|pem)=[^ ]+/\1=REDACTED/gi'
}

fail() {
  echo "ERROR: $*" >&2
  python3 - <<PY
import json, pathlib
p = pathlib.Path("$MANIFEST")
data = {}
if p.exists():
    data = json.loads(p.read_text())
data.update({
  "ok": False,
  "error": """$*""",
  "finished_at_utc": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
})
p.write_text(json.dumps(data, indent=2) + "\n")
PY
  exit 1
}

echo "=== Open-FDD Railway release orchestrator ==="
echo "utc=$UTC execute=$EXECUTE project=$PROJECT env=$ENV_NAME tag=$TAG"

command -v railway >/dev/null || fail "railway CLI required"
command -v jq >/dev/null || fail "jq required"
railway whoami >/dev/null || fail "railway whoami failed"

# Atomic lock: mkdir fails if another release holds the lock (no TOCTOU race).
LOCK_DIR="${LOCK_FILE}.d"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  fail "deployment lock exists: $LOCK_DIR (another release in progress?)"
fi
echo "$UTC $$ $TAG" >"$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

echo "=== tip completeness (GHCR) ==="
./scripts/check_ghcr_tip_stack.sh "$TAG" | redact || fail "GHCR tip stack check failed for $TAG"

CENTRAL_DIGEST="$(
  python3 - <<PY
import json, urllib.request
# Prefer skopeo/crane when available; else record tag only.
print("")
PY
)"

python3 - <<PY
import json, pathlib, datetime
pathlib.Path("$MANIFEST").write_text(json.dumps({
  "ok": False,
  "phase": "preflight",
  "started_at_utc": "$UTC",
  "project": "$PROJECT",
  "environment": "$ENV_NAME",
  "services": {
    "central": "$CENTRAL_SVC",
    "web": "$WEB_SVC",
    "mqtt": "$MQTT_SVC",
  },
  "source_sha": "$SOURCE_SHA",
  "image_tag": "$TAG",
  "hub_base": "$HUB_BASE",
  "execute": "$EXECUTE" == "1",
  "previous_known_good_note": "ops pin recorded in BUG_REPORT; do not invent digests",
}, indent=2) + "\n")
PY

echo "=== dry-run / preflight backup ==="
BACKUP_ROOT="$OUT_ROOT/backup"
OPENFDD_BACKUP_ROOT="$BACKUP_ROOT" ./scripts/railway_central_workspace_backup.sh \
  || fail "validated backup required before mutation"

echo "=== verify hub health (current) ==="
HEALTH_JSON="$(curl -sf --max-time 30 "$HUB_BASE/api/health" || true)"
if [[ -z "$HEALTH_JSON" ]]; then
  fail "could not read current /api/health from $HUB_BASE"
fi
echo "$HEALTH_JSON" | jq '{ok, service, version, multi_tenant}' | redact
PREV_VERSION="$(echo "$HEALTH_JSON" | jq -r '.version // empty')"

if [[ "$EXECUTE" != "1" ]]; then
  python3 - <<PY
import json, pathlib, datetime
p = pathlib.Path("$MANIFEST")
data = json.loads(p.read_text())
data.update({
  "ok": True,
  "phase": "dry_run_complete",
  "previous_version": """$PREV_VERSION""",
  "backup_dir": """$BACKUP_ROOT""",
  "finished_at_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
  "message": "Dry-run OK. Re-run with OPENFDD_RELEASE_EXECUTE=1 to mutate Railway pins.",
})
p.write_text(json.dumps(data, indent=2) + "\n")
print(json.dumps(data, indent=2))
PY
  echo "DRY-RUN complete - no Railway mutation. Manifest: $MANIFEST"
  exit 0
fi

echo "=== EXECUTE: re-pin services to $TAG (bounded timeout ${TIMEOUT_SECS}s) ==="
# Explicit image identity - agents must not improvise ad-hoc railway sequences.
# Prefer existing ops pin scripts when present; otherwise document BLOCKED.
if [[ -x "$ROOT/scripts/railway_repin_hub.sh" ]]; then
  timeout "$TIMEOUT_SECS" env OPENFDD_IMAGE_TAG="$TAG" "$ROOT/scripts/railway_repin_hub.sh" \
    || fail "repin timed out or failed"
else
  fail "OPENFDD_RELEASE_EXECUTE=1 but scripts/railway_repin_hub.sh missing - refuse improvised pin"
fi

echo "=== post-rollout verify (central / web / broker health surfaces) ==="
DEADLINE=$((SECONDS + 180))
NEW_VERSION=""
HEALTH_OK=""
while (( SECONDS < DEADLINE )); do
  HEALTH_JSON="$(curl -sf --max-time 20 "$HUB_BASE/api/health" || true)"
  if [[ -n "$HEALTH_JSON" ]]; then
    HEALTH_OK="$(echo "$HEALTH_JSON" | jq -r 'if .ok == true then "1" else "" end' 2>/dev/null || true)"
    NEW_VERSION="$(echo "$HEALTH_JSON" | jq -r '.version // empty' 2>/dev/null || true)"
    if [[ "$HEALTH_OK" == "1" && -n "$NEW_VERSION" && "$NEW_VERSION" == *"$SHORT_SHA"* ]]; then
      break
    fi
  fi
  NEW_VERSION=""
  HEALTH_OK=""
  sleep 5
done
[[ "$HEALTH_OK" == "1" && -n "$NEW_VERSION" && "$NEW_VERSION" == *"$SHORT_SHA"* ]] \
  || fail "post-rollout health failed (ok='$HEALTH_OK' version='$NEW_VERSION', want ok=true + *$SHORT_SHA*)"

# Structured compare (not SHA-OR-semver regex)
python3 - <<PY
import json, pathlib, datetime, re
prev = """$PREV_VERSION"""
new = """$NEW_VERSION"""
def parts(v):
    m = re.match(r"^([0-9]+(?:\.[0-9]+)*)(?:\+([0-9a-fA-F]+))?$", v.strip())
    if not m:
        raise SystemExit(f"unstructured version: {v!r}")
    return m.group(1), (m.group(2) or "")[:7]
ps, psha = parts(prev) if prev else ("", "")
ns, nsha = parts(new)
assert nsha == """$SHORT_SHA"""[:7] or nsha.startswith("""$SHORT_SHA"""[:7])
path = pathlib.Path("$MANIFEST")
data = json.loads(path.read_text())
data.update({
  "ok": True,
  "phase": "executed",
  "previous_version": prev,
  "new_version": new,
  "previous_semver": ps,
  "new_semver": ns,
  "backup_dir": """$BACKUP_ROOT""",
  "finished_at_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
})
path.write_text(json.dumps(data, indent=2) + "\n")
print(json.dumps(data, indent=2))
PY

echo "RELEASE OK - manifest $MANIFEST"
echo "Reminder: code/config rollback != data restore. See backup-update-restore.md"
