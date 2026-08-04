---
name: openfdd-architecture
description: >-
  Use when enforcing Open-FDD product boundaries: production DataFusion SQL vs
  pandas oracle, vibe19/vibe20 ownership, dual cookbooks, edge/os never-delete,
  ownership.yaml, forbidden imports. Triggers on: architecture, ownership,
  pandas fallback, cookbook delete, Milestone A Phase 0.
---

# Open-FDD architecture

Read [`ARCHITECTURE.md`](../../ARCHITECTURE.md) and [`ownership.yaml`](../../ownership.yaml).

## Non-negotiables

- Production FDD = DataFusion SQL (`sql_rules/`) — no silent pandas fallback in central.
- Pandas oracle = `open_fdd.rules` + `analytics` — permanent.
- Both cookbooks permanent — see [`docs/COOKBOOK_OWNERSHIP.md`](../../docs/COOKBOOK_OWNERSHIP.md).
- Sole product UI = React SPA (`frontend/web` → `openfdd-web`) → central `/api` only.
- Never reintroduce Streamlit / `openfdd-ui` / overview-oracle as product surfaces.
- Never delete `edge/` or `os/`.
- Do not rename `open_fdd.rules` → `open_fdd.oracle` without product decision.
- Keep [`../../AGENTS.md`](../../AGENTS.md) / [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) / this skill honest when product truth changes.

## Phase 0 coding (when executing)

Add CI that validates `ownership.yaml` and fails on prohibited imports /
missing cookbook paths / terminology regressions.
