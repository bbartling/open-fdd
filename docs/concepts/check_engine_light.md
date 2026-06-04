---
title: Building check-engine light
parent: Concepts
nav_order: 4
---

# Building check-engine light

The building has one **GREEN / YELLOW / RED** light on the home dashboard. A tree underneath breaks faults down by equipment. **Local Ollama** explains the light using a **fixed** code list — it never invents codes. See [Local Ollama](../local_ollama).

## Fixed fault codes (letter suffix)

Codes live in `fault_catalog.py` and are served at `GET /api/faults/catalog`.
Format: **`FAMILY-SUFFIX`** where suffix is **1–3 letters** (`VAV-C`, `AHU-B`, `BLD-D`) —
**not** numeric codes like `VAV-03`, which collide with physical equipment names on retrofit sites.

Link graph (fault code → category → cookbook pattern): `GET /api/faults/graph`.

APIs that accept a `code` reject unknown values. FDD covers four categories only:

| Category | Meaning |
|----------|---------|
| `performance_degradation` | Efficiency/capacity drifting from baseline. |
| `simultaneous_heat_cool` | Heating and cooling fighting each other. |
| `sensor_fault` | Flatline / out-of-range / drift / inconsistent sensors. |
| `io_fault` | Command vs feedback mismatch, stuck actuators, stale points. |

This is **not** classic BAS alarm-and-dial-out.

## Equipment families

`AHU`, `VAV`, `HEATPUMP`, `GEO`, `CHILLER`, `DATACENTER`, `BUILDING` — each owns a
short code list (browse them on the dashboard **Fault catalog** page).

## How it lights up

Tag a Rule Lab rule with a `fault_code` (e.g. `VAV-C` for zone sensor flatline) → the scheduled FDD run executes **`workspace/data/rules_py/*.py`** →
results group by family in `GET /api/faults/status`. `ok → green`,
`warning → yellow`, `critical → red`.

## Synergy with expression rules

Each catalog entry lists **`cookbook_patterns`** (e.g. `flatline_1h`, `spread_1h`) that map to templates in
[Expression cookbook (Python)](../expression_rule_cookbook_python.md). Rule Lab shows the picker; the Agent
context includes `fault_codes` and `fault_code_graph` for Ollama commentary on home **Building insight**.

See also: [Rule Lab — Python storage](../howto/rule_lab_storage), `skills/building-check-engine/SKILL.md`.
