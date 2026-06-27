#!/usr/bin/env bash
# Generate or rotate workspace/auth.env.local using openfdd-edge (bcrypt hashes).
# No host Rust/cargo required — runs openfdd-edge from Docker when needed.
#
#   ./scripts/openfdd_auth_init.sh --show-secrets          # create if missing
#   ./scripts/openfdd_auth_init.sh --force --show-secrets  # replace existing
#   ./scripts/openfdd_auth_init.sh --rotate --all --show-secrets
#   ./scripts/openfdd_auth_init.sh --hash-password 'secret'
#
# After rotating credentials, recreate containers so they reload env:
#   docker compose -f docker-compose.yml up -d --force-recreate openfdd-bridge
#   # or: docker compose -f docker/compose.edge.rust.yml --profile full-edge up -d --force-recreate openfdd-bridge
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/openfdd_rust_site_lib.sh
source "$ROOT/scripts/openfdd_rust_site_lib.sh"
AUTH_PATH="${OPENFDD_AUTH_PATH:-$ROOT/workspace/auth.env.local}"
IMAGE="${OPENFDD_AUTH_IMAGE:-open-fdd-openfdd-bridge:local}"
GHCR_IMAGE="${OPENFDD_RUST_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-edge-rust:latest}"

FORCE=false
SHOW_SECRETS=false
ROTATE=false
ROTATE_ALL=false
ROTATE_ROLE=""
HASH_PASSWORD=""
RESTART=false
SUBCMD=(auth init --path "$AUTH_PATH")

usage() {
  cat <<'EOF'
Usage: scripts/openfdd_auth_init.sh [options]

Creates or rotates workspace/auth.env.local with bcrypt password hashes (Rust openfdd-edge).
Does not require cargo on the host — uses Docker when openfdd-edge is not in PATH.

Options:
  --path PATH           Auth env file (default: workspace/auth.env.local)
  --image IMAGE         Docker image for openfdd-edge (default: open-fdd-openfdd-bridge:local)
  --ghcr                Use ghcr.io/bbartling/openfdd-edge-rust:latest instead of local image
  --force               Overwrite existing auth file (init only)
  --show-secrets        Print plaintext passwords once (lab only — not logged to disk)
  --rotate              Rotate passwords (use with --all or --role NAME)
  --all                 Rotate all roles + OFDD_AUTH_SECRET (invalidates JWTs)
  --role NAME           Rotate one role: operator|integrator|agent|admin
  --hash-password PASS  Print bcrypt hash for manual auth.env.local editing
  --restart             After init/rotate, recreate local openfdd-bridge container
  -h, --help            Show this help

After rotate or force init, recreate bridge containers to pick up new env.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --path) AUTH_PATH="$2"; SUBCMD=(auth init --path "$AUTH_PATH"); shift 2 ;;
    --image) IMAGE="$2"; shift 2 ;;
    --ghcr) IMAGE="$GHCR_IMAGE"; shift ;;
    --force) FORCE=true; shift ;;
    --show-secrets) SHOW_SECRETS=true; shift ;;
    --rotate)
      ROTATE=true
      SUBCMD=(auth rotate --out "$AUTH_PATH")
      shift
      ;;
    --all) ROTATE_ALL=true; shift ;;
    --role) ROTATE_ROLE="$2"; shift 2 ;;
    --hash-password) HASH_PASSWORD="$2"; SUBCMD=(auth hash-password "$2"); shift 2 ;;
    --restart) RESTART=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

mkdir -p "$(dirname "$AUTH_PATH")"
CONTAINER_AUTH_PATH="/app/workspace/$(basename "$AUTH_PATH")"
WORKSPACE_MOUNT="$(cd "$(dirname "$AUTH_PATH")" && pwd)"
HANDOFF="$WORKSPACE_MOUNT/bootstrap_credentials.once.txt"
AUTH_LOG="$(mktemp "${TMPDIR:-/tmp}/openfdd-auth-init.XXXXXX")"
trap 'rm -f "$AUTH_LOG"' EXIT

