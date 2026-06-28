# Open-FDD agent current standing (2026-06)

This document summarizes **what is true in the repo today** versus **legacy Python / built-in Ollama / MCP-RAG** assumptions still visible in UI stubs, comments, or old workflows.

## Current runtime (authoritative)

| Item | Current state |
| --- | --- |
| **Stack** | Rust edge — `open_fdd_edge_prototype` / `openfdd-edge` binary, React dashboard |
| **GHCR image** | `ghcr.io/bbartling/openfdd-edge-rust` (tags e.g. `3.2.2`, `3.2.3`, `latest`) |
| **Compose profiles** | `desktop-json-csv`, `full-edge`, optional `caddy-http` / `caddy-tls` |
| **Service containers** | `openfdd-bridge`, `openfdd-commission` (host network BACnet), `openfdd-haystack-gateway` |
| **Service modes** | `SERVICE_MODE=bridge \| commission \| haystack-gateway` (same image) |
| **Auth** | JWT + RBAC from `workspace/auth.env.local` (bcrypt; not in compose `env_file`) |
| **Historian / FDD** | Apache Arrow/Feather + DataFusion SQL in bridge |
| **Agent HTTP surface** | JSON REST + JWT (`GET /api/agent/tools`, `/openfdd-agent/building-insight` stub) |
| **MCP service mode** | **Phase 1 scaffold** — `openfdd-mcp` crate + `ghcr.io/bbartling/openfdd-mcp` (stdio sidecar); not in edge binary |
| **Built-in Ollama** | **Not required** — UI panels and host-stats placeholders only |

## External orchestration (target policy)

| Role | Tooling | Scope |
| --- | --- | --- |
| **Deterministic runtime** | Open-FDD Rust edge | Poll, historian, FDD, reports, driver trees |
| **Orchestrator** | Cursor / Codex (this repo's agents) | Plans, PRs, docs, safe script invocation |
| **Simple triage** | Worker / mini model | Pass/fail tests, HTTP status, missing selectors, syntax |
| **Complex evaluation** | Thinking model | Auth, multi-service failures, deploy scripts, field-bus writes |
| **Optional local LLM** | Ollama (operator LAN only) | Doc Q&A / RAG helper — **not** a runtime dependency |
| **Future MCP** | `openfdd-mcp` (scaffold) | Read-first tools; writes gated by human approval |

## Legacy artifacts (do not treat as current without verification)

| Location | Legacy signal | Current interpretation |
| --- | --- | --- |
| `workspace/dashboard` — Agent tab, Faults "Validate with Ollama", Host stats Ollama panel | Built-in Ollama chat/RAG | **Deferred UI**; edge returns stub/offline for Ollama stats |
| `GET /openfdd-agent/building-insight` | Python-era building agent | **Rust stub** (`building_insight_stub`) |
| `docs/AI_AGENT_API.md` header | Mentions `edge_bootstrap.sh`, demo JWT body | Partially stale — prefer `openfdd_rust_edge_bootstrap.sh` + real login |
| `.github/workflows/ghcr-multiarch-publish.yml` | Python `openfdd-mcp-rag` image | **Legacy** — marked in workflow; Rust uses `rust-ghcr.yml` |
| `.github/actions/publish-multiarch` | `mcp-rag:openfdd-mcp-rag` | Legacy Python stack only |
| `edge/src/ops/bridge.rs` parity manifest | `"Rule Lab"`, deferred `mcp-rag` / `ollama` | Accurate deferral list for porting audit |
| README OpenClaw copy-paste blocks | External agent on Pi | **Still valid** as external orchestrator prompts (not in-container Ollama) |
| `docker-compose.yml` comment | "MCP will be added later" | Still accurate |
| Rule Lab naming in dashboard copy | Old tab name | Functionality lives under **SQL FDD rules** / FDD Wires — no Rule Lab route in CI guards |

## Model routing (for agents working this repo)

**SIMPLE** (worker/mini): single-file lint, one HTTP 4xx/5xx, one failing test name, env missing, `cargo fmt` diff.

**COMPLEX** (orchestrator/thinking): auth/RBAC, race/flaky CI, bridge + commission + haystack + frontend together, deploy/restore scripts, any BACnet/Modbus/Haystack **write**, behavior that passes tests but violates safety rules.

## Related docs

- [openfdd-agent-architecture.md](openfdd-agent-architecture.md) — target multi-agent design
- [bench-driver-setup-wsl-agent.md](bench-driver-setup-wsl-agent.md) — on-bench WSL Cursor agent prompt (Haystack + drivers)
- [openfdd-mcp-tool-contract.md](openfdd-mcp-tool-contract.md) — MCP tools + bench extensions
- [../security/agent-safety-boundaries.md](../security/agent-safety-boundaries.md) — hard limits
- [../ai-agent/README.md](../ai-agent/README.md) — session start + API index (updated to link here)

## Downloads research pack

The operator research folder `research_review_agent_skills_v1_2_openfdd_agent_retrofit` was not present on the dev WSL mount at implementation time. Content below was derived from repo inspection and issue #402 / external-agent retrofit requirements. Merge any missing research files into `docs/agent/` in a follow-up commit if the pack is copied to the repo.
