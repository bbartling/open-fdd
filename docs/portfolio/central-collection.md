---
title: Central collection
parent: Portfolio
nav_order: 1
---

# OpenFDD RCx Central — collection

**OpenFDD Edge** sites emit **interval summaries** (not raw historian by default). **OpenFDD RCx Central** ingests rollups over Tailscale/VPN, stores them locally, and feeds the Dash overview and validation jobs.

RCx Central is read-only toward Edge/BACnet. It runs on an analyst workstation or Docker Desktop — not on the OT edge by default.

## Interval summary schema

Defined in `portfolio/store/interval_schema.py` as `FaultIntervalSummary`:

- Identity: `site_id`, `building_id`, `equipment_id`, `equipment_family`
- Window: `timestamp_start`, `timestamp_end`
- Fault: `fault_code`, `canonical_id`, `severity`, `confidence`
- Activity: `active_minutes`, `percent_active`, `occurrence_count`
- Evidence: `evidence_json` (summarized, not full trend)
- Tuning: `tuning_version`, `tuning_params_hash`
- Operator: `operator_status` (`new` | `acknowledged` | `resolved` | `false_positive` | …)

## Edge export formats

- JSONL (append-only events)
- Parquet / Feather (batch intervals)

## Collect today (rollup API)

```bash
source infra/ansible/secrets/acme.env.local
python3 scripts/portfolio_collect.py
```

## Tuning proposals

Human-reviewable proposals use `TuningProposal` in the same module. The AI agent **never** auto-writes BACnet points on edge — use `GET /api/building-agent/tuning-brief` and `POST /api/building-agent/apply-tuning` with `apply: false` first. Maintainer workflow: `skills/openfdd-edge-deploy-tune/SKILL.md`.
