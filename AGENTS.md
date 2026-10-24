# Agent Guide (container stack + external agents)

Open-FDD 4.0 ships as a **portal container stack**: `openfdd-central`, `openfdd-web`
(React), Timescale, plus optional `openfdd-mcp`. BACnet/Modbus/Haystack wire and the
MQTTS broker are an **unqualified archive**
([`archive/ot-edge/unqualified-cdaa4f15/`](archive/ot-edge/unqualified-cdaa4f15/README.md)),
not the default compose or publish path. It does **not** ship an embedded AI chatbot.
External orchestrators — Codex CLI, Cursor, OpenClaw, Claude Desktop, or any MCP host —
connect via **JWT REST** and optional **`openfdd-mcp` stdio**.

| Layer | Responsibility |
| --- | --- |
| **central** | Portal HTTPS ingest, **Timescale** historian, `.sql` FDD + `/api/analytics/*`, REST + JWT (Rust image — no Python). Ingest is the Normal Framework portal and CSV only. Wave-X 3.6.0: no DataFusion/Parquet/Arrow product path ([ADR-010](docs/architecture/adr-010-timescale-hard-cutover.md)) |
| **web** | React product UI (`frontend/web`) — sole product UI ([ADR-001](docs/architecture/adr-001-react-rust-modernization.md)) |
| **fieldbus** | Archived OT drivers (BACnet / Modbus / Haystack wire). Not in the `portal` recipe. |
| **mqtt** | Archived Mosquitto MQTTS broker. Not in the `portal` recipe. |
| **timescale** | Sole product historian + SQL FDD store (`openfdd-timescale`) |
| **mcp** | Optional read-first stdio tools → central (`OPENFDD_API_BASE`). OT wire tools are retired. |

**Docs:** [Build recipes](docs/operations/build-recipes.md) · [Local deploy (HTTP / firewall)](docs/operations/LOCAL_DEPLOYMENT.md) · [Railway CLI hub](docs/operations/RAILWAY_DEPLOYMENT.md) · [Stress closeout](docs/operations/STRESS_CLOSEOUT.md) · [Grok Bot Soft-OPEN handoff](docs/operations/GROK_BOT_SOFTOPEN_HANDOFF.md) (mega prompt → `python3 scripts/ops/kickoff_grok_bot.py <prompt.md>`) · [External agents](docs/examples/external-agents.md) · [MCP README](mcp/README.md) · [ECM engineering (PyPI)](docs/ecm/README.md) · [Package authoring](docs/agent/PACKAGE_AUTHORING.md) · [Security](SECURITY.md)

**Software-engineering agent OS:** [`openfdd_agent_spec/`](openfdd_agent_spec/) — architecture locks, skills, Milestone A.


**Current test tooling:** [qualification](scripts/qualification/README.md),
[stress v2 evidence](scripts/stress/README.md), [parsed semantic known answers](scripts/qualification/semantic/README.md)
and [ZAP limits](scripts/qualification/zap/README.md). Offline evaluator passes
are not live application/security qualification.3.x OT pins/fieldbus notes below
are historical; do not restore retired transports to satisfy them. Keep one
container/scanner workload at a time and save frequent evidence checkpoints.

**Release outcomes:** [`MILESTONES.md`](MILESTONES.md) separates implementation, candidate verification and release. Wave U's 2026-09-20 independent acceptance audit is the local Cursor handoff at `.cursor/plans/wave_u_independent_acceptance_audit.plan.md`; follow its reopened acceptance criteria under the Wave U master. A missing Nessus license blocks the actual assessment, not standalone/field readiness work.

**Active recovery / Vibe 21 twin program:** [`tools/open-fdd-vibe21-production/`](tools/open-fdd-vibe21-production/README.md) · capability ledger [`docs/migration/react-rust/capabilities.yaml`](docs/migration/react-rust/capabilities.yaml). Modernization Phase 1+2 exit is **architecture direction**; Vibe 21 recovery is the active qualification program (not “Phase 1 complete”).

**PyPI (`open-fdd`):** ECM engineering + pandas oracle (`open_fdd.rules` / `analytics` / `reporting`) for **third-party tooling** and **test-only** parity (DuckDB allowed in harnesses only). Product FDD is Timescale + `sql/fdd/*.sql` on GHCR — never pandas/DuckDB in the product request path.

