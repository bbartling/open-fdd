---
title: External agents
layout: default
nav_order: 11
has_children: true
permalink: /agent/
---

# External agents

Open-FDD is a **vendor-neutral, local-first edge platform**. It does **not** ship an embedded AI chatbot or in-dashboard LLM runtime.

## Open-FDD core (GHCR edge)

| Layer | Components |
|-------|------------|
| Runtime | `openfdd-bridge`, `openfdd-commission`, `openfdd-haystack-gateway` |
| Data | Arrow/Feather historian, DataFusion SQL FDD |
| Model | Haystack RDF, assignments, FDD wires |
| API | JWT REST, `/api/agent/tools` catalog |
| UI | React dashboard (no chat panel) |
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
| [bench-vs-source.md](bench-vs-source.md) | Bench vs WSL source trees *(paste-only — not on Pages)* |
| [bench-330-beta-cycle-agent-prompt.md](bench-330-beta-cycle-agent-prompt.md) | Linux edge tester — 3.3.0-beta cycle *(paste-only — not on Pages)* |
| [bench-driver-setup-wsl-agent.md](bench-driver-setup-wsl-agent.md) | WSL builder agent setup |

## Repo-side config (allowed)

| Path | Role |
|------|------|
| `.codex/` | Codex CLI project agents + MCP |
| `.cursor/agents/` | Cursor external development agents |
| `.agents/skills/` | Portable review skills (not edge runtime) |

These configure **external** tools. They are not bundled into the GHCR edge image.
