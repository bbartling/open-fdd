---
name: "Wave-X 3.6.1+ completion — DF purge, 77-case prove, broker-free OT"
overview: "AUTHORIZED completion after #1232 MERGED. FORBIDDEN: DF/Arrow/Parquet/Feather + dual-write. Timescale SQL + all 77 warehouse rules. Lean Plotly (results vs GET /plot). Mimic sparql-playground: POST SPARQL query route → opaque ids → lean Timescale. Broker-free OT; proxy X2b; Railway; Grok mega. Soft-OPEN ≠ FQ."
todos:
  - id: c0-identity
    content: "C0 Identity — origin/master tip 9d128b66 / VERSION 3.6.0; ART; reopen Soft-OPEN claims; issue matrix; private audit read; dirty primary preserved"
    status: completed
  - id: c1-branch-pr
    content: "C1 Follow-up PRs #1233 (3.6.1) + #1234 (3.6.2) from origin/master — never reopen #1232"
    status: completed
  - id: c2-df-purge
    content: "C2 Full DF/Arrow/Parquet product purge — workspace cargo-tree gate; CI/docs/features/CLI gone"
    status: completed
  - id: c3-db-security-proxy
    content: "C3 Shared pools + private security; X2b cloud/OT/field proxy exposure from deployment_route_exposure contract"
    status: completed
  - id: c4-durable-ingest
    content: "C4 Atomic seed/append/remap; commit-before-success; reconnect; MQTT receipt = Timescale commit"
    status: completed
  - id: c5-brokerfree-ot
    content: "C5 PARTIAL — mqtt 8883 Soft-OPEN; gate39/OT BLOCKED; central 8.5GiB pending-delete is UI-only (CLI retry failed)"
    status: pending
  - id: c6-sql-executor-ui
    content: "C6 Soft-OPEN honesty — no fake health score=1.0; lean plots fed; daily AFDD timer stays off"
    status: completed
  - id: c7-77-api-parity
    content: "C7 Soft-OPEN 77/77 product API matrix (warehouse cases + FC13 alias); pandas mask parity residual ≠ FQ"
    status: completed
  - id: c8-image-recipes
    content: "C8 GHCR ships sql/fdd+migrations; Soft-OPEN without bind mounts; DB retention/WAL/restore contracts"
    status: completed
  - id: c9-railway-memory
    content: "C9 DONE Soft-OPEN — Pro eval ART; applied 14/4/1/1 GiB; tip sha-eacdf79/3.6.2; crash timeline + volume restore notes"
    status: completed
  - id: c10-grok-mega
    content: "C10 BLOCKED — 2x --send SENT; Grok ART files NOT_AVAILABLE; interim agent crash/memory notes only"
    status: pending
  - id: c11-issue-closeout
    content: "C11 No issues closed — AC incomplete; #1070 commented Soft-OPEN broker≠gate39"
    status: pending
  - id: c12-lean-plotly
    content: "C12 Lean Plotly for ALL 77 catalog rules — GET /plot per visible rule+equip; catalog roles+SPARQL/point_map; max_points≈1500; Update-rule one SQL; no bulk plots_by_rule"
    status: completed
  - id: c13-sparql-route
    content: "C13 Mimic sparql-playground — POST /api/model/sparql (JSON query) + optional upload; read-only guard; JWT/tenant; SPARQL→opaque id→lean Timescale series; MCP same path"
    status: completed
isProject: true
---

# Wave-X 3.6.1+ completion patch train — 2026-10-13 (double-checked)

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

**Status: SUPERSEDED (2026-10-14) by [post_wave_x_363_softopen_residuals_20261014.plan.md](post_wave_x_363_softopen_residuals_20261014.plan.md).** Done Soft-OPEN on tip **`sha-eacdf79` / 3.6.2** retained as evidence; unfinished work (C5/C10/C11/C12 polish/C13 probes/pandas/X2b/A0–A9) lives in the 3.6.3 residuals plan. Soft-OPEN ≠ FQ.

**Prior status (archived):** Soft-OPEN ≠ FQ. Hub tip **`sha-eacdf79` / 3.6.2+eacdf79cede8**. Residuals: C5 gate39/OT + central 8.5GiB **UI-only**, C10 Grok ART missing after 2× `--send`, C11 no AC closes.

