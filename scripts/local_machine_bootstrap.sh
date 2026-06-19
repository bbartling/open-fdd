#!/usr/bin/env bash
# One-time host setup for open-fdd dev on a fresh Linux machine.
# Run from repo root after clone:
#   ./scripts/local_machine_bootstrap.sh
#
# Requires sudo once for Docker + python3-venv (password prompt).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> System packages (sudo)"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  docker.io docker-compose-v2 python3-venv python3-pip build-essential uidmap

echo "==> Docker group + service"
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

echo "==> User tools (no sudo)"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
if ! command -v gh >/dev/null 2>&1; then
  mkdir -p "$HOME/bin"
  GH_VER=2.74.2
  curl -fsSL "https://github.com/cli/gh/releases/download/v${GH_VER}/gh_${GH_VER}_linux_amd64.tar.gz" \
    | tar -xz -C /tmp
  cp "/tmp/gh_${GH_VER}_linux_amd64/bin/gh" "$HOME/bin/gh"
  chmod +x "$HOME/bin/gh"
fi
if [[ ! -d "$HOME/.nvm" ]]; then
  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
fi

export PATH="$HOME/.local/bin:$HOME/bin:$PATH"
# shellcheck disable=SC1091
[[ -s "$HOME/.nvm/nvm.sh" ]] && . "$HOME/.nvm/nvm.sh"
command -v node >/dev/null 2>&1 || nvm install 22

echo "==> Python venv + deps"
if [[ ! -x .venv/bin/python ]]; then
  uv venv .venv
  uv pip install pip
fi
uv pip install -e ".[dev,test,analytics]"
uv pip install -r workspace/api/requirements.txt httpx

echo "==> Auth env (lab defaults)"
cp -n workspace/auth.env.example workspace/auth.env.local 2>/dev/null || true

echo "==> Shell PATH snippet"
MARKER="# open-fdd dev PATH"
if ! grep -qF "$MARKER" "$HOME/.bashrc" 2>/dev/null; then
  cat >>"$HOME/.bashrc" <<'EOF'

# open-fdd dev PATH
export PATH="$HOME/.local/bin:$HOME/bin:$PATH"
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
EOF
fi

echo ""
echo "OK — log out/in (or: newgrp docker) so docker group applies, then:"
echo "  cd $ROOT"
echo "  gh auth login"
echo "  ./scripts/build_and_test.sh"
echo "  ./scripts/docker_build.sh && ./scripts/openfdd_stack.sh up"
echo ""
echo "Dashboard: http://127.0.0.1:8765  (integrator / msi-local from workspace/auth.env.local)"
