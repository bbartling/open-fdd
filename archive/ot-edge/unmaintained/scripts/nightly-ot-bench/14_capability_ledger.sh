#!/usr/bin/env bash
# Gate 14 — P1-M0 capability ledger validator (no container recreate required).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/lib.sh"
load_bench_env
cd "$ROOT"

ART="${ARTIFACT_DIR:-$(artifact_dir)}"
mkdir -p "$ART"

hdr "P1-M0 capability ledger"

LEDGER="$ROOT/docs/migration/react-rust/capabilities.yaml"
if [[ ! -f "$LEDGER" ]]; then
  bad "missing capabilities.yaml"
  summary
  exit 1
fi
cp "$LEDGER" "$ART/capabilities.yaml"

if ! python3 -c 'import yaml' 2>/dev/null; then
  if ! python3 -m pip install --user -q PyYAML 2>/dev/null \
    && ! python3 -m pip install --break-system-packages -q PyYAML 2>/dev/null; then
    bad "PyYAML required — pip install PyYAML"
    summary
    exit 1
  fi
fi

OUT="$ART/capabilities_ledger_validate.txt"
set +e
python3 "$ROOT/scripts/validate_capabilities_ledger.py" >"$OUT" 2>&1
rc=$?
set -e
cat "$OUT"
if [[ "$rc" -eq 0 ]]; then
  ok "validate_capabilities_ledger.py PASS"
else
  bad "validate_capabilities_ledger.py FAIL (see capabilities_ledger_validate.txt)"
fi

# Summary artifact for humans
if command -v python3 >/dev/null; then
  python3 - <<'PY' >"$ART/capabilities_summary.txt" 2>/dev/null || true
import yaml
from pathlib import Path
from collections import Counter
p = Path("docs/migration/react-rust/capabilities.yaml")
data = yaml.safe_load(p.read_text())
caps = data.get("capabilities") or []
c = Counter(x.get("status") for x in caps)
print(f"capabilities={len(caps)}")
for k, v in sorted(c.items()):
    print(f"  {k}: {v}")
demo = sum(1 for x in caps if x.get("demo_only"))
print(f"demo_only={demo}")
PY
  [[ -f "$ART/capabilities_summary.txt" ]] && ok "wrote capabilities_summary.txt" || skip "summary dump skipped"
fi

summary
[[ "$FAIL" -eq 0 ]]