**Offline AHU Typst (single system or building folder):** the only shipped PDF command is `open-fdd-anomaly report <folder> --out <dir> --month YYYY-MM --compile` (`--scope single-system|building`). Do not use `build_april_report.py` or any other out-of-tree runner, and do not compile `report.typ` by hand. Default title is **Open-FDD AI Agent Report** (`--title` overrides it). `--location` is an optional site line (example `AHU · Example Campus · City, ST`). It is empty unless passed. The PDF chrome is the Open-FDD blue (`#2563eb` / `#1e3a8a`) and lists month, sample count, sample interval, and span. It works with any AI agent that can read markdown skills and run the PyPI CLI. `openfdd_agent_spec/skills/` is the only source of truth for Open-FDD agent skills. Do not author a parallel skill under `.cursor/skills/` or any other vendor directory. `./scripts/openfdd_install_agent_skills.sh --sync` is the sync into Cursor, Claude, Codex, OpenClaw, Hermes, and Grok. Related skills: typst report, pypi-oracle, rcx-fdd-plot-poll, package-mapping. Fixture example `--month 2026-06`. April device-folder example (do not fetch it in CI): `--month 2026-04 --web-oat ./open_meteo_april.csv --week 2026-04-06` for an 8640-row 5-minute `history_wide.csv` (`2026-04-01` through `2026-04-30`) and a 15-minute Open-Meteo sidecar (`web_oa_t` / `web-outside-air-temp`, reindexed with `align_to_index`). That week is the recommended RCx window through `2026-04-12`. Web OAT otherwise is a mapped `web-outside-air-temp` column, `--web-oat weather.csv`, or `--web-oat fetch --lat --lon` (`open_fdd.analytics.open_meteo`, then `prefer_web_oat`). PDF order for facility readers: a sensor-check paragraph (failed checks only, grouped into sentences), then an anomaly paragraph (“look normal” / “needs a look” / skipped when fan-on data is thin), then an executive summary that opens with those two paragraphs, then motor weekly run-hours (`motor_weekly_runtime_chart` for every mapped fan and pump on any profile; a short note when none are mapped), then one fan-on week of AHU RCx lines from `charts` / `rcx_plots` / `economizer_temps_overlay` / `bas_vs_web_oat_overlay`, then `rule_result_chart` only for non-SV rules with confirmed hours, then `economizer_delta_scatter` with **x = OAT − RAT** (`delta_or_f`), **y = MAT − RAT** (`delta_mr_f`), viewport `bottom_left` (both deltas ≤ 0). Point builder is `build_economizer_delta_points` (`economizer_delta_frame` is the same function). Do not plot OAT−MAT vs RAT−MAT. Do not put histograms, scoreboards, or anomaly method names in this PDF. The template is `open_fdd.reporting.report_template`: `vav_ahu` and `cv_ahu` share the air-side figures (`unitVentilator` / `uv` → `cv_ahu`). Single-zone, chiller, boiler, heat pump, VAV box, fan coil, geothermal field, and data hall are registered stubs. History is mapped roles and is not Railway-only: a local CSV plus column map, a Railway or self-hosted Open-FDD central (agent-supplied reader), or a future vendor API. Agents may add `ai_comments.json`. The PDF has no re-run footer. RCx keeps the economizer rainbow (OAT/RAT/MAT/SAT plus damper percent) and adds fan-on supply-air vs web outdoor air plus a fan-on duct-static box. It does not repeat `ahu_dats`, `ahu_mats`, `ahu_rats`, `ahu_dampers`, `ahu_cooling_valves`, or `fan_speeds`. `--compile` writes `report.pdf` when `typst` is on `PATH`. The economizer scatter caption (`econ_scatter_caption`) sits under the figure: damper color against the outdoor-air fraction lines, damper position is not fresh-air fraction, and mild weather where MAT ≈ RAT ≈ OAT shrinks the deltas. This path does not read `/home/ben/building100_rcx_report` and does **not** replace the BUILDING_100 Overview-mirrored lab PDF. Skill: [`openfdd_agent_spec/skills/openfdd-typst-rcx-report/SKILL.md`](openfdd_agent_spec/skills/openfdd-typst-rcx-report/SKILL.md).

