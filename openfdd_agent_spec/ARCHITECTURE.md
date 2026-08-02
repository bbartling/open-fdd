# Open-FDD architecture locks

Human-readable ownership. Machine-readable twin: [`ownership.yaml`](ownership.yaml).

Trust **tested current code** over historical `docs/migration/vibe19/*` stage notes.
Update this file when code truth changes.

---

## Surfaces

| Surface | Role | Must not |
| --- | --- | --- |
| **Open-FDD production** (GHCR stack) | Rust central, Arrow/Feather, DataFusion SQL FDD, JWT REST, React SPA (`openfdd-web`) sole product UI | Silent pandas FDD fallback; claim Streamlit is still the shipping default; claim Vibe 21 recovery Phase 1 complete without `capabilities.yaml` evidence |
| **React SPA** | Sole production UI → central `/api` only ([ADR-001](../docs/architecture/adr-001-react-rust-modernization.md)) | FastAPI/Python sidecar; FDD math in TypeScript; BACnet wire ownership |
| **Streamlit UI (archived)** | `services/ui` oracle/recovery (`ARCHIVED.md`, `streamlit-legacy` profile) | Be reintroduced as product default without a new ADR |
| **Vibe 21 program kit** | [`tools/open-fdd-vibe21-production/`](../tools/open-fdd-vibe21-production/) — recovery → twin → Unity ZIP import | Skip Master Loop gates; Unity Editor in production; BAS writes without authority |
| **Open-FDD PyPI** (`open-fdd`) | Reusable libs: `ecm_engineering`, `rules`, `analytics`, `reporting` | Be the production FDD runtime |
| **Vibe 19** (playground) | Educational pandas oracle + Streamlit demo + GHCR demo image | Remain canonical home of duplicated rule/analytics/reporting once migrated |
| **Vibe 20** (playground) | EnergyPlus twin, calibration, ECM cross-check, Studio | Retain duplicate **generic** ECM formulas after Open-FDD parity |
| **MCP** (`openfdd-mcp`) | Read-first stdio tools → central | Embed EnergyPlus / WattLab dial tools without an explicit product decision |
| **`edge/`, `os/`** | Future OS / edge concepts | Be deleted “for cleanup” |

---

## Rule cookbooks (both forever)

| Cookbook | Location | Role |
| --- | --- | --- |
| DataFusion SQL expression cookbook | `docs/rules/cookbook/datafusion-sql-cookbook.md` + `sql_rules/` | Production execution SoT |
| Pandas expression cookbook | `docs/rules/cookbook/pandas-cookbook.md` + `open_fdd.rules` | Oracle / engineering explanation |
| Parity matrix | `docs/rules/cookbook/parity-matrix.md` | Honesty about gaps |

Never replace cookbooks with generated API docs alone.
Never delete one cookbook because the other engine “won.”

**Execution SoT:** SQL registry (`sql_rules/registry.yaml`).
**Identity/metadata SoT (Phase 2 target):** shared rule manifest under `open_fdd.contracts` (not shipped yet).
**Recovery evidence SoT:** [`docs/migration/react-rust/capabilities.yaml`](../docs/migration/react-rust/capabilities.yaml) — modernization Phase 1+2 exit ≠ Vibe 21 P1-G0.
**Oracle SoT:** pandas cookbook + `open_fdd.rules`.

---

## Pandas allowed-use boundaries

**Allowed:** vibe19; PyPI oracle extras; notebooks; characterization/parity tests; UI plotting/display helpers that do not replace `/api/fdd/run`.

**Forbidden:** production central computing FDD via pandas; silent fallback from SQL to pandas when a rule fails; documentation claiming production FDD is pandas.

---

## ECM ownership

| Kind | Owner |
| --- | --- |
| Generic HVAC / finance formulas | `open_fdd.ecm_engineering` |
| EnergyPlus IDF, sim orchestration, APIHelper, calibration tied to E+ | vibe20 |
| Adapters / field-name translation | vibe20 (no recomputation of canonical formulas) |

---

## Reporting ownership

| Kind | Owner |
| --- | --- |
| Portable report builders / schemas | `open_fdd.reporting` |
| Streamlit download UX / session wiring | vibe19 and/or `services/ui` |
| Engineering Findings product rules | vibe19 agent skills + reporting lib |

---

## Container ownership

| Image | Channel for test | Notes |
| --- | --- | --- |
| `openfdd-central`, `openfdd-ui`, `openfdd-fieldbus`, `openfdd-mqtt` | `:nightly` on master | Also `sha-<short>` immutable |
| `openfdd-mcp` | `:nightly` | Separate workflow |
| `vibe19`, `vibe20` | `:develop` | Interim; retire only after parity matrix |

---

## Versioning ownership

See [`docs/VERSIONING.md`](docs/VERSIONING.md). Do not leave contradictory root README version claims.
