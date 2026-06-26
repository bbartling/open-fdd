#!/usr/bin/env bash
# One-time bench hardening: buildx, weekly maintenance cron, bench env template, optional disk extend.
#
#   ./scripts/openfdd_bench_setup.sh
#   sudo ./scripts/openfdd_bench_setup.sh --extend-disk
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTEND_DISK=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --extend-disk) EXTEND_DISK=1 ;;
    -h|--help)
      cat <<'EOF'
Usage: scripts/openfdd_bench_setup.sh [--extend-disk]

  --extend-disk   Run LVM extend (requires sudo — pass on same command line)

Does NOT run local Docker Rust --build. GHCR images are built in GitHub Actions.
EOF
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

chmod +x "$ROOT/scripts/openfdd_bench_extend_disk.sh" \
  "$ROOT/scripts/openfdd_bench_pull_ghcr.sh" \
  "$ROOT/scripts/openfdd_docker_maintenance.sh" \
  "$ROOT/scripts/openfdd_remote_up.sh" \
  "$ROOT/scripts/openfdd_health_check.sh" 2>/dev/null || true

mkdir -p "$ROOT/workspace/logs"

BENCH_ENV="$ROOT/workspace/bench.env.local"
if [[ ! -f "$BENCH_ENV" ]]; then
  cat >"$BENCH_ENV" <<'EOF'
# Bench overrides (gitignored). Defaults keep local Rust --build off.
OPENFDD_CARGO_BUILD_JOBS=1
OPENFDD_ALLOW_LOCAL_BUILD=0
OPENFDD_RUST_GHCR_IMAGE=ghcr.io/bbartling/openfdd-edge-rust:latest
EOF
  chmod 600 "$BENCH_ENV"
  echo "==> Created $BENCH_ENV"
else
  echo "==> Keeping existing $BENCH_ENV"
fi

echo "==> Docker buildx (memory-capped builds when OPENFDD_ALLOW_LOCAL_BUILD=1)"
if command -v docker >/dev/null 2>&1 && docker buildx version >/dev/null 2>&1; then
  echo "    buildx already available: $(docker buildx version | head -1)"
elif [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  apt-get update -qq
  apt-get install -y -qq docker-buildx-plugin || apt-get install -y -qq docker-buildx || true
  docker buildx create --name openfdd-bench --use 2>/dev/null || docker buildx use openfdd-bench 2>/dev/null || docker buildx use default
  echo "    buildx installed"
else
  echo "    Install manually (once): sudo apt install docker-buildx-plugin"
  echo "    Then: docker buildx create --name openfdd-bench --use"
fi

CRON_LINE="0 3 * * 0 cd $ROOT && ./scripts/openfdd_docker_maintenance.sh --aggressive >> workspace/logs/bench-maintenance.log 2>&1"
if crontab -l 2>/dev/null | grep -Fq "openfdd_docker_maintenance.sh"; then
  echo "==> Weekly maintenance cron already installed"
else
  existing="$(crontab -l 2>/dev/null || true)"
  { echo "$existing"; echo "$CRON_LINE"; } | crontab -
  echo "==> Installed weekly cron (Sun 03:00): openfdd_docker_maintenance.sh --aggressive"
fi

if [[ "$EXTEND_DISK" == "1" ]]; then
  "$ROOT/scripts/openfdd_bench_extend_disk.sh"
else
  avail="$(df --output=avail / | tail -1 | tr -d ' ')"
  avail_gb=$((avail / 1024 / 1024))
  if [[ "$avail_gb" -lt 50 ]]; then
    echo "==> Tip: root has ${avail_gb}GB free but disk is ~233GB — extend once:"
    echo "    sudo ./scripts/openfdd_bench_extend_disk.sh"
  fi
fi

echo ""
echo "Bench setup complete."
echo "  Daily remote dial-in:  ./scripts/openfdd_remote_up.sh"
echo "  Health check:          ./scripts/openfdd_health_check.sh --remote --auth"
echo "  Pull GHCR (no build):  ./scripts/openfdd_bench_pull_ghcr.sh"
echo "  GHCR images built by:  .github/workflows/rust-ghcr.yml (GitHub Actions — not on this host)"