Dual expression cookbooks (permanent): `docs/rules/cookbook/` (SQL + pandas).

## Start session

Unmerged UI is **not** on GHCR. Resolve newest published images by OCI
`created` (`./scripts/ghcr_newest_by_created.py`), and never paste a Caddy
URL until `./scripts/openfdd_demo_gate.sh` exits 0. See
[`CONTAINER_AGENT.md`](openfdd_agent_spec/CONTAINER_AGENT.md).

```bash
./scripts/openfdd_stack_up.sh portal       # 4.0: React SPA + central + Timescale
# OT archive render only (no containers, digest-pinned):
# OPENFDD_OT_ARCHIVE_RESTORE=1 ./archive/ot-edge/unqualified-cdaa4f15/recipes/restore-isolated.sh --replay
# csv is central + web without the portal provider env forwarder
# Admin (UI) — or use username "agent" + OPENFDD_AGENT_PASSWORD for operator JWT (Railway / MCP)
TOKEN="$(curl -s -X POST http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"agent","password":"'"$OPENFDD_AGENT_PASSWORD"'"}' \
  | jq -r '.token // .access_token')"
```

On Railway: set `OPENFDD_JWT_SECRET`, `OPENFDD_ADMIN_PASSWORD`, and `OPENFDD_AGENT_PASSWORD` on central; keep MCP private; see [RAILWAY_DEPLOYMENT.md](docs/operations/RAILWAY_DEPLOYMENT.md) § Secure agent auth. Admins can also `POST /api/auth/agent-token` for short-lived operator JWTs.

Discover routes: `curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/agent/tools | jq '.tools | length'`

## Rust and React best practices (agents)

Product Rust and the React SPA follow one review standard. Coding and review agents read it before editing or approving either tree.

- **Rust:** [`openfdd_agent_spec/docs/RUST_BEST_PRACTICES.md`](openfdd_agent_spec/docs/RUST_BEST_PRACTICES.md) — safety, async locks, API shape, Clippy denies. Suppressions: [`openfdd_agent_spec/docs/RUST_LINT_HYGIENE.md`](openfdd_agent_spec/docs/RUST_LINT_HYGIENE.md).
- **React:** [`openfdd_agent_spec/docs/REACT_BEST_PRACTICES.md`](openfdd_agent_spec/docs/REACT_BEST_PRACTICES.md) — render cost, hooks, fetch abort, TypeScript, accessibility. Screen rules stay in [`openfdd-react-spa`](openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md).
- **Review skill:** [`openfdd-code-review-rust-react`](openfdd_agent_spec/skills/openfdd-code-review-rust-react/SKILL.md).
- **Product surface:** NF portal API and CSV ingest only. No legacy protocol code (MQTT, BACnet, Haystack, Modbus, fieldbus, edge wire) and no dual-write paths in product code. Archived code lives in `archive/` and is not a workspace member.

When changing Rust:

- **Delete** unused items (`dead_code`) — do not keep “just in case”; Git retains history.
- **Remove** `#[allow(...)]` / `#![allow(...)]`; fix the cause. Prefer `_` / `_guard`, `?`, or smallest-scope `#[expect(...)]` with a one-line constraint comment. Never crate-wide `#![allow]`.
- Never silently discard `Result`/`Option`; prefer `?` or explicit match/log. Last resort: `let _ = …;` + why.
- Prefer `?` / combinators over `.unwrap()` on production paths. Tests may unwrap and expect (`allow-unwrap-in-tests` and `allow-expect-in-tests`). Product crates deny `clippy::unwrap_used` and `clippy::expect_used`.
- Historian: **Timescale** (`OPENFDD_DATABASE_URL` / `OPENFDD_HISTORIAN=timescale`) is canonical ([ADR-010](docs/architecture/adr-010-timescale-hard-cutover.md), [`TIMESCALE_WAVE_X.md`](docs/operations/TIMESCALE_WAVE_X.md)). No dual-write. Do not resurrect DataFusion/Parquet/Arrow on the product path (`legacy-*` features stay OFF). Feather dual-write remains retired.

