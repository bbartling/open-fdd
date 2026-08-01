# Agent Guide (container stack + external agents)

Open-FDD ships as a **container stack**: `openfdd-central`, `openfdd-web` (React),
`openfdd-fieldbus`, `openfdd-mqtt`, plus optional `openfdd-mcp` (legacy
`openfdd-ui` Streamlit archived). It does **not** ship an embedded AI chatbot.
External orchestrators — Codex CLI, Cursor, OpenClaw, Claude Desktop, or any MCP
host — connect via **JWT REST** and optional **`openfdd-mcp` stdio**.

| Layer | Responsibility |
| --- | --- |
| **central** | MQTTS ingest, Feather, FDD registry SQL, REST + JWT |
| **web** | React product UI (`frontend/web`) — sole production UI after Phase 2 ([ADR-001](docs/architecture/adr-001-react-rust-modernization.md)) |
| **ui (archived)** | Streamlit (`services/ui`) — recovery via `ARCHIVED.md` / `streamlit-legacy` |
| **fieldbus** | BACnet / Modbus / Haystack OT drivers |
| **mqtt** | Mosquitto MQTTS broker |
| **mcp** | Optional read-first stdio tools → central (`OPENFDD_API_BASE`) |

**Docs:** [Build recipes](docs/operations/build-recipes.md) · [External agents](docs/examples/external-agents.md) · [MCP README](mcp/README.md) · [ECM engineering (PyPI)](docs/ecm/README.md) · [React/Rust modernization](docs/migration/react-rust/README.md)

**Software-engineering agent OS:** [`openfdd_agent_spec/`](openfdd_agent_spec/) — architecture locks, skills, Milestone A ([`openfdd_agent_spec/MILESTONE_A.md`](openfdd_agent_spec/MILESTONE_A.md)). Ops/edge soak prompts stay under [`docs/agent/`](docs/agent/).

**React/Rust modernization (Phase 1+2 exit approved; Phase 3 outlook):** [`tools/open-fdd-modernization/`](tools/open-fdd-modernization/README.md) · skill bridge [`AGENT_SKILL_BRIDGE.md`](tools/open-fdd-modernization/AGENT_SKILL_BRIDGE.md) · required UI skill [`streamlit-to-react`](tools/open-fdd-modernization/skills/streamlit-to-react/SKILL.md).

**PyPI (`open-fdd` 4.1+):** ECM engineering + pandas oracle (`open_fdd.rules` / `analytics` / `reporting`) via extras. Production FDD is DataFusion/GHCR, not this wheel.

## Start session

```bash
./scripts/openfdd_stack_up.sh standalone   # or csv / central
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"'"$OPENFDD_ADMIN_PASSWORD"'"}' \
  | jq -r '.token // .access_token')"
```

Discover routes: `curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/agent/tools | jq '.tools | length'`

## Safe scripts

```bash
./scripts/openfdd_stack_pull.sh standalone
./scripts/openfdd_stack_up.sh standalone
./scripts/openfdd_stack_up.sh csv
```

## External agent workflow

1. Stack healthy on LAN/VPN only — never expose on public internet.
2. JWT for admin/operator/viewer (see central auth env).
3. `openfdd-mcp` stdio outside the web UI, or REST `/api/agent/tools`.
4. Read-first; writes need `OPENFDD_MCP_ALLOW_WRITES=1` and `confirm:true`.
5. Never print secrets. BACnet writes need explicit human approval.

## Never

- delete `workspace/`
- run `docker compose down -v`
- run `docker volume prune`
- print secrets or tokens
- expose API on public internet
- write BACnet without explicit human approval
- embed vendor chat relays or model API keys in the stack

See [docs/agent/index.md](docs/agent/index.md) for external-agent architecture and API context.

For library/migration/PR missions (Milestone A), start at [openfdd_agent_spec/AGENTS.md](openfdd_agent_spec/AGENTS.md).
