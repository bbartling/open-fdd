#!/usr/bin/env bash
# Report FDD rule backend mix (Arrow vs legacy row) for the mounted workspace.
#
#   ./scripts/validate_fdd_backends.sh              # host python if pyarrow present
#   ./scripts/validate_fdd_backends.sh --docker     # inside bridge container (recommended)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

USE_DOCKER=0
[[ "${1:-}" == "--docker" ]] && USE_DOCKER=1

run_py() {
  python3 - <<'PY'
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("workspace/api").resolve()))
sys.path.insert(0, str(Path("open_fdd").resolve()))

from openfdd_bridge.rule_source import read_source
from openfdd_bridge.rule_store import RuleStore
from open_fdd.arrow_runtime.rules import detect_rule_backend

store = RuleStore()
rules = [r for r in store.list_rules() if isinstance(r, dict) and r.get("enabled", True)]
counts: dict[str, int] = {}
rows: list[dict] = []

for rule in rules:
    code = read_source(str(rule.get("source_path") or "")) or str(rule.get("code") or "")
    backend = detect_rule_backend(code, rule)
    counts[backend] = counts.get(backend, 0) + 1
    rows.append(
        {
            "name": rule.get("name"),
            "id": rule.get("id"),
            "stored_backend": rule.get("backend"),
            "detected_backend": backend,
            "has_apply_faults_arrow": "apply_faults_arrow" in code,
            "has_evaluate": "def evaluate" in code,
        }
    )

legacy = counts.get("legacy_row", 0)
arrow = counts.get("arrow", 0)
script = counts.get("script", 0)
total = len(rules)

print(f"Enabled rules: {total}")
print(f"  arrow:       {arrow}")
print(f"  legacy_row:  {legacy}")
print(f"  script:      {script}")
print()

for row in rows:
    print(
        f"- {row['name']}: detected={row['detected_backend']}"
        f" stored={row['stored_backend']!r}"
        f" arrow_fn={row['has_apply_faults_arrow']} evaluate_fn={row['has_evaluate']}"
    )

print()
if legacy and not arrow:
    print("WARN: All enabled rules use legacy_row (def evaluate). Batch FDD runs row-by-row via pandas.")
    print("      Migrate rules to apply_faults_arrow(table, cfg, context) for Arrow-native execution.")
    sys.exit(1)
if legacy:
    print("WARN: Some rules still legacy_row — not 100% Arrow FDD execution.")
    sys.exit(1)
print("OK — enabled rules are Arrow-native (apply_faults_arrow) or script mode.")
PY
}

if [[ "$USE_DOCKER" == "1" ]]; then
  COMPOSE=(docker compose -f docker/compose.dev.yml -f docker/compose.bench.yml)
  cid="$("${COMPOSE[@]}" ps -q bridge 2>/dev/null || true)"
  [[ -n "$cid" ]] || { echo "bridge container not running — start stack first" >&2; exit 1; }
  "${COMPOSE[@]}" exec -T bridge python3 - <<'PY'
import json
import sys
from openfdd_bridge.rule_source import read_source
from openfdd_bridge.rule_store import RuleStore
from open_fdd.arrow_runtime.rules import detect_rule_backend

store = RuleStore()
rules = [r for r in store.list_rules() if isinstance(r, dict) and r.get("enabled", True)]
counts = {}
for rule in rules:
    code = read_source(str(rule.get("source_path") or "")) or str(rule.get("code") or "")
    backend = detect_rule_backend(code, rule)
    counts[backend] = counts.get(backend, 0) + 1
    print(f"- {rule.get('name')}: {backend} (stored={rule.get('backend')!r})")

legacy = counts.get("legacy_row", 0)
arrow = counts.get("arrow", 0)
print(f"\nTotals: arrow={arrow} legacy_row={legacy} script={counts.get('script', 0)}")
if legacy and not arrow:
    print("\nWARN: All enabled rules are legacy_row — FDD batch is NOT Arrow-native yet.")
    sys.exit(1)
if legacy:
    print("\nWARN: Mixed backends — not 100% Arrow FDD.")
    sys.exit(1)
print("\nOK — Arrow-native FDD rules.")
PY
else
  run_py
fi
