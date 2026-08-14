# Agent Guide (container stack + external agents)

Open-FDD ships as a **container stack**: `openfdd-central`, `openfdd-web` (React),
`openfdd-fieldbus`, `openfdd-mqtt`, plus optional `openfdd-mcp`. It does **not**
ship an embedded AI chatbot. External orchestrators — Codex CLI, Cursor,
OpenClaw, Claude Desktop, or any MCP host — connect via **JWT REST** and optional
**`openfdd-mcp` stdio**.

| Layer | Responsibility |
| --- | --- |
| **central** | MQTTS ingest, Feather/Parquet historian, DataFusion SQL FDD + `/api/analytics/*`, REST + JWT (Rust image — no Python) |
| **web** | React product UI (`frontend/web`) — sole product UI ([ADR-001](docs/architecture/adr-001-react-rust-modernization.md)) |
| **fieldbus** | BACnet / Modbus / Haystack OT drivers |
| **mqtt** | Mosquitto MQTTS broker |
| **mcp** | Optional read-first stdio tools → central (`OPENFDD_API_BASE`) |

**Docs:** [Build recipes](docs/operations/build-recipes.md) · [External agents](docs/examples/external-agents.md) · [MCP README](mcp/README.md) · [ECM engineering (PyPI)](docs/ecm/README.md)

**Software-engineering agent OS:** [`openfdd_agent_spec/`](openfdd_agent_spec/) — architecture locks, skills, Milestone A.

**Active recovery / Vibe 21 twin program:** [`tools/open-fdd-vibe21-production/`](tools/open-fdd-vibe21-production/README.md) · capability ledger [`docs/migration/react-rust/capabilities.yaml`](docs/migration/react-rust/capabilities.yaml).

**PyPI (`open-fdd`):** ECM engineering + pandas oracle (`open_fdd.rules` / `analytics` / `reporting`) for **third-party tooling** outside the product app. Product FDD is DataFusion on GHCR.

Dual expression cookbooks (permanent): `docs/rules/cookbook/` (SQL + pandas).

## Start session

Unmerged UI is **not** on GHCR. Resolve newest published images by OCI
`created` (`./scripts/ghcr_newest_by_created.py`), and never paste a Caddy
URL until `./scripts/openfdd_demo_gate.sh` exits 0. See
[`CONTAINER_AGENT.md`](openfdd_agent_spec/CONTAINER_AGENT.md).

```bash
./scripts/openfdd_stack_up.sh react-ot     # React SPA + mqtt + central + fieldbus
# or: react (no fieldbus) / csv
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"'"$OPENFDD_ADMIN_PASSWORD"'"}' \
  | jq -r '.token // .access_token')"
```

Discover routes: `curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/agent/tools | jq '.tools | length'`

## Safe scripts

```bash
./scripts/openfdd_stack_pull.sh react-ot
./scripts/openfdd_stack_up.sh react-ot
./scripts/nightly-ot-bench/run_all.sh      # pull sha-* + OT/API gates
./scripts/openfdd_stack_up.sh csv
```

## External agent workflow

1. Stack healthy on LAN/VPN only — never expose on public internet.
2. JWT for admin/operator/viewer (see central auth env).
3. `openfdd-mcp` stdio outside the web UI, or REST `/api/agent/tools`.
4. Read-first; writes need `OPENFDD_MCP_ALLOW_WRITES=1` and `confirm:true`.
5. Never print secrets. BACnet writes need explicit human approval.

## Product UI / FDD agent notes

- **Overview plots:** plot Expanders default **open** so charts are not hidden behind carets (`OverviewPopulated`).
- **Lab → FDD Plots:** `session_config` `confirm_min` (and rule params) apply to the series overlay (`sql_detail_session`). After **Update this rule**, Reports/FDD Plots must refetch on `RULES_UPDATED`.
- **SCHED-1 occupancy:** treat numeric `0` / `0.0` / `false` **and** string `unoccupied` (and related tokens) as unoccupied — SQL + pandas cookbook stay aligned.
- **Synthetic-59:** soak via `scripts/synthetic_59_*.py` under `reports/wattlab-parity/fixtures/synthetic_59/`. Do not greenwash `expected_faults.csv`. B100 dump-parity remains **paused**.
- **Units:** FDD SQL is °F canonical. Metric CSVs convert at query (`unit_system=metric|si`). Lab sliders show °C when metric is selected; Run all rules after switching.
- **Hourly append:** seed with `POST /api/csv/import/package`, then `POST /api/csv/import/package/append` (JWT, `confirm:true`). Custom appenders stay outside the repo.
- **Overview layout:** full width beside sidebar (Streamlit-like); named Plotly PNG stems via `downloadFilename`; Lab rule menu A–Z; FDD series = required∪optional roles.
- **Mech OAT bins:** status/cmd before amps; prefer web/weather OAT. Analytics envelopes: `scripts/synthetic_59_overview_analytics_soak.py`.

## Low-RAM hosts (bensbench)

- **Never** local `docker build` / heavy Rust compile for stack images. Ship via PR → GH Actions → GHCR `nightly` / `sha-*`.
- Before pulling new images: prune unused/old digests first, then `./scripts/openfdd_stack_pull.sh …` and `./scripts/openfdd_stack_up.sh … --no-pull`.
- Details: [`openfdd_agent_spec/CONTAINER_AGENT.md`](openfdd_agent_spec/CONTAINER_AGENT.md).

## Never

- delete `workspace/`
- run `docker compose down -v`
- run `docker volume prune`
- print secrets or tokens
- expose API on public internet
- write BACnet without explicit human approval
- embed vendor chat relays or model API keys in the stack
- add Python to the product central/web request path
- local stack image builds on low-RAM hosts (use GHCR)

See [docs/agent/index.md](docs/agent/index.md) for external-agent architecture.

For library/migration/PR missions (Milestone A), start at [openfdd_agent_spec/AGENTS.md](openfdd_agent_spec/AGENTS.md).
