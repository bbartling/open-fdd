# Changelog

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

## Unreleased

## 4.0.8 — 2026-10-31

Workspace patch after the C2 product-fix and C3 SQL-QUAL qualification rows on master. `/api/health` and `/api/version` report `4.0.8+<sha>`. Contract pack versions move to `4.0.8-softopen`; `metric_storage_status` remains `released` (set at 4.0.7 W7). PyPI `open-fdd` stays **5.0.0**. No new SQL rule or analytics body changes in this bump PR.

- **#1469** — FC1 mode-delay defaults aligned with the product SQL contract.
- **#1470** — FC6 `min_cfm_design` L/s defaults match the LPS_PER_CFM contract.
- **#1471** — RCx economizer overlay SI keys and unified `dt_min` gate.
- **#1472** — Per-point ingest stored-hour coverage for gap planning (#1423).
- **#1473** — OAT-METEO web as-of interval join (#1439 scaling).
- **#1474** — Analytics cache integration fixture creates `role_map` and `point_map` for purge.
- **#1475** — Cookbook FC6 `min_cfm_design` SI sync to LPS_PER_CFM contract.
- **#1476** — SQL-QUAL-11 OAT-METEO bench and SQL-QUAL-12A disposable cutover harness.
- **#1477** — SQL-QUAL-01..06 harness (runners A–D, Postgres matrix).
- **#1478** — SQL-QUAL-07..10 and 19 analytics fresh Postgres harness.

### open-fdd 5.0.0 (PyPI)

Breaking: the pandas oracle and offline report path treat historian/package
frames as **metric-c-v2** storage when ``storage_abi`` is declared on the column
map. ``open-fdd-anomaly report`` adds ``--units imperial|si`` (default imperial)
for presentation-only conversion on Plotly figures and Typst copy. Economizer
scatter keeps x = OAT − RAT and y = MAT − RAT in the active display units.
Legacy device folders without ``storage_abi`` remain imperial-f-v1 until
re-exported in SI.

## 4.0.6 — 2026-10-28

Workspace patch after the 4.0.6 issue cycle on master. `/api/health` and `/api/version` report `4.0.6+<sha>`. PyPI `open-fdd` stays **4.4.9**. No SQL or product behavior changes in this bump PR.

- **#1401** — Local stack repin assert, compose env passthrough, multi-site provider config, site backfill, coverage visibility, provider point counts.
- **#1402** — FDD results in Timescale and a single analytics result cache path.
- **#1403** — AFDD continuous scheduler scope and window contract.
- **#1404** — OAT–METEO as-of join and primary local outdoor-air reference.
- **#1405** — General Haystack tag normalization and added zone airflow / return-air humidity roles.
- **#1406** — Engineer unit, quantity, and primary-reference overlay on provider points.
- **#1407** — VAV-1 occupancy gate and comfort band in declared units.
- **#1408** — Sensor validation sweeps by quantity and sensor-health flatline scope.
- **#1130** — CSP `style-src` split; Plotly inline attributes via `style-src-attr` only.
- Follow-on merge and qualification work tracked under **#1409–#1421** (neutral; see linked PRs on the cycle board).

## 4.0.2 — 2026-10-20

Workspace patch on master `5d56bf32` (4.0.1). `/api/health` reports `4.0.2+<sha>`. PyPI `open-fdd` stays **4.4.9**. `archive/` is unchanged. Default startup still does not purge Timescale or reseed.

- NF ingest-queue jobs fetch their own `[window start, window end)` with `GET /api/v1/point/data` and record provider health (`last_success_at`, `last_ingested_points`). `OPENFDD_HOURLY_WINDOW_SECS` (60..=3600) and `OPENFDD_PROVIDER_TICK_SECS` apply on that path.
- Provider hourly job and gap inserts use `ON CONFLICT DO NOTHING` so a logical-key duplicate does not warn or retry.
- An explicit one-shot destructive reset also clears `jobs/` and `data/datasets`. `openfdd/control_plane/tenants.json` and `users.json` stay.
- The Active site list omits historian ids with no equipment and no samples, package dirs without a manifest, and provider sites with zero mapped points.
- Overview equipment count still excludes weather and says so. Timescale package mapping carries per-equipment first/last timestamps so dataset start, end, and span fill in. AHU health matrices join stored PASS/FAULT rows. Results `fault_pct` is derived from fault hours when the stored row omitted it.
- `Cargo.lock` bumps `rustls-webpki` to 0.103.16, `webpki-roots` to 1.0.10, and `webpki-root-certs` to 1.0.10 (RUSTSEC-2026-0382, RUSTSEC-2026-0381, RUSTSEC-2026-0383).
- Destructive reset clears `jobs/` and `data/datasets` before the one-shot token is stored. Short ingest windows still enqueue the whole catch-up span. NF portal logins are reused for the same credentials and replaced after HTTP 401. Queue scheduling uses the same device map as execution, and an unmapped device is a permanent job failure. Health matrices honor requested equipment ids. Diagnostic SQL that declares `fault_pct` keeps that column.

## 4.0.1 — 2026-10-20

Workspace patch on master `04673e4f` (4.0.0). `/api/health` reports `4.0.1+<sha>` from the central crate version. PyPI `open-fdd` stays **4.4.9** (no publish). `archive/` is unchanged. No Timescale backup and no Parquet or DataFusion product path.

- **#1305** — Updates and central startup apply forward-only schema and leave existing historian rows in place. A full wipe needs a new `OPENFDD_RESET_DB` token plus `OPENFDD_ALLOW_DESTRUCTIVE_DB=1`. That token is recorded and will not purge again.
- **#1306** — Product ingest is the Normal Framework portal and CSV only. BACnet, Modbus, Haystack wire, fieldbus, the MQTT broker and client, and the compiled Parquet micro-batch writer stay under `archive/ot-edge/unmaintained`. They are not workspace members, CI jobs, or GHCR images. `/api/health` reports portal provider count plus CSV ingest. Retired with that cut: the BACnet/MQTT CI workflow, Wave C isolated workflow, standalone MQTTS smoke, MQTT/BACnet guard gates, the broker ACL / field-exposure security checks, and the OT compose-selection checker. `openfdd_health_check.sh` stays for the portal.
- **#1307** — NF portal and CSV crates deny `unwrap`, `expect`, lock-across-await, and the related Clippy restriction lints. The SPA treats hooks, keys, `any`, and direct DOM access as ESLint errors.
- **#1308** — Remove 3.x OT-edge, ACME, and Railway stress tooling that is not on the 4.0 portal path. Field-container source and `archive/` were left in place for #1306.
- **#1309** — An empty Timescale database copies the Building 50 starter pack once and does not delete rows. NF hourly ingest accepts a short validation window. The provider panel shows the last pull. Starter rules apply to stamped equipment, trend overlays carry `confirmed_fault`, and motor weekly hours count status. The central image does not build the archived MQTT provisioner.
