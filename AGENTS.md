# Open-FDD agent policy

This repository is **engine-first**. The published PyPI wheel (`open-fdd`) contains pandas/YAML fault detection only. Everything beyond the engine is built on demand from `skills/` using the operator manifest (`openfdd.toml`) and the local agent shell (`packages/openfdd-agent-shell`).

## Default path

- Rules-only work: `pip install open-fdd` (or editable install from the repo root) and use `open_fdd.engine` on pandas DataFrames.
- A committed **operator starter** lives in `workspace/api/` and `workspace/dashboard/` (Rule Lab + FastAPI bridge). **Extend** that code when `[build]` includes `api` or `dashboard`; do not replace it unless asked.
- Do **not** add new top-level services beyond the manifest `[build]` section.

## Workspace writes

- Put all generated application code under `workspace/` (see `openfdd.toml` `workspace_dir` and `scratch_dir`).
- Durable portfolio context belongs in `workspace/MEMORY.md` and `workspace/memory/` (see [skills/workspace-memory/SKILL.md](skills/workspace-memory/SKILL.md)).
- When working `workspace/` code or automation diverges from skills or this file, append to `workspace/memory/architecture/working-divergence.md` (see `workspace/memory/architecture/README.md`).
- Recurring automation belongs in `workspace/cron/jobs.json` (see [skills/workspace-cron/SKILL.md](skills/workspace-cron/SKILL.md)).
- Ordered mini work belongs in `workspace/BUILD_CHECKPOINTS.md`; scheduled wakes use `openfdd-wake` or cron service `wake`.
- Do **not** modify `open_fdd/`, `packages/openfdd-engine/`, or `skills/` unless the operator explicitly asks for engine or skill maintenance.
- Experiments stay in `workspace/scratch/`; promote reviewed helpers into the relevant `skills/<domain>/scripts/` folder via PR.

## FDD execution

- Use `open_fdd.engine.RuleRunner` and YAML rules on DataFrames.
- Authoring reference: [docs/expression_rule_cookbook.md](docs/expression_rule_cookbook.md).
- Do not ship a bespoke rule runner in generated apps.

## Security

- Bind services to `127.0.0.1` by default; require explicit operator opt-in for LAN (`0.0.0.0`) or Caddy ingress.
- Secrets via environment variables or local env files — never commit credentials.
- Historical desktop/MCP how-tos under `docs/howto/` describe the **retired monolith**; prefer `skills/` for new builds.

## Skill routing

| Operator intent | Start with |
|-----------------|------------|
| Run YAML rules on CSV/DataFrames | [skills/engine-pandas-fdd/SKILL.md](skills/engine-pandas-fdd/SKILL.md) |
| Column map / manifest | [skills/column-map-and-manifests/SKILL.md](skills/column-map-and-manifests/SKILL.md) |
| HTTP bridge API | [skills/fastapi-bridge-api/SKILL.md](skills/fastapi-bridge-api/SKILL.md) |
| React dashboard | [skills/react-operator-dashboard/SKILL.md](skills/react-operator-dashboard/SKILL.md) |
| Local feather storage | [skills/feather-local-storage/SKILL.md](skills/feather-local-storage/SKILL.md) |
| CSV / weather / BACnet ingest | `skills/driver-*-ingest/` |
| BACnet single-stack / 47808 exclusivity | [skills/bacnet-single-stack/SKILL.md](skills/bacnet-single-stack/SKILL.md) |
| Rules CRUD + batch run | [skills/rules-crud-and-batch-run/SKILL.md](skills/rules-crud-and-batch-run/SKILL.md) |
| Building check-engine light + fault codes | [skills/building-check-engine/SKILL.md](skills/building-check-engine/SKILL.md) |
| Plots / cleaning | [skills/timeseries-plots-and-cleaning/SKILL.md](skills/timeseries-plots-and-cleaning/SKILL.md) |
| BRICK TTL model | [skills/brick-ttl-data-model/SKILL.md](skills/brick-ttl-data-model/SKILL.md) |
| MCP doc retrieval | [skills/mcp-doc-retrieval/SKILL.md](skills/mcp-doc-retrieval/SKILL.md) |
| Codex on bridge host | [skills/codex-agent-on-bridge/SKILL.md](skills/codex-agent-on-bridge/SKILL.md) |
| Workspace memory | [skills/workspace-memory/SKILL.md](skills/workspace-memory/SKILL.md) |
| Workspace cron | [skills/workspace-cron/SKILL.md](skills/workspace-cron/SKILL.md) |
| Local multi-process dev | [skills/local-dev-orchestration/SKILL.md](skills/local-dev-orchestration/SKILL.md) |
| Caddy / systemd / Ansible bench | `skills/caddy-*`, `skills/systemd-*`, `skills/ansible-*` |

Load each selected skill's `SKILL.md` and follow linked `references/REFERENCE.md` for route tables, env catalogs, and legacy source maps.
