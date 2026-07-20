# Multi-site CSV and SQL input (App 19)

Vibe App 19 extends the Streamlit demo from single-building CSV toward a **multi-site, multi-building** mapping lab.

## Scope

- Multiple CSV uploads (one file per equipment, wide building CSV, or long/tidy CSV)
- Nested site → building → equipment → role YAML
- Read-only SQL: SQLite, DuckDB, optional SQL Server
- All **50 pandas cookbook rules** still run with explicit skip / not-applicable results

## Data model

See `app/site_model.py`:

- `Site` → `Building` → `Equipment` → role map
- Lightweight Haystack-*like* IDs — **no RDF/Oxigraph**

## Role map formats

**Flat (legacy):**

```yaml
AHU_1:
  sat: discharge_air_temp_f
```

**Nested (preferred):**

```yaml
sites:
  acme_main:
    name: ACME Main Campus
    timezone: America/Chicago
    buildings:
      BUILDING_100:
        equipment:
          AHU_1:
            equipment_type: AHU
            roles:
              sat: discharge_air_temp_f
```

Flat maps load unchanged and can be exported to nested YAML from the **Site Mapping** tab.

## Rule result contract

Every evaluation returns:

`PASS` | `FAULT` | `SKIPPED_MISSING_ROLES` | `NOT_APPLICABLE_EQUIPMENT_TYPE` | `ERROR`

No silent omission.

## Production engine

Rust/DataFusion FDD belongs in [Open-FDD](https://github.com/bbartling/open-fdd). App 19 is pandas/Streamlit only.