Patch-cycle train after Plans 1–4: log gate FAILs in [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md) **before** fixing → tiny rev bump (product only) → GHCR `sha-*` → re-pin → smoke → re-stress affected gate → move row to patched. Local synthetic CSV FDD and Railway F1 are separate stress tiers (see [`openfdd_agent_spec/CONTAINER_AGENT.md`](openfdd_agent_spec/CONTAINER_AGENT.md) § Ops patch cycle).

## Safe scripts

```bash
./scripts/openfdd_stack_pull.sh portal
./scripts/openfdd_stack_up.sh portal
./scripts/openfdd_stack_up.sh csv
```

## External agent workflow

1. Stack healthy on LAN/VPN only — never expose on public internet.
2. JWT for admin/operator/viewer (see central auth env).
3. `openfdd-mcp` stdio outside the web UI, or REST `/api/agent/tools`.
4. Read-first; writes need `OPENFDD_MCP_ALLOW_WRITES=1` and `confirm:true`.
5. Never print secrets. BACnet writes need explicit human approval.

## Security reports

Do **not** open a public GitHub issue, discussion, or chat thread for a suspected vulnerability. Direct reporters to GitHub Private Vulnerability Reporting:

`https://github.com/bbartling/open-fdd/security/advisories/new`

Ask for the affected component/version, complete reproduction steps, proof of impact, redacted screenshots/logs, and a suggested correction when available. Never copy credentials, tokens, private hostnames, OT details, or exploit evidence into public tickets or agent transcripts. Canonical policy: [`SECURITY.md`](SECURITY.md).

## Package authoring (any BAS job)

Open-FDD is a **generic** data-model-driven framework. Charts / FDD / RCx / motors / mixing / OAT-METEO read **SQL roles** after `POST /api/csv/import/package`. They do **not** know a vendor or campus. Empty Overview tables, RCx plots, Inspect traces, or `?/3` health scores mean the **package map is incomplete** — map in the zip. Gold shape (`AHU_1`, `VAV_1`, `CHW_1`, `weather/`) is a layout example, not a selector. Product paths — SPA, central / Timescale historian / analytics, PyPI report / fault / oracle (`open_fdd` reporting, rules, Typst, anomaly CLI), and RCx / FDD plot selection — never hard-code one building, campus, vendor suffix table, or fixture equipment id. `building_id` is always a caller, request, JWT, or env parameter. Equipment selection uses `equipType` / `equipment_type`, roles, and the registry: never prefer `RTU_01` or `VAV_1` over type, and never substring, prefix, `LIKE`, `contains`, or `starts_with` on `equipment_id` (`RTU_01` must not hit `RTU_010`). An exact id is allowed only after the type filter. Tests, stress, ops, migrate helpers, and lab fixtures may **name** ACME, BUILDING_100, or LAKESIDE as env defaults; their selectors stay type-first and exact-id-only. See [`openfdd_agent_spec/AGENTS.md`](openfdd_agent_spec/AGENTS.md) rule 62 and [`openfdd-site-identity`](openfdd_agent_spec/skills/openfdd-site-identity/SKILL.md).

| Need | Haystack → SQL | If the BAS has no binary point |
| --- | --- | --- |
| Motors | `fan-status` / pump status | Synthesize 0/1 from VFD %; never leave-temp hours |
| Compressor / mech OAT bins | `chiller-status` / `compressor-status` | Never CHW pump or `clg_valve_pct`. Status → cmd → amps |
| Mixing / economizer | fan on + OA + RA + MA | Copy site-global OA onto AHUs in the zip |
| VAV / zone | `zone-air-temp`, actual CFM, damper, reheat | Stamp `equipType: vav` |
| BAS vs web OAT | `outside-air-temp` + `{building}/weather/` `web-outside-air-temp` | Job lat/lon in preprocess; `prefer_web_oat` |
| Typing | `equipType` / `equipment_type` | `rtu`→AHU; `heatPump`→HP; **UV→CV AHU**; **FCU/standalone DDC→ZONE**; chillers→chwPlant |

