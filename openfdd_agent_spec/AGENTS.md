# Open-FDD agent workspace — orientation

Plain Markdown on disk is the source of truth for **Cursor**, **Codex CLI**, and
similar agents. Product code lives in `services/`, `sql_rules/`, `frontend/`,
`mcp/`, `edge/`, `os/`. PyPI libraries live in `open_fdd/`. Orchestration lives in
**`openfdd_agent_spec/`**.

**Primary agent prompt (paste into new sessions):** [`../AGENTS.md`](../AGENTS.md)

**Software-engineering mission:** [`MILESTONE_A.md`](MILESTONE_A.md)

**Haystack RDF / JSON model rollout (planned):**
[`HAYSTACK_RDF_ROLLOUT.md`](HAYSTACK_RDF_ROLLOUT.md) owns compatibility and
HR-01–HR-12 acceptance requirements; the
[Cursor handoff](../.cursor/agents/haystack-rdf-implementation-handoff.md) asks
Cursor to reconcile S5/V5 and create executable plans. Existing compact ZIP maps
remain supported. A declared Haystack prefix, valid Turtle, or an old green model
gate does not establish Haystack interoperability. Update capability claims only
from candidate evidence; this handoff ships no new product capability.

**Ops / edge soak prompts:** [`../docs/agent/`](../docs/agent/) — GHCR bench, nightly
retest. Do not confuse those with this engineering OS.

---

## Product vs libraries

| Layer | Owns |
| --- | --- |
| `services/` + `sql_rules/` + `frontend/web` | **Product:** central DataFusion SQL FDD + analytics, React SPA (`openfdd-web`), fieldbus, mqtt |
| `open_fdd/` | **PyPI libraries** for third-party tooling: ECM + pandas oracle (`rules` / `analytics` / `reporting`) — not the product runtime |
| `mcp/` | Optional read-first MCP → central |
| `edge/`, `os/` | Future concepts — **never delete** |
| `docs/rules/cookbook/` | Dual expression cookbooks (SQL + pandas) + parity matrix |
| `tools/open-fdd-vibe21-production/` | Active recovery + Vibe 21 twin program |
| `docs/migration/react-rust/capabilities.yaml` | Machine-readable capability ledger |
| `openfdd_agent_spec/` | Agent law, Milestone A, skills, session log |
| Playground vibe19/20 | External demos; consumers of PyPI |

**Package / timestamp contract (product + PyPI):** `timestamp_utc` is RFC3339 UTC (`Z` or `+00:00`). Rust ingest skips bad rows (no epoch 0 / now). Pandas oracle uses `open_fdd.timestamps.to_utc_datetime`. String `"equip"` on a Haystack sidecar is metadata. **Package authoring (any BAS job):** [`../docs/agent/PACKAGE_AUTHORING.md`](../docs/agent/PACKAGE_AUTHORING.md). Modeling (compact map vs SCAFFOLD, HP buildings, readiness): [`../docs/modeling/`](../docs/modeling/). Aliases: [`../docs/migration/vibe19/ROLE_MAPPING_PARITY.md`](../docs/migration/vibe19/ROLE_MAPPING_PARITY.md).

**Naming (code truth):**

| Concept | Module / extra |
| --- | --- |
| Pandas oracle (PyPI) | `open_fdd.rules` (+ `open_fdd.analytics`) |
| Pip extras | `oracle`, `analytics`, `reporting` (`vibe19` deprecated alias through 4.3) |
| ECM math | `open_fdd.ecm_engineering` |
| Shared contracts | `open_fdd.contracts` — Phase 2 target (not shipped) |

---

## AI agent quick rules (read first)

