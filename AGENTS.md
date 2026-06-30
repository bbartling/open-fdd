# Agent Guide (Rust edge + external orchestrators)

Open-FDD **3.2.x** is a **deterministic Rust edge runtime** (`ghcr.io/bbartling/openfdd-edge-rust`). AI assistance uses **external** tools — Cursor, Codex, OpenClaw — via git, safe bash scripts, and JWT REST. Built-in Ollama and MCP-RAG are **not** required for core operation.

| Layer | Responsibility |
| --- | --- |
| **Rust edge** | `openfdd-bridge`, `openfdd-commission`, `openfdd-haystack-gateway` — poll, historian, FDD, reports |
| **External agent** | Docs/code PRs, validation scripts, read-only API inspection |
| **Optional Ollama** | Local-only doc helper for operators — not a bridge dependency |
| **Optional MCP** | Read-first `openfdd-mcp` GHCR sidecar (3.2.3+) — [mcp/README.md](mcp/README.md); not started by site update |

**Agent docs:** [MCP & agents](https://bbartling.github.io/open-fdd/mcp-agents/) · [API routes](https://bbartling.github.io/open-fdd/api/routes.html) · [agent safety](https://bbartling.github.io/open-fdd/mcp-agents/agent-safety.html) · [mcp/README.md](mcp/README.md)

**Cursor agents:** `.cursor/agents/openfdd-retrofit-orchestrator.md` · `.cursor/agents/simple-test-triage.md`

Use Rust lifecycle scripts and JSON API. No Python runtime required.

## Start session

After auth merge on `master`:

```bash
INTEGRATOR_PW="$(grep '^OFDD_INTEGRATOR_PASSWORD=' ~/open-fdd/workspace/auth.env.local | cut -d= -f2-)"
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u integrator --arg p "$INTEGRATOR_PW" '{username:$u,password:$p}')" \
  | jq -r '.token // .access_token')"
```

Discover routes: `curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/agent/tools | jq '.tools | length'`

## Safe scripts

```bash
./scripts/openfdd_rust_edge_bootstrap.sh --start
./scripts/openfdd_rust_site_backup.sh
./scripts/openfdd_rust_site_update.sh   # pull GHCR :latest after master merge
./scripts/openfdd_rust_check_ghcr_platform.sh
./scripts/openfdd_rust_edge_validate.sh
./scripts/openfdd_drivers_validate.sh   # field bench: BACnet/Modbus/Haystack/JSON API
```

After a release merge to `master`, run `openfdd_rust_site_update.sh` to pull the new `ghcr.io/bbartling/openfdd-edge-rust` image. Verify with `/api/health` (`version` + `image_tag`).

**Optional MCP (3.2.3+):** site update does not pull/start MCP. After validate:

```bash
export OPENFDD_COMPOSE_ROOT=~/open-fdd OPENFDD_IMAGE_TAG=3.2.6
docker compose -f docker/compose.edge.rust.yml --profile mcp-sidecar pull openfdd-mcp
export OPENFDD_MCP_TOKEN="$TOKEN"
```

Cursor stdio config: [mcp/README.md](mcp/README.md).

## Model routing (external agents)

| Class | Examples | Use |
| --- | --- | --- |
| **Simple** | One test fail, HTTP status, fmt diff, missing selector | Worker / `simple-test-triage` |
| **Complex** | Auth/RBAC, deploy scripts, multi-service smoke, OT writes | Orchestrator / thinking model |

## Never

- delete `workspace/`
- run `docker compose down -v`
- run `docker volume prune`
- print secrets or tokens
- expose API on public internet
- write BACnet without explicit human approval
- hardcode BACnet device instances (e.g. 5007), building names, or bench-specific routes in production Rust/TS
- add simulated/smoke-mirror OT data paths (`OPENFDD_*_MODE=simulated`, `simulated_values`, `simulation_phase`, fake driver points)
- use `#[allow(dead_code)]` to silence unused code — delete or wire it up instead
- treat dashboard Ollama/Agent UI placeholders as production requirements

Live OT I/O uses `OPENFDD_BACNET_MODE=live` and `OPENFDD_MODBUS_MODE=live` only. CI SQL proof uses `validation:fixture` historian rows (not OT simulation). Opt-in field tests require env-configured device instances — never a default bench ID in repo code.

## Assignment rule

Bind drivers → Haystack IDs → FDD/CDL via `/api/model/assignments`.

## Legacy (Python / built-in Ollama / MCP-RAG)

Older docs or UI labels may reference Rule Lab, FastAPI bridge, or `openfdd-mcp-rag`. Archived material is under `docs/archive/` — use the [online docs](https://bbartling.github.io/open-fdd/) for current Rust 3.2.x guidance.