Aliases: [`docs/migration/vibe19/ROLE_MAPPING_PARITY.md`](docs/migration/vibe19/ROLE_MAPPING_PARITY.md). Full brief: [`docs/agent/PACKAGE_AUTHORING.md`](docs/agent/PACKAGE_AUTHORING.md).

## Product UI / FDD agent notes

- **Overview:** tabulated analytics + plant/VAV **health matrices** (AHU → chiller → boiler → HP → VAV). No Plotly on Overview. Motor / mech / econ / BAS figures live on **RCx Plots** (additive presets). CSV overlay is the **Inspect** radio (`/inspect`).
- **Sidebar revision:** `data-testid="app-revision"` shows `GET /api/health` `semver+shortsha` (fallback `version.json`).
- **Lab → FDD Plots:** `session_config` `confirm_min` (and rule params) apply to the series overlay (`sql_detail_session`). After **Update this rule**, Reports/FDD Plots must refetch on `RULES_UPDATED`.
- **Series preview:** FDD Plots and each RCx timeseries card show the most recent N rows of the plot window already loaded (newest first). Per-plot dropdown default 10 (10/20/50/100/500). Do not load the historian again for the table.
- **SCHED-1 occupancy:** treat numeric `0` / `0.0` / `false` **and** string `unoccupied` (and related tokens) as unoccupied — SQL + pandas cookbook stay aligned.
- **Synthetic-59:** soak via `scripts/synthetic_59_*.py` under `reports/eplus-dump/fixtures/synthetic_59/` (legacy `reports/wattlab-parity/` still works). Do not greenwash `expected_faults.csv`. Vibe19 dual-parity is **retired** — use OpenFDD-only soaks + `scripts/eplus_dump_clustering_export.py` for E+ dump/clustering.
- **Units:** FDD SQL is °F canonical. Metric CSVs convert at query (`unit_system=metric|si`). Lab sliders show °C when metric is selected; Run all rules after switching.
- **Hourly append:** seed with `POST /api/csv/import/package`, then `POST /api/csv/import/package/append` (JWT, `confirm:true`). Custom vendor appenders stay outside the repo.
- **Package timestamps + maps:** `timestamp_utc` accepts ISO-8601 `Z` and `+00:00`. Unparseable rows are skipped (never epoch 0 / now). String `"equip": "AHU_1"` on a sidecar is metadata; package maps need object `equip`/`equipment`. Site vendor names belong in zip preprocess — not product code. See [`docs/RUST_DATAFUSION_ENGINE.md`](docs/RUST_DATAFUSION_ENGINE.md) and [`docs/mcp-agents/roles/package-mapping.md`](docs/mcp-agents/roles/package-mapping.md).
- **Overview layout:** full width beside sidebar (Streamlit-like); named Plotly PNG stems via `downloadFilename` on RCx / Inspect / FDD Plots; Lab rule menu A–Z; FDD series = required∪optional roles.
- **Mech OAT bins:** status/cmd before amps; prefer web/weather OAT.

## Deployment

### Railway cloud lab

Railway is an **experimental cloud path**, not a replacement for the LAN/VPN/OT deployment contract or a claim of production public-internet hardening.

**Agent ops (bensbench):** use the **Railway CLI** for backup + hub tip re-pin — [`openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md`](openfdd_agent_spec/skills/openfdd-railway-cli/SKILL.md) · [`docs/operations/RAILWAY_DEPLOYMENT.md`](docs/operations/RAILWAY_DEPLOYMENT.md). Do **not** confuse Railway CLI / Railway MCP with **`openfdd-mcp`** FDD tools. Resolve the image with `./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web`. Do not reuse a 3.5.x pin. Retired pins are `historical/non-executable` in [`docs/archive/ai-agent/historical-3.5-ot-ops.md`](docs/archive/ai-agent/historical-3.5-ot-ops.md).

