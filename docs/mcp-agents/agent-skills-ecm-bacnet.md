---
title: Agent skills — ECM + BACnet companions
parent: MCP Agents
nav_order: 8
---

# Agent skills — ECM (PyPI) + BACnet companions

## Python engineering calcs (PyPI)

```bash
pip install "open-fdd[oracle]"
```

- Section hub: [PyPI agent tools](../ecm/)
- API / agent rules: [AGENTS_ECM_ENGINEERING](../ecm/AGENTS_ECM_ENGINEERING.html)
- Math on GH Pages: [ECM_ENGINEERING_MATH](../operations/ECM_ENGINEERING_MATH.html)
- Release: [PYPI_RELEASE_CHECKLIST](../ecm/PYPI_RELEASE_CHECKLIST.html)

Do **not** treat the wheel as the product FDD runtime (that is GHCR DataFusion).

## MCP hosts

| Server | Role |
|--------|------|
| `openfdd-mcp` | JWT REST → central (FDD, historian, jobs) |
| [rusty-bacnet-mcp](companion-rusty-bacnet-mcp.md) | Read-only BACnet on OT LAN |
| py-bacnet-stacks-playground | External vibe/oracle apps — not shipped in open-fdd containers |

## OT fieldbus

[`BACNET_OT_POLICY.md`](../operations/BACNET_OT_POLICY.md) — fixed 300 s poll; **never** deploy fieldbus on cloud.
