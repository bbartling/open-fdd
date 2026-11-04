# SI SQL contract — portable distribution handoff

Soft-OPEN dependency artifact for generic downstream consumers. **Not** full live Open-FDD application qualification.

## Identities

| Field | Value |
| --- | --- |
| Processing ABI | `metric-c-v2` |
| Scientific contract | `openfdd-sql-schema-fdd-v1` @ `4.0.8-softopen.1` |
| Scientific `pack_sha256` | `82efa9027adbe0e3e75e64365474b238e74cc0fed307caf6187b80063c7d3422` |
| Distribution | `openfdd-si-sql-distribution-v1` @ `4.0.8-softopen.1-dist-20261103` |
| Distribution `distribution_sha256` | `7db7d2cc7fa24d5d482f3294dc3c53f8134bde7bf02b22bfd7352d3c1b13f94a` |

### Superseded scientific identity (do not re-pin)

| Field | Value |
| --- | --- |
| `contract_version` | `4.0.8-softopen` |
| `pack_sha256` | `742b9bcf4e3873665ed4f64378888826b54998ee6ef845a8eed6f720f16c6260` |

That pin is retired because **documentation bytes only** changed under the same version string (brief-forbidden silent reinterpretation). No SQL, DDL, constant, or equation file bytes changed versus the superseded pack. Ledger files whose hashes differ are:

- `sql/contract/README.md` — SI consumer language (metric-c-v2 shipped SQL; distribution pointer)
- `sql/contract/metric_units.json` — `notes[]` only (same processing ABI `metric-c-v2`)

Current `4.0.8-softopen.1` additionally bumps version metadata in `sql/analytics/registry.json` and `sql/contract/successor_bundle/manifest.softopen.json` (still no equation/DDL body edits).

The scientific digest is **unchanged in definition**. The distribution digest additionally binds renderer/tuning companions (`tuning_catalog.json`, `runtime_defaults.json`, `render_rule.py`).

## Export and verify

From an Open-FDD checkout at the pinned `source_revision`:

```bash
python3 scripts/sql_contract/export_distribution.py \
  --out /tmp/openfdd-si-dist \
  --write-committed-manifest

# Integrity + catalog + unit goldens + optional Postgres smoke
export OPENFDD_VERIFY_REPO="$PWD"
export OPENFDD_SI_ARTIFACT_ROOT=/tmp/openfdd-si-dist
export OPENFDD_SI_EXPECTED_SOURCE_REV="$(git rev-parse HEAD)"
export OPENFDD_DATABASE_URL=postgresql://USER:PASS@HOST:5432/DB   # disposable Timescale

python3 scripts/sql_contract/verify_installed.py \
  --artifact-root "$OPENFDD_SI_ARTIFACT_ROOT" \
  --receipt-out /tmp/installed_consumer_receipt.json
```

CI command authority: `.github/workflows/si-parity.yml` job `si-installed-artifact-consumer`.

## Install order (Postgres product path)

1. Schema DDL in order: `00_extensions` → `01_bps_core` → `02_openfdd_dims` → `03_wide_history_helper` → `05_portal_inventory` → `11_point_map_binding_metadata` → `07_opaque_series_binding`
2. `sql/fdd/postgres/postgres_helpers.sql`
3. FDD: render with `sql/fdd/render_rule.py` + execute bodies under `sql/fdd/postgres/rules/`
4. Analytics: load bodies from `sql/analytics/registry.json` paths under `sql/analytics/postgres/queries/`

Warehouse-dialect templates under `sql/fdd/warehouse/` (if present) are **not** a silent substitute for Postgres product SQL.

## Client bindings

- **Unit admission:** `sql/contract/metric_units.json` — e.g. 68°F admits as 20°C storage; declared 20°C stays 20°C; temperature **differences** are scale-only (no ±32 on deltas).
- **FDD render:** `python3 sql/fdd/render_rule.py FC1 --dialect postgres --poll-seconds 300 --params '{"confirm_min":0}'`
- **Tuner keys:** SI names via `parameter_si_rename_map.json`; defaults in `tuning_catalog.json` / `runtime_defaults.json`.

## Asset inventory (summary)

- Scientific ledger: 110 files in `sql/contract/manifest.json` (schema, 77 Postgres FDD rules + registry, 19 analytics bodies + analytics registry, contract goldens, metric metadata).
- Distribution companions: 6 files in `sql/contract/distribution_manifest.json` → `companion_files` (renderer/tuning plus required product schema DDL not in the 110-file ledger).

### Nineteen analytics SQL bodies

`bas_vs_web_oat`, `diurnal_hourly`, `economizer_deltas`, `fuel_daily`, `mechanical_cooling_oat_bins`, `metering_kwh`, `motor_weekly_runtime`, `mv_change_point_daily`, `pid_hunting_proxy`, `plant_health_inventory`, `rcx_preset_role_coverage`, `role_timeseries`, `schedule_occupancy`, `sensor_faults_staleness`, `sensor_stats`, `setpoints_snapshot`, `sql_anomaly_series`, `sql_anomaly_zscore`, `topology_equipment`.

### Supported / unsupported rules

- **Supported surface:** 77 rule IDs in `sql/fdd/registry.yaml` (SI storage units on Postgres path).
- **Explicit unsupported:** `SV-RATE` (`metric_units.json` — time policy not versioned for metric-c-v2). Catalog size ≠ SI-supported count.

## Receipts and gates

| Gate | Status |
| --- | --- |
| Installed-artifact verify (export outside checkout) | Blocking in `si-parity` |
| Full si-parity P0–P2 + W4 blocking families | Unchanged; separate job steps |
| Live stack / UI / writer API readback | **Unperformed** (C5) |
| Field data imperial→metric migration | **Unperformed** — rehearse on synthetic fixtures first |
| Full application penetration / FQ | **Unperformed** |

## Upstream defects (this handoff)

**No shared SQL/helper/schema class-A defect reproduced.** Packaging/docs/export + installed-consumer verification only (class B).

## Consumer upgrade sequence

1. Pin vendor **exact** distribution (`distribution_sha256` + `scientific_pack_sha256` + `source_revision`).
2. Export or obtain byte-identical tree; run `verify_installed.py` on disposable Postgres.
3. Adapt auth/DB drivers and parameter binding only — **do not** edit equation bodies.
4. Rehearse schema + SI admission + tuner conversion on neutral synthetic data; run the same unit goldens (`sql/contract/goldens/unit_vectors.json`).
5. Qualify deployment on owner stack (separate program).

## Imperial → metric transition (live data)

Migrate admission, stored samples, unit metadata, tuners, and result interpretation **together**. Pin or flag flips alone are unsafe; unknown-provenance history needs an explicit engineering decision.

## Cleanup and resume

- **Cleanup proof:** delete artifact root (`rm -rf /tmp/openfdd-si-dist`) and drop disposable DB role/database.
- **Checkpoint / resume:** keep `distribution_manifest.json`, `SOURCE_REVISION`, and `installed_consumer_receipt.json`; re-run verify from step 2 after any companion or scientific pin change.

Machine-readable twin: [`si_sql_contract_handoff.json`](si_sql_contract_handoff.json).
