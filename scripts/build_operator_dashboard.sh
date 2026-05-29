#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/workspace/dashboard"
if [ -f package-lock.json ]; then npm ci; else npm install; fi
npm run build
echo "Dashboard built to workspace/api/static/app"
