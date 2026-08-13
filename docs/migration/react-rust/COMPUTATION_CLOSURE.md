# P2-M1 — Computation closure ledger

Prompt 2 inventory against code truth (commit of this PR). Production React
callers already use Rust/DataFusion; remaining Python is React SPA-local,
explicitly gated oracle, or deferred product.

Status values: `CLOSED` | `CUTOVER-NEEDED` | `ORACLE` | `DEFER` | `PROVISIONAL`

| family | React caller | central owner | React twin | prod Python on React path | status | notes |
|---|---|---|---|---|---|---|
| FDD registry run | `fddApi` → `POST /api/fdd/run` | `fdd_rules` + DataFusion SQL | `agent_api` / gated `rules/runner` | No | CLOSED | Pandas only if `OPENFDD_ALLOW_PANDAS_FDD=1` (oracle) |
| FDD results/series | Rules / Reports | `/api/fdd/results`, `/api/fdd/series` | charts / rule_card | No | CLOSED | |
| Analytics metering (inline) | `analyticsApi` / MeteringPage | `analytics/metering.rs` monthly sum | `metering.py` rate→monthly prep | No | CLOSED | React posts `{period,kwh}`; no pandas |
| Analytics metering (historian rate→kWh) | — | descriptive counts only | `metering.py` integrate_rate | N/A | PROVISIONAL | Historian invents no energy; rate integrate stays twin until M1 follow-on or delete |
| Analytics runtime / RCx / sensor / schedule / econ | MeteringPage / Overview | `analytics/*.rs` + historian DF | `ui_analytics`, `ui_rcx_tab`, `runtime_intervals` | No | CLOSED / PROVISIONAL | Descriptive historian rows where full formula not yet proven |
| Jobs / findings / dispositions | FindingsPage / JobsPage | `jobs.rs` | `eng_findings`, `ui_jobs` | No | CLOSED | |
| Reports artifacts | ReportsPage | `/api/reports*` | `reports.py`, downloads | No | CLOSED | PDF/DOCX = ORACLE |
| WattLab handoff | WattLabPage | jobs wattlab handoffs | `ui_wattlab_*`, dump | No | CLOSED | |
| Upload / mapping / package | UploadPage / MappingPage | csv_ingest / package.rs | package_io, mapping_wizard | No | CLOSED | React twins ORACLE until delete |
| Weather acquisition | — | — | open_meteo / weather_* | — | ORACLE / DEFER | CAP-WEATHER NOT_STARTED; ORACLE-ONLY |
| ECM workbooks | — | — | ui_ecm_job | — | DEFER | KEEP-AS-LIB `open_fdd/ecm_engineering` |
| Site delete FS | — | — | site_model | — | DEFER | CAP-SITE NOT_STARTED |

## Remaining Python call sites (must stay unreachable on React/no-Python stack)

| path | gate | disposition |
|---|---|---|
| `frontend/web/app/metering.py` | React Metering/RCx only | DELETE-P2 after canary (`P2-DEL-01`) |
| `frontend/web/app/rules/**` + `OPENFDD_ALLOW_PANDAS_FDD` | explicit env | ORACLE-ONLY (`P2-DEL-08` prod image) |
| `OPENFDD_ANALYTICS_ORACLE=1` branches | explicit env | ORACLE-ONLY |
| `open_fdd/analytics` | PyPI / React shims | REPLACE → delete after observation |
| `open_fdd/rules` | oracle / emergency | ORACLE-ONLY |

## Registry production status honesty

`sql_rules/registry.yaml` (63 rules) — Wave 0 ladder:

| raw `parity_status` | count | production meaning |
|---|---|---|
| `sql_screening` | 62 | SQL present; **not** mask/duration-proven vs pandas |
| `concept_only` | 1 | Incomplete roles (`FC7`) |
| `predicate_parity` / `mask_parity` / `duration_parity` / `site_soak` | 0 | Require executable oracle fixtures before promotion |

Legacy labels `proven_building_100` / `ported_from_cookbook` are retired. Screening ≠ proven.

## Policy proof (this PR)

`scripts/phase2_computation_policy_check.py`:

1. `docker/compose.react.yml` ships the product UI as `openfdd-web` (no alternate UI image).
2. Product React compose must not set `OPENFDD_ALLOW_PANDAS_FDD` or `OPENFDD_ANALYTICS_ORACLE`.
3. `services/central/src` (non-test) has no `python`/`pandas`/`pip` interpreter spawn strings.
4. This ledger file exists.

## Follow-on PRs (not this PR)

| PR | scope |
|---|---|
| P2-M2-01/02 | Shadow harness + soak evidence |
| P2-M3-* | Canary promotion decisions |
| P2-M4-01 | React production default flip (authorized separately / turnkey) |
| P2-M5 / DEL-* | Leaf twin deletion per `PHASE_2_DELETION_CANDIDATES.md` |
| P2-M6 / Prompt 7–8 | React product removal + final no-Python qual |
