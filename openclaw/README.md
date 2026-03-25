# OpenClaw lab (bench + operator context)

**Cursor + OpenClaw collaboration:** see [`HANDOFF_PROTOCOL.md`](HANDOFF_PROTOCOL.md) (shared `issues_log.md` + logs; no live agent-to-agent chat).

**Agent skill (OpenClaw):** [`SKILL.md`](SKILL.md) with [`references/`](references/) (install: [`references/skill_installation.md`](references/skill_installation.md)), [`scripts/`](scripts/), [`assets/`](assets/).

This directory is the **lab workspace** for OpenClaw and humans: optional E2E/BACnet bench harness, SPARQL fixtures, Windows runners, report templates, and issue-tracking notes. It **supersedes** the experimental repo **bbartling/open-fdd-automated-testing**—use this tree inside **open-fdd** only.

Product docs and canonical operator guidance remain in [`docs/`](../docs/), especially [`docs/openclaw_integration.md`](../docs/openclaw_integration.md), [`docs/operations/`](../docs/operations/), and [`config/ai/operator_framework.yaml`](../config/ai/operator_framework.yaml).

## What this bench is for

This is a **test-bench only** workspace. Use it to validate:
- full-stack startup and stability
- knowledge-graph-only behavior
- data-ingestion/BACnet scrape behavior
- fault calculation against fake BACnet devices
- AI-assisted Brick/data modeling flows
- frontend widget smoke tests
- bootstrap script health and logs
- issue-driven regression coverage

## Three modes (how to work)

These are **workflow labels**, not separate Docker products. Pick commands to match intent.

1. **Software dev / app testing** — From repo root: `./scripts/bootstrap.sh --test` (frontend + pytest + Caddy). For heavier, environment-specific checks (Selenium, long BACnet runs), see [`bench/e2e/README.md`](bench/e2e/README.md) and [`docs/operations/testing_plan.md`](../docs/operations/testing_plan.md).
2. **AI data modeling** — Bring up a model-capable stack: `./scripts/bootstrap.sh --mode model` (or `--mode full` when you need the whole graph + API). Use SPARQL examples in [`bench/sparql/`](bench/sparql/) and the export/import loop in [`docs/openclaw_integration.md`](../docs/openclaw_integration.md).
3. **AI virtual building operator / assistant** — Full stack: `./scripts/bootstrap.sh` (default **full**). Optional retrieval sidecar: `./scripts/bootstrap.sh --with-mcp-rag` → RAG service at `http://localhost:8090`. Discover HTTP tool mappings at `http://localhost:8000/mcp/manifest` (Bearer `OFDD_API_KEY` from `stack/.env` when auth is on). Operator runbooks: [`docs/operations/mode_aware_runbooks.md`](../docs/operations/mode_aware_runbooks.md).

## Modes to test explicitly

- `./scripts/bootstrap.sh --test`
- `./scripts/bootstrap.sh --mode collector`
- `./scripts/bootstrap.sh --mode model`
- `./scripts/bootstrap.sh --mode engine`
- `./scripts/bootstrap.sh --with-mcp-rag`
- `./scripts/bootstrap.sh --verify`

## Layout

| Path | Purpose |
|------|---------|
| [`bench/fake_bacnet_devices/`](bench/fake_bacnet_devices/) | Ansible + Python fake BACnet devices for end-to-end FDD validation. |
| [`bench/sparql/`](bench/sparql/) | Example `.sparql` files for graph / operator checks. |
| [`bench/scripts/`](bench/scripts/) | Small helpers (e.g. fault schedule monitor). |
| [`bench/e2e/`](bench/e2e/) | Optional Selenium / long-run Python suites (`requirements-e2e.txt`). |
| [`bench/fixtures/`](bench/fixtures/) | Sample LLM/import JSON payloads for testing. |
| [`bench/rules_lab/README.md`](bench/rules_lab/README.md) | Canonical live rules live under **`stack/rules/`** (not duplicated here). |
| [`bench/rules_reference/`](bench/rules_reference/) | Reference YAML (AHU FC, chillers, weather, …) for docs and lab; see [Test bench rule catalog](../docs/rules/test_bench_rule_catalog.md). |
| [`windows/`](windows/) | Example `.cmd` wrappers (edit URLs/paths for your host). |
| [`dashboard/`](dashboard/) | Static operator progress UI; `progress.json` is gitignored. |
| [`reports/`](reports/) | Templates + README; dated summaries gitignored by default. |
| [`reports/drafts/`](reports/drafts/) | Issue-draft artifacts moved from the old repo. |
| [`docs/`](docs/) | Optional lab-only notes not published on GitHub Pages (most docs live under repo `docs/`). |
| [`issues_log.md`](issues_log.md) | Rolling diagnosis log for bugs, regressions, and follow-up items. |

## Testing coverage goals

The bench should stay focused on:
- BACnet raw-read vs calculated-fault comparisons
- rules engine verification
- SPARQL and graph sync checks
- frontend widget and data-model workflow smoke tests
- bootstrap and service health monitoring
- issue-driven regression notes

## Issue hygiene

Keep a local diagnosis trail in `openclaw/issues_log.md` while testing. If a real regression is found, note:
- what failed
- which mode reproduced it
- what endpoint/script was used
- any logs or evidence worth preserving
- whether it maps to a GitHub issue

## Quick commands (repo root)

```bash
./scripts/bootstrap.sh                    # full stack
./scripts/bootstrap.sh --mode collector   # collector slice
./scripts/bootstrap.sh --mode model       # model slice
./scripts/bootstrap.sh --mode engine      # engine slice
./scripts/bootstrap.sh --test             # CI-style matrix
./scripts/bootstrap.sh --with-mcp-rag     # add MCP RAG :8090
```

## Host prerequisites for `./scripts/bootstrap.sh --test`

Backend checks use **`pytest` on the host** (not inside the API container). `scripts/bootstrap.sh` picks **`.venv/bin/python`** when that file exists and is executable; otherwise it uses **`python3`**, which often has **no `pytest`** → you see `No module named pytest`.

**One-time setup from repo root** (matches [root README](../README.md#development-branches-and-tests)):

```bash
python3 -m venv .venv
source .venv/bin/activate   # or: . .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
```

Then run `./scripts/bootstrap.sh --test` again. Frontend + Caddy parts of the matrix use Docker/containers; backend pytest is the usual first failure without this venv.

**Logs:** capture long runs under `openclaw/logs/` (e.g. `bootstrap-test-YYYY-MM-DD_HH-MM-SS.txt` with `stdout`+`stderr`).

## Copy-paste for an agent

*Path discipline: workspace root may contain `AGENTS.md` / `SOUL.md`; all `./scripts/*` run from **open-fdd** repo root after `cd open-fdd`. Logs under `openclaw/logs/`.*

*Before `./scripts/bootstrap.sh --test`, ensure host dev deps: `python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"` (pytest comes from `[dev]`). Then `./scripts/bootstrap.sh` (if stack needed) and `./scripts/bootstrap.sh --test`. Discover tools from `http://localhost:8000/mcp/manifest` and, if MCP RAG is up, `http://localhost:8090/manifest`. Read `stack/.env` for `OFDD_API_KEY`. Use `openclaw/issues_log.md` for diagnosis notes.*
