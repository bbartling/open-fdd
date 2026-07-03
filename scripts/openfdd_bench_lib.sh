#!/usr/bin/env bash
# Bench defaults — source from lifecycle scripts (gitignored workspace copy optional).
# Copy to workspace/bench.env.local to override without editing repo files.

export OPENFDD_CARGO_BUILD_JOBS="${OPENFDD_CARGO_BUILD_JOBS:-1}"
export OPENFDD_RUST_GHCR_IMAGE="${OPENFDD_RUST_GHCR_IMAGE:-ghcr.io/bbartling/openfdd-edge-rust:latest}"
# Set to 1 only when you intentionally compile Rust on this host (needs 12GB+ free disk).
export OPENFDD_ALLOW_LOCAL_BUILD="${OPENFDD_ALLOW_LOCAL_BUILD:-0}"

openfdd_bench_load_env() {
  local root="${1:?root}"
  if [[ -f "$root/workspace/bench.env.local" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$root/workspace/bench.env.local"
    set +a
  fi
}

openfdd_bench_free_disk_gb() {
  local avail_kb
  avail_kb="$(df --output=avail / | tail -1 | tr -d ' ')"
  echo $((avail_kb / 1024 / 1024))
}

openfdd_bench_require_free_disk_gb() {
  local min_gb="${1:?min gb}"
  local avail_gb
  avail_gb="$(openfdd_bench_free_disk_gb)"
  if [[ "$avail_gb" -lt "$min_gb" ]]; then
    echo "ERROR: only ${avail_gb}GB free on / — need at least ${min_gb}GB." >&2
    echo "  Run: ./scripts/openfdd_docker_maintenance.sh --aggressive" >&2
    echo "  Or:  sudo ./scripts/openfdd_bench_extend_disk.sh" >&2
    return 1
  fi
}

openfdd_bench_require_local_build_allowed() {
  if [[ "${OPENFDD_ALLOW_LOCAL_BUILD:-0}" != "1" ]]; then
    echo "ERROR: local Docker Rust --build is disabled on this bench." >&2
    echo "  Use: ./scripts/openfdd_remote_up.sh  (pulls GHCR + Caddy, no rebuild)" >&2
    echo "  Or:  ./scripts/openfdd_bench_pull_ghcr.sh" >&2
    echo "  To allow one rebuild: OPENFDD_ALLOW_LOCAL_BUILD=1 ./scripts/openfdd_local_up.sh --build" >&2
    return 1
  fi
  openfdd_bench_require_free_disk_gb "${1:-12}"
}
