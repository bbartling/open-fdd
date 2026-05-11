---
name: workspace-memory
description: "Authors and maintains workspace MEMORY.md and memory/ daily and domain notes for building systems, generated tools, and operator outcomes. Use when persisting portfolio context across Codex sessions."
---

# Workspace memory

## Layout

- `workspace/MEMORY.md` — curated bootstrap loaded each session (truncate via `bootstrap_max_chars`).
- `workspace/memory/YYYY-MM-DD.md` — daily append-only notes.
- `workspace/memory/sites|clients|engineers|tools/<id>.md` — domain detail.
- `workspace/scratch/` — ephemeral agent drafts (gitignored with the rest of `workspace/`).

## Agent duties

- Record durable site maps, rule decisions, and generated service inventory in `MEMORY.md`.
- Put session detail in daily notes; promote only stable facts to `MEMORY.md`.
- Never store secrets in Markdown.
- Promote reviewed helpers from `workspace/scratch/` into `skills/<domain>/scripts/` via PR.

## Shell commands

- `/memory` — preview bootstrap memory.
- `/memory search <query>` — keyword search across memory files.
- `/memory remember <text>` — append to today's daily note.

See [references/REFERENCE.md](references/REFERENCE.md).
