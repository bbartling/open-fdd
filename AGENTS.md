# Open-FDD agent policy

This repository is **engine-first**. The published PyPI wheel (`open-fdd`) provides pandas fault detection (`open_fdd.engine`, optional YAML via `[engine]` extra) and reports. The **operator stack** under `workspace/` uses **Python rules in Rule Lab**, not hot-reloaded YAML files.

## Default path

- Rules-only library work: `pip install "open-fdd[engine]"` (or editable install) and use `open_fdd.engine.RuleRunner` on pandas DataFrames in notebooks.
- Operator **Rule Lab** work: extend `workspace/api/` and `workspace/dashboard/` — Python rules only; no YAML hot-reload directory.
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

- Author Python rules in **Rule Lab** (`evaluate(row, cfg, …)` or DataFrame scripts); persist via `POST /api/rules/save` → **`workspace/data/rules_py/*.py`** + `rules_store.json`.
- Humans and AI share the same `.py` files: browser save and `POST /openfdd-agent/tool` (`rules.save`) both call `RuleStore.upsert()`. Doc: [docs/howto/rule_lab_storage.md](docs/howto/rule_lab_storage.md).
- Run batches with `POST /api/rules/batch` or `python -m openfdd_bridge.fdd_runner` (from `workspace/api/`); local stack: `./scripts/run_local.sh start`.
- Use `open_fdd.engine.column_map_from_model` (and playground sandbox) on the bridge — not a separate YAML rule runner in generated apps.
- For standalone **library** use outside the operator stack, `open_fdd.engine.RuleRunner` with YAML files remains available via `pip install "open-fdd[engine]"` (see [engine-pandas-fdd](skills/engine-pandas-fdd/SKILL.md)).

## Security

- Bind services to `127.0.0.1` by default; require explicit operator opt-in for LAN (`0.0.0.0`) or Caddy ingress.
- Secrets via environment variables or local env files — never commit credentials.
- Historical desktop/MCP how-tos under `docs/howto/` describe the **retired monolith**; prefer `skills/` for new builds.

## Skill routing

| Operator intent | Start with |
|-----------------|------------|
| Python rules in Rule Lab / batch FDD | [skills/rules-crud-and-batch-run/SKILL.md](skills/rules-crud-and-batch-run/SKILL.md) |
| YAML rules on CSV/DataFrames (library only) | [skills/engine-pandas-fdd/SKILL.md](skills/engine-pandas-fdd/SKILL.md) |
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
