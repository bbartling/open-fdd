---
name: "Wave-X 3.6.3 Soft-OPEN residuals — Timescale tip finish"
overview: "AUTHORIZED Soft-OPEN residuals after tip 3.6.2 / sha-eacdf79. Do not re-litigate done DF purge / C7 API smoke / C9 memory / mqtt 8883 / C12–C13 code. Finish C5 OT+volume, C10 Grok ART, C11 issue tidy, C12 SPA polish leftovers, C13 Soft-OPEN probes, pandas mask parity, X2b proxy, A0–A9 acceptance gaps. Tiny rev 3.6.3. Soft-OPEN ≠ FQ."
todos:
  - id: r0-identity
    content: "R0 Identity — tip sha-eacdf79 / 3.6.2 baseline; bump 3.6.3; ART /tmp/openfdd-softopen/3.6.3/; dirty primary preserved; mintbench .16 OFF"
    status: pending
  - id: r1-c5-ot-volume
    content: "R1 C5 residual — gate39/#1070 MQTTS ≥24h; broker-free OT/hisRead when edge available; central 8.5GiB volume UI cancel/reattach"
    status: pending
  - id: r2-c10-grok
    content: "R2 C10 — Grok mega ART (RAILWAY_CRASH_MEMORY_NOTES + SOFTOPEN_MATRIX); prior 2× --send NOT_AVAILABLE; retry with tip 3.6.3"
    status: pending
  - id: r3-c11-issues
    content: "R3 C11 — close only AC-proven; DF-stale closed 2026-10-14 (#1010/#1192); keep live Soft-OPEN residuals"
    status: pending
  - id: r4-c12-polish
    content: "R4 C12 leftovers — SPA plots_by_rule removal, AbortController, window propagation, role-correct series for all 77, network ≪1MB Soft-OPEN"
    status: pending
  - id: r5-c13-probes
    content: "R5 C13 Soft-OPEN probes — JWT POST /api/model/sparql SELECT+guard+tenant; MCP same path; X2b exposure manifest"
    status: pending
  - id: r6-pandas-parity
    content: "R6 pandas mask/seconds/golden parity for all 77 (C7 API smoke ≠ FQ); fix A0 harness + A1 adapters"
    status: pending
  - id: r7-x2b-proxy
    content: "R7 X2b — cloud/OT/field proxy exposure profiles tested per deployment_route_exposure contract"
    status: pending
  - id: r8-a-acceptance
    content: "R8 A2–A9 leftovers — coherent results, analytics SQL, lean plot bounds, typed ingest, AFDD resources, recipes/DB ops, security, agent docs"
    status: pending
  - id: r9-exit
    content: "R9 Exit — Soft-OPEN ≠ FQ until mega contract + residuals satisfied; no FQ claim on green CI alone"
    status: pending
isProject: true
---

# Wave-X 3.6.3 Soft-OPEN residuals — 2026-10-14

