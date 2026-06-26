#!/usr/bin/env bash
# Start Open-FDD bridge + Caddy for remote LAN dial-in (same auth.env.local as production).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${OPENFDD_CADDY_MODE:-tls}"
LAN_IP=""
FORCE_CERTS=0

usage() {
  cat <<'EOF'
Usage: scripts/openfdd_local_caddy_up.sh [--mode http|tls] [--lan-ip ADDR] [--regen-certs]

Production-like local ingress: Caddy on 0.0.0.0:80 and :443, bridge internal only.
Uses workspace/auth.env.local (same JWT users as production).

  --mode tls        HTTPS with self-signed certs (default, recommended)
  --mode http       HTTP only on port 80
  --lan-ip ADDR     Include LAN IP in cert SANs (default: first non-loopback IP)
  --regen-certs     Regenerate cert.pem/key.pem before starting Caddy

After start:
  https://<LAN-IP>/     (accept browser cert warning)
  Login: integrator + password from workspace/bootstrap_credentials.once.txt
         (auth.env.local stores bcrypt hashes only — not login passwords)

Requires: open-fdd-openfdd-bridge:local image (run ./scripts/openfdd_local_up.sh --build first)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --lan-ip) LAN_IP="$2"; shift 2 ;;
    --regen-certs) FORCE_CERTS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "$MODE" != "http" && "$MODE" != "tls" ]]; then
  echo "ERROR: --mode must be http or tls" >&2
  exit 2
fi

if ! docker image inspect open-fdd-openfdd-bridge:local >/dev/null 2>&1; then
  echo "ERROR: missing image open-fdd-openfdd-bridge:local"
  echo "Run: ./scripts/openfdd_local_up.sh --build"
  exit 1
fi

if [[ ! -f "$ROOT/workspace/auth.env.local" ]]; then
  echo "ERROR: missing workspace/auth.env.local"
  exit 1
fi

if [[ -z "$LAN_IP" ]]; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi
if [[ -z "$LAN_IP" ]]; then
  LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')"
fi

CERT_DIR="$ROOT/workspace/deploy/caddy/certs"
mkdir -p "$CERT_DIR"

if [[ "$MODE" == "tls" ]]; then
  if [[ "$FORCE_CERTS" -eq 1 || ! -f "$CERT_DIR/cert.pem" || ! -f "$CERT_DIR/key.pem" ]]; then
    echo "==> Generating self-signed TLS certs (CN=openfdd.local SAN: localhost + ${LAN_IP:-none})"
    cert_extra=()
    if [[ -n "$LAN_IP" ]]; then
      cert_extra=(--lan-ip "$LAN_IP")
    fi
    docker run --rm \
      --user "$(id -u):$(id -g)" \
      -v "$ROOT/workspace:/app/workspace" \
      open-fdd-openfdd-bridge:local \
      openfdd-edge tls generate --cn openfdd.local --out /app/workspace/deploy/caddy/certs \
      "${cert_extra[@]}"
  fi
  export OPENFDD_CADDY_FILE="$ROOT/docker/caddy/Caddyfile.local.tls"
else
  export OPENFDD_CADDY_FILE="$ROOT/docker/caddy/Caddyfile.local.http"
fi

export OPENFDD_CADDY_MODE="$MODE"
export OPENFDD_CADDY_HOSTNAME="${OPENFDD_CADDY_HOSTNAME:-openfdd.local}"

echo "==> Starting bridge + Caddy (mode=$MODE)"
docker compose \
  -f "$ROOT/docker-compose.local.yml" \
  -f "$ROOT/docker-compose.local.caddy.yml" \
  --profile caddy \
  up -d --no-build openfdd-bridge openfdd-caddy

sleep 2

if [[ "$MODE" == "tls" ]]; then
  echo "==> Waiting for HTTPS health…"
  for i in $(seq 1 20); do
    if curl -kfsS "https://127.0.0.1/api/health" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
  curl -kfsS "https://127.0.0.1/api/health" || true
  echo
else
  curl -fsS "http://127.0.0.1/api/health" || true
  echo
fi

echo ""
echo "==> Remote dial-in (same auth as workspace/auth.env.local)"
if [[ -n "$LAN_IP" ]]; then
  if [[ "$MODE" == "tls" ]]; then
    echo "    https://${LAN_IP}/"
    echo "    https://${OPENFDD_CADDY_HOSTNAME}/  (add to client /etc/hosts: ${LAN_IP} ${OPENFDD_CADDY_HOSTNAME})"
  else
    echo "    http://${LAN_IP}/"
  fi
else
  echo "    Could not detect LAN IP — use: ip -4 addr show"
fi
echo "    Login users: operator, integrator, agent"
echo "    Passwords: workspace/bootstrap_credentials.once.txt (plaintext)"
echo "               auth.env.local stores bcrypt hashes only — do not use as login password"
if [[ "$MODE" == "tls" ]]; then
  echo "    Browser: accept self-signed certificate warning (expected for lab TLS)"
fi
echo ""
echo "    If remote host cannot connect, allow firewall: sudo ufw allow 443/tcp"