| Fact | Value |
| --- | --- |
| #1232 | **MERGED** → `9d128b66` / 3.6.0 |
| #1233 | **MERGED** → `ad48491f` / **3.6.1** (lean plot, SPARQL, DF purge) |
| #1234 | **MERGED** → `eacdf79` / **3.6.2** (catalog aliases on `/api/fdd/rules`) |
| Master VERSION | **3.6.2** |
| Live hub tip | **`sha-eacdf79` / 3.6.2+eacdf79cede8** (newest-by-created) |
| Dirty primary | `/home/ben/Desktop/open-fdd` — **do not reset**; worktrees `/tmp/open-fdd-wt-*` |
| Railway hub | `gleaming-cooperation` — Pro caps 14/4/1/1 GiB; mqtt 8883 Soft-OPEN broker-up |
| Soft-OPEN evidence | C7 **77/77**; C6 honesty; C9 memory ART; C12/C13; mqtt ACME PEMs restored; gate39 **NOT claimed** |
| ART | `/tmp/openfdd-softopen/3.6.2/` + `~/Documents/openfdd-softopen-art/3.6.2/` |

## Absorbed contracts (mandatory reads)

| Document | Role |
| --- | --- |
| [Completion audit handoff](../agents/wave_x_timescale_completion_audit_20261013.md) | Owner defects + locked intent (source of this train) |
| [Mega acceptance X0–X13](wave_x_timescale_purge_mega_acceptance_20261013.plan.md) | Detailed engineering gates — **execute these**, not smoke |
| [Route/proxy exposure](../agents/deployment_route_exposure_wave_x_20261013.md) | X2b cloud / OT / field-only |
| [Grok mega](../agents/wave_x_grok_mega_acceptance_20261013.md) | Replaces short `/tmp/.../WAVE_X_SOFTOPEN_PROMPT.md` |
| [Parent Wave-X](timescale_sql_warehouse_greenfield_explore_20261012.plan.md) | Historical Soft-OPEN tip |
| [Thin 3.6.1](post_wave_x_361_patch_ghcr_20261012.plan.md) | Superseded for scope |
| [sparql-playground](/home/ben/Desktop/sparql-playground) | Teaching app to **mimic**: `POST /api/sparql` + guard + SPARQL→timeseries_id→store |

Private audits (no public paste): `/home/ben/Documents/Codex/private_audits/openfdd_wave_x_20261013_047fa67/` — read `DATABASE_INGEST_REVIEW.md`, `SQL_CORRECTNESS_REVIEW.md`, `API_SECURITY_PRIVATE.md`, `AUDIT_SUMMARY.md`.

## FORBIDDEN on the product path (no exceptions / no “just in case”)

| Forbidden | Meaning |
| --- | --- |
| **DataFusion** | No crate, feature (`legacy-*`), SessionContext, CLI, CI job, or runtime switch that runs product FDD/analytics on DF |
| **Apache Arrow** (product) | No in-process Arrow batch materialize path for historian/analytics/FDD results |
| **Apache Parquet** (product historian) | No Parquet writer/reader as canonical or co-canonical store |
| **Feather** | Already retired — **do not reintroduce** |
| **Dual-write / dual-read** | No write-both, no “Parquet if Timescale miss”, no sidecar mirror, no migrate-and-keep-both. **Timescale only** |
| **“legacy-OFF is enough”** | Incomplete — DF/Parquet/Arrow product code must be **deleted**, not parked behind flags |

**Still allowed (not product FDD engine):** CSV/JSON/ZIP package I/O, RDF/SPARQL/model, PyPI pandas oracle (test-only), DuckDB offline tests.

**Also forbidden (UI transport):** bulk plot payloads for all rules; full-window historian dumps to the browser; `plots_by_rule` caches for the whole catalog; “first N `point_map` keys” as plot series; Parquet/CSV of the analysis window shipped to Plotly.

## Locked owner intent

