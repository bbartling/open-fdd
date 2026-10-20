#!/usr/bin/env bash
# Gate 28 — Wave L L7 legacy-tenant migrate dry-run (inventory only).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"
LOG="$ART/wave_l_legacy_migrate.log"
: >"$LOG"

export ARTIFACT_DIR="$ART/migrate_dry_run"
mkdir -p "$ARTIFACT_DIR"
bash "$ROOT/scripts/ops/wave_l_legacy_migrate_dry_run.sh" 2>&1 | tee -a "$LOG"
cp -f "$ARTIFACT_DIR/migrate_plan.json" "$ART/migrate_plan.json" 2>/dev/null || true

ok "Wave L legacy migrate dry-run PASS"
exit 0
