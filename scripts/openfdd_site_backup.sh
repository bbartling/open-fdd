#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
TS="$(date +%Y%m%d-%H%M%S)"
mkdir -p workspace/backups
tar -czf "workspace/backups/workspace-${TS}.tgz" workspace --exclude='workspace/backups' || true
echo "workspace/backups/workspace-${TS}.tgz"
