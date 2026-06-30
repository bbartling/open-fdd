# Open-FDD external multi-agent architecture

Open-FDD is a **deterministic Rust edge runtime**. AI assistance is provided by **external orchestrators** (Cursor, Codex, OpenClaw on a bench host) using safe repo workflows, tests, and JWT-authenticated REST — not by embedding Ollama or MCP-RAG inside the bridge container.

## Layered model

```text
┌─────────────────────────────────────────────────────────────┐
│  External orchestrator (Cursor / Codex / OpenClaw on LAN)      │
│  - plans, edits docs/code, opens PRs                         │
│  - runs safe scripts (bootstrap, validate, smoke)              │
│  - uses thinking model for security / multi-service issues   │
└───────────────────────────┬─────────────────────────────────┘
                            │ git, bash, curl+JWT (127.0.0.1)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Open-FDD Rust edge (deterministic)                          │
│  openfdd-bridge │ openfdd-commission │ openfdd-haystack-gw   │
│  historian · DataFusion FDD · drivers · reports              │
└───────────────────────────┬─────────────────────────────────┘
                            │ BACnet / Modbus / Haystack (OT LAN)
                            ▼
                     Field devices & stations
```

Optional (operator choice, **not required**):

```text
┌──────────────────┐     read-only docs/RAG
│ Ollama (local)   │ ──► external agent only — never bridge runtime
└──────────────────┘

┌──────────────────┐     future read-first tools
│ openfdd-mcp      │ ──► SERVICE_MODE=mcp (not in 3.2.x core)
└──────────────────┘
```

## Responsibilities

### Rust edge (in scope for releases)

- Authenticate operators/integrators/agents via JWT
- Discover, poll, and historize OT data (live drivers)
- Run DataFusion SQL fault rules with confirmation delays
- Export overrides, faults, RCx/PDF reports
- Enforce RBAC on integrator/agent mutations

### External Cursor/Codex agents (in scope for this retrofit)

- Read and update **docs**, **scripts**, **tests**, and **dashboard** in git
- Invoke **safe** lifecycle scripts (`openfdd_rust_edge_*`, smoke harnesses)
- Never mutate live `workspace/` on a production bench without operator intent
- Route tasks: **simple-test-triage** vs **openfdd-retrofit-orchestrator** (see `.cursor/agents/`)

### Mini / worker models

Use for:

- CI log triage ("test X failed", "404 on route Y")
- Markdown/link checks, `git diff --check`
- Single-service health (`curl /api/health`)

Escalate to thinking/orchestrator when auth, OT writes, or cross-container behavior is involved.

### Thinking / orchestrator models

Use for:

- Security and RBAC changes
- Deploy/update/restore script edits
- Flaky or race-sensitive validation
- BACnet/Modbus/Haystack write APIs (design + approval gates)
- "Green CI but wrong behavior" investigations

### Ollama (optional, local-only)

- May assist operators with **documentation** and **runbook Q&A**
- Must not be exposed on public interfaces
- Dashboard Agent tab and Ollama host-stats blocks are **placeholders** — not production dependencies
- Do not block releases on Ollama availability

### MCP (`openfdd-mcp`)

- Stdio sidecar — [mcp/README.md](../../mcp/README.md)
- Read-first tools including model SPARQL — [openfdd-mcp-tool-contract.md](openfdd-mcp-tool-contract.md)
- Writes and rule activation require explicit human approval

## Session pattern (external agent)

1. Read [AGENTS.md](../../AGENTS.md) and [agent-safety-boundaries.md](../security/agent-safety-boundaries.md)
2. Login via integrator/agent role (password from local env file — never log token)
3. `GET /api/health/stack`, driver trees, model coverage
4. Propose changes in git; validate with `cargo test`, compose smoke, or field scripts
5. Field proof on edge bench (`~/open-fdd`) via GHCR pull — not git clone on device

## OpenClaw / field bench

README OpenClaw prompts remain valid as **external** operator agents driving the Rust edge over SSH — they are not an in-process Ollama integration.

## See also

- [openfdd-agent-current-standing.md](openfdd-agent-current-standing.md)
- [../AI_AGENT_API.md](../AI_AGENT_API.md) — REST catalog (verify routes against `GET /api/agent/tools`)
