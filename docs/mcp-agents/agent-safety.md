---
title: Agent safety
parent: MCP & Agents
nav_order: 2
---

# Agent safety boundaries

Automation and MCP agents must follow the same rules as human operators.

## Never

| Action | Reason |
|--------|--------|
| Delete `workspace/` | Destroys site state, historian, model |
| `docker compose down -v` | Wipes volumes |
| `docker volume prune` | Irreversible data loss |
| Print tokens or passwords | Credential leak |
| BACnet write without explicit human approval | Live equipment risk |
| Expose API on public internet | OT security |

## Always

| Action | When |
|--------|------|
| Back up `workspace/` | Before updates or destructive changes |
| Preflight CSV import | Before `/api/csv/import/execute` |
| Dry-run BACnet writes | Before `/api/bacnet/write` |
| Validate after changes | `openfdd_health_check.sh` |

## Assignment rule

Bind drivers → Haystack IDs → FDD/CDL via `/api/model/assignments` before activating rules.

## LAN / OT deployment

Run on loopback or behind VPN/TLS. JWT auth is required in production configurations.

See root [AGENTS.md](https://github.com/bbartling/open-fdd/blob/master/AGENTS.md) for session scripts.
