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
- Product central image = Rust/debian only — no Python runtime; WattLab export is offline opt-in.
- Never delete `edge/` or `os/`.
- Do not rename `open_fdd.rules` → `open_fdd.oracle` without product decision.
- Keep [`../../AGENTS.md`](../../AGENTS.md) / [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) / this skill honest when product truth changes.
- Vendor dictionaries, campus names, and weather lat/lon stay in **preprocess zips**, never in product SQL/UI.

## Phase 0 coding (when executing)

Add CI that validates `ownership.yaml` and fails on prohibited imports /
missing cookbook paths / terminology regressions.

## Skill home

`openfdd_agent_spec/skills/` is the only authoring tree. Do not create a parallel copy under `.cursor/skills/`, `.claude/skills/`, `.agents/skills/`, or a home directory. Sync with [`scripts/openfdd_install_agent_skills.sh`](../../../scripts/openfdd_install_agent_skills.sh) (`--sync`, optional `--user`). Orientation: [`openfdd_agent_spec/AGENTS.md`](../../AGENTS.md) and the repo [`AGENTS.md`](../../../AGENTS.md).

## Related skills

- [`openfdd-sql-fdd`](../openfdd-sql-fdd/SKILL.md) — product FDD engine
- [`openfdd-react-spa`](../openfdd-react-spa/SKILL.md) — product UI
- [`openfdd-pypi-oracle`](../openfdd-pypi-oracle/SKILL.md) — library boundary
- [`openfdd-milestone-a-pr`](../openfdd-milestone-a-pr/SKILL.md) — PR loop
- [`openfdd-stack-ghcr`](../openfdd-stack-ghcr/SKILL.md) — image pull
