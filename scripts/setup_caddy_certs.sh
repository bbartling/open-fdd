#!/usr/bin/env bash
# Generate self-signed TLS certs for Caddy (OT LAN, not public internet).
#
#   ./scripts/setup_caddy_certs.sh
#   ./scripts/setup_caddy_certs.sh --cn openfdd.local --out workspace/deploy/caddy/certs
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CN="${OFDD_CADDY_TLS_CN:-openfdd.local}"
OUT="${ROOT}/workspace/deploy/caddy/certs"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cn) CN="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--cn HOSTNAME] [--out DIR]"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl required" >&2
  exit 1
fi

mkdir -p "$OUT"
echo "Writing self-signed cert CN=$CN → $OUT"

if openssl req -x509 -newkey rsa:4096 \
  -keyout "$OUT/key.pem" \
  -out "$OUT/cert.pem" \
  -days 365 -nodes \
  -subj "/CN=${CN}" \
  -addext "subjectAltName=DNS:${CN},DNS:localhost,IP:127.0.0.1" 2>/dev/null; then
  :
else
  openssl req -x509 -newkey rsa:4096 \
    -keyout "$OUT/key.pem" \
    -out "$OUT/cert.pem" \
    -days 365 -nodes \
    -subj "/CN=${CN}"
fi
chmod 600 "$OUT/key.pem"
echo "Done. Use OFDD_CADDY_MODE=tls with Caddy."