0. **Low-RAM bensbench / machine port (always):** One agent only (no duplicate Task/subagents on the same train). Never local `docker build` of central/web/mqtt/fieldbus. Pull GHCR `sha-*` only; prune old images before pull. After ZAP/stress, `docker rm -f` leftover zap/MCP disposable containers — keep only needed fieldbus. Never run Vibe13 `cargo`/Ansible TX in parallel with Open-FDD ZAP/docker. Push often. Portable brain: [`docs/operations/recovery/AI_CONTEXT_HANDOFF.md`](../docs/operations/recovery/AI_CONTEXT_HANDOFF.md). **Wave K CLOSED / PINNED** (`sha-9c3e8b1` / **3.4.0**). **Wave L ACTIVE** — **3.5.x multi-client shared hosting** (tenant-partitioned Parquet + control plane — **not** Postgres time-series); L4 LIVE mode OFF; mid-wave = smoke + gates 11–14; **ONE** enhanced full stress at **L8**. Handbook: [`CONTAINER_AGENT.md`](CONTAINER_AGENT.md) · [`PATCH_CYCLE.md`](../docs/operations/PATCH_CYCLE.md) · Cursor [`wave_l_shared_db_mega_master`](../../.cursor/plans/wave_l_shared_db_mega_master.plan.md).
1. Product FDD + Overview analytics = **DataFusion SQL** on GHCR. Never silent pandas fallback in central.
2. Pandas oracle stays forever on **PyPI** + cookbooks + vibe19 — never delete the pandas cookbook because production uses SQL.
3. Never delete the SQL cookbook because pandas remains the oracle.
4. **Product UI:** React SPA (`frontend/web` → `openfdd-web`, `compose.react.yml`) only. Overview = central `/api/analytics/*` (DataFusion) **tables + health matrices**. Plotly motor/mech/econ/BAS figures live on RCx (additive presets). Inspect radio hosts the CSV overlay. Browser → central Rust `/api` only — **no Python in the product request path**.
5. **Internet-facing auth/UI hygiene:** Never put bench/dev secrets, credential file paths, default passwords, or JWT dumps on login or other product surfaces. Generic login errors only.
6. Test containers on **`OPENFDD_IMAGE_TAG=nightly`**, but **pin/run `sha-*`** per [`CONTAINER_AGENT.md`](CONTAINER_AGENT.md).
6b. **Rust lint hygiene:** eliminate `#[allow]` / `#![allow]` — see [`docs/RUST_LINT_HYGIENE.md`](docs/RUST_LINT_HYGIENE.md). Prefer fix / `_` / `?` / smallest-scope `#[expect]` + comment; never crate-wide `#![allow]`.
7. Playground images: `ghcr.io/bbartling/vibe19:develop`, `vibe20:develop` (external).
8. `edge/` and `os/` are future concepts — never delete.
9. Bounded PRs only — see [`PR_PROTOCOL.md`](PR_PROTOCOL.md).
10. Prefer exact wheel install tests over editable-only validation for packaging PRs.
11. Never trust a moving GHCR tag alone — resolve/pull immutable `sha-*`, recreate containers, then record the digest.
12. Append [`SESSION_LOG.md`](SESSION_LOG.md) after non-trivial work.
13. Update [`BUILD_CHECKPOINTS.md`](BUILD_CHECKPOINTS.md) when Milestone A or product capability status changes.
14. CodeRabbit: fix actionable defects; reject suggestions that violate architecture.
15. vibe21 = separate plan — not Milestone A.
16. When blocked (secrets, permissions), finish non-blocked work and record the exact error.
17. Bound each PR to its declared scope.
18. **Active program:** [`tools/open-fdd-vibe21-production/`](../tools/open-fdd-vibe21-production/README.md) Master Loop. Keep [`capabilities.yaml`](../docs/migration/react-rust/capabilities.yaml) honest.
19. For `frontend/web` work: follow [`openfdd-react-spa`](skills/openfdd-react-spa/SKILL.md).
20. Central product image is **debian + Rust binaries only** — no Python. **Engineering & ML bundle** export is Rust-first (`POST /api/jobs/{id}/exports`, schema `openfdd_engineering_bundle_v1`). Offline Python parity stays in `tools/wattlab_export/` (`OPENFDD_WATTLAB_PYTHON_EXPORT=1` bench only). `/wattlab/dumps` is a deprecated alias.
21. **Site lock:** Overview + sidebar Active site are the only editors of `?site=`. `SectionTabs` (and sidebar App pages) must `navigate` with `hrefWithSession` so `site` + `eq` survive. FDD / RCx / Results / **Dump** show a locked `zip:BUILDING_*` caption — no Building `<Select>`.
22. **FDD Plots = vibe19 `rule_result_chart`:** auto-load series; last y-axis title is `fault`; `confirmed_fault` is the last trace on the bottom domain (`domain[0] < 0.4`). A successful rule run with an empty overlay is a bug (fail the test), not a soft banner.
23. **RCx catalog freeze:** every `REQUIRED_RCX_PRESET_IDS` id must stay listed. Family picker order is `RCX_FAMILY_ORDER` (Zones first) plus empty Heat pump / Weather placeholders. Auto-run the selected preset when site+preset are set.
24. **Actions housekeeping:** default `GET /api/actions?limit=10`; `DELETE /api/actions/:id` and `DELETE /api/actions`; JSONL prune cap 50.
25. **Section radios:** left, horizontal, **after** hero + Equipment on Overview (never inside `.oracle-hero`, never centered in the logo column). Other pages: same left radio row at the top of the page body.
26. **Overview is tables + health matrices** — no Plotly on Overview. Motor / mech / econ / BAS figures are additive RCx presets (`ahu_motor_weekly`, `economizer_*`, `boiler_motor_weekly`, `chiller_motor_weekly`, `mech_cooling_oat_bins`, `bas_vs_web_oat`). CSV overlay is the **Inspect** radio (`/inspect`). Do not drop `REQUIRED_RCX_PRESET_IDS`.
27. **FDD Plots series overlay** honors Lab/`session_config` `confirm_min` (and typed rule params); source may be `sql_detail_session`. After Update-this-rule, listen for `RULES_UPDATED` and refetch results + series.
28. **SCHED-1 portable occupancy:** numeric/boolean falsey (`0`, `0.0`, `false`) **and** string `unoccupied` (plus related tokens) — keep SQL (`sched1_unoccupied_runtime.sql`) and pandas `sched1` aligned.
29. **Low-RAM / bensbench:** never local stack `docker build`; prune old images before pull; wait for GHCR publish then pull `sha-*` / `nightly`. Synthetic-59 soaks: `scripts/synthetic_59_*.py` (OpenFDD-only). GHCR poll: `scripts/ghcr_watch_central.py`. E+ dump/clustering: `scripts/eplus_dump_clustering_export.py`, `scripts/agent_eplus_dump.sh`. Vibe19 B100 dump-parity **retired** → `scripts/retired/vibe19-parity/`. Never edit goldens to hide misses.
30. **Plot PNG downloads:** `PlotlyHost` must pass `toImageButtonOptions.filename` (Overview/Reports). Default Plotly `newplot.png` is a regression.
31. **Full-width UI:** `.app-content` / `.overview-populated` stretch (`max-width: none`) like Streamlit — do not reintroduce a rem content cap on Overview plots.
32. **Rule Lab menu:** `RuleTuningPanel` sorts visible rules A–Z by `rule_id` (registry YAML order is engine priority only). Labels must use the shared rule display contract — [`docs/RULE_DISPLAY_NAMES.md`](../../docs/RULE_DISPLAY_NAMES.md); no sidebar truncation vs full center labels.
33. **FDD Plots series roles:** `series_response` SELECT = `required_roles ∪ optional_roles` (SV-*/PID-HUNT keep required empty). Soft-empty when none present on equipment.
34. **Mech cooling OAT bins:** status/cmd proof **before** amps (never OR amps when status exists); prefer web/`dry_bulb_f`/weather OAT over site-averaged AHU BAS `oa_t`. Version `mechanical-cooling-oat-bins-v2`.
35. **Synthetic analytics soak:** `scripts/synthetic_59_overview_analytics_soak.py` asserts runtime + mech bin envelopes (separate from FDD pair scores).
36. **Metric CSVs:** store as-uploaded; convert temperature roles C→F at run-rules/historian query. Do not duplicate 59 SQL files. Sliders display user units.
37. **Package append:** `POST /api/csv/import/package/append` is the IoT hourly path (JWT + confirm). **AFDD routine sim:** `scripts/csv_flood_afdd_routine_sim.py` + `scripts/fixtures/b50_afdd_routine.json` on `raw_BUILDING_50_openfdd.zip` (append → session-config patch → `/api/fdd/run`). Doc: [`docs/agent/CSV_FLOOD_AFDD_ROUTINE.md`](../docs/agent/CSV_FLOOD_AFDD_ROUTINE.md). Vendor pullers stay out-of-repo.
38. **E+ dump / clustering:** prefer `reports/eplus-dump/` (`EPLUS_DUMP_ROOT`); `scripts/eplus_dump_clustering_export.py` emits sklearn-ready features. Online: `scripts/agent_eplus_dump.sh` (calls `/exports` or deprecated `/wattlab/dumps`). Bundle schema: `openfdd_engineering_bundle_v1`. Doc: [`docs/agent/EPLUS_DUMP_CLUSTERING.md`](../docs/agent/EPLUS_DUMP_CLUSTERING.md).
39. **Railway hub CLI (bensbench) — primary ops tool for tip re-pin:** Install `@railway/cli` (`npm i -g @railway/cli`). Auth: `railway login` (browser) **or** `set -a && source ~/.config/railway/bensbench.env && set +a` (`RAILWAY_TOKEN`). Project **`gleaming-cooperation`** / env **`production`**. Live services: `openfdd-central-cQ-F`, `openfdd-mqtt`, `openfdd-web` (confirm with `railway service list` — never assume `openfdd-central`). Loop: tip Publish green → `./scripts/check_ghcr_tip_stack.sh sha-<7>` → **`./scripts/railway_central_workspace_backup.sh`** → `railway service source connect --service … --image ghcr.io/bbartling/openfdd-*:sha-<7>` (central → mqtt → web) → `./scripts/openfdd_fieldbus_railway_up.sh sha-<7>` → smoke `/api/health` → Wave L mid-wave gates **11–14** or full stress at L8/ship pins. For smoke auth: export **`RAILWAY_ADMIN_PASSWORD`** from Railway vars (local `.env` must not clobber). Skill: [`skills/openfdd-railway-cli/SKILL.md`](skills/openfdd-railway-cli/SKILL.md). Railway CLI ≠ [`mcp/`](../mcp/) FDD tools. Never commit tokens; never treat Railway AI as the FDD agent.
40. **Always pin tip after Publish:** hub sidebar/`/api/health` must match tip `sha-*` (`3.5.x+…` on Wave L tips). Stale version while tip is newer is a P0 fail. **Backup** `/workspace` before every central re-pin (`scripts/railway_central_workspace_backup.sh`). Docs-only tips may Publish `sha-<docs>` images — ops pin stays on the **product** tip until an operator re-pins.
41. **Field → Railway only:** bensbench x86 `openfdd-fieldbus` → Railway MQTTS. Raspberry Pis are **out** of Open-FDD stress. Do not stand up local `react-ot` as the patch-cycle AFDD head-end. 60s poll+publish. Handbook: [`docs/operations/STRESS_CLOSEOUT.md`](../docs/operations/STRESS_CLOSEOUT.md) · [`PATCH_CYCLE.md`](../docs/operations/PATCH_CYCLE.md).
42. **FDD + STORAGE_URL:** when `OPENFDD_STORAGE_URL=file:///workspace/openfdd`, set `OPENFDD_PARQUET_ROOT=/workspace/openfdd` so `/api/fdd/run` finds package historian parquet (else “parquet cache missing”).
43. **Tip mqtt ACL path:** `acl_file /mosquitto/certs/acl` — local stacks must place ACL under `deploy/mqtt/certs/acl`, not only `deploy/mqtt/acl`.
44. **Stream roles ≠ package roles until mapped:** live tags `zonetemp`/`sa_t` normalize to `zone_t`/`sat`. Empty Overview with rising `ingest_ok` ⇒ roles, not nginx. OT poll+MQTT publish floor **60s**.
45. **Patch cycle (3.3.15+ ops closeout):** every nightly gate FAIL → log row in [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md) **Patch cycle — Phase 7 bugs** before opening a fix PR. Train: fix (one concern/PR) → `VERSION` bump if product change → GHCR publish → backup + re-pin → smoke `01`/`10` → **gate 18** volume restore → re-stress affected gate only → move row to **patched** when green. **Local synthetic CSV FDD** is accepted when import → parquet → `fdd/run` → `results[]` passes; gate 06 **#528** `poll_seconds` is harness-only. **Railway F1** (DF55, BUILDING_50 import/FDD, AFDD flood, bldg2 Overview) is a **separate** stress tier — do not block local bench closeout on Railway F1 in the same `run_all` session.
46. **Rule display names (one contract):** `rule_id` is the machine key; `sql_rules/registry.yaml` `description` is the **short human name** for all product UI. Cookbook headings extend that name (GL36 refs, etc.) — see [`docs/RULE_DISPLAY_NAMES.md`](docs/RULE_DISPLAY_NAMES.md). React must use shared formatters (`ruleLabels.ts` — planned) in sidebar `RuleTuningPanel`, FDD Plots picker, plot titles, health-matrix tooltips, and CSV exports. Do **not** truncate sidebar labels while showing full names in the center panel. Merge API rules into `cookbookRuleCatalog` at boot; avoid duplicate static description maps. Cookbook/registry drift is a parity bug — fix in the same PR family as rule changes.
47. **Package utilities (#805):** `openfdd_package_v1` may include `utilities/manifest.json` (`utilities_v1`) with `electric/monthly_bills.csv`, optional interval/submeter CSVs, or wrapper-level `utility_bills_monthly.csv` (Creekside). Ingest code: [`edge/src/csv_ingest/package.rs`](../edge/src/csv_ingest/package.rs). **Metering UI** reads package utilities for the active site (Uploads / Sites) — do **not** treat legacy fuel campus ZIP as primary ingest. Legacy fuel ZIP API: [`services/central/src/fuel/import.rs`](../services/central/src/fuel/import.rs) (read-only residue).
48. **Utility meter FDD:** `UTIL-MONTHLY` / `UTIL-INTERVAL` in `sql_rules/registry.yaml` compare BAS vs utility bills/intervals; `SV-*` rules accept `kwh` / `electric_kw` roles on `meter` equipment. Modeling skill: [`skills/data-modeling/SKILL.md`](skills/data-modeling/SKILL.md).
49. **Local deploy = HTTP behind firewall** — Compose UI `:3000` / API `:8080` are **plain HTTP**; product local stack does **not** terminate TLS yet. Do not expose to the public internet; do not claim local HTTPS unless an ops reverse proxy is documented. Handbook: [`docs/operations/LOCAL_DEPLOYMENT.md`](../docs/operations/LOCAL_DEPLOYMENT.md).
50. **Stress LAST (rigorous closeout):** after tip GHCR + Railway hub re-pin + x86 fieldbus up — `run_railway_hub_stress.sh` (gates **00–10** Wave K MEGAs + **11–15** Wave L OFF smokes + **16** A/B isolation harness + **17** legacy migrate dry-run; ZAP on Railway public URL). Wave L: mid-wave = smoke only; **ONE** enhanced full stress at **L8** (`fully_qualified=true`, no `SKIP_ZAP`). Cite tip-pin artifacts only. Next-rev template: [`PATCH_CYCLE.md`](../docs/operations/PATCH_CYCLE.md). Skill [`openfdd-stress-closeout`](skills/openfdd-stress-closeout/SKILL.md).
51. **Demo freshness (buyer UX — Wave H + O7):** Dialing into Overview / FDD / RCx / Inspect must not require mashing **Run all rules** or **Update analytics** on every visit or every **building switch**. Serve **last-good** / per-`buildingId` cached Overview+health **under the hood**; soft-refresh only when needed (`RULES_UPDATED`, existing explicit refresh). Prefer durable `GET /api/fdd/results` over live DF fan-out on `?site=` change. **Do not** add new explanatory banners/badges about caching, agents, or “optimization.” Manual Run remains for deliberate recompute. Empty matrices/`—` while `ingest_ok` climbs or historian has points is a **P0 bug**.
52. **SPA copy discipline (quiet UI):** Product UI stays quiet. **No froofy grey
   captions** under section titles — the menu/matrix/plot **name is enough**.
   Prefer one heading per table/matrix. Keep blue `InlineAlert` for actionable
   empty/error states only (e.g. no site locked → run FDD from Lab). Agent
   rationale belongs in `openfdd_agent_spec` / PR bodies / GitHub `AGENTS.md` —
   never in-app tip strips, session-restore tutorials, or AI-agent help panels.
   Hide `tenant:legacy`. Left rail: Sites · CSV Upload · Units · Lab + Sign in/out
   by revision. Skill: [`openfdd-react-spa`](skills/openfdd-react-spa/SKILL.md).
   Wave O7 plan: `.cursor/plans/wave_o7_overview_site_cache_ce235993.plan.md`.
52c. **Nav nesting:** Results by Category under **Data Model** (`?view=results`);
   Sites inventory under **Operations** (`?view=sites`) with MQTT Test Client /
   AFDD Config. Do not re-promote them as top-level main section radios.
52e. **M&V / metering UI (Wave S):** Change-point, savings, and IPMVP-style charts belong on **Metering** section radios (or one new left radio) — not Overview Plotly. Product data = DataFusion `/api/analytics/*` (or dedicated M&V SQL). PyPI/`camber-toolkit` oracle is stress/agent only. Keep [`openfdd-react-spa`](skills/openfdd-react-spa/SKILL.md) rule 7b current when adding radios.
52b. **Hub admin console (Wave O8):** Selling shared Railway MQTTS+CSV accounts requires hub_admin **user/tenant/data CRUD** in the SPA (quiet django-like). File `control_plane/*.json` is the storage backend until Stage C IdP — not a substitute for missing UI. Non-admin must stay 403 on admin APIs; gate 31 family proves isolation. Plan: `.cursor/plans/wave_o8_hub_admin_console_ce235993.plan.md`. Do **not** claim admin UI exists when only Sites dataset delete is present.
52c. **Site data-model export (Wave O9):** Data Model export is **entire active site** only — no device/point export picker. Equipment selector is for mapping **edits**. Server must ACL mapping + data-model JSON + session/fault configs so non-admin cannot read foreign buildings. Plan: `.cursor/plans/wave_o9_site_datamodel_export_acl_ce235993.plan.md`. Stress with gate 31/34 pairwise tenants.
52d. **ACME ALL HVAC health MQTT (Wave O10):** Poll/publish **300 s** fixed; health-roles only (few sensors, most outputs, key setpoints). Cover **all** HVAC from site_scan (JCI VAV imperial °F, Trane VAV metric °C, RTU, HW, needed TEC/Tracer) — not eGauge floods. rusty-* tip ([bacnet](https://github.com/jscott3201/rusty-bacnet/releases) / [haystack](https://github.com/jscott3201/rusty-haystack/releases) / [modbus](https://github.com/jscott3201/rusty-modbus)) after **Mint compile + BACnet scrape**; GHCR then **ACME last**. Plan: `.cursor/plans/wave_o10_acme_full_hvac_health_mqtt_ce235993.plan.md`. Do not claim whole-HVAC streaming when data model is still `rtu_01`/`oa_t` only.
53. **Multi-site chart bar:** Lakeside (Creekside → `LAKESIDE_ES`), `BUILDING_100`, `BUILDING_50` (when package present), and MQTT `bldg2` must show **visible charts/data** after Wave H — Inspect + ≥1 FDD series + ≥1 RCx preset where applicable. B50 missing package → honest DEFERRED in BUG_REPORT with obtain path, not silent skip. Railway hub: **0 failed/crashed** central/mqtt/web; fieldbus up; MQTT ingest climbing.
54. **MQTT = CSV data model:** MQTTS historian paths use the same `history/building_id=<site>/…` shape as packages. Inspect must pick MQTT equipment (not CSV-only). Roles normalize to columns (`zone_t`, etc.). RCx/FDD plots share the CSV codepath.
55. **Keep this spec current:** any PR that changes demo freshness, site catalog scoping, Inspect/MQTT plots, Overview tables, Data Model export, Lakeside/FDD planning, plot date-span defaults, Railway closeout workflow, **Wave L tenant/Parquet isolation**, **Kali O2c/P2c pre-auth / MT ACL / CSP/`security.txt`**, **security harness (gates 25/25b/26)**, or agent tooling (Railway CLI / GHCR / MCP) updates this file + [`SESSION_LOG.md`](SESSION_LOG.md) + relevant skills (`openfdd-mt-security`, `openfdd-railway-cli`, `openfdd-stress-closeout`) in the same train. After every tip merge: bump **Current ops pin** here + railway-cli skill + root `AGENTS.md` (tip-in-flight → OPS PINNED only after FQ MEGA).
56. **Basic app functionality (Wave I — non-negotiable):** Selecting a packaged or MQTT site must not explode FDD (`read_csv` / planning errors). Overview main-tab tables (especially bottom devices table) must **never** be filtered differently for MQTT vs CSV — same chrome; empty = honest zero/shell. Data Model must offer **Export data model JSON** that works for MQTT and CSV. Do not close Wave I on stress green if these SPA/API checks fail.
57. **Default plot span:** Overview / Inspect / RCx defaults must cover the historian’s available `first_timestamp`→`last_timestamp` (even downsample to `max_points`). Newest-only `LIMIT` that hides earlier months (e.g. B100 July-only) is a **P0 MEGA**.
58. **MQTT dual OAT:** Live fieldbus Open-Meteo must publish into historian as concurrent BAS `oa_t` + web `web_oa_t` (catalog dual-publish on railway loopback). Empty `bas-vs-web-oat` on bldg2 while `/weather` is live is a **P0 MEGA**, not DEFERRED demo fluff.
59. **Wave I stress:** Mid-wave = smoke only. **ONE** `run_railway_hub_stress.sh` at master I7 after enhanced gates (I6). No duplicate full stresses between children unless a mega cannot be proven without a new tip pin.
60. **Wave L/N multi-tenant:** `OPENFDD_MULTI_TENANT` defaults OFF. When ON (Wave N Railway authorized early Stage C): JWT `tenant_ids` + control-plane `building_ids`; `/api/tenants` list+select; historian_prefix `tenants/{tid}`. **Data-path ACL (3.5.10+):** FDD equipment/results/series/run, CSV package mapping/buildings, and analytics must call `TenantContext::allow_building` and return **403** for foreign buildings (gate 31 probes mapping+series). Do not treat list/select-only ACL as sufficient. Parquet isolation remains path-scoped DF providers. ADR: [`docs/architecture/ADR_multi_client_shared_hosting.md`](../docs/architecture/ADR_multi_client_shared_hosting.md). Soft-OPEN: IdP/MFA/SKU. **Wave U V7 (3.5.41+):** dual-read prefers `tenants/{tid}/…` when present, else hub-root; additive migrate helper `scripts/ops/wave_u_v7_tenant_path_migrate.sh`.
60b. **Kali O2c / Wave P2c pre-auth (2026-09-15 verified):** When `OPENFDD_JWT_SECRET` is set, never serve detailed tenant/building rosters or topology via unauthenticated routes. `/api/tenants`, `/api/capabilities`, `/api/health/stack`, `/api/building/snapshot`, `/api/dashboard/summary` are **JWT-protected** — unauth → **401**. Never fall back to `dev_anonymous()` **Admin** for those handlers. Public lean readiness = `/api/health` (+ `/api/auth/status` / login). Web: CSP must allow Google Fonts; HSTS when HTTPS/`X-Forwarded-Proto=https`; `/.well-known/security.txt` must not SPA-fallback to HTML. Tests: `services/central/tests/preauth_disclosure.rs` · gate 34. Skill: [`openfdd-mt-security`](skills/openfdd-mt-security/SKILL.md). Plans: Wave O § O2c · Wave P § P2c. Kali owns next staging cross-tenant + MQTT ACL pentest; Mint does not ActiveScan OT.
60c. **Wave P residual:** Ordered tips ≤3 GHCR; docs+SPA local batch then security tip; **no Railway re-pin while Kali owns the hub** unless operator OK. Plan: `.cursor/plans/wave_p_residual_stress_gh_tidy_ce235993.plan.md`.
60d. **Security Python harness (3.5.29+):** `scripts/security/openfdd_security_probe.py` + gates **25** / **25b** / **26** in Railway stress. Offline evaluator tests: `tests/security/`. Default dry-run is **BLOCKED** (not PASS); live execute needs `OPENFDD_SECURITY_EXECUTE=1` in an authorized window. Gate **26** is N/A unless `OPENFDD_SECURITY_MQTT_ACL=1` with isolated broker fixtures. Continuity ≠ ACL. Brief: `.cursor/agents/openfdd-security-python-harness.md` · contract: `.cursor/plans/security_stress_integration_audit.md`.
61. **Agent tooling map (use the right tool):** GHCR Publish / tip gate = GitHub Actions + `scripts/check_ghcr_tip_stack.sh`. Hub re-pin / backup / ssh health = **Railway CLI** (rule 39). Local lab stack = `openfdd_stack_*.sh` (HTTP firewall only). FDD/analytics for AI hosts = **`openfdd-mcp`** + agent JWT — not Railway MCP. Stress = `scripts/nightly-ot-bench/`. Typst RCx PDFs = [`skills/openfdd-typst-rcx-report`](skills/openfdd-typst-rcx-report/SKILL.md). BUILDING_100 Overview mirror stays the legacy kit. Offline single-system or building-folder AHU packs use `open-fdd-anomaly report` (`open_fdd.reporting.single_system_typst`) and must not overwrite that kit. That pack's PDF is month-filtered (`--month YYYY-MM`), uses PyPI Plotly helpers only (no histograms, no anomaly day zooms), and its economizer scatter is `economizer_delta_scatter` with viewport `bottom_left`: **x = OAT − RAT** (`delta_or_f`), **y = MAT − RAT** (`delta_mr_f`), via `build_economizer_delta_points`. Do not plot OAT−MAT vs RAT−MAT. Web OAT comes from a mapped column, `--web-oat` CSV, or `--web-oat fetch`. Hygiene every merge: **0 open PRs**, remote **only `master`**, tip Actions green (ignore cancelled docs-tip Publish noise).

**Current ops pin (2026-09-19):** **FQ OPS PINNED** VERSION **3.5.31** · tip **`sha-7b81eb8`** · stress **`reports/nightly-ot-bench_20260919T195100Z/`** **`fully_qualified=true`** (gates **19**+**35**+**25**/**25b**, edge **`vim-1`**) — Wave S1. **Hub smoke tip (no FQ claim):** **3.5.33** / **`sha-3cd3745`** (#954 DM IRI) · backup **`20260919T231221Z`** · health **`3.5.33+3cd37451220a`**. Wave S Soft-OPEN: S3 PyPI M&V · S4 SQL/UI/FQ · S5 DM-04..10/ECM. Prior: **`sha-f727a55`** / **3.5.29**; Soft Tip B **`sha-4a5c11e`** / **3.5.28**; Wave N **`sha-9072e0b`** / **3.5.10**. Low-RAM always (rule 0). Tracker: [`BUG_REPORT_WAVE_P.md`](../docs/operations/BUG_REPORT_WAVE_P.md).

---

## Authority order

1. Root [`AGENTS.md`](../AGENTS.md)
2. Machine manifests: [`ownership.yaml`](ownership.yaml), [`capabilities.yaml`](../docs/migration/react-rust/capabilities.yaml)
3. Current phase docs under [`tools/open-fdd-vibe21-production/`](../tools/open-fdd-vibe21-production/)
4. Generated OpenAPI / MCP / rule catalogs
5. Workflow guides and examples

Nested instructions may specialize but never contradict a higher authority.

## Bootstrap reading order

1. [`../AGENTS.md`](../AGENTS.md)
2. This file
3. [`../docs/agent/PACKAGE_AUTHORING.md`](../docs/agent/PACKAGE_AUTHORING.md)
4. [`../docs/modeling/`](../docs/modeling/) when packaging / HP / readiness context matters
5. [`ARCHITECTURE.md`](ARCHITECTURE.md) + [`ownership.yaml`](ownership.yaml)
6. Deploy bootstrap: [`PATCH_CYCLE.md`](../docs/operations/PATCH_CYCLE.md) + [`STRESS_CLOSEOUT.md`](../docs/operations/STRESS_CLOSEOUT.md) + [`RAILWAY_DEPLOYMENT.md`](../docs/operations/RAILWAY_DEPLOYMENT.md) + [`LOCAL_DEPLOYMENT.md`](../docs/operations/LOCAL_DEPLOYMENT.md) (x86 field only)
7. [`BUILD_CHECKPOINTS.md`](BUILD_CHECKPOINTS.md)
8. [`tools/open-fdd-vibe21-production/prompts/MASTER_PRODUCTION_LOOP.md`](../tools/open-fdd-vibe21-production/prompts/MASTER_PRODUCTION_LOOP.md)
9. [`MILESTONE_A.md`](MILESTONE_A.md) if executing Milestone A
10. [`PR_PROTOCOL.md`](PR_PROTOCOL.md) before opening a PR
11. [`docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md`](../docs/operations/BUG_REPORT_OT_MODBUS_HAYSTACK.md) during ops patch cycles
12. Matching skill
13. Cookbooks under `docs/rules/cookbook/` + [`docs/RULE_DISPLAY_NAMES.md`](docs/RULE_DISPLAY_NAMES.md) when touching rule labels in UI

---

## Skills

| Skill | Use when |
| --- | --- |
| [`openfdd-architecture`](skills/openfdd-architecture/SKILL.md) | Ownership / engine boundaries |
| [`openfdd-react-spa`](skills/openfdd-react-spa/SKILL.md) | Product SPA (`frontend/web`) |
| [`openfdd-package-mapping`](skills/openfdd-package-mapping/SKILL.md) | Zip / `equipType` / Haystack→SQL / empty charts |
| [`openfdd-rcx-fdd-plot-poll`](skills/openfdd-rcx-fdd-plot-poll/SKILL.md) | Blank RCx/FDD → roles → fieldbus poll gaps (no TEC / Modbus gateway) |
| [`openfdd-mt-security`](skills/openfdd-mt-security/SKILL.md) | Pre-auth disclosure, tenant ACL, Kali disposition, CSP/`security.txt` |
| [`openfdd-sql-fdd`](skills/openfdd-sql-fdd/SKILL.md) | DataFusion SQL rules |
| [`openfdd-pypi-oracle`](skills/openfdd-pypi-oracle/SKILL.md) | PyPI pandas oracle packaging |
| [`openfdd-cookbook-parity`](skills/openfdd-cookbook-parity/SKILL.md) | Dual cookbook honesty |
| [`openfdd-railway-cli`](skills/openfdd-railway-cli/SKILL.md) | Railway CLI auth / backup / tip re-pin / fieldbus up |
| [`openfdd-stack-ghcr`](skills/openfdd-stack-ghcr/SKILL.md) | GHCR pull / recreate / local firewall hub |
| [`openfdd-stress-closeout`](skills/openfdd-stress-closeout/SKILL.md) | Stress LAST / Railway CSV + ZAP / BUG_REPORT |
| [`openfdd-ecm-engineering`](skills/openfdd-ecm-engineering/SKILL.md) | ECM math library |
| [`openfdd-typst-rcx-report`](skills/openfdd-typst-rcx-report/SKILL.md) | VAV AHU Typst RCx lab PDF (Overview mirror) plus offline `open-fdd-anomaly report` |
| [`openfdd-milestone-a-pr`](skills/openfdd-milestone-a-pr/SKILL.md) | Milestone A PR loop |
| [`data-modeling`](skills/data-modeling/SKILL.md) | Package layout, utilities/, equipType, export bundle |

### Equipment typing contract

Package `equipType` / `equipment_type` stamps are persisted and preferred over id heuristics. Opaque ids are valid (`AC_1` + `equipType: ahu`). Never solve a site-specific naming problem by hard-coding a vendor, campus, or building into product code.

**ZONE control** = fan-coil (`fcu`, valve PID hunting) **or** standalone DDC zone monitor — both get Overview schedule/comfort + zone sensor fault equations (`equipType: zone_other` / `fcu` / `zone`). **Unit ventilator** = CV AHU (`unitVentilator` / `uv` / `cv_ahu`) — same as constant-volume AHU, **not** ZONE. Detail: [`docs/modeling/zone-terminals.md`](../docs/modeling/zone-terminals.md) · [`DATA_CONTRACT.md`](DATA_CONTRACT.md).
