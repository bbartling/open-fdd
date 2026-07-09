# SQL rule tuning contract

Typed, registry-driven parameters for DataFusion rules. **No raw SQL from the browser.**

## Source of truth

| layer | path |
| --- | --- |
| Rule metadata + param defs | `sql_rules/registry.yaml` |
| Global defaults | `rule_tuning/defaults.yaml` (optional) |
| Building overrides | `rule_tuning/building_overrides.yaml` (optional) |
| Equipment overrides | `rule_tuning/equipment_overrides.yaml` (optional) |

## Merge order (Rust runner + Python API)

1. Registry `parameters.*.default`
2. `rule_tuning/defaults.yaml` → `rules.{rule_id}`
3. `building_overrides.yaml` → `{building_id}.{rule_id}`
4. `equipment_overrides.yaml` → `{equipment_id}.{rule_id}`
5. Session/request override (preview only)

Values are clamped to `min`/`max`. Unknown keys are rejected.

## SQL placeholders

- Allowed built-ins: `{{POLL_SECONDS}}`, `{{CONFIRM_ROWS}}`, `{{CONFIRM_SECONDS}}`
- Rule-specific: declared in `parameters.*.sql_placeholder` (e.g. `{{ZONE_T_LO}}`)
- Rust `assert_sql_placeholders()` fails on undeclared `{{...}}` in SQL text

## Frontend controls

Each parameter may specify:

- `label`, `default`, `min`, `max`, `step`, `unit`
- `frontend_control`: `slider` | `number` (future)

Static UI: `fdd_app/frontend/static/dashboard_sql_tuning.js`

## Security

- Save profile requires engineer login (`can_edit`)
- Writes only under `rule_tuning/` — never SQL files or client data paths
- Preview reads batch cache `.cache/rule_results/{rule_id}.json` when `VIBE19_RUST_CACHE=1`
