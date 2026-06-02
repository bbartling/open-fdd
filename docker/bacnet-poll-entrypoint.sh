#!/usr/bin/env bash
# BACnet poll driver — reads commission.env on the mounted workspace volume.
set -euo pipefail

ENV_FILE="${COMMISSION_ENV:-/var/openfdd/workspace/bacnet/commissioning/commission.env}"
POINTS="${POINTS_CSV:-/var/openfdd/workspace/bacnet/commissioning/points.csv}"
OUTPUT="${POLLS_CSV:-/var/openfdd/workspace/bacnet/polls/samples.csv}"
INTERVAL="${BACNET_POLL_INTERVAL:-60}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "bacnet-poll: missing $ENV_FILE — mount workspace and run commission deploy first" >&2
  exit 1
fi

declare -A CFG=()
while IFS='=' read -r key value; do
  key="${key//$'\r'/}"
  value="${value//$'\r'/}"
  [[ -z "$key" || "$key" =~ ^# ]] && continue
  CFG["$key"]="$value"
done < "$ENV_FILE"

NAME="${CFG[BACNET_NAME]:-OpenFddEdge}"
INSTANCE="${CFG[BACNET_INSTANCE]:-599999}"
BIND="${CFG[BACNET_BIND]:-0.0.0.0/24:47808}"

ARGS=(
  python -m bacnet_toolshed.poll_driver
  --config "$POINTS"
  --interval "$INTERVAL"
  --name "$NAME"
  --instance "$INSTANCE"
  --address "$BIND"
  --output "$OUTPUT"
)

if [[ -n "${CFG[ROUTER_IP]:-}" ]]; then
  ARGS+=(--route-aware --network "${CFG[BACNET_NETWORK]:-1}" --router-ip "${CFG[ROUTER_IP]}" --mstp-net "${CFG[MSTP_NET]:-2000}")
fi

exec "${ARGS[@]}"
