---
name: openfdd-site-identity
description: >-
  Absolute law: Open-FDD is a generic data-model framework. Product paths never
  hardcode one building, campus, vendor, or fixture equipment id. Equipment
  selection uses equipType / equipment_type / roles / registry. Never prefer
  RTU_01 or VAV_1 over type. Never substring, prefix, LIKE, contains, or
  starts_with on equipment_id (RTU_01 must not hit RTU_010). building_id is a
  caller, request, JWT, or env parameter. Ops, tests, and stress may name a
  lab site as an env default; selectors that claim type-first stay exact-id
  only after the type filter. Triggers on: ACME, BUILDING_100, LAKESIDE,
  fixture id, equipment_id match, plot filter, EXAMPLE_LOCATION.
---

# Site identity is a parameter

Open-FDD is a generic data-model-driven framework. Product code selects sites and equipment from the data model the caller supplied. It does not embed one building, campus, vendor naming scheme, or fixture equipment id.

A spec audit that only searches for the string `ACME` does not satisfy this skill. Preferring `RTU_01` over `equipment_type`, or letting that id match `RTU_010`, is the same class as the plot and equipment id-text filters in #1043.

## Product paths

These paths stay generic:

- SPA (`frontend/web`), including RCx and FDD plot selection
- central, DataFusion, historian, and analytics
- PyPI AI report, fault, and oracle tooling (`open_fdd` reporting, rules, Typst, anomaly CLI)

Forbidden as a product default or a runtime branch: `ACME`, `BUILDING_100`, `LAKESIDE`, `LAKESIDE_ES`, a Detroit ACME office, or any other single-site constant.

`building_id` always comes from the caller: package, request, JWT, or env. There is no product default building.

A help string may show a site only when it is clearly an example; prefer `AHU · Example Campus · City, ST`. Location stays empty unless the caller passes it. `BUILDING_100` in a docstring is allowed only to say it is a separate lab dataset.

Gold package folder names (`AHU_1`, `VAV_1`, `CHW_1`, `weather/`) are layout examples. They are not selection keys.

## Equipment selection

Selection uses `equipType` / `equipment_type`, mapped roles, and the rule registry.

- Do not prefer a fixture id (`RTU_01`, `VAV_1`, `AHU_1`, or any other lab id) over type.
- Do not match `equipment_id` with a substring, prefix, SQL `LIKE` / `ILIKE`, `contains`, or `starts_with`.
- An exact id match is allowed only after the type filter. `RTU_01` must not select `RTU_010`.

The same rule binds product code and any stress or ops selector that claims to be type-first. Naming a lab building or a fixture id in an env default (`OPENFDD_GAP_BUILDING`, `OPENFDD_GAP_FIXTURE_IDS`) is allowed. Using that name as a substring selector is not.

## Names that may stay

Unit tests, integration tests, stress and ops scripts, migrate helpers, and lab fixtures may **name** `ACME`, `BUILDING_100`, and `LAKESIDE`. Do not rename those fixtures to satisfy this rule. Their selection logic still follows the equipment rule above.

Docs and the external BUILDING_100 kit may name maintainer datasets. Do not copy those names into a product default.

## Dual-read

Historian dual-read (#1014) compares Parquet trees for the building id the caller passed. It does not branch on a lab name. A tie prefers hub-root. An empty legacy directory is not history.
