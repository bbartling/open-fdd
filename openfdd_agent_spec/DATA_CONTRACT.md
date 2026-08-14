# Data contracts (agent-facing)

Portable artifact shapes agents must respect. Prefer versioned schemas; do not
silently reinterpret old fields when meaning changes.

When `open_fdd.contracts` ships (Milestone A Phase 2), this doc points at those
models. Until then, code truth lives in the paths below.

**Capability ledger:** product capability status for the Vibe 21 recovery
program is machine-readable at
[`docs/migration/react-rust/capabilities.yaml`](../docs/migration/react-rust/capabilities.yaml)
(validated by `scripts/validate_capabilities_ledger.py`). Do not invent
QUALIFIED status without evidence paths.

---

## WattLab dump

| Item | Truth |
| --- | --- |
| Producer | vibe19 / `frontend/web` Export (v3 preferred) |
| Consumer | vibe20 Studio / WattLab loaders |
| Spec pointers | playground vibe19 `docs/PACKAGE_SPEC.md`; vibe20 `DATA_CONTRACT.md` |

Agents must stamp `data_window` / telemetry years on export README so twin
agents see weather year vs bill year mismatches.

---

## Rule result (pandas oracle)

Canonical statuses and shapes come from `open_fdd.rules.base.RuleResult` and
cookbook catalog metadata. Custom rules:

- Use reserved `CUSTOM-*` IDs
- Never override canonical IDs
- Declare required roles, parameters, equipment applicability
- Fail safely
- Excluded from production SQL parity claims unless explicitly migrated

---

## Findings / reporting

`open_fdd.reporting` owns portable builders. Detection ≠ finding — see vibe19
`vibe19-engineering-report` skill. UI owns download buttons and session state.

---

## ECM calculator results

`open_fdd.ecm_engineering` calculators should return enough detail for vibe20
rendering without recomputing formulas (summary + bins/detail + assumptions +
warnings + provenance). Adapters may translate field names only.

Target shape (Phase 4 hardening):

```json
{
  "schema_version": "1",
  "calculator_id": "scheduling_cooling_bins",
  "summary": {
    "baseline_kwh": 0.0,
    "proposed_kwh": 0.0,
    "saved_kwh": 0.0
  },
  "bins": [],
  "assumptions": {},
  "warnings": [],
  "provenance": {}
}
```

---

## Production FDD run

| Item | Truth |
| --- | --- |
| API | `POST /api/fdd/run` (registry / DataFusion) |
| Registry | `sql_rules/registry.yaml` |
| Storage | Arrow / Feather via central |

Agents must not treat pandas oracle output as production FDD execution.

---

## Package append (hourly IoT)

| Item | Truth |
| --- | --- |
| Seed | `POST /api/csv/import/package` |
| Append | `POST /api/csv/import/package/append` with JWT + `confirm: true` |
| Body | `{ building_id, equipment_id, csv }` history_wide chunk |
| Dedup | exact `timestamp` last-write-wins |
| Units | session `unit_system`; FDD converts metric→°F at query |

Do not commit vendor appenders or full Building 50 zips. CI uses `tests/fixtures/hourly_append/`.

---

## Units and roles

Role aliases and equipment types: `open_fdd.analytics` / site model helpers and
docs under `docs/rules/cookbook/` + migration `ROLE_MAPPING_PARITY.md`.
Phase 2 consolidates into shared contracts.
