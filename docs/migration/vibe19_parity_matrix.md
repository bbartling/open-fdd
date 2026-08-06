---
title: Vibe19 capability parity matrix
parent: Migration
nav_order: 2
---

# Vibe19 presentation parity → Open-FDD (DataFusion)

Open-FDD product Overview / FDD Plots / RCx use **central DataFusion**
(`/api/analytics/*`, `/api/fdd/*`) + **React client Plotly**. vibe19 remains an
external pandas demo for cookbook/oracle work — not the product runtime.

Status legend: **DONE** · **PARTIAL** · **MISSING** · **N/A** (intentional).

| Capability | Open-FDD path | Engine | Status | Notes |
|------------|---------------|--------|--------|-------|
| ZIP / package import | central + edge package ingest → parquet | DF ingest | DONE | |
| Session configuration | `/api/fdd/session-config` | Rust | PARTIAL | |
| Overview motor weekly (air/boiler/chiller) | `POST /api/analytics/runtime` | DataFusion | DONE | Client Plotly + rainbow palette |
| Mech cooling OAT bins | `POST /api/analytics/mechanical-cooling` | DataFusion | DONE | Site-broadcast web OAT when needed |
| Economizer delta / MAT residual / temps | `POST /api/analytics/economizer` | DataFusion | DONE | Fan-on + identifiable \|OAT−RAT\| |
| Economizer weather dewpoint table | — | — | MISSING | Dewpoint hours not wired on historian yet |
| BAS vs web OAT + hist | `POST /api/analytics/bas-vs-web-oat` | DataFusion | DONE | Palette-aligned overlay |
| Data inspection | `POST /api/analytics/inspect` | DataFusion | DONE | Preferred AHU role columns |
| FDD run | `POST /api/fdd/run` | DataFusion SQL | DONE | `sql_rules/` |
| FDD Plots + sensor health | `/api/fdd/series` + `/api/analytics/sensor-health` | DataFusion | DONE | Sensor-fault lanes partial (client masks) |
| RCx presets (timeseries/box/ranking/metering) | `POST /api/analytics/rcx/preset` | DataFusion | DONE | Honest empties when columns missing |
| RCx OAT reset scatters | `rcx_oat_scatter_from_history` | DataFusion | DONE | ts alias `ts_utc` |
| Metering tab | `/api/analytics/metering` + RCx meter presets | DataFusion / inline rows | PARTIAL | Liberty may lack gas roles |
| WattLab dump zip | `tools/wattlab_export` offline | Optional Python | N/A | Not in product central image |

## Registry honesty

Use `parity_status` on each rule in `sql_rules/registry.yaml`. Do not claim full
rule-level parity without evidence. See [parity-matrix.md](../rules/cookbook/parity-matrix.md).
