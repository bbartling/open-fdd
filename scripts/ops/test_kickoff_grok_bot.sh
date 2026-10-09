#!/usr/bin/env bash
# Smoke-test local Grok Bot kickoff plumbing (clipboard + deep link).
# Does NOT claim Soft-OPEN started — only that Cursor can stage the prompt.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
KICK="$ROOT/scripts/ops/kickoff_grok_bot.py"
TMP="$(mktemp -t grokbot-kickoff-XXXXXX.md)"
trap 'rm -f "$TMP"' EXIT

cat >"$TMP" <<'EOF'
# Grok Bot kickoff smoke test (Cursor Soft-OPEN plumbing)

Reply with exactly one line:
GROK_KICKOFF_OK

Then stop. Do not run Open-FDD stress or touch Railway.
EOF

echo "== dry-run =="
python3 "$KICK" --dry-run "$TMP"

echo "== kickoff (clipboard + grokbot://app/v1/open) =="
python3 "$KICK" "$TMP"

echo "PASS: kickoff staged. Confirm Grok Bot focused; paste with Ctrl+V if needed."
echo "PROMPT_FILE=$TMP (removed on exit — re-run with a real Soft-OPEN prompt for live work)"
