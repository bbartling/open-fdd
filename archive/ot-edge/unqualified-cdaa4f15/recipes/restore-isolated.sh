#!/usr/bin/env bash
# Isolated OT archive restore/replay lane.
# Renders the digest-pinned compose file and checks the pin. Does not pull,
# start containers, or write a database.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIN="$ROOT/evidence/oci-pin.json"
MODE="${1:-}"

if [[ "${OPENFDD_OT_ARCHIVE_RESTORE:-}" != "1" ]]; then
  echo "Refusing restore: set OPENFDD_OT_ARCHIVE_RESTORE=1 (explicit archive lane)." >&2
  exit 2
fi
if [[ "$MODE" == "--boot" ]]; then
  echo "Refusing boot: this lane does not start containers or deploy." >&2
  echo "Use --replay to render the pinned compose file. See ${ROOT}/evidence/MISSING.md" >&2
  exit 2
fi
if [[ -n "$MODE" && "$MODE" != "--replay" ]]; then
  echo "Usage: OPENFDD_OT_ARCHIVE_RESTORE=1 $0 [--replay|--boot]" >&2
  exit 2
fi

eval "$(python3 - "$PIN" <<'PY'
import json, shlex, sys
pin = json.load(open(sys.argv[1]))
wanted = {"openfdd-fieldbus": "OPENFDD_OT_FIELDBUS_DIGEST", "openfdd-mqtt": "OPENFDD_OT_MQTT_DIGEST"}
found = {}
for image in pin["images"]:
    key = wanted.get(image["package"])
    if key:
        found[key] = image["index_digest"]
missing = [name for name in wanted.values() if name not in found]
if missing:
    raise SystemExit("pin missing " + ", ".join(missing))
for key, digest in found.items():
    print(f"export {key}={shlex.quote(digest)}")
PY
)"

rendered="$(docker compose -f "${ROOT}/recipes/compose.ot-archive.yml" config)"
printf '%s\n' "$rendered"
for digest in "$OPENFDD_OT_FIELDBUS_DIGEST" "$OPENFDD_OT_MQTT_DIGEST"; do
  if ! grep -q "$digest" <<<"$rendered"; then
    echo "Rendered compose is missing pinned digest $digest" >&2
    exit 1
  fi
done
if grep -E 'openfdd-central|openfdd-web|timescale|:/var/lib/postgresql' <<<"$rendered" >/dev/null; then
  echo "Rendered archive compose must not attach central, web, or a database." >&2
  exit 1
fi
# Boundary checks (workspace exclude, pin, checksums) run in the protocol job
# via scripts/archive/verify_ot_edge_snapshot.py. This lane only renders compose.
echo "Replay render only. No containers were started. 4.0 databases are out of scope."
