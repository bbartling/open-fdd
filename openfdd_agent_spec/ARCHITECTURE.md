# Open-FDD architecture locks

Human-readable ownership. Machine-readable twin: [`ownership.yaml`](ownership.yaml).

Trust **tested current code**. Update this file when code truth changes.

---

## Surfaces

| Surface | Role | Must not |
| --- | --- | --- |
| **Open-FDD product** (GHCR stack) | Rust central (Timescale historian + `sql/fdd` FDD + `/api/analytics/*`), React SPA (`openfdd-web`). `architecture_epoch: portal-timescale-v1`. Ingest is the Normal Framework portal API and CSV. Deploy central + web + Timescale (`./scripts/openfdd_stack_up.sh portal`). Hosting is the local single-host stack only (Railway / cloud web-app hosting retired). Soft-OPEN ≠ FQ ([ADR-010](../docs/architecture/adr-010-timescale-hard-cutover.md)) | Python/pandas in the product request path; FDD math in TypeScript; Parquet/DataFusion co-canonical; restoring MQTT or fieldbus as product ingest |
| **React SPA** | Sole product UI → central `/api` only ([ADR-001](../docs/architecture/adr-001-react-rust-modernization.md)); internet-facing hygiene (no bench credential hints on login) | Secret/path handoffs in product UI; BACnet wire ownership in the browser |
| **Historian** | **TimescaleDB durable history** + versioned SQL FDD (`sql/fdd`, `sql/schema`); ADR-010 Timescale hard cutover ([historian lock](docs/HISTORIAN_ARCHITECTURE.md)) | Dual-write; Parquet/Arrow/DataFusion co-canonical; Feather durability; Python on FDD equation path |
| **Open-FDD PyPI** (`open-fdd`) | Third-party libraries: `ecm_engineering`, `rules`, `analytics`, `reporting` — runs **outside** the product app | Be mistaken for the product FDD runtime |
| **Camber** (external) | [yroussev/camber](https://github.com/yroussev/camber) Apache-2.0 — algorithm reference for PyPI M&V / change-point ports only | GHCR request path; OT adapters; `camber serve` as product UI |
| **Vibe 21 program kit** | [`tools/open-fdd-vibe21-production/`](../tools/open-fdd-vibe21-production/) — recovery → twin → Unity ZIP import | Skip Master Loop gates; Unity Editor in production |
| **Vibe 19** (playground) | External pandas oracle demo + GHCR demo image | Own production FDD or product UI |
| **Vibe 20** (playground) | EnergyPlus twin, calibration, ECM cross-check | Retain duplicate **generic** ECM formulas after Open-FDD parity |
| **MCP** (`openfdd-mcp`) | Read-first stdio tools → central | Embed EnergyPlus dial tools without an explicit product decision |
| **`edge/`** | Package, semantic, and SQL helper linked by central. The edge process is archived. | Be deleted “for cleanup” |
| **`os/`** | Future OS concept | Be deleted “for cleanup” |
| **WattLab export tooling** | `tools/wattlab_export` (optional offline Python) | Ship inside the product central image or block health/analytics |

---

## Historian ownership

Canonical contract: [`docs/HISTORIAN_ARCHITECTURE.md`](docs/HISTORIAN_ARCHITECTURE.md) + [`../docs/architecture/adr-010-timescale-hard-cutover.md`](../docs/architecture/adr-010-timescale-hard-cutover.md).

- **TimescaleDB is the canonical durable historian** (Wave-X 3.6.0+).
- FDD/analytics equations live in versioned SQL packs (`sql/fdd`, future `sql/analytics`); Rust binds/auth/serializes only.
- **FORBIDDEN:** Parquet/Arrow/DataFusion/Feather co-canonical, dual-write, dual-read.
- Continuous AFDD uses watermark/incremental windows over Timescale samples — not a full-DB hammer every tick.
- Bulk package import and continuous AFDD remain separate modes.

---

## Rule cookbooks (both forever)

| Cookbook | Location | Role |
| --- | --- | --- |
| PostgreSQL / Timescale SQL pack | `sql/fdd/` + `sql/schema/` (+ cookbook where dual-expression) | Production execution |
| Pandas expression cookbook | `docs/rules/cookbook/pandas-cookbook.md` + `open_fdd.rules` | PyPI oracle / engineering explanation |
| Parity matrix | `docs/rules/cookbook/parity-matrix.md` | Honesty about gaps |

Never replace cookbooks with generated API docs alone.
Never delete one cookbook because the other engine “won.”

**Execution:** versioned Timescale SQL packs (`sql/fdd/`, `sql/schema/`) on central — not DataFusion ([ADR-010](../docs/architecture/adr-010-timescale-hard-cutover.md)).
**Oracle / PyPI:** pandas cookbook + `open_fdd.rules`.
**Recovery evidence:** [`docs/migration/react-rust/capabilities.yaml`](../docs/migration/react-rust/capabilities.yaml).

---

## Pandas allowed-use boundaries

**Allowed:** vibe19 playground; PyPI oracle extras; notebooks; characterization/parity tests against cookbooks; clean-room / Apache-attributed ports inspired by Camber into `open_fdd.*`.

**Forbidden:** production central computing FDD or Overview analytics via pandas; silent SQL→pandas fallback; claiming product FDD is pandas; vendoring Camber into GHCR images.

## Data model / graph (Wave S)

- ADR: [`docs/architecture/ADR_data_model_graph.md`](../docs/architecture/ADR_data_model_graph.md)
- Consumer/route matrix: [`docs/modeling/consumer-route-matrix.md`](../docs/modeling/consumer-route-matrix.md)
- Telemetry/FDD = Timescale + `sql/fdd`; RDF/SPARQL = relationships (when product central exposes them)
- Package TTL namespace: `urn:openfdd:ns#`; legacy commissioning RDF: `https://open-fdd.dev/model#`

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
| `openfdd-central`, `openfdd-web` | newest-by-OCI-`created` `sha-*` (`./scripts/ghcr_newest_by_created.py`) | Central image is **Rust/debian only** (no Python). Timescale is the database, not a GHCR app image. |
| `openfdd-fieldbus`, `openfdd-mqtt` | historical/non-executable | Unqualified archive. Do not pull them as the 4.0 stack. See [`docs/archive/ai-agent/historical-3.5-ot-ops.md`](../docs/archive/ai-agent/historical-3.5-ot-ops.md). |
| `openfdd-mcp` | `:nightly` | Separate workflow |
| `vibe19`, `vibe20` | `:develop` | External playgrounds |

---

## Versioning ownership

See [`docs/VERSIONING.md`](docs/VERSIONING.md).
