#!/usr/bin/env bash
# Shared helpers for Rust Open-FDD edge lifecycle scripts.
# Source from bootstrap/update/backup/validate; not executed directly.
set -euo pipefail

OPENFDD_RUST_GHCR_IMAGE="${OPENFDD_RUST_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-edge-rust}"
OPENFDD_GITHUB_REPO="${OPENFDD_GITHUB_REPO:-bbartling/open-fdd}"

openfdd_rust_site_root_from_caller() {
  local caller="${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}"
  cd "$(dirname "$caller")/.." && pwd
}

openfdd_rust_detect_docker_platform() {
  case "$(uname -m)" in
    aarch64|arm64) echo "linux/arm64" ;;
    x86_64|amd64) echo "linux/amd64" ;;
    *) echo "linux/$(uname -m)" ;;
  esac
}

openfdd_rust_normalize_docker_platform() {
  local raw="${1:-auto}"
  case "$raw" in
    ""|auto) openfdd_rust_detect_docker_platform ;;
    linux/arm64|arm64|aarch64) echo "linux/arm64" ;;
    linux/amd64|amd64|x86_64) echo "linux/amd64" ;;
    linux/*) echo "$raw" ;;
    *)
      echo "ERROR: unknown platform: $raw (use auto, linux/arm64, or linux/amd64)" >&2
      return 1
      ;;
  esac
}

openfdd_rust_resolve_docker_platform() {
  openfdd_rust_normalize_docker_platform "${OPENFDD_DOCKER_PLATFORM:-auto}"
}

openfdd_rust_export_docker_platform() {
  local platform
  platform="$(openfdd_rust_resolve_docker_platform)" || return 1
  export OPENFDD_DOCKER_PLATFORM="$platform"
  export DOCKER_DEFAULT_PLATFORM="$platform"
  printf '%s' "$platform"
}

openfdd_rust_resolve_compose_file() {
  local root="$1"
  local compose="${COMPOSE_FILE:-}"
  if [[ -z "$compose" ]]; then
    if [[ -f "$root/docker-compose.yml" ]]; then
      compose="$root/docker-compose.yml"
    elif [[ -f "$root/docker/compose.edge.rust.yml" ]]; then
      compose="$root/docker/compose.edge.rust.yml"
    fi
  fi
  printf '%s' "$compose"
}

openfdd_rust_redact_line() {
  local line="$1"
  if [[ "$line" =~ (SECRET|PASSWORD|TOKEN|AUTH)= ]]; then
    echo "${line%%=*}=***REDACTED***"
  else
    echo "$line"
  fi
}

openfdd_rust_check_docker() {
  command -v docker >/dev/null 2>&1 || {
    echo "ERROR: Docker is not installed." >&2
    return 1
  }
  docker info >/dev/null 2>&1 || {
    echo "ERROR: Docker daemon is not running or not accessible." >&2
    echo "Hint: sudo systemctl start docker && sudo usermod -aG docker \$USER" >&2
    return 1
  }
  docker compose version >/dev/null 2>&1 || {
    echo "ERROR: Docker Compose v2 (docker compose) is required." >&2
    return 1
  }
}

openfdd_rust_warn_root_owned_workspace() {
  local ws="$1"
  [[ -d "$ws" ]] || return 0
  local bad
  bad="$(find "$ws" -user root 2>/dev/null | head -5 || true)"
  if [[ -n "$bad" ]]; then
    echo "WARN: workspace contains root-owned paths (container may fail to write):" >&2
    echo "$bad" >&2
    echo "Fix: sudo chown -R \"\$(id -un):\$(id -gn)\" \"$ws\"" >&2
  fi
}

openfdd_rust_wait_for_health() {
  local url="${1:-http://127.0.0.1:8080/api/health}"
  local timeout="${2:-120}"
  local i
  for ((i = 0; i < timeout; i += 2)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "ERROR: health check timed out: $url" >&2
  return 1
}

openfdd_rust_login_smoke() {
  local base="${1:-http://127.0.0.1:8080}"
  local auth_file="$2"
  [[ -f "$auth_file" ]] || {
    echo "ERROR: missing $auth_file" >&2
    return 1
  }
  # shellcheck source=scripts/openfdd_auth_lib.sh
  source "$(dirname "${BASH_SOURCE[0]}")/openfdd_auth_lib.sh"
  local token
  token="$(openfdd_auth_login_token "$base" "$auth_file" integrator)" || return 1
  [[ -n "$token" && "$token" != "null" ]] || {
    echo "ERROR: login failed (no token returned)" >&2
    return 1
  }
  curl -fsS "${base}/api/health/stack" -H "Authorization: Bearer ${token}" >/dev/null
  echo "Login smoke OK (integrator, token redacted)"
}

openfdd_rust_safe_docker_maintenance() {
  echo "==> Safe Docker maintenance (never volume prune, never compose down -v)"
  docker container prune -f 2>/dev/null || true
  docker network prune -f 2>/dev/null || true
  docker image prune -f 2>/dev/null || true
  if [[ "${PRUNE_UNUSED_IMAGES:-1}" == "1" ]]; then
    docker image prune -a -f 2>/dev/null || true
  fi
}

openfdd_rust_backup_archive_path() {
  printf '%s/workspace-full.tgz' "$1"
}

openfdd_rust_validate_backup_archive() {
  local archive="$1"
  [[ -f "$archive" ]] || {
    echo "ERROR: backup not found: $archive" >&2
    return 1
  }
  tar -tzf "$archive" workspace >/dev/null 2>&1 || {
    echo "ERROR: backup integrity check failed: $archive" >&2
    return 1
  }
  echo "Backup archive OK: $archive"
}

openfdd_rust_compose_image_tag_assert() {
  local compose="$1"
  local expected="${2:-latest}"
  grep -q "ghcr.io/bbartling/openfdd-edge-rust:${expected}" "$compose" \
    || grep -q '\${OPENFDD_IMAGE_TAG' "$compose" \
    || echo "WARN: compose may not reference expected Rust GHCR image tag"
}

openfdd_rust_generate_auth_env_local() {
  local path="$1"
  local force="${2:-false}"
  local show_secrets="${3:-false}"
  mkdir -p "$(dirname "$path")"
  if [[ -f "$path" && "$force" != "true" ]]; then
    echo "Keeping existing $path"
    return 0
  fi
  if command -v openfdd_edge >/dev/null 2>&1; then
    local args=(auth init --path "$path")
    [[ "$force" == "true" ]] && args+=(--force)
    [[ "$show_secrets" == "true" ]] && args+=(--show-secrets)
    openfdd_edge "${args[@]}"
    chmod 600 "$path" 2>/dev/null || true
    return 0
  fi
  # Docker openfdd-edge (bcrypt) when host has no Rust toolchain
  local ws_root auth_basename img
  ws_root="$(cd "$(dirname "$path")" && pwd)"
  auth_basename="$(basename "$path")"
  img="${OPENFDD_AUTH_IMAGE:-open-fdd-openfdd-bridge:local}"
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    if ! docker image inspect "$img" >/dev/null 2>&1; then
      img="${OPENFDD_RUST_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-edge-rust:latest}"
      docker pull "$img" || return 1
    fi
    if docker image inspect "$img" >/dev/null 2>&1; then
      local dargs=(auth init --path "/app/workspace/$auth_basename")
      [[ "$force" == "true" ]] && dargs+=(--force)
      [[ "$show_secrets" == "true" ]] && dargs+=(--show-secrets)
      docker run --rm --user "$(id -u):$(id -g)" -v "$ws_root:/app/workspace" "$img" openfdd-edge "${dargs[@]}" \
        || return 1
      chmod 600 "$path" 2>/dev/null || true
      return 0
    fi
  fi
  # Last-resort bash fallback (plaintext passwords — lab only)
  local secret op_pw int_pw ag_pw
  secret="$(openssl rand -hex 32 2>/dev/null || date +%s%N | sha256sum | cut -c1-64)"
  op_pw="$(openssl rand -base64 24 2>/dev/null | tr -d '/+=$' | head -c 28)"
  int_pw="$(openssl rand -base64 24 2>/dev/null | tr -d '/+=$' | head -c 28)"
  ag_pw="$(openssl rand -base64 24 2>/dev/null | tr -d '/+=$' | head -c 28)"
  cat >"$path" <<EOF
# Generated by openfdd_rust_site_lib.sh — do not commit
OFDD_AUTH_REQUIRED=true
OFDD_AUTH_SECRET=${secret}
OFDD_OPERATOR_USER=operator
OFDD_OPERATOR_PASSWORD=${op_pw}
OFDD_INTEGRATOR_USER=integrator
OFDD_INTEGRATOR_PASSWORD=${int_pw}
OFDD_AGENT_USER=agent
OFDD_AGENT_PASSWORD=${ag_pw}
OFDD_JWT_TTL_SECONDS=28800
OFDD_COOKIE_SECURE=false
EOF
  chmod 600 "$path" 2>/dev/null || true
  if [[ "$show_secrets" == "true" ]]; then
    cat "$path"
  else
    while IFS= read -r line; do openfdd_rust_redact_line "$line"; done <"$path"
  fi
}

openfdd_rust_github_raw() {
  local ref="$1" path="$2" dest="$3"
  curl -fsSL -o "$dest" "https://github.com/${OPENFDD_GITHUB_REPO}/raw/refs/heads/${ref}/${path}"
}

openfdd_rust_write_site_env() {
  local root="$1"
  local tag="${2:-latest}"
  cat >"$root/.env" <<EOF
# Generated by Open-FDD Rust edge lifecycle scripts — do not hand-edit
OPENFDD_COMPOSE_ROOT=${root}
OPENFDD_IMAGE_TAG=${tag}
COMPOSE_PROFILES=full-edge
EOF
}

openfdd_rust_install_edge_compose() {
  local root="$1"
  local ref="${2:-master}"
  local dest="$root/docker-compose.yml"
  mkdir -p "$root/docker/caddy"
  openfdd_rust_github_raw "$ref" "docker/compose.edge.rust.yml" "$dest" \
    || cp "$(dirname "${BASH_SOURCE[0]}")/../docker/compose.edge.rust.yml" "$dest"
  for caddy in Caddyfile.http Caddyfile.tls; do
    local cdest="$root/docker/caddy/$caddy"
    if [[ ! -f "$cdest" ]]; then
      openfdd_rust_github_raw "$ref" "docker/caddy/$caddy" "$cdest" 2>/dev/null \
        || cp "$(dirname "${BASH_SOURCE[0]}")/../docker/caddy/$caddy" "$cdest" 2>/dev/null || true
    fi
  done
}
