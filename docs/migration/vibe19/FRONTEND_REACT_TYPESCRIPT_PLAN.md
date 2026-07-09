# Frontend React + TypeScript cutover plan (preparation only)

**Do not start the Vite app until BUILDING_100 parity residuals are clean.**

## Current static frontend

| file | role |
| --- | --- |
| `dashboard_tune.js` | Global dashboard params → `/api/config`, `/api/refresh/{pageId}` |
| `dashboard_rules.js` | Custom rule plugins → `/api/rules/run` |
| `dashboard_cookbook.js` | Pandas cookbook sliders → `/api/cookbook/equipment/{id}` |
| `dashboard_sql_tuning.js` | **New** SQL registry sliders → `/api/sql-rules*` |
| `dashboard_auth.js` | Engineer PIN |
| `dashboard_settings.js`, `dashboard_units.js`, `dashboard_notes.js` | Site settings, units, notes |

HTML shells: `generate_dashboard.py` embeds scripts + `#cookbook-mount` + `#sql-tuning-section`.

## Future React app

- Vite + TypeScript + shared component library for sliders tied to registry metadata
- Same API contracts — no raw SQL editing
- Parity badges from `parity_status` field
- Feature flag: hide SQL panel when `rust_cache_enabled === false`

## TypeScript interfaces (draft)

```typescript
type ParityStatus = "proven_building_100" | "near_parity" | "material_mismatch" | "skipped_missing_roles" | string;

interface RuleParameter {
  key: string;
  label: string;
  default: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  control: "slider" | "number";
  sql_placeholder: string;
}

interface RuleRegistry {
  rule_id: string;
  description: string;
  required_roles: string[];
  parity_status: ParityStatus;
  dashboard_wired: boolean;
  parameters: RuleParameter[];
  effective_values: Record<string, number>;
  engine: "sql_datafusion" | "pandas_oracle";
}

interface RuleTuningProfile {
  rule_id: string;
  scope: "global" | "building" | "equipment";
  building_id?: string;
  equipment_id?: string;
  params: Record<string, number>;
}

interface RulePreviewRequest {
  rule_id: string;
  equipment_id: string;
  params?: Record<string, number>;
  use_rust_cache?: boolean;
}

interface RulePreviewResponse {
  ok: boolean;
  available?: boolean;
  row?: Record<string, number | string>;
  reason?: string;
}

interface EquipmentSummary {
  equipment_id: string;
  kind: string;
}
```

## Migration steps

1. Keep static JS until React feature parity for cookbook + SQL tuning panels
2. Extract shared slider component from registry metadata
3. Wire React routes beside existing HTML pages (or replace shells one page at a time)
4. Preserve `params_by_rule` cookbook behavior during transition
5. Tunable SQL params must survive cutover via same `rule_tuning/*.yaml` files
