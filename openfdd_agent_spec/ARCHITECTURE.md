# Open-FDD architecture locks

Human-readable ownership. Machine-readable twin: [`ownership.yaml`](ownership.yaml).

Trust **tested current code**. Update this file when code truth changes.

---

## Surfaces

| Surface | Role | Must not |
| --- | --- | --- |
| **Open-FDD product** (GHCR stack) | Rust central (DataFusion SQL FDD + `/api/analytics/*`), React SPA (`openfdd-web`), fieldbus, mqtt | Python/pandas in the product request path; FDD math in TypeScript |
| **React SPA** | Sole product UI → central `/api` only ([ADR-001](../docs/architecture/adr-001-react-rust-modernization.md)); internet-facing hygiene (no bench credential hints on login) | Secret/path handoffs in product UI; BACnet wire ownership in the browser |
| **Historian** | **Parquet durable history**, Arrow in-memory batches, DataFusion SQL; provider-neutral `file://` / `s3://` storage contract ([historian lock](docs/HISTORIAN_ARCHITECTURE.md)) | Treat Feather/IPC as canonical durability; one file per telemetry sample; hard-code Railway; introduce a traditional DB as historian |
| **Open-FDD PyPI** (`open-fdd`) | Third-party libraries: `ecm_engineering`, `rules`, `analytics`, `reporting` — runs **outside** the product app | Be mistaken for the product FDD runtime |
| **Vibe 21 program kit** | [`tools/open-fdd-vibe21-production/`](../tools/open-fdd-vibe21-production/) — recovery → twin → Unity ZIP import | Skip Master Loop gates; Unity Editor in production |
| **Vibe 19** (playground) | External pandas oracle demo + GHCR demo image | Own production FDD or product UI |
| **Vibe 20** (playground) | EnergyPlus twin, calibration, ECM cross-check | Retain duplicate **generic** ECM formulas after Open-FDD parity |
| **MCP** (`openfdd-mcp`) | Read-first stdio tools → central | Embed EnergyPlus dial tools without an explicit product decision |
| **`edge/`, `os/`** | Future OS / edge concepts | Be deleted “for cleanup” |
| **WattLab export tooling** | `tools/wattlab_export` (optional offline Python) | Ship inside the product central image or block health/analytics |

---

## Historian ownership

Canonical contract: [`docs/HISTORIAN_ARCHITECTURE.md`](docs/HISTORIAN_ARCHITECTURE.md). Full repository audit and rationale: [`../docs/architecture/historian.md`](../docs/architecture/historian.md).

- Parquet is the canonical durable historian.
- Arrow is the in-memory execution format.
- DataFusion is the analytical SQL/FDD engine.
- Feather / Arrow IPC is optional cache/export/interchange only.
- Local/VM storage uses `OPENFDD_STORAGE_URL=file:///...`.
- Cloud/object storage uses generic `s3://` + `OPENFDD_S3_*` configuration; deployment platforms map their own variables into those names.
- Continuous telemetry is micro-batched into immutable monthly Hive-partitioned Parquet parts; never one file per point/poll.
- Bulk analysis and continuous AFDD are explicit separate modes. Scheduled continuous AFDD uses rolling, overlapping persisted-data windows rather than rescanning retained history.

---

## Rule cookbooks (both forever)

| Cookbook | Location | Role |
| --- | --- | --- |
| DataFusion SQL expression cookbook | `docs/rules/cookbook/datafusion-sql-cookbook.md` + `sql_rules/` | Production execution |
| Pandas expression cookbook | `docs/rules/cookbook/pandas-cookbook.md` + `open_fdd.rules` | PyPI oracle / engineering explanation |
| Parity matrix | `docs/rules/cookbook/parity-matrix.md` | Honesty about gaps |

Never replace cookbooks with generated API docs alone.
Never delete one cookbook because the other engine “won.”

**Execution:** SQL registry (`sql_rules/registry.yaml`) on central DataFusion.
**Oracle / PyPI:** pandas cookbook + `open_fdd.rules`.
**Recovery evidence:** [`docs/migration/react-rust/capabilities.yaml`](../docs/migration/react-rust/capabilities.yaml).

---

## Pandas allowed-use boundaries

**Allowed:** vibe19 playground; PyPI oracle extras; notebooks; characterization/parity tests against cookbooks.

**Forbidden:** production central computing FDD or Overview analytics via pandas; silent SQL→pandas fallback; claiming product FDD is pandas.

---

## ECM ownership

| Kind | Owner |
| --- | --- |
| Generic HVAC / finance formulas | `open_fdd.ecm_engineering` (PyPI) |
| EnergyPlus IDF, sim orchestration, APIHelper, calibration | vibe20 |
| Adapters / field-name translation | vibe20 (no recomputation of canonical formulas) |

---

## Reporting ownership

| Kind | Owner |
| --- | --- |
| Portable report builders / schemas | `open_fdd.reporting` (PyPI) |
| Product download UX | React SPA (`frontend/web`) |

---

## Container ownership

| Image | Channel | Notes |
| --- | --- | --- |
| `openfdd-central`, `openfdd-web`, `openfdd-fieldbus`, `openfdd-mqtt` | `:nightly` → pin `sha-<short>` | Central image is **Rust/debian only** (no Python) |
| `openfdd-mcp` | `:nightly` | Separate workflow |
| `vibe19`, `vibe20` | `:develop` | External playgrounds |

---

## Versioning ownership

See [`docs/VERSIONING.md`](docs/VERSIONING.md).
