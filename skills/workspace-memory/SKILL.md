---
name: workspace-memory
description: "Authors and maintains workspace MEMORY.md and memory/ daily and domain notes for building systems, generated tools, and operator outcomes. Use when persisting portfolio context across Codex sessions."
---

# Workspace memory

## Layout

- `workspace/MEMORY.md` — curated bootstrap loaded each session (truncate via `bootstrap_max_chars`).
- `workspace/BUILD_CHECKPOINTS.md` — ordered mini queue; critique rewrites **Next for mini**.
- `workspace/scratch/memory-bootstrap-latest.md` — regenerated each wake for stable Codex context.
- `workspace/memory/YYYY-MM-DD.md` — daily append-only notes.
- `workspace/memory/sites|clients|engineers|tools/<id>.md` — domain detail.
- `workspace/memory/architecture/working-divergence.md` — append-only log when working `workspace/` or automation differs from skills or `AGENTS.md` because the documented path failed or was incomplete.
- `workspace/scratch/` — ephemeral agent drafts (gitignored with the rest of `workspace/`).

## Agent duties

- Record durable site maps, rule decisions, and generated service inventory in `MEMORY.md`.
- Put session detail in daily notes; promote only stable facts to `MEMORY.md`.
- Never store secrets in Markdown.
- Promote reviewed helpers from `workspace/scratch/` into `skills/<domain>/scripts/` via PR.
- **Mini:** if implementation works but skills or spec do not, append one dated block to `working-divergence.md` (expectation, reality, evidence, status open).
- **Critique:** triage open divergence entries; promote stable patterns into `skills/*/references/` or `MEMORY.md`; mark entries promoted or superseded.

## Shell commands

- `/memory` — preview bootstrap memory.
- `/memory search <query>` — keyword search across memory files.
- `/memory remember <text>` — append to today's daily note.

See [references/REFERENCE.md](references/REFERENCE.md).
