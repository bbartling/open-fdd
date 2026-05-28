---
name: workspace-cron
description: "Registers and runs scheduled workspace jobs for FDD batches, HVAC health checks, ingest, shell workers, and Codex turns. Use when operators need recurring automation beyond interactive shell sessions."
---

# Workspace cron

## Storage

- `workspace/cron/jobs.json` — durable job definitions (version control friendly).
- `workspace/cron/jobs-state.json` — runtime next/last run metadata (gitignore).
- `workspace/cron/runs/<job_id>/*.json` — run logs.

## Services

`noop`, `shell`, `memory_append`, `codex_turn`, `wake`, `fdd_batch`, `health_bridge`, `health_hvac`, `webhook`.

`wake` runs the full mini + critique loop (`openfdd-wake`). For single turns, set `codex_turn` `payload.wake_mode` to `mini` or `critique` (see [workspace-memory](../workspace-memory/SKILL.md)).

## CLI

```bash
openfdd-workspace-cron --repo-root . list
openfdd-workspace-cron --repo-root . add --name nightly-fdd --every-seconds 86400 --service fdd_batch --payload-json "{\"site_ids\":[\"site-1\"]}"
openfdd-workspace-cron --repo-root . tick
```

Shell: `/cron list`, `/cron tick`, `/cron run <job_id>`.

See [references/REFERENCE.md](references/REFERENCE.md).