1. Production analytics/FDD = **PostgreSQL/Timescale SQL**. Rust: auth, typed ingest, scheduling, admission, API serialization. **Pandas external oracle only** — validates **all 77** through the **actual Rust product API**. DuckDB offline-only. **No Python equations on the request path.**
2. **Fully delete** DataFusion + product Arrow/Parquet/Feather per FORBIDDEN table. Keep CSV/JSON/ZIP, RDF/model, migrate historian data → SQL, PyPI oracle.
3. Generic model/type/role/relationship selection — **no** fixture-id / equipment-name classification.
4. Keep BACnet/Modbus/Haystack drivers + **local direct SQL ingest**; MQTTS edge→cloud supported. **No OT on Railway.**
5. Railway CLI: measured allocation/limits, teardown of **owned temporary** resources, deployment. Count **Timescale + central + broker + web** in memory compares. On **Railway Pro** (hard membership limits): produce an **optimization evaluation** that recommends how to **distribute memory across each app** (timescale / central / mqtt / web) so the hub stays under Pro caps without crash loops — reversible caps only; ask before paid upsizing.
6. **Do not** enable the held daily AFDD timer.
7. Soft-OPEN ≠ FQ. No secrets in prompts/issues.
8. **Worktrees / disposable deletes only under `/tmp`** (`/tmp/open-fdd-wt-*`, ART `/tmp/openfdd-softopen/…`). **Never** create worktrees on Desktop. All open-fdd clones, data backups, seeds, and ART scratch live under `/tmp` (or `~/Documents/openfdd-softopen-art/` for reboot-durable ART only).
9. **Compile locally on this host (bensbench)** for Rust product patches. After each useful build: `cargo clean` / delete `target/` so **no leftover testing Rust binaries** linger. Prefer GHCR images for stack Soft-OPEN once published.
10. **mintbench `.16` (8 GiB) is OFF-LIMITS** — dedicated to another project. Do not soak, compile, or Docker Soft-OPEN there.
11. **Railway hub + ACME + MQTTS:** after GHCR tip publish, deploy/recreate hub (central + mqtt + web; Timescale as required), pin newest-by-created `sha-*`, bring ACME fieldbus → MQTTS pipeline. Fieldbus stays off Railway. Soft-OPEN ≠ FQ.
12. **Tiny rev bumps** (3.6.1 → 3.6.2…) as product patches land; ensure **GHCR refresh** via normal PR → Actions publish; verify with `ghcr_newest_by_created` / tip completeness.
13. **Grok** (updated ≥0.70.2 + xdotool `--send`) runs mega acceptance near closeout; **close GH issues only** when their AC pass with evidence.

## High-priority source findings → required fixes

| Finding | Required change | Maps to |
| --- | --- | --- |
| Image copies old `sql_rules`, omits `sql/fdd` | Ship versioned rules/helpers/migrations; Soft-OPEN **without** checkout bind mounts | C8 |
| Append success without Timescale writes | Scoped txn, durable readback/replay, **commit-before-success** | C4 |
| Full seed deletes samples before validate/COPY | Validate/stage/promote atomically; last-good survives failure | C4 |
| Mapping edits still invoke Parquet ingest | Atomic SQL remapping + model/role consistency | C4 / C2 |
| Boot DB failure permanently disables writer | Managed reconnect/readiness + bounded durable retry | C4 |
| Pools per request; FDD/seed bypass admission | Shared bounded pools, E2E permits, SQL deadlines, reserved ingest | C3 |
| Health `score=1.0`, mixed pivots, count-only | Real scoped SQL; preserve SPA contract | C6 |
| AFDD → retired registry stub / Parquet watermark | One SQL executor; SQL watermark; durable checkpoints | C6 |
| Errors/partial advertise success/freshness | Coherent terminal status; atomic publication; full cohort | C6 |
| Filesystem retention/backup semantics survive | DB-specific storage/WAL/retention/migration/restore | C8 |

## ALL 77 warehouse rules (C7 + C8 + C12 — not optional)

**Source of truth (must ship + prove):**  
`/home/ben/Downloads/OPENFDD_WAREHOUSE_SYNTHETIC_HANDOFF_20261012.zip`  
SHA256 `0597b6d6492750edae2c994ac5d2fcbb26a8a2bd6c122013da5399b94b8b24ec`

Verified inventory in handoff (exact count **77**):
- `open-fdd-warehouse-handoff/cases.json` → **77** cases
- `open-fdd-warehouse-handoff/sql/original_datafusion/*.sql` → **77** rule SQL files
- Plus: `parity.py`, `oracle_catalog.json`, `role_map.json`, `units.json`, `tuning_crosswalk.json`, fixtures/labels, `KNOWN_DIFFERENCES.md`

**Complete `cases.json` rule_id list (all must land in product catalog + `sql/fdd/` + API parity + lean plot roles):**

