#!/usr/bin/env bash
# Install research_review_agent_skills_v1 into Open-FDD .agents/.codex/.cursor trees.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ZIP="${1:-/mnt/c/Users/ben/Downloads/research_review_agent_skills_v1.zip}"
if [[ ! -f "$ZIP" ]]; then
  echo "ZIP not found: $ZIP" >&2
  echo "Usage: $0 [path/to/research_review_agent_skills_v1.zip]" >&2
  exit 1
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
unzip -q "$ZIP" -d "$TMP"
BASE="$TMP/research_review_agent_skills_v1"
mkdir -p "$ROOT/.agents/skills" "$ROOT/.cursor/skills"
cp -r "$BASE/codex/.agents/skills/"* "$ROOT/.agents/skills/"
cp -r "$BASE/cursor/.cursor/skills/"* "$ROOT/.cursor/skills/"
for f in "$BASE/codex/.codex/agents/"*.toml; do
  cp "$f" "$ROOT/.codex/agents/"
done
for f in "$BASE/cursor/.cursor/agents/"*.md; do
  bn="$(basename "$f")"
  if [[ ! -f "$ROOT/.cursor/agents/$bn" ]]; then
    cp "$f" "$ROOT/.cursor/agents/"
  fi
done
echo "Installed skills from $ZIP"
echo "  Codex skills: $ROOT/.agents/skills/"
echo "  Cursor skills: $ROOT/.cursor/skills/"
echo "Merge .codex/config.toml [agents] manually if needed — see docs/agent/model-routing.md"
