---
title: FDD ops story → Twin schedule knobs
parent: MCP Agents
nav_order: 36
---

# FDD ops story → Twin schedule knobs (pointer)

**Ownership:** EnergyPlus IDF / G14 calibration runs via **EnergyPlus-MCP** on the
**open-fdd** stack (WattLab section) — never inside `openfdd-mcp`. vibe19/vibe20
app tips are **frozen** (2026-07-30 cutover). This page only tells open-fdd agents
**where to continue** when FDD / dump / bills disagree with the model.

## When to leave openfdd-mcp (stay in open-fdd product)

| Signal in Open FDD | Continue with |
|--------------------|---------------|
| Scheduling / always-on / OA / fan runtime findings | Twin dial (ops schedules) in openfdd-web WattLab |
| Monthly bills vs Twin ±% charts wrong shape | `wattlab-twin-ops-reheat-dial` + playbook §2c |
| Envelope / glass / infil still annual-short | `wattlab-twin-calibrate-dial` Phase 1 |
| IDF patch / EnergyPlus simulate | EnergyPlus-MCP / stack `mcp-exec` |

## Recipe (generic — no campus IDs)

1. Read monthly ±% (Studio dial charts) and any dump DAT/fan/OA story.
2. Form **one** schedule/HW hypothesis (see reheat coupling below).
3. Patch + simulate via EnergyPlus-MCP — score **both** fuels every run.
4. Do **not** invent ECM savings or flip a previously-passing fuel.

### Reheat coupling

```
more mechanical cooling (cool DAT, long fans, low OA)
  → more reheat opportunity
  → gas up unless HW is scheduled/softened
```

Prefer **daytime-only HW** in gas-spike months; full HW plant-off usually
overshoots (that month gas ≈ −100% vs bills).

## Pointers

| Doc | Repo |
|-----|------|
| Method SoT | playground `vibe20_agent_spec/docs/BUG_REPORT_TWIN_DIAL_AI_CONTEXT.md` |
| Playbook §2c | `vibe20_agent_spec/docs/TWIN_DIAL_PLAYBOOK.md` |
| Skills | `wattlab-twin-calibrate-dial`, `wattlab-twin-ops-reheat-dial` |
| Dual-MCP | [`companion-wattlab-energyplus.md`](companion-wattlab-energyplus.md) |
| Agent handoff | `/data/tools/AGENT_CONTEXT.md` when workspace mounted |

G14 gate (both fuels): `|NMBE| ≤ 5%` and `CVRMSE ≤ 15%`.