`AHU-DUCTHI`, `AHU-SATDEV`, `AHU-SIMUL`, `AVG-ZONE-TEMP`, `CHW-1`, `CHW-2`, `CHW-3`, `CHW-4`, `CHW-NOLOAD-1`, `CMD-1`, `CW-APR-1`, `CW-FAN-1`, `CW-OPT-1`, `DMP-1`, `ECON-1`, `ECON-2`, `ECON-3`, `ECON-4`, `ECON-5`, `ECON-6`, `ECON-7`, `FAN-RUNTIME-HOURS`, `FAULT-ELAPSED-HOURS`, `FC1`–`FC15` (incl. FC13), `FCU-CLG-COIL`, `FCU-CO2-DAMPER`, `FCU-DAMPER-POS`, `FCU-DEADBAND`, `FCU-HTG-COIL`, `FCU-MODE-CYCLE`, `FCU-SENSOR-NULL`, `FCU-VALVE-PASS-CLG`, `FCU-VALVE-PASS-HTG`, `HP-1`, `MECH-OAT-1`, `OA-1`, `OAT-METEO`, `PID-HUNT-1`, `RESET-1`, `SCHED-1`, `SCHED-247`, `SV-FLATLINE`, `SV-RANGE`, `SV-RATE`, `SV-SPIKE`, `SV-STALE`, `TRIM-1`, `TRIM-3`, `TRIM-4`, `UTIL-INTERVAL`, `UTIL-MONTHLY`, `VAV-1`–`VAV-7`, `VAV-AHU-LEAVE`, `VAV-REHEAT`, `VLV-1`, `WX-1`, `ZONE-COMFORT-PCT`

**Non-negotiable:**
- Product registry / image must contain **all 77** `.sql` + catalog rows (roles, tuners, equipment_kinds) — not a FC*/ECON* subset.
- C7: pandas oracle vs product API for **all 77** (masks/seconds/goldens). `#1232` `parity_smoke` row counts = **not** parity.
- C12: every catalog rule resolves to a non-empty role list (or explicit override) for lean `GET /plot` — wrong-series / empty dump for any of the 77 is FAIL.
- ≥9 adapter I/O gaps + FC1 + SV-RATE must be fixed with identical effective config — **no** skip / xfail / tolerance widen / erase from catalog.
- Incomplete matrix (anything &lt; 77) = qualification **incomplete**.

## Seeds (lab profiles only)

1. `/home/ben/Downloads/OPENFDD_WAREHOUSE_SYNTHETIC_HANDOFF_20261012.zip` — SHA256 `0597b6d6492750edae2c994ac5d2fcbb26a8a2bd6c122013da5399b94b8b24ec`
2. `/home/ben/Downloads/BUILDING_50_openfdd.zip` — SHA256 `c888be3e1ceeaa028897cb16c285f1447be7140d83b91d03daa9caa9eed3b2ad`

Preserve originals; derive disposable fixtures + manifests. Ordinary bootstrap does **not** auto-load maintainer buildings.

## Broker-free OT + hisRead (C5)

BACnet/Modbus/Haystack commit to local SQL via private ingest **without MQTT**. Large hisRead = resumable bounded history-import (original ts/type/quality/unit). Preview/current-read ≠ persistence. Optional cloud MQTTS is independent and must not block local SQL. Detail: mega plan **X3b**.

## API / proxy (C3 / X2b)

Implement [deployment_route_exposure_wave_x_20261013.md](../agents/deployment_route_exposure_wave_x_20261013.md) before release: method/path classes, cloud vs OT vs field-only, JWT/role/tenant, private driver/local-ingest/DB, TLS/local-CA, forwarded headers, body/rate/time/error limits.

## Agent kickoff

```text
AUTHORIZED: complete post_wave_x_361_completion_patch_20261013.plan.md end-to-end.

Read: this plan → wave_x_timescale_completion_audit_20261013.md
→ wave_x_timescale_purge_mega_acceptance_20261013.plan.md (X0–X13)
→ deployment_route_exposure_wave_x_20261013.md
→ wave_x_grok_mega_acceptance_20261013.md
→ private audit dir (no public secrets)

#1232 MERGED (9d128b66 / 047fa67). Follow-up PR from origin/master only.
VERSION on master = 3.6.0 → bump 3.6.1+ when product changes justify.
Worktree /tmp/open-fdd-wt-wave-x-361-*; ART /tmp/openfdd-softopen/<ver>/.
Dirty Desktop primary preserved. No dual-write. Soft-OPEN ≠ FQ.
Do not enable daily AFDD timer. Railway destructive/cost → ask if unapproved.
Replace short Grok paste with mega acceptance; close only proven issues.
Execute C0→C13 (lean Plotly + sparql-playground-style SPARQL query route); update todos as you go.
```

---

## C0 — Identity / reopen Soft-OPEN

