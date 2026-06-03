#!/usr/bin/env bash
# Reset local Docker dev workspace for bensserver MSTP test bench (device 5007).
# Keeps Acme artifacts in edge_backup/local/acme/ — does not touch Acme deploy.
#
#   ./scripts/setup_local_testbench.sh              # discover + model + rules + verify
#   ./scripts/setup_local_testbench.sh --skip-discover  # reuse points_discovered.csv
#   ./scripts/setup_local_testbench.sh --no-docker     # files only, no compose restart
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VENV="${ROOT}/.venv"
COMPOSE=(docker compose -f docker/compose.dev.yml -f docker/compose.bench.yml)
BENCH_BACKUP="${ROOT}/edge_backup/local/demo/bens-office"
ACME_BACKUP="${ROOT}/edge_backup/local/acme/vm-bbartling"
COMMISSION_ENV="${ROOT}/workspace/bacnet/commissioning/commission.env"
DISCOVERED="${ROOT}/workspace/bacnet/commissioning/points_discovered.csv"
POINTS="${ROOT}/workspace/bacnet/commissioning/points.csv"
SKIP_DISCOVER=0
NO_DOCKER=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-discover) SKIP_DISCOVER=1; shift ;;
    --no-docker) NO_DOCKER=1; shift ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

if [[ ! -x "${VENV}/bin/python" ]]; then
  python3 -m venv "$VENV"
  "${VENV}/bin/pip" install -q -e ".[dev]" -r bacnet_toolshed/requirements.txt
fi

export OPENFDD_REPO_ROOT="$ROOT"
export OPENFDD_WORKSPACE_DIR="${ROOT}/workspace"
export OFDD_DESKTOP_DATA_DIR="${ROOT}/workspace/data"
export PYTHONPATH="${ROOT}:${ROOT}/workspace/api"

echo "==> Archive workspace BACnet CSVs (if Acme-tainted) to ${ACME_BACKUP}/"
mkdir -p "$BENCH_BACKUP" "$ACME_BACKUP"
if [[ -f "$POINTS" ]] && head -2 "$POINTS" | grep -q ',acme,'; then
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  cp -a "$POINTS" "${ACME_BACKUP}/points.csv.workspace-${ts}"
  echo "    saved ${ACME_BACKUP}/points.csv.workspace-${ts}"
fi

echo "==> Reset local poll CSV / feather scratch (keep rules_py)"
rm -f "${ROOT}/workspace/bacnet/polls/samples.csv"
find "${ROOT}/workspace/data/feather_store" -name 'latest.*' -delete 2>/dev/null || true

if [[ "$SKIP_DISCOVER" == 0 ]]; then
  echo "==> BACnet Who-Is smoke (device ${DISCOVER_LOW:-5007})"
  "${COMPOSE[@]}" stop commission bacnet-poll 2>/dev/null || true
  sleep 2
  if ! "${VENV}/bin/python" -m bacnet_toolshed.smoke_whois --low 5007 --high 5007; then
    echo "Who-Is failed — check ${COMMISSION_ENV} (bind, ROUTER_IP, MSTP_NET)" >&2
    exit 1
  fi

  echo "==> Discover device 5007 (MS/TP via router)"
  rm -f "$DISCOVERED"
  # shellcheck disable=SC1090
  source "$COMMISSION_ENV"
  "${VENV}/bin/python" -m bacnet_toolshed.discover 5007 5007 \
    -o "$DISCOVERED" \
    --site-id "$SITE_ID" --building-id "$BUILDING_ID" \
    --name "$BACNET_NAME" --instance "$BACNET_INSTANCE" \
    --address "$BACNET_BIND" \
    --router-ip "$ROUTER_IP" --mstp-net "$MSTP_NET" \
    --timeout "${DISCOVER_TIMEOUT:-30}"
else
  echo "==> Skipping discover (using existing ${DISCOVERED})"
fi

if [[ ! -f "$DISCOVERED" ]]; then
  echo "Missing $DISCOVERED" >&2
  exit 1
fi

echo "==> Fix point_id / series_id (BACpypes ObjectType slug)"
"${VENV}/bin/python" <<'PY'
import csv
from pathlib import Path
from bacnet_toolshed.config import CSV_FIELDNAMES, normalize_row
from bacnet_toolshed.paths import commissioning_dir

for name in ("points_discovered.csv", "points.csv"):
    p = commissioning_dir() / name
    if not p.is_file():
        continue
    rows = []
    with p.open(newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            raw["point_id"] = ""
            raw["series_id"] = ""
            rows.append(normalize_row(raw))
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"    normalized {p} ({len(rows)} rows)")
PY

echo "==> Enable bench poll set (device 5007 @ 2000:7 — four analog inputs only)"
"${VENV}/bin/python" -m bacnet_toolshed.enable_points \
  --input "$DISCOVERED" \
  --output "$POINTS" \
  --object-instance analog-input,1168 \
  --object-instance analog-input,1173 \
  --object-instance analog-input,1192 \
  --object-instance analog-input,10014 \
  --poll-interval 60
mkdir -p "${ROOT}/edge_config/demo/bens-office"
cp -a "$POINTS" "${ROOT}/edge_config/demo/bens-office/points.csv"
cp -a "$POINTS" "${BENCH_BACKUP}/points.csv"
echo "    bench points backed up to ${BENCH_BACKUP}/points.csv"

echo "==> Import bench BRICK model + FDD rules (bench-only; no Acme rules)"
"${VENV}/bin/python" scripts/setup_bench_afdd.py
if [[ -x "${ROOT}/scripts/edge_site_backup.sh" ]]; then
  "${ROOT}/scripts/edge_site_backup.sh" demo bens-office
  mkdir -p "${ROOT}/edge_config/demo/bens-office"
  cp -a "${BENCH_BACKUP}/model.json" "${BENCH_BACKUP}/rules_store.json" \
    "${BENCH_BACKUP}/points.csv" "${BENCH_BACKUP}/commission.env" \
    "${ROOT}/edge_config/demo/bens-office/" 2>/dev/null || true
fi

chmod 644 "${ROOT}/workspace/data/model.json" 2>/dev/null || true

if [[ "$NO_DOCKER" == 0 ]]; then
  echo "==> Restart Docker stack (bench overlay: host network)"
  # Poll loop runs inside commission (host network); skip bacnet-poll to avoid duplicate polls / ingest 403.
  "${COMPOSE[@]}" up -d --build bridge commission mcp-rag
  docker compose -f docker/compose.dev.yml -f docker/compose.bench.yml --profile bacnet stop bacnet-poll 2>/dev/null || true
  sleep 8
  ./scripts/openfdd_stack.sh health || true
  if [[ -x "${ROOT}/scripts/stack_health_check.sh" ]]; then
    OPENFDD_BASE_URL=http://127.0.0.1:8765 "${ROOT}/scripts/stack_health_check.sh" || true
  fi
fi

echo "==> Operational verify (localhost)"
if [[ -f "${ROOT}/infra/ansible/scripts/bench_operational_verify.sh" ]]; then
  RUN_WAIT_MINUTES=2 SKIP_WAIT=0 \
    "${ROOT}/infra/ansible/scripts/bench_operational_verify.sh" \
    --host 127.0.0.1 --port 8765 --wait-minutes 2 || true
fi

echo ""
echo "OK — local test bench ready."
echo "  UI:      http://127.0.0.1:8765/  (integrator / msi-local)"
echo "  Bench:   edge_backup/local/demo/bens-office/"
echo "  Acme:    edge_backup/local/acme/vm-bbartling/ (unchanged)"
echo "  BACnet:  ${COMMISSION_ENV}"
