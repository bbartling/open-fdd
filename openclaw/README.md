# OpenClaw lab (bench + operator context)

This directory is the **lab workspace** for OpenClaw and humans: optional E2E/BACnet bench harness, SPARQL fixtures, Windows runners, and report templates. It **supersedes** the experimental repo **bbartling/open-fdd-automated-testing**—use this tree inside **open-fdd** only.

Product docs and canonical operator guidance remain in [`docs/`](../docs/), especially [`docs/openclaw_integration.md`](../docs/openclaw_integration.md), [`docs/operations/`](../docs/operations/), and [`config/ai/operator_framework.yaml`](../config/ai/operator_framework.yaml).

## Three modes (how to work)

These are **workflow labels**, not separate Docker products. Pick commands to match intent.

1. **Software dev / app testing** — From repo root: `./scripts/bootstrap.sh --test` (frontend + pytest + Caddy). For heavier, environment-specific checks (Selenium, long BACnet runs), see [`bench/e2e/README.md`](bench/e2e/README.md) and [`docs/operations/testing_plan.md`](../docs/operations/testing_plan.md).
2. **AI data modeling** — Bring up a model-capable stack: `./scripts/bootstrap.sh --mode model` (or `--mode full` when you need the whole graph + API). Use SPARQL examples in [`bench/sparql/`](bench/sparql/) and the export/import loop in [`docs/openclaw_integration.md`](../docs/openclaw_integration.md).
3. **AI virtual building operator / assistant** — Full stack: `./scripts/bootstrap.sh` (default **full**). Optional retrieval sidecar: `./scripts/bootstrap.sh --with-mcp-rag` → RAG service at `http://localhost:8090`. Discover HTTP tool mappings at `http://localhost:8000/mcp/manifest` (Bearer `OFDD_API_KEY` from `stack/.env` when auth is on). Operator runbooks: [`docs/operations/mode_aware_runbooks.md`](../docs/operations/mode_aware_runbooks.md).

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

## Quick commands (repo root)

```bash
./scripts/bootstrap.sh                    # full stack
./scripts/bootstrap.sh --mode collector   # collector slice
./scripts/bootstrap.sh --mode model       # model slice
./scripts/bootstrap.sh --mode engine      # engine slice
./scripts/bootstrap.sh --test             # CI-style matrix
./scripts/bootstrap.sh --with-mcp-rag     # add MCP RAG :8090
```

## Copy-paste for an agent

*Working directory: **open-fdd** repo root. Run `./scripts/bootstrap.sh` then `./scripts/bootstrap.sh --test` when asked to validate. Discover tools from `http://localhost:8000/mcp/manifest` and, if MCP RAG is up, `http://localhost:8090/manifest`. Read `openclaw/README.md` and `stack/.env` for `OFDD_API_KEY`.*
