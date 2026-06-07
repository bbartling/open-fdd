#!/usr/bin/env bash
# Bootstrap an Open-FDD edge host: layout, docker-compose.yml, auth, BACnet bind, optional stack start.
#
#   curl -fsSL https://github.com/bbartling/open-fdd/raw/refs/heads/master/scripts/openfdd_edge_bootstrap.sh -o /tmp/openfdd_edge_bootstrap.sh
#   bash /tmp/openfdd_edge_bootstrap.sh
#   bash /tmp/openfdd_edge_bootstrap.sh --start
#
# Options:
#   --start          docker compose pull && up -d after bootstrap
#   --image-tag TAG  default: latest (falls back to 2026.06.07-edge if latest missing)
#   --repo-ref REF   GitHub branch for compose.edge.yml (tries master, then this ref)
#   --root PATH      default: ~/open-fdd
#   --force-auth     regenerate workspace/auth.env.local
#   --show-secrets   print role passwords at end (lab only)
set -euo pipefail

OPENFDD_ROOT="${OPENFDD_ROOT:-$HOME/open-fdd}"
OPENFDD_REPO_REF="${OPENFDD_REPO_REF:-master}"
OPENFDD_IMAGE_TAG="${OPENFDD_IMAGE_TAG:-latest}"
OPENFDD_IMAGE_FALLBACK="${OPENFDD_IMAGE_FALLBACK:-2026.06.07-edge}"
GITHUB_REPO="bbartling/open-fdd"
DO_START=false
FORCE_AUTH=false
SHOW_SECRETS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --start) DO_START=true; shift ;;
    --image-tag) OPENFDD_IMAGE_TAG="$2"; shift 2 ;;
    --repo-ref) OPENFDD_REPO_REF="$2"; shift 2 ;;
    --root) OPENFDD_ROOT="$2"; shift 2 ;;
    --force-auth) FORCE_AUTH=true; shift ;;
    --show-secrets) SHOW_SECRETS=true; shift ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

_github_raw() {
  local ref="$1" path="$2" dest="$3"
  curl -fsSL -o "$dest" "https://github.com/${GITHUB_REPO}/raw/refs/heads/${ref}/${path}"
}

_download_helper_scripts() {
  local scripts_dir="$1"
  mkdir -p "$scripts_dir"
  local refs=(master "${OPENFDD_REPO_REF}" fix/security-hardening-log-rotation)
  local name ref dest
  for name in openfdd_site_backup.sh openfdd_site_update.sh; do
    dest="${scripts_dir}/${name}"
    for ref in "${refs[@]}"; do
      if _github_raw "$ref" "scripts/${name}" "$dest" && [[ -s "$dest" ]]; then
        chmod +x "$dest"
        echo "    OK scripts/${name} from ${ref}"
        break
      fi
    done
  done
}

_download_compose() {
  local dest="$1"
  local refs=(master "${OPENFDD_REPO_REF}" fix/security-hardening-log-rotation)
  local seen="" ref
  for ref in "${refs[@]}"; do
    [[ " ${seen} " == *" ${ref} "* ]] && continue
    seen="${seen} ${ref}"
    echo "==> Trying compose from branch: ${ref}"
    if _github_raw "$ref" "docker/compose.edge.yml" "$dest" && [[ -s "$dest" ]]; then
      echo "    OK docker-compose.yml from ${ref}"
      return 0
    fi
  done
  echo "==> Using embedded docker-compose.yml (GitHub download failed)"
  cat >"$dest" <<'COMPOSE'
name: openfdd-edge

services:
  bridge:
    image: ghcr.io/bbartling/openfdd-bridge:${OPENFDD_IMAGE_TAG:-latest}
    pull_policy: always
    ports:
      - "127.0.0.1:8765:8765"
    volumes:
      - ./workspace:/var/openfdd/workspace
    environment:
      OPENFDD_BACNET_COMMISSION_URL: http://host.docker.internal:8767
      OFDD_ALLOW_LAN_INTERNAL_INGEST: "1"
      OFDD_MCP_REST_BASE: http://mcp-rag:8090
      OFDD_BRIDGE_HOST: "0.0.0.0"
    env_file:
      - path: ./workspace/auth.env.local
        required: false
    extra_hosts:
      - "host.docker.internal:host-gateway"
    depends_on:
      - commission
      - mcp-rag
    restart: unless-stopped

  commission:
    image: ghcr.io/bbartling/openfdd-commission:${OPENFDD_IMAGE_TAG:-latest}
    pull_policy: always
    network_mode: host
    volumes:
      - ./workspace:/var/openfdd/workspace
    environment:
      OPENFDD_WORKSPACE_DIR: /var/openfdd/workspace
      OPENFDD_REPO_ROOT: /app
      OPENFDD_BRIDGE_INGEST_URL: http://127.0.0.1:8765/internal/bacnet/ingest-samples
    restart: unless-stopped

  mcp-rag:
    image: ghcr.io/bbartling/openfdd-mcp-rag:${OPENFDD_IMAGE_TAG:-latest}
    pull_policy: always
    volumes:
      - ./workspace:/var/openfdd/workspace
    expose:
      - "8090"
    restart: unless-stopped
COMPOSE
}

