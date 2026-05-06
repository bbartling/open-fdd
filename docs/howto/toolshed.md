---
title: Toolshed
parent: How-to Guides
nav_order: 13
description: "Where the built-in Codex agent writes code (scratch vs published) and how operators curate a small tools library."
---

# Toolshed (agent artifacts)

The **built-in Open-FDD agent** runs **Codex CLI** in your configured **workdir** (usually the `open-fdd` repo root). To keep the tree clean and reviewable, the bridge **injects rules** so Codex treats two directories as the default home for file work.

## Layout

| Directory | Who | Git | Use |
|-----------|-----|-----|-----|
| **`toolshed/scratch/`** | Codex / agent | **Not committed** (gitignored except a placeholder) | **All new code** the agent writes: Python helpers, shell snippets saved as files, probes, drafts. |
| **`toolshed/published/`** | Humans (after review) | **Committed** | Small, reusable utilities you want in the repo long-term (“library” candidates). |

Repo pointers: `toolshed/README.md`, `toolshed/published/README.md`.

## Agent behavior (hard rule)

The system prompt tells Codex:

- **Create and edit new files only under `toolshed/scratch/`** relative to the workdir, unless the operator explicitly asks for another path (e.g. “patch `open_fdd/gateway/server.py`”).
- Do **not** drop throwaway scripts at the repo root, under `open_fdd/`, or under `apps/` unless explicitly instructed.
- **Secrets**: never write API keys, tokens, or raw `.env` into `toolshed/` (or anywhere).

Implementation lives in **`open_fdd.gateway.openfdd_agent`** (`_openfdd_agent_identity`) and bootstrap notes in **`open_fdd.gateway.openfdd_agent_context`**.

## Operator workflow

1. Run the agent (AI Agent tab or `POST /openfdd-agent/chat`) with workdir = repo root.
2. Inspect **`toolshed/scratch/`** after a turn — new files appear there.
3. If something is worth keeping, **copy or move** to **`toolshed/published/`**, add a short module docstring, run **`pytest`** / smoke as appropriate, then **commit in a normal PR**.

Scratch is ephemeral: clones may not have your local scratch contents; only **`published/`** is shared via Git.

## MCP / RAG

After adding or renaming toolshed docs, rebuild the MCP index if you rely on `search_docs` picking up new prose:

```bash
python scripts/build_mcp_rag_index.py --output stack/mcp-rag/index/rag_index.json
```

Then restart **`open-fdd-mcp-rag`** (or full **`start-local`**) so the server reloads the index — see **[Desktop app — Restarting start-local and MCP](desktop_app#restarting-start-local-and-mcp-important)**.

## Related

- **[Agent & operator playbook](agent_operator_playbook)** — bridge routes, MCP, execution patterns.
- **[Desktop app](desktop_app)** — workdir, Codex sandbox, `start-local`.