- **Portal lab:** `openfdd-central` + `openfdd-web` + Timescale. Ingest is the Normal Framework portal API and CSV.
- **CSV-only lab:** `openfdd-central` + `openfdd-web` (`./scripts/openfdd_stack_up.sh csv`).
- Real optional image: `openfdd-mcp`.
- Do **not** invent `openfdd-commission`, `openfdd-mcp-rag`, or a Python/Streamlit commissioning runtime.
- Both central and web listen on container port `8080`; local Compose maps web host port `3000` to container `8080`.
- Central health is `GET /api/health`, not `/health`.
- **Deploy order:** Timescale → central (healthy `/api/health`) → web. Web uses `OPENFDD_CENTRAL_UPSTREAM=openfdd-central.railway.internal:8080` (no `http://`). Tip web images resolve upstream DNS lazily (`OPENFDD_NGINX_RESOLVER=auto`) so nginx does not crash if private DNS is not ready at process start.
- Cloud pulls require public GHCR package visibility or Railway registry pull credentials. Railway private-registry credentials are plan-dependent; public GHCR is the simplest open-source path.
- `OPENFDD_JWT_SECRET` and `OPENFDD_ADMIN_PASSWORD` must be deployment-unique secrets and must never be committed.
- Attach persistent storage at central `/workspace` before relying on imported packages across redeploys.
- Prefer the `sha-*` from `./scripts/ghcr_newest_by_created.py` over a tag named `:nightly`. A `master` merge triggers the GHCR stack and MCP publishers; do not claim the new image until those publish jobs are green and that created-time resolves.

Full guide: [`docs/operations/RAILWAY_DEPLOYMENT.md`](docs/operations/RAILWAY_DEPLOYMENT.md). Checklist: [`docs/operations/RAILWAY_DEPLOYMENT_CHECKLIST.md`](docs/operations/RAILWAY_DEPLOYMENT_CHECKLIST.md). Image/tag contract: [`docs/operations/ghcr-images.md`](docs/operations/ghcr-images.md). Local stack entry point remains `./scripts/openfdd_stack_up.sh`.

A Railway one-click template should eventually encode **Timescale → central → web** with generated secrets. Do not add a README deployment button until the real template exists and has been verified.

## Low-RAM hosts (bensbench)

- **Never** local `docker build` / heavy Rust compile for stack images. Ship via PR → GH Actions → GHCR `nightly` / `sha-*`.
- Before pulling new images: prune unused/old digests first, then `./scripts/openfdd_stack_pull.sh …` and `./scripts/openfdd_stack_up.sh … --no-pull`.
- Memory / AFDD: prefer lookback-bounded Timescale SQL cycles on small hosts; see [`docs/operations/AFDD_MODES.md`](docs/operations/AFDD_MODES.md). Legacy DataFusion spill pool vars are not the tip path ([ADR-010](docs/architecture/adr-010-timescale-hard-cutover.md)).
- Fieldbus, BACnet Who-Is, and Pi fieldbus-only soaks are `historical/non-executable` ([`docs/archive/ai-agent/historical-3.5-ot-ops.md`](docs/archive/ai-agent/historical-3.5-ot-ops.md)). Do not pull `openfdd-fieldbus` for a portal lab.
- Details: [`openfdd_agent_spec/CONTAINER_AGENT.md`](openfdd_agent_spec/CONTAINER_AGENT.md).

## AFDD vs bulk FDD

Same Timescale SQL registry. Bulk = CSV/package / manual run; continuous AFDD = opt-in timer + lookback on the Timescale historian (watermark/incremental — not full-DB every tick). Ingest is the Normal Framework portal and CSV. Multi-site isolation is by `building_id`. Full contract: [`docs/operations/AFDD_MODES.md`](docs/operations/AFDD_MODES.md).

Product ingest has no `mqtts`, `local_fieldbus`, or `dual` mode. Those modes are `historical/non-executable` in [`docs/archive/ai-agent/historical-3.5-ot-ops.md`](docs/archive/ai-agent/historical-3.5-ot-ops.md).

## Platform revision (sidebar)

SPA shows `GET /api/health` → `{semver}+shortsha`. On each turnkey platform patch cycle, bump the workspace **patch** version (`VERSION` + Cargo workspace) so operators see a new semver after pulling nightly — not only a new SHA.

## Analytics cache and disk budget

