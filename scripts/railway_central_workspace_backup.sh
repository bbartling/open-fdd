#!/usr/bin/env bash
# Export Railway central /workspace (and optional mqtt certs) before re-pin.
# Requires: railway CLI linked to gleaming-cooperation / production.
# Secrets stay in the tarball on local disk — never commit backups.
set -euo pipefail

UTC="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_ROOT="${OPENFDD_BACKUP_ROOT:-$HOME/openfdd-backups/railway}/${UTC}"
CENTRAL_SVC="${OPENFDD_RAILWAY_CENTRAL_SVC:-openfdd-central-cQ-F}"
MQTT_SVC="${OPENFDD_RAILWAY_MQTT_SVC:-openfdd-mqtt}"
INCLUDE_MQTT_CERTS="${OPENFDD_BACKUP_MQTT_CERTS:-1}"

mkdir -p "$OUT_ROOT"
echo "backup dir: $OUT_ROOT"

command -v railway >/dev/null || { echo "railway CLI required" >&2; exit 1; }
railway whoami >/dev/null

echo "=== inventory central /workspace (sample) ==="
railway ssh -s "$CENTRAL_SVC" -- bash -lc 'ls -la /workspace 2>/dev/null; du -sh /workspace /workspace/openfdd /workspace/mqtt 2>/dev/null || true' \
  | tee "$OUT_ROOT/central-workspace-inventory.txt"

echo "=== tar central /workspace → local ==="
# Pipe tar over ssh; exclude huge caches if present
railway ssh -s "$CENTRAL_SVC" -- bash -lc \
  'tar -C /workspace -czf - --exclude=".cache/*" openfdd mqtt 2>/dev/null || tar -C /workspace -czf - .' \
  > "$OUT_ROOT/central-workspace.tgz"

ls -lh "$OUT_ROOT/central-workspace.tgz"
sha256sum "$OUT_ROOT/central-workspace.tgz" | tee "$OUT_ROOT/central-workspace.sha256"

if [[ "$INCLUDE_MQTT_CERTS" == "1" ]]; then
  echo "=== tar mqtt /mosquitto/certs ==="
  railway ssh -s "$MQTT_SVC" -- bash -lc 'tar -C /mosquitto/certs -czf - .' \
    > "$OUT_ROOT/mqtt-certs.tgz" || echo "WARN: mqtt certs backup skipped" >&2
  if [[ -s "$OUT_ROOT/mqtt-certs.tgz" ]]; then
    ls -lh "$OUT_ROOT/mqtt-certs.tgz"
    sha256sum "$OUT_ROOT/mqtt-certs.tgz" | tee "$OUT_ROOT/mqtt-certs.sha256"
  fi
fi

cat > "$OUT_ROOT/README.txt" <<EOF
Railway hub backup $UTC
central service: $CENTRAL_SVC
mqtt service: $MQTT_SVC
Restore: railway ssh -s $CENTRAL_SVC -- bash -lc 'cd /workspace && tar -xzf -' < central-workspace.tgz
Never commit this directory. Never delete the Railway volume for an upgrade.
EOF

echo "DONE: $OUT_ROOT"
