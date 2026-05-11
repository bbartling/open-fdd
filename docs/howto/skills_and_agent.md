---
title: Skills and agent shell
parent: How-to guides
nav_order: 5
---

# Skills and agent shell

The repository ships the **pandas rules engine** on PyPI. Dashboards, HTTP bridges, ingest drivers, MCP retrieval, and deployment recipes live under **`skills/`** and are built on demand with **`openfdd.toml`** plus the local **agent shell**.

## Install paths

| Goal | Command |
|------|---------|
| Bare import / DataFrame work | `pip install open-fdd` |
| YAML rules + `RuleRunner` | `pip install "open-fdd[engine]"` |
| Maintainer checkout | `pip install -e ".[dev]"` |
| Agent shell (not on PyPI) | `pip install -e packages/openfdd-agent-shell` |

The **`[engine]`** extra adds **PyYAML** and **pydantic** for rule loading and validation. NumPy arrives transitively through **pandas**.

## Manifest

Copy **`openfdd.toml.example`** to **`openfdd.toml`** and set:

- **`[build].targets`** — `api`, `dashboard`, `feather_storage`, …
- **`[build].drivers`** — `csv`, `openmeteo`, `bacnet`, …
- **`[build].auth`** / **`[build].deploy`** — local, Caddy, systemd, Ansible bench
- **`[agent].skills`** — skill folder names under **`skills/`**
- **`[memory]`** — `MEMORY.md` bootstrap path, daily note lookback, truncation budget
- **`[cron]`** — `jobs.json`, runtime state, and run log directories

Generated application code belongs in **`workspace/`** (see **`AGENTS.md`**). Portfolio memory and schedules live beside generated services under the same workspace tree.

## Agent shell

```bash
openfdd-agent-shell --repo-root .
```

The shell loads **`AGENTS.md`**, workspace **`MEMORY.md`** (plus recent daily notes), selected **`skills/*/SKILL.md`** files, and launches **Codex CLI** with a composed system prompt. Slash commands include **`/skills`**, **`/plan`**, **`/verify`**, **`/engine-check`**, **`/open-workspace`**, **`/memory`**, and **`/cron`**.

Workspace cron CLI:

```bash
openfdd-workspace-cron --repo-root . list
openfdd-workspace-cron --repo-root . tick
```

Dry-run a single turn:

```bash
openfdd-agent-shell --repo-root . --dry-run --message "scaffold csv ingest only"
```

## Rule authoring

Expression and YAML semantics are unchanged. Start with the **[Expression rule cookbook](../expression_rule_cookbook)** and **[Rules overview](../rules/overview)**.

Historical desktop/MCP how-tos under **`howto/desktop_app.md`** describe the retired monolith; new integrations should follow **`skills/`**.