> **Historical, superseded by the Timescale-only mandate.** Any Parquet, Arrow, Arrow IPC, Feather, DataFusion, result-cache, or dual-write statement in this document records a past plan or outcome and is not current guidance. Current rule: **Timescale/PostgreSQL only, one canonical telemetry write path, no dual record writing** ([storage mandate](../../openfdd_agent_spec/DATA_CONTRACT.md#storage-mandate-timescalepostgresql-only-mandatory)).

**Status: ACTIVE Soft-OPEN residuals train.** Supersedes [post_wave_x_361_completion_patch_20261013.plan.md](post_wave_x_361_completion_patch_20261013.plan.md) for unfinished work. Soft-OPEN ≠ FQ.

| Fact | Value |
| --- | --- |
| Prior tip | **`sha-eacdf79` / 3.6.2** (#1232/#1233/#1234 merged) |
| This train VERSION | **3.6.3** (tiny rev bump → GHCR via Actions) |
| Dirty primary | `/home/ben/Desktop/open-fdd` — **do not reset**; worktrees `/tmp/open-fdd-wt-*` only |
| Railway hub | `gleaming-cooperation` — Pro 14/4/1/1 GiB Soft-OPEN applied |
| mintbench `.16` | **OFF-LIMITS** |
| Compile | Local bensbench OK; `cargo clean` after useful builds |

## Done Soft-OPEN (do **not** re-litigate as unfinished product DF work)

| Item | Evidence |
| --- | --- |
| #1232 / #1233 / #1234 | Merged; tip was `sha-eacdf79` / 3.6.2 |
| C2 DF product purge | Workspace gate; Timescale SQL product path |
| C7 API matrix | **77/77** Soft-OPEN API smoke (pandas **mask** parity still residual ≠ FQ) |
| C9 Pro memory | Applied **14/4/1/1** GiB; ART eval |
| mqtt Soft-OPEN | **8883** broker-up; ACME PEMs restored |
| C12 / C13 code | Lean `GET /plot` + playground-style SPARQL route **shipped** |
| Grok results | **NOT_AVAILABLE** after 2× `--send` (retry = residual) |
| Central 8.5 GiB volume | **UI-only** cancel/reattach (`CENTRAL_VOLUME_UI_ONLY.md`) |

ART baseline: `~/Documents/openfdd-softopen-art/3.6.2/` (+ disposable `/tmp/openfdd-softopen/3.6.3/` for this train).

## Absorbed contracts (mandatory reads)

| Document | Role |
| --- | --- |
| [361 completion (superseded)](post_wave_x_361_completion_patch_20261013.plan.md) | Prior C0–C13 + unchecked leftovers |
| [362 acceptance followup](../agents/post_wave_x_362_acceptance_followup_20261013.md) | A0–A9 gaps (parity harness, adapters, analytics, ingest, AFDD, recipes, security) |
| [Mega acceptance X0–X13](wave_x_timescale_purge_mega_acceptance_20261013.plan.md) | Engineering gates |
| [Route/proxy exposure](../agents/deployment_route_exposure_wave_x_20261013.md) | X2b cloud / OT / field-only |
| [Grok mega](../agents/wave_x_grok_mega_acceptance_20261013.md) | Browser Soft-OPEN |
| Private audits | `/home/ben/Documents/Codex/private_audits/openfdd_wave_x_20261013_047fa67/` — no public secrets |

## FORBIDDEN (unchanged)

| Forbidden | Meaning |
| --- | --- |
| **DataFusion** | No product DF crate / feature / SessionContext / CLI / CI revival |
| **Arrow / Parquet historian** | No product historian co-canonical store |
| **Feather / dual-write** | Do not reintroduce |
| **“legacy-OFF is enough”** | Purge already required — do not park DF behind flags |
| **mintbench `.16`** | Off-limits |
| **Desktop worktrees** | `/tmp/open-fdd-wt-*` only |
| **FQ claims** | Soft-OPEN ≠ FQ |

**Still allowed:** CSV/JSON/ZIP I/O, RDF/SPARQL/model, PyPI pandas oracle (external), DuckDB offline tests.

## Live Soft-OPEN issues — **keep open**

| Issue | Why open |
| --- | --- |
| **#1070** | gate39 ACME MQTTS ≥24h publish-ledger prove |
| **#1221** / **#1222** | ACME / BUILDING_100 analytics package-map Soft-OPEN |
| **#1130** / **#1132** | Live tip ZAP CSP / HSTS |
| **#1168** | MQTT receipt ledger 50k stall (product-relevant) |
| **#997** / **#1123** / **#1003** / **#1004** | Haystack RDF still applies (Timescale bindings; DF wording noted obsolete) |
| **#1069** | Mapping + MQTT soaks may still apply (tip-stale note; not DF product work) |
| **#1193** | Harness Soft-OPEN defects |

### DF-stale closed 2026-10-14 (this train)

| Issue | Disposition |
| --- | --- |
| **#1010** | Closed — DF DataFrame API companion (#1078); Timescale is product path |
| **#1192** | Closed — DF tip 3.5.69 AFDD run-now residual; re-prove on Timescale if needed |

When unsure if Timescale-relevant: **leave open** + one comment (do not close).

---

## R0 — Identity / 3.6.3 bump

- [ ] `/tmp/open-fdd-wt-wave-x-363-*` from `origin/master` (tip was 3.6.2 / `eacdf79`).
- [ ] Tiny rev **VERSION + Cargo workspace → 3.6.3**; PR → master; GHCR via Actions.
- [ ] ART `/tmp/openfdd-softopen/3.6.3/` + durable copy under `~/Documents/openfdd-softopen-art/3.6.3/`.
- [ ] `cargo clean` after local compiles; mintbench `.16` OFF; Desktop dirt untouched.

**Test:** PR URL; `ghcr_newest_by_created` after publish; Soft-OPEN ≠ FQ.

---

## R1 — C5 residual (OT + volume)

Frontmatter C5 was **PARTIAL**. Unfinished:

- [ ] **#1070 gate39** ≥24h ACME MQTTS publish-ledger prove on tip (broker Soft-OPEN ≠ gate39 close).
- [ ] Broker-free BACnet/Modbus/Haystack → private ingest → SQL when OT edge/hardware available; else honest **BLOCKED**.
- [ ] Resumable bounded hisRead Soft-OPEN or BLOCKED.
- [ ] **Central 8.5 GiB volume:** owner **Railway UI** cancel pending deletion + reattach to `openfdd-central-cQ-F` `/workspace` before schedule (~2026-10-15T12:47Z). CLI Soft-OPEN already failed (`CENTRAL_VOLUME_UI_ONLY.md`).
- [ ] mqtt volume continuity preserved; owned temps only.

**Test:** ART volume attach state; gate39 evidence or NOT_RUN/BLOCKED; Soft-OPEN ≠ FQ.

---

## R2 — C10 Grok mega ART

- [ ] Populate Soft-OPEN prompt with tip **3.6.3** / newest-by-created `sha-*`.
- [ ] Kickoff Grok (`--send`); collect `RAILWAY_CRASH_MEMORY_NOTES.md` + `SOFTOPEN_MATRIX.md`.
- [ ] Prior 3.6.2 results were **NOT_AVAILABLE** after 2× `--send` — do not greenwash; retry or BLOCKED.
- [ ] Browser Soft-OPEN per Grok mega + A9 (BUILDING_100 / ACME where loaded; Overview; FDD/RCx; no 502).

**Test:** SUMMARY PASS/FAIL/BLOCKED/NOT_RUN; Soft-OPEN ≠ FQ.

---

## R3 — C11 issue closeout + tidy

- [x] DF-stale closes **#1010**, **#1192** (2026-10-14) citing tip 3.6.2 / #1233; Soft-OPEN ≠ FQ.
- [ ] Close further issues **only** when AC proven on tip candidate.
- [ ] Keep live Soft-OPEN residuals listed above.
- [ ] Sync BUG_REPORT / MILESTONES / agent_spec where accurate.
- [ ] Issue→criterion→artifact matrix in ART.

**Test:** matrix in ART; no premature FQ closes.

---

## R4 — C12 SPA polish leftovers

Code shipped; **unchecked Soft-OPEN polish** from 361 body remains:

- [ ] Remove client `plots_by_rule` (or equivalent) all-rules memory cache.
- [ ] `useEffect` deps: site/rule/equip/window → **one** plot load; AbortController on flip.
- [ ] Propagate optional analysis window from FDD / RCx / Inspect callers (A4).
- [ ] Chart-local busy; Plotly purge stale axes; show server `note` on missing series.
- [ ] Each RCx preset = lean endpoint; no full-building dump.
- [ ] Unit tests: no point_map LIMIT-N fallback; OAT-METEO ≠ duct-static; downsample keeps endpoints; **all 77** roles non-empty or explicit override.
- [ ] Network Soft-OPEN: rule flips typically ≪ 1 MB; ART payload size log.

**Test:** DevTools Soft-OPEN on BUILDING_50 / loaded sites; Soft-OPEN ≠ FQ.

---

## R5 — C13 Soft-OPEN probes

Route code shipped; **live probes** unfinished:

- [ ] JWT `POST /api/model/sparql` SELECT → bindings; mutating query → 400.
- [ ] Lesson-style equip→points→timeseries ids on lab package RDF.
- [ ] Upload `.rq` Soft-OPEN or documented deferred.
- [ ] Plot path uses resolved ids (R4); MCP `openfdd_model_sparql` Soft-OPEN fail-closed.
- [ ] X2b: route in exposure manifest; anonymous SPARQL denied.

**Test:** ART redacted request/response; Soft-OPEN ≠ FQ.

---

## R6 — Pandas mask parity (C7 residual ≠ FQ)

C7 **77/77 API smoke** is done. FQ still blocked on:

- [ ] Repair A0 harness: do not PASS on HTTP ok alone; compare masks/seconds/hours/goldens vs pandas oracle.
- [ ] A1 typed adapters for metric/weather/utility/CHW cases; no hardcoded `AHU_1` for every plot.
- [ ] FC1 / SV-RATE / ≥9 adapter gaps with identical effective config — no skip/xfail widen.
- [ ] ART = full 77-row **parity** matrix (not smoke-only).

**Test:** any missing golden/mask mismatch = FAIL; Soft-OPEN ≠ FQ until matrix green.

---

## R7 — X2b proxy exposure

- [ ] Implement/verify [deployment_route_exposure_wave_x_20261013.md](../agents/deployment_route_exposure_wave_x_20261013.md) profiles: cloud / full OT / field-only.
- [ ] Method/path classes, JWT/role/tenant, private driver/DB, TLS/local-CA, forwarded headers, body/rate/time limits.
- [ ] Automated exposure manifest + tests; JWT before SQL.

**Test:** exposure ART; Soft-OPEN ≠ FQ.

---

## R8 — A2–A9 acceptance leftovers

Absorb [post_wave_x_362_acceptance_followup](../agents/post_wave_x_362_acceptance_followup_20261013.md). Priority leftovers (not exhaustive — read A0–A9):

- [ ] **A2** Coherent cohort results + real fault_series for plots.
- [ ] **A3** Complete SQL analytics (plant health, runtime, economizer, BAS/web OAT, mech OAT bins) — honest unsupported until delivered.
- [ ] **A4** Lean plot SQL bounds, downsample extrema, byte budgets.
- [ ] **A5** Typed ingest/eligibility; atomic remap; managed DB reconnect.
- [ ] **A6** Statement timeouts; AFDD async watermark; no `block_on` panic; daily timer stays **off**.
- [ ] **A7** Residual Arrow/Parquet callers in store/CSV paths; DB backup/WAL/restore vs workspace tar; image no-bind Soft-OPEN.
- [ ] **A8** Security recheck + ZAP (#1130/#1132); private audit only for repros.
- [ ] **A9** Amend stale agent docs that still call Parquet/DF canonical; Grok browser Soft-OPEN.

**Test:** per-item ART; Soft-OPEN ≠ FQ.

---

## R9 — Exit criteria

- [ ] VERSION **3.6.3** merged + GHCR `sha-*` newest-by-created pinned for Soft-OPEN
- [ ] C5: gate39 evidence or honest BLOCKED; volume UI residual resolved or dated BLOCKED
- [ ] C10: Grok ART present or honest NOT_AVAILABLE/BLOCKED
- [ ] C11: only proven closes; live Soft-OPEN issues remain open
- [ ] C12 polish + C13 probes Soft-OPEN evidence
- [ ] Pandas mask parity matrix (or explicit residual ≠ FQ)
- [ ] X2b profiles tested or BLOCKED with reason
- [ ] Soft-OPEN ≠ FQ until mega contract satisfied — **no FQ claim**

## Train loop

```text
residual gap → patch on /tmp/open-fdd-wt-wave-x-363-* → VERSION if product
→ PR → Actions → GHCR sha-* → newest-by-created → Soft-OPEN evidence → next
```

## Agent kickoff

```text
AUTHORIZED: execute post_wave_x_363_softopen_residuals_20261014.plan.md.

Baseline tip sha-eacdf79 / 3.6.2 done Soft-OPEN listed in plan — do not re-purge DF.
Finish R0–R9 residuals. Worktree /tmp only. Mintbench .16 OFF. Soft-OPEN ≠ FQ.
Read 362 acceptance followup A0–A9 + mega acceptance + route exposure + Grok mega.
Close GH issues only with tip AC evidence. Keep #1070 #1221 #1222 #1130 #1132 #1168 Haystack.
```
