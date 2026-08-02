---
title: MCP & Agents
layout: default
nav_order: 9
has_children: true
permalink: /mcp-agents/
---

# MCP & agents

Open-FDD supports **MCP (Model Context Protocol)** for AI-assisted commissioning, validation, and documentation — grounded in the real REST API, not simulated data.

| Guide | Content |
|-------|---------|
| [MCP setup](mcp.html) | Images, entrypoints, tools |
| [MCP role packs](roles/) | Four agent contexts: package/mapping, surrogate-train, Unity WebGL, operator (portable ZIP lanes; no Jupyter-in-SPA) |
| [Companion — WattLab + EnergyPlus](companion-wattlab-energyplus.html) | Twin/ECM: three surfaces, golden loop, dual-MCP |
| [Dual-site MCP IT](dual-site-mcp-it.html) | Liberty B50≠B100 accuracy / historian / findings |
| [FDD ops → Twin knobs](fdd-ops-to-twin-knobs.html) | Pointer: open-fdd findings → vibe20 G14 dial (no IDF in mcp) |
| [Agent safety](agent-safety.html) | Hard boundaries for automation |
| [Cursor & OpenClaw](cursor-openclaw.html) | IDE and edge agent wiring |
| [External agent workflow](../examples/external-agents.html) | Codex, Cursor, MCP patterns |

Repository reference: [mcp/README.md](https://github.com/bbartling/open-fdd/blob/master/mcp/README.md)
