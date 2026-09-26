#!/usr/bin/env bash
# Agent skills installer.
#
# Source of truth for Open-FDD product skills is openfdd_agent_spec/skills/.
# That tree is not Cursor-only. Any agent that can read markdown skills can use it.
#
#   ./scripts/openfdd_install_agent_skills.sh --sync [--user]
#       Symlink each product skill into repo homes for Cursor, Claude, and Codex.
#       --user also links into the home directories used by Cursor, Claude, Codex,
#       OpenClaw, Hermes, and Grok-style hosts.
#
#   ./scripts/openfdd_install_agent_skills.sh [path/to/research_review_agent_skills_v1.zip]
#       Install the separate research-review skill zip (existing behavior).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

sync_product_skills() {
  local user_home="${1:-}"
  local src_root="$ROOT/openfdd_agent_spec/skills"
  if [[ ! -d "$src_root" ]]; then
    echo "Missing skill source: $src_root" >&2
    exit 1
  fi
  local repo_dests=(
    "$ROOT/.cursor/skills"
    "$ROOT/.agents/skills"
    "$ROOT/.claude/skills"
  )
  local dest rel name target
  for dest in "${repo_dests[@]}"; do
    mkdir -p "$dest"
    rel="$(realpath --relative-to="$dest" "$src_root")"
    for skill in "$src_root"/*; do
      [[ -d "$skill" ]] || continue
      name="$(basename "$skill")"
      target="$dest/$name"
      if [[ -e "$target" && ! -L "$target" ]]; then
        echo "skip existing directory $target" >&2
        continue
      fi
      ln -sfn "$rel/$name" "$target"
    done
  done
  if [[ -n "$user_home" ]]; then
    local homes=(
      "$user_home/.cursor/skills"
      "$user_home/.claude/skills"
      "$user_home/.codex/skills"
      "$user_home/.agents/skills"
      "$user_home/.openclaw/skills"
      "$user_home/.hermes/skills"
      "$user_home/.grok/skills"
    )
    for dest in "${homes[@]}"; do
      mkdir -p "$dest"
      for skill in "$src_root"/*; do
        [[ -d "$skill" ]] || continue
        name="$(basename "$skill")"
        target="$dest/$name"
        if [[ -e "$target" && ! -L "$target" ]]; then
          echo "skip existing directory $target" >&2
          continue
        fi
        ln -sfn "$skill" "$target"
      done
    done
  fi
  echo "Synced product skills from $src_root"
  echo "Works with any AI agent that can read markdown skills and run the PyPI CLI."
  echo "Repo links: .cursor/skills .agents/skills .claude/skills"
}

if [[ "${1:-}" == "--sync" ]]; then
  if [[ "${2:-}" == "--user" ]]; then
    sync_product_skills "${HOME}"
  elif [[ -n "${2:-}" ]]; then
    echo "Usage: $0 --sync [--user]" >&2
    exit 2
  else
    sync_product_skills
  fi
  exit 0
fi

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
