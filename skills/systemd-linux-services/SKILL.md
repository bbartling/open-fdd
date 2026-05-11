---
name: systemd-linux-services
description: "Authors systemd units for bridge, MCP RAG, Vite UI, and bench sidecars on Linux. Use when deploy=systemd or as part of ansible bench roles."
---

# systemd Linux services

## Units (legacy names)

- `openfdd-gateway.service` — uvicorn bridge on 8765
- `openfdd-mcp-rag.service` — MCP on 8090
- `openfdd-ui-vite.service` — `npm run dev` in dashboard dir on 5173
- `easyaso-supervisor.service`, `diy-bacnet-server.service` when sidecars enabled

Shared env file: `/etc/openfdd/bench.env` (or operator path).

See [references/REFERENCE.md](references/REFERENCE.md).