_detect_bacnet_bind() {
  python3 <<'PY'
import ipaddress, re, socket, subprocess

DEFAULT_PORT = 47808
LOOPBACK = {"127.0.0.1", "0.0.0.0", "::1"}

def parse_ip_addr_show():
    try:
        out = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show", "scope", "global"],
            text=True, stderr=subprocess.DEVNULL, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    iface = ""
    for line in out.splitlines():
        m = re.match(r"^\d+:\s+(\S+)", line)
        if m:
            iface = m.group(1)
        for token in line.split():
            if "/" in token and token.count(".") == 3:
                ip_part, _, prefix = token.partition("/")
                try:
                    ipaddress.IPv4Address(ip_part)
                    if iface in ("docker0", "tailscale0"):
                        continue
                    rows.append((iface, ip_part, int(prefix)))
                except ValueError:
                    pass
                break
    return rows

def pick(candidates):
    private = [(i, ip, pl) for i, ip, pl in candidates if ipaddress.IPv4Address(ip).is_private]
    pool = private or candidates
    for prefix in ("192.168.", "10.", "172."):
        for iface, ip, pl in pool:
            if prefix == "172.":
                if ipaddress.IPv4Address(ip) in ipaddress.ip_network("172.16.0.0/12"):
                    return iface, ip, pl
            elif ip.startswith(prefix):
                return iface, ip, pl
    return pool[0] if pool else ("", "", 0)

cands = parse_ip_addr_show()
if not cands:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in LOOPBACK:
            print(f"|{ip}|24|{DEFAULT_PORT}")
            raise SystemExit
    except OSError:
        pass
    print("||24|" + str(DEFAULT_PORT))
else:
    iface, ip, pl = pick(cands)
    print(f"{iface}|{ip}|{pl}|{DEFAULT_PORT}")
PY
}

