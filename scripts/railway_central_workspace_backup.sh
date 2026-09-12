#!/usr/bin/env bash
# Export Railway central /workspace (and optional mqtt certs) before re-pin.
# Requires: railway CLI linked to gleaming-cooperation / production.
# Secrets stay in the tarball on local disk - never commit backups.
#
# Wave M D5: fail hard on tar errors (no concatenated/partial fallback stream).
set -euo pipefail

UTC="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_ROOT="${OPENFDD_BACKUP_ROOT:-$HOME/openfdd-backups/railway}/${UTC}"
CENTRAL_SVC="${OPENFDD_RAILWAY_CENTRAL_SVC:-openfdd-central-cQ-F}"
MQTT_SVC="${OPENFDD_RAILWAY_MQTT_SVC:-openfdd-mqtt}"
INCLUDE_MQTT_CERTS="${OPENFDD_BACKUP_MQTT_CERTS:-1}"
MIN_BYTES="${OPENFDD_BACKUP_MIN_BYTES:-1024}"

mkdir -p "$OUT_ROOT"
echo "backup dir: $OUT_ROOT"

command -v railway >/dev/null || { echo "railway CLI required" >&2; exit 1; }
railway whoami >/dev/null

echo "=== inventory central /workspace (sample) ==="
railway ssh -s "$CENTRAL_SVC" -- sh -lc 'ls -la /workspace 2>/dev/null; du -sh /workspace /workspace/openfdd /workspace/mqtt 2>/dev/null || true' \
  | tee "$OUT_ROOT/central-workspace-inventory.txt"

echo "=== tar central /workspace -> local (authoritative trees only) ==="
# Prefer openfdd + mqtt trees. If either is missing, fail (do NOT fall back to
# piping a second tar into the same file - that concatenates garbage).
TMP_TAR="$OUT_ROOT/central-workspace.tgz.partial"
rm -f "$TMP_TAR" "$OUT_ROOT/central-workspace.tgz"
set +e
railway ssh -s "$CENTRAL_SVC" -- sh -lc \
  'set -e; test -d /workspace/openfdd; tar -C /workspace -czf - --exclude=".cache/*" openfdd mqtt' \
  >"$TMP_TAR"
TAR_RC=$?
set -e
if [[ "$TAR_RC" -ne 0 ]]; then
  echo "ERROR: authoritative backup tar failed (rc=$TAR_RC); refusing partial/concat fallback" >&2
  rm -f "$TMP_TAR"
  exit "$TAR_RC"
fi
BYTES=$(wc -c <"$TMP_TAR" | tr -d ' ')
if [[ "$BYTES" -lt "$MIN_BYTES" ]]; then
  echo "ERROR: backup tarball too small ($BYTES bytes < $MIN_BYTES)" >&2
  rm -f "$TMP_TAR"
  exit 1
fi
# Basic gzip magic check
python3 - <<'PY' "$TMP_TAR"
import sys
path = sys.argv[1]
with open(path, "rb") as f:
    magic = f.read(2)
if magic != b"\x1f\x8b":
    raise SystemExit(f"ERROR: not a gzip stream: {path}")
print("gzip magic OK")
PY
mv "$TMP_TAR" "$OUT_ROOT/central-workspace.tgz"

ls -lh "$OUT_ROOT/central-workspace.tgz"
sha256sum "$OUT_ROOT/central-workspace.tgz" | tee "$OUT_ROOT/central-workspace.sha256"

if [[ "$INCLUDE_MQTT_CERTS" == "1" ]]; then
  echo "=== tar mqtt /mosquitto/certs ==="
  set +e
  railway ssh -s "$MQTT_SVC" -- sh -lc 'tar -C /mosquitto/certs -czf - .' \
    > "$OUT_ROOT/mqtt-certs.tgz"
  MQTT_RC=$?
  set -e
  if [[ "$MQTT_RC" -ne 0 || ! -s "$OUT_ROOT/mqtt-certs.tgz" ]]; then
    echo "WARN: mqtt certs backup skipped (rc=${MQTT_RC:-?})" >&2
    rm -f "$OUT_ROOT/mqtt-certs.tgz"
  else
    ls -lh "$OUT_ROOT/mqtt-certs.tgz"
    sha256sum "$OUT_ROOT/mqtt-certs.tgz" | tee "$OUT_ROOT/mqtt-certs.sha256"
  fi
fi

cat > "$OUT_ROOT/README.txt" <<EOF
Railway hub backup $UTC
central service: $CENTRAL_SVC
mqtt service: $MQTT_SVC
Contents: openfdd + mqtt trees under /workspace (no concat fallback).
Restore (data only - never auto-overwrite newer telemetry without operator review):
  railway ssh -s $CENTRAL_SVC -- sh -lc 'cd /workspace && tar -xzf -' < central-workspace.tgz
Code/config rollback is separate from data restore - see docs/operations/backup-update-restore.md
Never commit this directory. Never delete the Railway volume for an upgrade.
EOF

echo "DONE: $OUT_ROOT"
