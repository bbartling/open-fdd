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

- API: [`docs/ecm/AGENTS_ECM_ENGINEERING.md`](../ecm/AGENTS_ECM_ENGINEERING.md)
- Math on GH Pages: [`ECM_ENGINEERING_MATH.md`](../operations/ECM_ENGINEERING_MATH.md)
- Release: [`PYPI_RELEASE_CHECKLIST.md`](../ecm/PYPI_RELEASE_CHECKLIST.md)

Do **not** treat the wheel as the product FDD runtime (that is GHCR DataFusion).

## MCP hosts

| Server | Role |
|--------|------|
| `openfdd-mcp` | JWT REST → central (FDD, historian, jobs) |
| [rusty-bacnet-mcp](companion-rusty-bacnet-mcp.md) | Read-only BACnet on OT LAN |
| py-bacnet-stacks-playground | External vibe/oracle apps — not shipped in open-fdd containers |

## OT fieldbus

[`BACNET_OT_POLICY.md`](../operations/BACNET_OT_POLICY.md) — fixed 300 s poll; **never** deploy fieldbus on cloud.
