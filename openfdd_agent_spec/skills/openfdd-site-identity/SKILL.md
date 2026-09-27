---
name: openfdd-site-identity
description: >-
  Never hardcode a building id, site id, campus id, or lab dataset name in
  Open-FDD product code. Python/PyPI open_fdd and Rust product crates are both
  first-class. Identity is a package, JWT, request, or env parameter.
  Triggers on: ACME, BUILDING_100, LAKESIDE, Detroit address, campus_id constant.
---

# Site identity is a parameter

Open-FDD is a multi-building framework. Two product trees follow this rule with no exceptions.

## Python / PyPI (`open_fdd`)

Library and CLI code, including:

- reporting and Typst report builders
- analytics
- ECM / oracle (`ecm_engineering`)
- rules
- agent skills under `openfdd_agent_spec/skills/` that ship behavior — a command, default, or snippet an agent would copy into library or CLI code

## Rust

- `crates/*`
- `services/central`, `services/mqtt`, `services/fieldbus`
- `edge/`
- web backends: `mcp/` responses and any Rust HTTP on the product path
- `frontend/web` product UI (storybook-only samples are not the product UI)

## Forbidden as compile-time identity

`ACME`, `BUILDING_100`, `BUILDING_50`, `LAKESIDE_ES`, `LAKESIDE`, a Detroit ACME street or office address, `liberty_practice_bensbench`, `bensbench` as a building or campus id, and paths such as `tenants/acme/…` that only work for one lab.

Do not replace one real site with another real site. Role names and equipment types are vocabulary, not building identity.

`default_site` and `HVAC_BUILDING` in the mapping wizard are generic placeholders for a flat role map that has no site object. They are not a lab campus. Callers pass `site_id` and `building_id` when the package has them.

## Allowed

- Tests and fixtures. Newly written tests, and any test you touch, use `BldgA`, `tenant_a`, or `demo_site`. Do not copy ACME, BUILDING_100, LAKESIDE, or a Detroit ACME address into a new or touched test.
- Docs, ops scripts, stress harnesses, migrate helpers, and Railway lab recipes that intentionally operate on a maintainer dataset.
- The external BUILDING_100 / LAKESIDE_ES legacy kit documented in `openfdd-typst-rcx-report`. Those names stay in that kit's commands. They do not become defaults inside `open_fdd` or Rust.

## Dual-read

Historian dual-read (#1014) compares the newer Parquet tree for the building id the caller passed. It does not branch on a lab name. Do not regress newer-wins: a tie prefers hub-root, and an empty legacy directory is not history.

## Checks

Search both trees before merging. A comment that only explains scale is not an identity constant. Do not leave a site name in user-visible copy, CLI defaults, MCP payloads, report chrome, or `include_str!` datasets.
