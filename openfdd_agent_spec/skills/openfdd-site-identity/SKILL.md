---
name: openfdd-site-identity
description: >-
  Never hardcode a building id, site id, campus id, or lab dataset name in
  Open-FDD product code. Identity is a package, JWT, request, or env parameter.
  Triggers on: ACME, BUILDING_100, LAKESIDE, campus_id constant, site hardcode.
---

# Site identity is a parameter

Open-FDD is a multi-building framework. Product paths must not compile one site.

## Product paths

- `services/` (central, mqtt, fieldbus)
- Runtime crates under `crates/` used by those services
- `edge/`
- `frontend/web` product UI (storybook-only samples are not the product UI)
- `open_fdd/` analytics, reporting, and rules
- `mcp/` responses

## Forbidden as compile-time identity

`ACME`, `BUILDING_100`, `BUILDING_50`, `LAKESIDE_ES`, `LAKESIDE`, `liberty_practice_bensbench`, `bensbench` as a building or campus id, and paths such as `tenants/acme/…` that only work for one lab.

Do not replace one real site with another real site. Role names and equipment types are vocabulary, not building identity.

## Allowed

- Tests and fixtures. New tests use generic ids: `BldgA`, `tenant_a`, `demo_site`. When you touch a legacy test that still says ACME or BUILDING_100, migrate that test. Do not copy the lab name into new tests.
- Docs, ops scripts, stress harnesses, migrate helpers, and Railway lab recipes that intentionally operate on the maintainer lab.

## Dual-read

Historian dual-read (#1014) compares the newer Parquet tree for the building id the caller passed. It does not branch on a lab name. Do not regress newer-wins: a tie prefers hub-root, and an empty legacy directory is not history.

## Checks

Search product paths before merging. A comment that only explains scale is not an identity constant. Do not leave a site name in user-visible copy, CLI defaults, MCP payloads, or `include_str!` datasets.
