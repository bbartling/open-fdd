---
title: System overview
parent: Architecture
nav_order: 1
---

# System overview

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  BACnet OT  │────▶│ commission / poll │────▶│ feather historian│
│   devices   │     │   (containers)    │     │  workspace/data  │
└─────────────┘     └──────────────────┘     └────────┬────────┘
                                                       │
┌─────────────┐     ┌──────────────────┐              ▼
│  Operator   │◀───▶│  openfdd-bridge  │◀──── Rule Lab / FDD batch
│  browser    │     │  FastAPI + React │
└─────────────┘     └──────────────────┘
        ▲                    │
        │            ┌───────┴────────┐
   Caddy :80         │ model.json TTL │
   (host)           │ Brick / RDF    │
                     └────────────────┘
```

## Components

| Layer | Responsibility |
|-------|----------------|
| **Operator Bridge** | Auth, REST/WebSocket API, compiled dashboard, Rule Lab |
| **BACnet commission** | Who-Is, read property, supervised writes (gated) |
| **BACnet poll** | Scheduled RPM reads → historian |
| **Historian** | Feather files per point; local-first retention |
| **FDD runner** | Executes `workspace/data/rules_py/*.py` on schedules or API batch |
| **Model** | Brick TTL + `model.json` bindings (`fdd_input`, equipment tree) |
| **MCP RAG** | Optional local doc retrieval for agent tools |
| **Caddy** | Host reverse proxy `:80` → bridge (typical edge) |
| **Ollama** | Optional host or container LLM for building insight (not required for FDD) |

## Optional PyPI-only path

`pip install open-fdd` ships `arrow_runtime` + playground lint helpers **without** the Operator Bridge UI. Use for offline Arrow rule tests or CI smoke. Graph ML experiments use optional `[ml]` (numpy/sklearn) per [issue #211](https://github.com/bbartling/open-fdd/issues/211). See [Appendix — Python package](../appendix/python-package).
