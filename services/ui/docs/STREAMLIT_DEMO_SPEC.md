# Streamlit UI contract (Open-FDD `services/ui`)

## Purpose

Product **Streamlit** engineering UI for Open-FDD: vibe19 FDD / RCx / Jobs plus vibe20 WattLab **export** in **one** app (`streamlit_app.py`).

| Layer | Engine |
|-------|--------|
| Production FDD | Central **DataFusion SQL** (`sql_rules/registry.yaml`, 63 rules) |
| Pandas cookbook | Retained under `app/rules/` (59) for analytics, docs, oracle — FDD math only if `OPENFDD_ALLOW_PANDAS_FDD=1` |

External vibe19 playground remains the preferred place to **test/maintain** pandas recipes before documenting them online. Do **not** delete the in-tree pandas catalog.

## Frozen sections (`dashboard_contract.py`)

1. Overview  
2. Data Model  
3. Run Rules  
4. Results by Category  
5. FDD Plots  
6. RCx Plots  
7. Metering  
8. Export (includes WattLab dump)

Plus sidebar: package ingest, Rule tuning, **Jobs (persistent)**.

## Do not

- Revive React LabShell / `/srv/assets`
- Add a second Streamlit process for WattLab/EnergyPlus
- Silently fall back to pandas FDD when SQL fails
- Claim full SQL↔pandas mask parity beyond [parity-matrix](../../docs/rules/cookbook/parity-matrix.md)
