---
title: External agents
layout: default
nav_order: 11
has_children: true
permalink: /agent/
---

# External agents

Open-FDD is a **vendor-neutral, local-first edge platform**. It does **not** ship an embedded AI chatbot or in-dashboard LLM runtime.

**Split:** this folder holds **ops / edge / GHCR soak** prompts. Software-engineering missions (architecture, PyPI oracle, Milestone A) live in [`openfdd_agent_spec/`](../../openfdd_agent_spec/).

## Open-FDD core (GHCR edge)

| Layer | Components |
|-------|------------|
| Runtime | `central` (API/FDD), `ui` (React), `fieldbus` (BACnet→MQTTS), `mqtt` (broker) |
| Data | Arrow/Feather historian, DataFusion SQL FDD |
| Model | Haystack RDF, assignments, FDD wires |
| API | JWT REST, `/api/agent/tools` catalog |
| UI | React SPA (`frontend/web`) — health matrices, E+ dump export (legacy WattLab routes) |
| Optional MCP | `openfdd-mcp` stdio — [mcp/README.md](../../mcp/README.md) |

## External agent layer (outside Open-FDD)

Operators may use any of these **outside** the dashboard:

- Codex CLI (`.codex/` project config)
- Cursor (`.cursor/agents/`)
- Claude Desktop, OpenClaw, Rig (if MCP-capable)
- Shell + JWT REST clients

See [examples/external-agents.md](../examples/external-agents.md).

## Docs in this folder

| Doc | Purpose |
|-----|---------|
| [openfdd-agent-architecture.md](openfdd-agent-architecture.md) | Layered architecture |
| [openfdd-agent-current-standing.md](openfdd-agent-current-standing.md) | What ships in 3.2.x |
| [model-routing.md](model-routing.md) | Codex/Cursor agent routing |
| [openfdd-mcp-tool-contract.md](openfdd-mcp-tool-contract.md) | MCP tool surface |
| [PACKAGE_AUTHORING.md](PACKAGE_AUTHORING.md) | Zip / equipType / Haystack→SQL (any BAS job) |
| [CSV_FLOOD_AFDD_ROUTINE.md](CSV_FLOOD_AFDD_ROUTINE.md) | BUILDING_50 hourly append + updatable AFDD routine sim |
| [EPLUS_DUMP_CLUSTERING.md](EPLUS_DUMP_CLUSTERING.md) | E+ dump zip + pandas clustering export |
| [bench-vs-source.md](bench-vs-source.md) | Bench vs product source trees *(paste-only — not on Pages)* |
| [vibe19-parity-nightly-monster-prompt.md](vibe19-parity-nightly-monster-prompt.md) | **Product agent** — vibe19 look/feel + 59 rules + security PR train *(paste-only)* |
| [vibe16-bacnet-feather-port-agent-prompt.md](vibe16-bacnet-feather-port-agent-prompt.md) | **Product agent** — vibe16 BACnet/Feather port cycle *(paste-only)* |
| [linux-edge-tester-stack-recipes-prompt.md](linux-edge-tester-stack-recipes-prompt.md) | **Second bench** — living daily prompt (overwrite in place, never date) — 4 recipes, 5007, leave-running + human Workbench *(paste-only)* |
| [linux-edge-tester-stack-nightly-prompt.md](linux-edge-tester-stack-nightly-prompt.md) | **Linux edge tester** — standalone stack nightly (central/ui/fieldbus/mqtt) *(paste-only)* |
| [linux-edge-tester-second-bench-ghcr-soak-prompt.md](linux-edge-tester-second-bench-ghcr-soak-prompt.md) | **Second bench** — rigorous GHCR soak (superseded by stack-recipes prompt) *(paste-only)* |
| [linux-edge-tester-prompt.md](linux-edge-tester-prompt.md) | **Linux edge tester** — turnkey copy-paste validation *(paste-only)* |
| [bench-driver-setup-wsl-agent.md](bench-driver-setup-wsl-agent.md) | WSL setup reference |

## Repo-side config (allowed)

| Path | Role |
|------|------|
| [`openfdd_agent_spec/`](../../openfdd_agent_spec/) | Software-engineering agent OS (Milestone A, skills) |
| `.codex/` | Codex CLI project agents + MCP |
| `.cursor/agents/` | Cursor external development agents |
| `.agents/skills/` | Portable review skills (not edge runtime) |

These configure **external** tools. They are not bundled into the GHCR edge image.