- [ ] Fetch; confirm tip `origin/master` = Wave-X merge.
- [ ] Resolve VERSION / GHCR newest-by-created (may lag publication).
- [ ] ART `/tmp/openfdd-softopen/<ver>/` + candidate manifest.
- [ ] Reopen unsupported claims: seed-smoke-as-parity, legacy-OFF-as-purge, FC1/SV-RATE, append-without-write, image missing `sql/fdd`, fake health, AFDD Parquet watermark, hisRead-without-SQL.
- [ ] Live issue matrix (#1127 CLOSED at audit — re-verify closure evidence).
- [ ] Read private audit files (redacted notes only in ART).

**Test:** `STATUS.json` with tip SHA, VERSION, defect list; Soft-OPEN ≠ FQ.

---

## C1 — Follow-up PR

- [ ] `/tmp/open-fdd-wt-wave-x-361-completion` from `origin/master`.
- [ ] Justified VERSION bump (**3.6.1+**).
- [ ] PR → master; never reopen #1232.

**Test:** PR URL; Desktop dirt untouched.

---

## C2 — Full DataFusion / Parquet / Arrow purge

- [ ] Delete `fdd_sql`, `historian_datafusion`, DF CLI/bench, `legacy-*`, DF CI/docs revival paths.
- [ ] Remove product Arrow/Parquet as callers move to SQL.
- [ ] Workspace-wide `cargo tree` gate: no `datafusion` / `fdd_sql`.

**Test:** CI fails on DF reintroduction.

---

## C3 — Pools, security, proxy

- [ ] Shared pools; reserved ingest; SQL deadlines/cancellation.
- [ ] Private security fixes (no public repro).
- [ ] X2b profiles from exposure contract.

**Test:** exposure manifest + automated tests; JWT before SQL.

---

## C4 — Durable ingest

- [ ] Atomic seed; append commit-before-success; SQL remap; reconnect.
- [ ] MQTT: receipt proves Timescale commit (not PUBACK alone).

**Test:** mid-fail preserves last-good; append readback exact.

---

## C5 — Broker-free OT + hisRead

- [ ] BACnet/Modbus/Haystack → private ingest → SQL without broker.
- [ ] Resumable bounded hisRead job; optional MQTTS independent.

**Test:** multi-chunk history import digest; broker-down local SQL still commits.

---

## C6 — SQL executor + SPA (metadata + honesty; plots → C12)

- [ ] One executor for run-now/AFDD/preview/detail; SQL watermark.
- [ ] Real Overview/RCx/FDD/Inspect **status/hours** (metadata); coherent errors; **no daily AFDD timer**.
- [ ] Do **not** embed full series in run-all / results — lean charts are **C12**.

**Test:** browser Soft-OPEN status/matrices honest; no fake `score=1.0` / empty success; no multi-MB results blobs.

---

## C7 — ALL 77-case product-API parity (warehouse ZIP)

- [ ] Unpack `OPENFDD_WAREHOUSE_SYNTHETIC_HANDOFF_20261012.zip`; verify SHA256; sync **all 77** SQL + `cases.json` + `role_map` / units / tuners into product `sql/fdd/` + registry.
- [ ] Integrate handoff `parity.py` + fixtures/labels (not `parity_smoke`).
- [ ] Run **all 77** through Rust import/run/detail on real Timescale vs pandas oracle.
- [ ] Fix FC1, SV-RATE, and ≥9 adapter gaps; ART = **77-row** matrix with pass/fail per `rule_id`.

**Test:** `wc` / catalog count = 77; ART matrix length = 77; any missing id = FAIL.

---

## C8 — Image / recipes / DB lifecycle

- [ ] Image contains `sql/fdd` + migrations; Soft-OPEN without bind mounts.
- [ ] DB retention/WAL/restore contracts replace filesystem Parquet semantics.

**Test:** immutable image Soft-OPEN; migrate/restore documented.

---

## C9 — Railway Pro memory distribution + stability

**Membership constraint:** Railway **Pro** plan — finite shared RAM/CPU across the hub. Crashes / restart notifications during Soft-OPEN are a first-class signal (OOM, proxy 502, deploy loops), not noise.

### Per-app allocation evaluation (required Soft-OPEN deliverable)

Measure and recommend a **memory split** for each service under Pro limits. Publish ART table + rationale (no secrets):

| Service | Role | Measure | Recommend | Notes |
| --- | --- | --- | --- | --- |
| `openfdd-timescale` | PGDATA + FDD SQL | RSS / cgroup / Railway metrics | GiB / share % | WAL + working set for BUILDING_50; never starve |
| `openfdd-central-cQ-F` | API + SQL FDD + ingest | `/api/health` `memory_budget` + cgroup | GiB / share % | Cap query/admission; avoid seed floods that OOM |
| `openfdd-mqtt` | MQTTS broker + certs | RSS | GiB / share % | Small; volume for certs |
| `openfdd-web` | nginx + SPA | RSS | GiB / share % | Smallest; do not over-allocate |

Also record: current Railway memory/CPU settings per service, hard vs soft limits, observed crash/restart timeline, and whether detached volumes amplify restart pain.

### Checklist

- [x] Railway CLI discover/measure current per-service memory/CPU (Pro-safe).
- [x] Write **Pro memory distribution eval** ART (`C9_RAILWAY_PRO_MEMORY_EVAL.md`) with recommended split + apply reversible caps.
- [x] Crash/OOM/502 restart timeline in ART; Grok documents flaps (C10) — agent timeline done; Grok ART still AWAITING.
- [x] Tear down **owned temps only**; preserve volumes/broker continuity.
- [ ] Re-attach `openfdd-central-cq-f-volume` → `/workspace` and `openfdd-mqtt-volume` → `/mosquitto/certs` when READY. *(mqtt Soft-OPEN via restored vol; central 8.5GiB **UI-only** — see `CENTRAL_VOLUME_UI_ONLY.md`)*
- [x] Re-pin hub to newest GHCR `sha-*` (3.6.2+) after Publish; verify `/api/health` version.
- [x] Ask before unapproved destructive/cost or paid plan upsizing.
- [ ] Compare to DF ART only when fixtures match — else `NOT_COMPARABLE`.

**Test:** redacted resource ART + applied reversible caps; hub stable enough for Soft-OPEN probes; temps cleaned. Soft-OPEN ≠ FQ.

---

## C10 — Grok mega

- [x] Populate candidate ID in Soft-OPEN prompt (`sha-eacdf79` / 3.6.2) + crash/memory instructions.
- [x] Kickoff `--send` ×2 (`KICKOFF_RESULT*.txt`).
- [ ] Grok ART `RAILWAY_CRASH_MEMORY_NOTES.md` + `SOFTOPEN_MATRIX.md` — **NOT_AVAILABLE** after wait; interim `AGENT_SOFTOPEN_CRASH_MEMORY_NOTES.md` only.
- [x] Durable archive copy to `~/Documents/openfdd-softopen-art/3.6.2/`.

**Test:** SUMMARY PASS/FAIL/BLOCKED/NOT_RUN; Soft-OPEN ≠ FQ. **C10 BLOCKED on Grok results.**

---

## C11 — Issue closeout + tidy

- [x] Close only AC-proven issues — **none closed** this Soft-OPEN (gate39/#1070 incomplete; #1123/#1004/#1168 open).
- [x] #1070 Soft-OPEN broker comment (≠ gate39 close).
- [ ] Sync BUG_REPORT / MILESTONES / agent_spec.
- [ ] GH tidy.

**Test:** issue→criterion→artifact matrix in ART.

---

## C12 — Lean FDD/RCx Plotly data plane (transport + scoping)

**Speed work is transport and scoping — not a new rule engine.** Keep the **full 77-rule** warehouse from the handoff ZIP + Timescale + catalog (every id listed above). SPARQL / Haystack RDF (or SPARQL-fed `point_map`) remains the semantic path from role → opaque timeseries id. Do **not** invent pandas-in-UI or dump whole AHU `point_map` into Plotly.

### Hard product rules

1. **No massive chart requests.** Forbidden: plot payloads for every rule in one `/results`; full historian windows (10k+ pts × many series) to the browser; rebuild all Plotly figures on category change; embed plot series in “run all” by default.
2. **One visible chart = one lean request.**  
   `GET /api/fdd/plot?site_id&rule_id&equipment_id&window_start&window_end&max_points=1500`  
   Target: **hundreds of KB**, not tens of MB. Default `max_points≈1500` (hard cap ~5000). Server downsamples evenly (keep first/last).
3. **Results / status = metadata only.** `GET /api/fdd/results` → `status`, `fault_hours`, `equipment_id`, window, timestamps — **no** `series`, **no** Plotly traces, **no** raw samples.
4. **Plot series = catalog roles only** (`required_roles` ∪ limited `optional_roles`). Cap ~**6** series. Map SQL cols → Haystack/`openfdd_key` via role map + equip-scoped `point_map` (site-wide only for weather/web OAT). Missing roles → empty series + clear `note` — **never** alphabetically dump unrelated tags. Special cases: OAT-METEO = equip OAT **and** web/meteo OAT (never duct-static fallback).
5. **Equipment scope.** Selected `equipment_id` only — do not mash every AHU/zone into one chart.

### Identity chain (SPARQL → Timescale)

```text
SPARQL (or SPARQL-fed point_map): site → equip → (role → timeseries_id / openfdd_key)
Catalog: rule_id → required_roles ∪ optional_roles
Map:     SQL col → role → openfdd_key(s) for that equip
Timescale: SELECT only those keys, windowed + downsampled (read cap e.g. 8k → max_points)
```

Graph / catalog is the **only** path from a point to chart data — no `ORDER BY openfdd_key LIMIT 6` as “what to plot.”

### React contract (FDD Plots + RCx/Overview Plotly)

| User action | Network |
| --- | --- |
| Open FDD / change category | Catalog + metadata results only |
| Select / flip rule or equipment | **Abort** prior plot; `GET …/plot` for that pair; `Plotly.newPlot` (purge stale axes) |
| Change analysis window | Re-fetch **that** plot only |
| Update rule / retune | `POST /api/fdd/run` for **that rule only** + tuners; refresh metadata + **one** plot |
| Run all (Overview) | Persist status/hours once; **no** plots for all rules |

Checklist:
- [ ] Remove client `plots_by_rule` (or equivalent) all-rules memory cache
- [ ] `useEffect` deps: `siteId`, `ruleId`, `equipmentId`, window → **one** plot load
- [ ] Chart-local busy: “Loading plot for {equipment}…”
- [ ] Plotly responsive; stacked unit-family lanes preferred
- [ ] Show server `note` when series missing
- [ ] Each RCx preset = its own lean series/plot endpoint — no full-building “just in case”

### Backend `build_rule_plot` (Timescale)

1. Resolve roles from warehouse catalog for `rule_id`.
2. Resolve each role → `openfdd_key` via `point_map` (equip-scoped; weather site-wide when required).
3. `SELECT` those keys only, window-bounded, read limit then downsample to `max_points`.
4. Return e.g.:
```json
{
  "rule_id": "FC1",
  "site_id": "...",
  "equipment_id": "AHU_1",
  "series": { "duct-static-pressure": { "ts": [], "y": [] } },
  "confirmed_fault": { "ts": [], "y": [] },
  "fault_hours": 1.0,
  "point_count": 4500,
  "max_points": 1500,
  "note": "Downsampled to ≤1500 pts/series for UI."
}
```
5. Never attach to bulk results unless debug `rebuild_plots=true`.

Unit tests:
- [ ] Unknown/missing catalog rule → empty series, **no** point_map LIMIT-N fallback
- [ ] OAT-METEO / weather parity does **not** return duct-static
- [ ] Downsample respects `max_points` and keeps endpoints
- [ ] **All 77** catalog rules have non-empty role list (or explicit override) — assert against handoff `cases.json` ids

### Update-rule tuners (Lab contract)

1. Catalog exposes `params[]`: key/label/default/min/max/step/unit (`confirm_min`, thresholds, …).
2. UI seeds from catalog; sliders bind local state.
3. `POST /api/fdd/run` with `rule_ids: [R]`, `params_by_rule`, `run_all: false`, window — one SQL render → one result row → metadata (+ client `GET /plot`).
4. UI `confirm_min` → SQL seconds. Snake_case catalog keys only.
5. **Do not** send giant multi-rule replot with tuner updates.

### Out of scope / anti-patterns

- Cache all plots in the SPA  
- Return Parquet/CSV of full window to browser  
- Plot unrelated points because `point_map` sorted alphabetically  
- Change SQL rule physics — only transport, scoping, downsample, API/UI split  

### C12 acceptance

- [ ] Network: flipping FDD rules never multi-MB; plot calls typically ≪ 1 MB (worst ~1–2 MB)
- [ ] Correctness: plotted series match catalog roles for **all** rules
- [ ] Tuners: Update rule → SQL placeholders → status + one chart
- [ ] Tests: role resolution, downsample caps, no bulk plots in results
- [ ] UX: chart swaps quickly; axes don’t linger from previous rule

**Test:** DevTools network + memory Soft-OPEN on BUILDING_50; ART screenshots + payload size log.

---

## C13 — SPARQL query route (mimic sparql-playground)

**Reference:** `/home/ben/Desktop/sparql-playground` — `POST /api/sparql` (`{"query": "…"}`), optional `POST /api/sparql/upload` for `.rq`, read-only guard (reject UPDATE/LOAD/SERVICE/FROM), timeout + row cap, then opaque `timeseries_id` → store read. See its `AGENTS.md` HTTP surface + `src/brickts/api/routers/sparql.py` + `graph/sparql_guard.py`.

Open-FDD already documents/advertises model SPARQL in places but product central historically lacked a complete playground-style pass-a-query route (or only predefined templates). **This train requires a real, JWT-scoped query endpoint on central** that agents/UI/MCP use — same service, package TTL / Haystack RDF dataset (not a separate legacy edge prototype).

### Required routes (product central)

| Method | Path | Behavior |
| --- | --- | --- |
| `POST` | `/api/model/sparql` or `/api/model/sparql/query` | Body `{"query": "<SPARQL SELECT|ASK>"}` → `{ results, meta }` (JSON bindings). Alias both if needed for MCP compatibility |
| `POST` | `/api/model/sparql/upload` (optional) | UTF-8 `.rq` / `.txt` upload → same runner (≤200KiB) |
| `GET` | `/api/model/sparql/predefined` | Curated catalog (keep); **not** a substitute for free-form SELECT |
| `GET` | `/api/model/ttl` (if not already) | Download Turtle for site/building model |

Align with [deployment_route_exposure](../agents/deployment_route_exposure_wave_x_20261013.md): authenticated own-scope; bounded algebra; no unbounded SERVICE/network/UPDATE.

### Guard + ops (copy playground contract)

- [ ] Read-only: allow SELECT/ASK only; reject UPDATE, DELETE, INSERT, LOAD, CLEAR, CREATE, DROP, SERVICE, FROM NAMED abuse per guard
- [ ] Timeout + max rows + concurrency semaphore
- [ ] JWT + tenant/building ownership before graph access; dataset = package/site model for that scope
- [ ] Parameterized / safe result serialization; no secrets in RDF or logs
- [ ] MCP `openfdd_model_sparql` hits **this** central route (fail closed if unavailable — do not claim success)

### How it feeds C12 lean plots

```text
POST /api/model/sparql  →  role / equip / timeseries_id (opaque)
GET  /api/fdd/plot|series → Timescale samples for those ids only (max_points)
```

Do **not** bypass SPARQL/catalog by `SELECT * FROM sample WHERE equipment=…` for charts. Graph (or SPARQL-fed `point_map`) is the only path from semantic point → historian id.

### C13 acceptance

- [ ] `curl` JWT `POST /api/model/sparql` with a SELECT returns bindings; bad/mutating query → 400
- [ ] Lesson-style query (equip → points → timeseries ids) works on BUILDING_50 / lab package RDF
- [ ] Upload `.rq` path works or documented as deferred with JSON-only shipping
- [ ] Plot path uses resolved ids (C12); MCP catalog + execute Soft-OPEN
- [ ] X2b: route in exposure manifest; public anonymous SPARQL denied

**Test:** ART with sample query request/response (redacted); unit tests for guard + tenant scope.

---

## Train loop

```text
audit defect / lean-plot / SPARQL gap → patch on wave-x/3.6.1-completion → VERSION if product
→ PR → Actions (real Timescale integration) → GHCR sha-*
→ newest-by-created → C7/C10/C12/C13 evidence → next
```

## Exit criteria

- [x] Follow-up PR(s) merged; VERSION ≥ 3.6.1 justified (**3.6.2** on master)
- [x] Zero DF product/dependency/feature/CI paths (workspace) — Soft-OPEN; residual Parquet helpers noted ≠ FQ
- [x] **77/77** Soft-OPEN API matrix from warehouse ZIP (pandas mask residual blocks FQ only)
- [ ] Broker-free OT + hisRead Soft-OPEN or hardware BLOCKED (volumes + no OT edge → BLOCKED)
- [ ] X2b proxy profiles tested
- [x] **C12 lean Plotly Soft-OPEN** (metadata results + one plot/request; no multi-MB flips)
- [x] **C13 SPARQL pass-query route** (playground-style) on central
- [x] Railway Pro memory distribution eval applied (14/4/1/1 GiB); owned temps / volume cancel residual
- [ ] Grok mega ART (incl. crash/memory notes); only proven issues closed
- [ ] Soft-OPEN ≠ FQ until mega contract satisfied

## Relationship to #1232 Soft-OPEN

| Claim | This train |
| --- | --- |
| Timescale Soft-OPEN / legacy-OFF | **Incomplete** — reopen for purge + 77 + durability |
| parity_smoke / FC1 hours alone | **Not** 77-case parity |
| Fat `/results` or all-rule Plotly loads | **Forbidden** — C12 lean data plane required |
| Short Grok paste | **Replaced** by mega acceptance (+ lean-plot UX cases) |
| Green CI / new DB | **Not** live memory/UI/FQ |