**Cache ≠ historian.** The durable product historian is **Timescale** ([ADR-010](docs/architecture/adr-010-timescale-hard-cutover.md)). Separately, analytics / RCx / sensor-fault **result cache** may persist as Parquet under `analytics_results/` (schema `analytics-result-parquet-v2`), keyed by the caller `building_id`, query id, query version, window, and config hash — that cache is not the telemetry store and is not co-canonical with Timescale. Explicit JSON nulls stay on the row that set them. Request `equipment_ids` are part of that config hash. This cache does not classify equipment with `equipment_id` text filters and does not invent `equipType`. AFDD `{rule_id}.json` stays the rule-runner path. The cache key includes the result contract, SQL pack, and model revision. A newer scoped Timescale watermark or coverage sets `stale: true` unless the client sends `refresh: true`. A failed watermark read is explicit and is not treated as order zero. CSV buildings unload the working set when the job finishes; the SPA leaves the lease on `?site=` change; idle default is 60s; max interactive sessions default to 2. MQTTS keeps a small ingest buffer keyed by the envelope site id. Soft-OPEN until edge disk proof; Soft-OPEN ≠ FQ.

Local/edge disk budget defaults to **100 GiB**, oldest cache artifacts first (`OPENFDD_LOCAL_DATA_BUDGET_GIB`). Railway eviction stays off unless `OPENFDD_DATA_BUDGET_ENABLED=1`. Soft-OPEN Railway/ACME: **no site backups** unless Ben asks — Timescale-only, dual-write false ([TIMESCALE_WAVE_X.md](docs/operations/TIMESCALE_WAVE_X.md)). `OPENFDD_TEST_DEPLOY=1` skips release backups unless `OPENFDD_BACKUP_ON_UPDATE=1`. Docs: [`docs/operations/ANALYTICS_RESULT_CACHE.md`](docs/operations/ANALYTICS_RESULT_CACHE.md) · [`docs/operations/DATA_RETENTION_BUDGET.md`](docs/operations/DATA_RETENTION_BUDGET.md).

## Never

- delete `workspace/`
- run `docker compose down -v`
- run `docker volume prune`
- set `OPENFDD_RESET_DB` or `OPENFDD_ALLOW_DESTRUCTIVE_DB` on a routine update (a one-time purge needs a new reset token plus the allow flag; the same token does not purge again)
- print secrets or tokens
- expose API on public internet
- report vulnerabilities in public GitHub issues/discussions
- write BACnet without explicit human approval
- embed vendor chat relays or model API keys in the stack
- add Python to the product central/web request path
- local stack image builds on low-RAM hosts (use GHCR)
- hardcode a building, campus, vendor, or fixture equipment id into product code, or select equipment by a substring or prefix match on `equipment_id` (type, roles, and registry only; exact id only after the type filter)

See [docs/agent/index.md](docs/agent/index.md) for external-agent architecture.

For library/migration/PR missions (Milestone A), start at [openfdd_agent_spec/AGENTS.md](openfdd_agent_spec/AGENTS.md).

### Stamped equipment type precedence

Package ingest persists `equipType` / `equipment_type`. A recognized stamp is the classifier for inventory, plant-health grouping, plots, RCx cohorts, weather selection, motor groups, VAV health, and rule applicability (`AC_1` + `equipType: ahu` → AHU). A missing or unrecognized stamp is unclassified and matches nothing. Plots, FDD, analytics, and type-first stress selectors use that stamp, roles, and the registry. The framework never hardcodes one building. Never prefer a fixture id over the stamp. Never substring, prefix, `LIKE`, `contains`, or `starts_with` on `equipment_id` (`RTU_01` must not select `RTU_010`). An exact id is allowed only after the type filter. Do not invent an MQTT delta payload. Parent-AHU id proposals are not cohort membership and are not a plot filter. Vendor/campus aliases remain preprocess concerns and must not be hard-coded into product Rust. Epic: [#1043](https://github.com/bbartling/open-fdd/issues/1043). Agent rule 64 in [`openfdd_agent_spec/AGENTS.md`](openfdd_agent_spec/AGENTS.md).

ZONE = FCU (valve PID) or standalone DDC monitor (`fcu` / `zone_other`); UV = CV AHU (`unitVentilator`). Detail: [`docs/modeling/zone-terminals.md`](docs/modeling/zone-terminals.md).