write_bootstrap_handoff_from_log() {
  [[ "$SHOW_SECRETS" == "true" ]] || return 0
  local role line
  local -a creds=()
  while IFS= read -r line; do
    if [[ "$line" =~ ^[[:space:]]*(operator|integrator|agent|admin):[[:space:]]+(.+)$ ]]; then
      role="${BASH_REMATCH[1]}"
      creds+=("${role}: ${BASH_REMATCH[2]}")
    fi
  done < <(grep -E '^[[:space:]]*(operator|integrator|agent|admin):' "$AUTH_LOG" 2>/dev/null || true)
  [[ ${#creds[@]} -eq 0 ]] && return 0
  {
    echo "# Open-FDD one-time bootstrap credentials — DELETE after saving to your password manager."
    echo "# Do NOT paste bcrypt hashes from auth.env.local as login passwords."
    echo "# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# Rotate again: ./scripts/openfdd_auth_init.sh --rotate --all --show-secrets --restart"
    echo
    printf '%s\n' "${creds[@]}"
    echo
    echo "# After saving passwords, delete this file:"
    echo "#   rm workspace/bootstrap_credentials.once.txt"
  } >"$HANDOFF"
  chmod 600 "$HANDOFF" 2>/dev/null || true
  echo "==> Wrote one-time handoff: $HANDOFF"
}

run_host() {
  if [[ -n "$HASH_PASSWORD" ]]; then
    openfdd-edge "${SUBCMD[@]}"
  elif [[ "$ROTATE" == "true" ]]; then
    local args=(auth rotate --out "$AUTH_PATH")
    [[ "$ROTATE_ALL" == "true" ]] && args+=(--all)
    [[ -n "$ROTATE_ROLE" ]] && args+=(--role "$ROTATE_ROLE")
    [[ "$SHOW_SECRETS" == "true" ]] && args+=(--show-secrets)
    openfdd-edge "${args[@]}"
  else
    local args=(auth init --path "$AUTH_PATH")
    [[ "$FORCE" == "true" ]] && args+=(--force)
    [[ "$SHOW_SECRETS" == "true" ]] && args+=(--show-secrets)
    openfdd-edge "${args[@]}"
  fi
}

run_local_binary() {
  local bin="$1"
  shift
  if [[ -n "$HASH_PASSWORD" ]]; then
    "$bin" auth hash-password "$HASH_PASSWORD"
  elif [[ "$ROTATE" == "true" ]]; then
    local args=(auth rotate --out "$AUTH_PATH")
    [[ "$ROTATE_ALL" == "true" ]] && args+=(--all)
    [[ -n "$ROTATE_ROLE" ]] && args+=(--role "$ROTATE_ROLE")
    [[ "$SHOW_SECRETS" == "true" ]] && args+=(--show-secrets)
    "$bin" "${args[@]}"
  else
    local args=(auth init --path "$AUTH_PATH")
    [[ "$FORCE" == "true" ]] && args+=(--force)
    [[ "$SHOW_SECRETS" == "true" ]] && args+=(--show-secrets)
    "$bin" "${args[@]}"
  fi
}

run_docker() {
  local img="$1"
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    -v "$WORKSPACE_MOUNT:/app/workspace" \
    "$img" \
    openfdd-edge "${DOCKER_ARGS[@]}"
}

resolve_docker_image() {
  if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    printf '%s' "$IMAGE"
    return 0
  fi
  echo "==> Local image missing — pulling $GHCR_IMAGE" >&2
  docker pull "$GHCR_IMAGE"
  printf '%s' "$GHCR_IMAGE"
}

if [[ -n "$HASH_PASSWORD" ]]; then
  if command -v openfdd-edge >/dev/null 2>&1; then
    run_host
  else
    img="$(resolve_docker_image)"
    docker run --rm "$img" openfdd-edge auth hash-password "$HASH_PASSWORD"
  fi
  exit 0
fi

if [[ "$ROTATE" == "true" ]]; then
  DOCKER_ARGS=(auth rotate --out "$CONTAINER_AUTH_PATH")
  [[ "$ROTATE_ALL" == "true" ]] && DOCKER_ARGS+=(--all)
  [[ -n "$ROTATE_ROLE" ]] && DOCKER_ARGS+=(--role "$ROTATE_ROLE")
  [[ "$SHOW_SECRETS" == "true" ]] && DOCKER_ARGS+=(--show-secrets)
elif [[ "$FORCE" == "true" ]]; then
  DOCKER_ARGS=(auth init --path "$CONTAINER_AUTH_PATH" --force)
  [[ "$SHOW_SECRETS" == "true" ]] && DOCKER_ARGS+=(--show-secrets)
else
  DOCKER_ARGS=(auth init --path "$CONTAINER_AUTH_PATH")
  [[ "$SHOW_SECRETS" == "true" ]] && DOCKER_ARGS+=(--show-secrets)
fi

if [[ -x "$ROOT/target/debug/openfdd-edge" ]]; then
  run_local_binary "$ROOT/target/debug/openfdd-edge" 2>&1 | tee "$AUTH_LOG"
elif command -v openfdd-edge >/dev/null 2>&1; then
  run_host 2>&1 | tee "$AUTH_LOG"
else
  img="$(resolve_docker_image)"
  run_docker "$img" 2>&1 | tee "$AUTH_LOG"
fi
write_bootstrap_handoff_from_log

chmod 600 "$AUTH_PATH" 2>/dev/null || true
echo "==> Auth env: $AUTH_PATH"
if [[ "$RESTART" == "true" ]]; then
  export OPENFDD_RUN_UID="${OPENFDD_RUN_UID:-$(id -u)}"
  export OPENFDD_RUN_GID="${OPENFDD_RUN_GID:-$(id -g)}"
  COMPOSE="$(openfdd_rust_resolve_compose_file "$ROOT")"
  echo "==> Recreating openfdd-bridge to reload auth env"
  if [[ -f "$COMPOSE" ]]; then
    docker compose -f "$COMPOSE" up -d --force-recreate openfdd-bridge
  else
    echo "WARN: no compose file found under $ROOT — recreate bridge manually" >&2
  fi
else
  echo "==> Recreate bridge after rotate/force:"
  echo "    docker compose -f docker-compose.yml up -d --force-recreate openfdd-bridge"
  echo "==> Or re-run with --restart"
fi
