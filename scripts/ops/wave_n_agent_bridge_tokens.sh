#!/usr/bin/env bash
# Run once in your Mint terminal (outside Cursor agent) so the agent can use gh/railway.
# Writes gitignored tokens under .secrets/ — never commit these.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
mkdir -p .secrets
chmod 700 .secrets

gh auth token >.secrets/GH_TOKEN
chmod 600 .secrets/GH_TOKEN

# Railway account token optional; CLI config already on disk for host.
# Export a project token if you use RAILWAY_TOKEN in CI-like agent shells:
if [[ -n "${RAILWAY_TOKEN:-}" ]]; then
  printf '%s\n' "$RAILWAY_TOKEN" >.secrets/RAILWAY_TOKEN
  chmod 600 .secrets/RAILWAY_TOKEN
fi

# Prove files exist without printing secrets
python3 - <<'PY'
from pathlib import Path
root = Path('.')
for name in ('GH_TOKEN', 'RAILWAY_TOKEN'):
  p = root / '.secrets' / name
  if p.exists():
    print(f'{name}: present bytes={p.stat().st_size}')
  else:
    print(f'{name}: absent')
PY
echo "OK — agent can now: export GH_TOKEN=\$(cat .secrets/GH_TOKEN)"