_write_commission_env() {
  local dest="$1" bind="$2" iface="$3"
  curl -fsSL -o "$dest" \
    "https://raw.githubusercontent.com/${GITHUB_REPO}/master/bacnet_toolshed/commission.env.example"
  python3 - "$dest" "$bind" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
bind = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()
out = []
replaced = False
for line in lines:
    if line.startswith("BACNET_BIND="):
        out.append(f"BACNET_BIND={bind}")
        replaced = True
    else:
        out.append(line)
if not replaced:
    out.append(f"BACNET_BIND={bind}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
  echo "    commission.env → BACNET_BIND=${bind} (interface: ${iface:-auto})"
}

_write_auth_env() {
  local dest="$1"
  python3 <<'PY' >"$dest"
import secrets, string
alpha = string.ascii_letters + string.digits + "!@#$%^&*-_"
def pw(n=24):
    return "".join(secrets.choice(alpha) for _ in range(n))
print(f"OFDD_AUTH_SECRET={secrets.token_urlsafe(48)}")
print("OFDD_OPERATOR_USER=operator")
print(f"OFDD_OPERATOR_PASSWORD={pw()}")
print("OFDD_INTEGRATOR_USER=integrator")
print(f"OFDD_INTEGRATOR_PASSWORD={pw()}")
print("OFDD_AGENT_USER=agent")
print(f"OFDD_AGENT_PASSWORD={pw()}")
PY
  chmod 600 "$dest"
}

_check_docker() {
  echo "==> Checking Docker"
  docker --version
  docker compose version
  if ! groups | grep -q '\bdocker\b'; then
    echo "WARN: user not in docker group — run: sudo usermod -aG docker \$USER && newgrp docker" >&2
  fi
  if [[ "$(systemctl is-active docker 2>/dev/null || echo unknown)" != "active" ]]; then
    echo "ERROR: docker service not active — run: sudo systemctl enable --now docker" >&2
    exit 1
  fi
}

_pull_and_start() {
  cd "$OPENFDD_ROOT"
  export OPENFDD_IMAGE_TAG
  echo "==> Pulling images (tag=${OPENFDD_IMAGE_TAG})"
  if ! docker compose pull 2>/dev/null; then
    if [[ "$OPENFDD_IMAGE_TAG" == "latest" ]]; then
      echo "    latest not found — falling back to ${OPENFDD_IMAGE_FALLBACK}"
      export OPENFDD_IMAGE_TAG="$OPENFDD_IMAGE_FALLBACK"
      docker compose pull
    else
      return 1
    fi
  fi
  docker compose up -d
  docker compose ps
  curl -sf http://127.0.0.1:8765/health && echo || echo "WARN: /health not ready yet"
}

echo "=== Open-FDD edge bootstrap ==="
echo "Site root: ${OPENFDD_ROOT}"
_check_docker

mkdir -p "${OPENFDD_ROOT}/workspace/bacnet/commissioning"
mkdir -p "${OPENFDD_ROOT}/workspace/bacnet/polls"
mkdir -p "${OPENFDD_ROOT}/workspace/data/feather_store"
mkdir -p "${OPENFDD_ROOT}/workspace/data/playground"
mkdir -p "${OPENFDD_ROOT}/workspace/logs"
mkdir -p "${OPENFDD_ROOT}/workspace/api/static/app"
touch "${OPENFDD_ROOT}/workspace/bacnet/polls/samples.csv"
touch "${OPENFDD_ROOT}/workspace/bacnet/commissioning/points.csv"

COMPOSE_PATH="${OPENFDD_ROOT}/docker-compose.yml"
_download_compose "$COMPOSE_PATH"

echo "==> Downloading backup/update scripts"
_download_helper_scripts "${OPENFDD_ROOT}/scripts"

AUTH_PATH="${OPENFDD_ROOT}/workspace/auth.env.local"
if [[ ! -f "$AUTH_PATH" || "$FORCE_AUTH" == true ]]; then
  echo "==> Generating ${AUTH_PATH}"
  _write_auth_env "$AUTH_PATH"
else
  echo "==> Keeping existing ${AUTH_PATH} (use --force-auth to regenerate)"
fi

IFS='|' read -r BACNET_IFACE BACNET_IP BACNET_PREFIX BACNET_PORT < <(_detect_bacnet_bind)
if [[ -z "$BACNET_IP" ]]; then
  BACNET_BIND="0.0.0.0/24:${BACNET_PORT:-47808}"
  echo "WARN: could not detect LAN IPv4 — using ${BACNET_BIND}; edit commission.env" >&2
else
  BACNET_BIND="${BACNET_IP}/${BACNET_PREFIX}:${BACNET_PORT}"
fi

COMMISSION_PATH="${OPENFDD_ROOT}/workspace/bacnet/commissioning/commission.env"
echo "==> Writing ${COMMISSION_PATH}"
_write_commission_env "$COMMISSION_PATH" "$BACNET_BIND" "$BACNET_IFACE"

if [[ "$DO_START" == true ]]; then
  _pull_and_start
fi

echo ""
echo "=== Bootstrap complete ==="
echo "  Site root:     ${OPENFDD_ROOT}"
echo "  Compose file:  ${COMPOSE_PATH}"
echo "  Image tag:     ${OPENFDD_IMAGE_TAG} (fallback: ${OPENFDD_IMAGE_FALLBACK})"
echo "  BACnet NIC:    ${BACNET_IFACE:-unknown}"
echo "  BACnet bind:   ${BACNET_BIND}"
echo "  Auth file:     ${AUTH_PATH}"
echo "  Commission:    ${COMMISSION_PATH}"
echo ""
echo "Validate before OT polling:"
echo "  ip -4 addr show scope global"
echo "  nano ${COMMISSION_PATH}"
echo "  grep OFDD_INTEGRATOR_USER ${AUTH_PATH}"
if [[ "$SHOW_SECRETS" == true ]]; then
  echo ""
  echo "Auth credentials (lab only — store securely):"
  grep -E '^OFDD_(AUTH_SECRET|OPERATOR|INTEGRATOR|AGENT)' "$AUTH_PATH" || true
else
  echo "  cat ${AUTH_PATH}   # integrator password for dashboard login"
fi
echo ""
if [[ "$DO_START" != true ]]; then
  echo "Start stack:"
  echo "  cd ${OPENFDD_ROOT} && docker compose pull && docker compose up -d"
  echo "Or re-run: bash $0 --start"
fi
echo ""
echo "Upgrade later:"
echo "  cd ${OPENFDD_ROOT} && ./scripts/openfdd_site_backup.sh && ./scripts/openfdd_site_update.sh"
