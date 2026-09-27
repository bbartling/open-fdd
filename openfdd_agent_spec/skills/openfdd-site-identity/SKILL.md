---
name: openfdd-site-identity
description: >-
  No hardcoded building or site id in PyPI report/fault tooling or in the Rust
  DataFusion historian runtime. Tests, ops, and lab fixtures may name ACME,
  BUILDING_100, or LAKESIDE. Triggers on: EXAMPLE_LOCATION, product default
  campus, site-specific historian branch.
---

# Site identity is a parameter

Two product surfaces must not assume one building. Everything else in this repo may name a lab dataset.

## Must be zero

Forbidden as a product default or a runtime branch: `ACME`, `BUILDING_100`, `LAKESIDE`, `LAKESIDE_ES`, a Detroit ACME office, or any other single-site constant.

1. **Python PyPI AI agent tooling.** `open_fdd` reporting, fault, oracle, and rules paths that make reports and faults. Includes Typst builders such as `EXAMPLE_LOCATION` and the anomaly CLI. Do not default a report to one building. A help string may show a site only when it is clearly an example; prefer `AHU · Example Campus · City, ST`. `BUILDING_100` in a docstring is allowed only to say it is a separate lab dataset, not a product default.
2. **Rust DataFusion / historian / analytics runtime** used by central and the crates that runtime calls. `building_id` comes from the package, JWT, request, or env. Do not branch on a lab name.

## Out of scope

Unit tests, integration tests, stress and ops scripts, migrate helpers, and lab fixtures. `ACME`, `BUILDING_100`, and `LAKESIDE` are fine there. Do not spend a change renaming those fixtures.

Docs and the external BUILDING_100 kit may name maintainer datasets. Do not copy those names into a PyPI default or a DataFusion branch.

## Dual-read

Historian dual-read (#1014) compares Parquet trees for the building id the caller passed. It does not branch on a lab name. A tie prefers hub-root. An empty legacy directory is not history.
