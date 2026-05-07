# Toolshed

Convention for **built-in Open-FDD agent** (Codex CLI) artifacts in the **Open-FDD workdir** (usually the repo root).

| Path | Purpose | Git |
|------|---------|-----|
| **`toolshed/scratch/`** | All **new** agent-written code: scripts, probes, one-offs, drafts. | **Ignored** — never commit machine-local experiments. |
| **`toolshed/published/`** | **Reviewed** helpers worth keeping; operators promote from scratch. | **Tracked** — commit via normal PR flow. |

## Rules

1. **Scratch is mandatory for new files** — The agent system prompt instructs Codex to create and edit **only** under `toolshed/scratch/` unless the human explicitly asks for another path.
2. **No secrets** — Never write API keys, tokens, or `.env` contents into either tree.
3. **Promotion** — When something is reusable, copy or move it to `toolshed/published/`, add a short header comment, then open a PR.

See **`docs/howto/toolshed.md`** (How-to → **Toolshed** on the docs site) for the full layout and operator workflow.
