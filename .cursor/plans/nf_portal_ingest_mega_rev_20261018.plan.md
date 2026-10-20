---
name: Wave-NF portal ingest mega 4.0
overview: "Wave-NF 4.0 portal ingest. Order: Wave-A N2+N6 → Wave-B parallel N1/N5/N3/N11 → Wave-C N8+N10 → Wave-D M10 GHCR. ACME later. SoftOPEN pilot ≠ full qualification."
todos:
  - id: wave-a-n2-n6
    content: "Wave-A PR1 — N2 security + N6 storage correctness (tenant filter, fail-closed secrets, no OAuth redirects, bounds, typed errors; per-equip routing, source ts/units/quality, truthful persist counts)"
    status: completed
  - id: wave-b-n1-archive
    content: "Wave-B parallel — N1 unqualified archive/ot-edge/unqualified-cdaa4f15 + prune dry-run keep. Merged #1294 e0df8bc7."
    status: completed
  - id: wave-b-n5-hourly
    content: "Wave-B parallel — N5 durable per-device hourly jobs, receipts, checkpoints, catch-up (GET history only; fixture-tested). Merged #1292 7c311101."
    status: completed
  - id: wave-b-n3-model
    content: "Wave-B parallel — N3 source-neutral committed model + scoped SPARQL ingest plans. Merged #1293 b2575575."
    status: completed
  - id: wave-b-n11-spa
    content: "Wave-B parallel — N11 Providers/Sites/Model/ledger SPA + source-neutral analytics. Merged #1289 018741d6."
    status: completed
  - id: wave-c-n8-leases
    content: "Wave-C — N8 shared Postgres queue/leases before replicas (stages 1–2; stage 3 live controller deferred). Merged #1291 698f8c52."
    status: completed
  - id: wave-c-n10-mcp
    content: "Wave-C — N10 scoped REST/MCP jobs/receipts/gaps; OT discovery retired from normal 4.0; provider health/sites stay. Merged #1291 698f8c52."
    status: completed
  - id: wave-d-m10-ghcr
    content: "Wave-D — VERSION 4.0.0. Master fe7e06b6 published ghcr.io/bbartling/openfdd-central:sha-fe7e06b (sha256:3ae2c2baaf49d9a8bc0c3c4a7f9dfc799d6e2c0c48ebf9b1d8c773b8c1a82b61) and ghcr.io/bbartling/openfdd-web:sha-fe7e06b (sha256:5cf2b0f5bf261480ea4443a6faebaba2edae41275be4e32f540473c14b7ccc61). No fieldbus image. No PyPI publish."
    status: completed
  - id: m0-milestones
    content: M0 MILESTONES Wave-NF; defer the 3620 ART sweep
    status: completed
  - id: m1-freeze-ot
    content: "M1 unqualified OT snapshot + portal compose. No 3.6.18 tag. Restore boot is n1-restore-boot."
    status: completed
  - id: m2-adr
    content: M2 ADR-011 DataProvider + Timescale + RDF
    status: completed
  - id: m3-trait
    content: M3 DataProvider trait and Timescale writer (N4 capability/history contract landed)
    status: completed
  - id: m4-nf-driver
    content: M4 NF OAuth + point/query latest + GET point/data hour window (connectivity prototype; harden in Wave-A/B)
    status: in_progress
  - id: m5-map
    content: M5 Roles from explicit provider_point_id or the committed ingest plan (display-name grep rejected)
    status: completed
  - id: m6-fe-blast
    content: M6 SPA Providers default; MQTT chrome archived (ledger hooks in wave-b-n11)
    status: completed
  - id: m7-fe-haystack
    content: SoftOPEN defer — M7 Model/SPARQL SPA for provider-mapped buildings (N11); server ingest-plan compiler landed with N3
    status: pending
  - id: m8-ops-ui
    content: M8 Ops panel shows provider poll health and window/gap ledger hooks (rows wait on N5)
    status: completed
  - id: m9-stub-ace
    content: M9 Ace IoT driver stub (visibly NotImplemented)
    status: completed
  - id: m10-ghcr
    content: "M10 VERSION 4.0.0. GHCR central sha-fe7e06b sha256:3ae2c2baaf49d9a8bc0c3c4a7f9dfc799d6e2c0c48ebf9b1d8c773b8c1a82b61 and web sha-fe7e06b sha256:5cf2b0f5bf261480ea4443a6faebaba2edae41275be4e32f540473c14b7ccc61. No fieldbus image. No PyPI publish. Merged #1302 fe7e06b6."
    status: completed
  - id: m10-railway-repin
    content: SoftOPEN defer — Railway re-pin to sha-fe7e06b was not part of this merge
    status: pending
  - id: actions-ot-gate
    content: "Gate Optional BACnet and Wave C isolated workflows so 4.0 master does not pull unpublished openfdd-fieldbus or openfdd-mqtt sha tags. Archive OCI pin stays unbooted."
    status: completed
  - id: m11-prove
    content: M11 bosspi hour smoke in Timescale (lab evidence only; not full N12 matrix)
    status: in_progress
  - id: m12-grok
    content: M12 Grok API proof on published sha (coverage/scoped endpoints, not rows-only)
    status: pending
  - id: m13-acme-later
    content: SoftOPEN defer — M13 ACME NF retrofit only after bounded bosspi SoftOPEN pilot is stable
    status: pending
  - id: m14-grok-tools
    content: "M14 Legacy OT Grok tips flagged retired. MCP OT wire/driver discovery is not in default tools/list. Provider health/sites stay. Merged #1300 75d86af5."
    status: completed
  - id: n0-boundary
    content: "N0 Define 4.0 product boundary + requirements-to-test matrix labels. Merged #1296 de042f70."
    status: completed
  - id: n1-archive-real
    content: "N1 snapshot landed as unqualified-cdaa4f15. Merged #1294 e0df8bc7."
    status: completed
  - id: n1-restore-boot
    content: "Isolated restore --replay renders the GHCR digest pin and prune-protects those digests. --boot stays refused (no live deploy). Merged #1300 75d86af5."
    status: completed
  - id: n1-workspace-remove
    content: "Live services/fieldbus is excluded from the default Cargo workspace, 4.0 publish, and fieldbus recipes. The archive workspace is the compile lane. Merged #1300 75d86af5."
    status: completed
  - id: n2-security
    content: N2 Tenant filter health/sites; fail-closed secrets; no OAuth redirects; bounds; typed safe errors (Wave-A)
    status: completed
  - id: n3-model
    content: N3 source-neutral committed model + scoped SPARQL ingest plans (Wave-B)
    status: completed
  - id: n3-replica-store
    content: SoftOPEN defer — N3 cross-replica derived-plan invalidation, durable multi-process model store, and in-flight SPARQL cancel (with N8)
    status: pending
  - id: n4-contract
    content: "N4 Provider registry with fetch_history capabilities; Ace stays NotImplemented. Merged #1301 5c38e4c1. #1297 and #1299 closed as superseded."
    status: completed
  - id: n5-durable
    content: "N5 durable per-device completed-hour jobs, receipts, checkpoints, catch-up, bounded reconciliation (fixture-tested; live NF pilot stays n12)"
    status: completed
  - id: n6-storage
    content: N6 Per-equipment type routing; source ts/units/quality; truthful persist counts; DB reconnect (Wave-A)
    status: completed
  - id: n7-gaps
    content: "N7 coverage ledger over N5 jobs/receipts (probe, window, durable commit, freshness, reconcile, retention); update-log 403; not gapless. Merged #1301 5c38e4c1."
    status: completed
  - id: n7-device-hour-route
    content: "SoftOPEN defer — tenant-scoped GET /api/providers/gaps and the #1299 device-hour ledger were not ported. They collide with #1301 CoverageLedger (six-axis summary, Postgres-receipt durable commit)."
    status: pending
  - id: n8-scale
    content: "SoftOPEN defer — N8 stage 3 live replica controller (stages 1–2 queue/leases landed in Wave-C; simulator is dry-run only)"
    status: pending
  - id: n9-meteo
    content: "N9 Open-Meteo weather adapter + contractor conformance fixture. Merged #1296 de042f70."
    status: completed
  - id: n10-api-mcp
    content: "N10 scoped REST/MCP jobs/receipts/gaps; OT discovery retired from normal 4.0"
    status: completed
  - id: n11-frontend
    content: SoftOPEN defer — N11 live window rows, backfill submit, and server-issued binding preview wait on N5/N3 (SPA hooks landed)
    status: pending
  - id: n12-evidence
    content: "SoftOPEN defer — bounded read-only NF SoftOPEN pilot and published-SPA regression (offline fixture matrix is in CI; no portal flood)"
    status: pending
  - id: n13-release
    content: "N13 phased delivery gates and machine-readable status (nothing deployed or qualified). Merged #1298 3d081622."
    status: completed
  - id: n2-dns-pin
    content: SoftOPEN defer — DNS-at-connect rebinding pin for provider endpoints (Wave-A left public-mode literal IP checks only)
    status: pending
  - id: n2-hot-secrets
    content: SoftOPEN defer — hot credential reload without process restart
    status: pending
isProject: true
---

# Wave-NF — portal ingest mega 4.0 (restored + 2026-10-19 review merge)

Product code stays all Rust. OT fieldbus and MQTT stay in-repo and **archived for normal 4.0**. They are not the ingest path for this wave. ACME waits. Building 100 history must not be disturbed; prior re-seed stays owner-deferred.

**2026-10-19 addendum sources** (read-only audit over uncommitted NF work — recheck against current HEAD before claiming fixes):

- Mega prompt: `Documents/…/2026-10-19/CURSOR_NF_4_0_MEGA_PROMPT_20261019.md` (also under `openfdd-softopen-art/4.0.0/`)
- Evaluation: `…/NF_4_0_EVALUATION.md`
- Autoscaling/gaps: `…/AUTOSCALING_AND_GAP_VALIDATION.md`
- Private security: `…/PRIVATE_SECURITY_REVIEW.md` (do not paste exploit detail into public tickets)
- Also: `INGEST_MODEL_REVIEW.md`, `FRONTEND_ARCHIVE_REVIEW.md`, `SOURCE_MANIFEST.json`, `CURSOR_NF_HANDOFF_4.0.0_20261019.md`

No live 4.0, capacity, security exploit, or passing full-matrix qualification is claimed by that review. A successful one-hour bosspi smoke is **lab evidence**, not full qualification.

## Async PR waves (owner order — Grok Bot + cloud agents)

| Wave | PR scope | When |
| --- | --- | --- |
| **A** | **N2 + N6** security/correctness first | Now (one PR) |
| **B** | Parallel: **N1** archive / **N5** hourly jobs / **N3** model / **N11** SPA | After Wave-A merges |
| **C** | **N8** leases + **N10** MCP | After Wave-B |
| **D** | **M10** 4.0.0 publish → GHCR `ghcr_newest_by_created` central+web | After Wave-C |

After each merge: update this plan's YAML todos **and** the live checklist at the bottom. Anything left unfinished: `status: pending` and content prefix `SoftOPEN defer —`.

**End goal:** green GHCR central+web, no stale wave-nf branches, no failed Actions on tip.

**Hard rules:** GET history only (`GET /api/v1/point/data` — never POST write); no portal flood; no Building 100 reseed; ACME later (M13). Salvage or ignore `/tmp/open-fdd-wt-wave-nf` WIP.

## Status labels (use everywhere)

| Label | Meaning |
| --- | --- |
| **prototype** | Compiles / connects; known integrity gaps |
| **implemented** | Code lands the contract |
| **tested** | Gate evidence recorded |
| **deployed** | Published sha pinned on hub |
| **qualified** | N12 matrix + bounded SoftOPEN pilot pass |

Do not mark M3/M4/M5/M11 complete merely because a trait/stub exists or five points emit samples.

## What already landed (prototype)

- Python smoke `scripts/nf/read_sensors.py` reads bosspi latest through Normal Online. Passed 2026-10-18.
- Rust under `services/central/src/providers/` (NF, Ace stub, role map, poller, writer).
- MCP tools `openfdd_provider_health` / `openfdd_provider_sites`.
- ADR-011. Lab files: `scripts/nf/provider_sites.bosspi.json`, `bosspi_gateway.json`, `bosspi_semantic_meta.json`.
- Five mapped points on `NF_EDGE` (`equipType: ahu`): `oa_t`, `oa_h`, `sat` (duct), `zone_t`, `mat` (**plate sensor — provisional lab stamp only; not proof of AHU mixed-air semantics**).
- Ops SPA default view → **Providers**. MQTT / fieldbus chrome stays on the archived tab only. Sites list portal registry ids with read-only source labels. Window/gap ledger, typed bindings, and request preview render when the API publishes them and stay empty otherwise. October 18 UI findings were rechecked against this branch's code; this is not a published-SPA browser audit.
- Worktree tip bump toward **4.0.0** on branch `wave-nf/4.0.0-portal-ingest`.

Roles come from UUID map or Haystack SPARQL binding set. Display names must not invent roles. No RDF text-grep as ingest capability.

## Explicit corrections (keep forever)

1. **NF history is GET** `GET /api/v1/point/data`. **POST** on that path is a **write**. Do not force all provider calls to POST. OAuth/query may still POST.
2. **Hourly device polling copies all source samples in the hour** — not one hourly average/value per point.
3. **Haystack semantics stay.** Remote Haystack **transport** retires with OT pipelines.
4. Lab plate→`mat` is not correct AHU MAT proof; mark provisional / exclude from production FDD until verified.
5. NF update log (`GET /api/v1/point/updates/data`) returned **403** on 2026-10-18. Do **not** claim range polling is gapless. State bounded reconciliation + upstream limits. Do not expand remote permissions automatically.
6. Preserve Building 100 data. ACME after bounded NF SoftOPEN pilot.
7. October 18 UI findings are historical; recheck current code before claiming fixed or still broken.

## How NF history works today

Source: [Points](https://docs.normal.dev/concepts/points/), [GetData](https://docs.normal.dev/api/html/api.html), [adapters](https://docs.normal.dev/howto/adapters/).

| Call | Meaning |
| --- | --- |
| `POST /api/v1/point/query` | Latest value scrape |
| `GET /api/v1/point/data?uuids=&from.seconds=&to.seconds=` | GetData history read |
| `POST /api/v1/point/data` | AddPointsData **write** — do not poll |
| `GET /api/v1/point/updates/data` | Preferred gapless log — **403 on lab key** |

Lab proof 2026-10-18: GetData returned ~60 samples/UUID over last hour for five mapped points.

**N5 poller (this branch):** per-device completed-hour jobs in Postgres (`sql/schema/04_provider_hourly_jobs.sql`), receipts, checkpoints, catch-up, and a bounded reconcile sweep. History is `GET /api/v1/point/data` only. A history error stays a failed job. The fixed `now−65min` lookback is gone. NF update-log HTTP 403 is stated on provider health; that path is not called and permissions are not expanded. The N7 ledger reads those jobs, receipts, checkpoints, and gaps. A per-device window browser remains a SoftOPEN defer for N11. Single-transaction sample+receipt across the historian writer remains N6. N8 replica control is not in this PR; claim SQL is `SKIP LOCKED` plus a fencing token so a later lease PR can build on it.

## Highest priority (from evaluation — P1)

| # | Theme | Required outcome |
| --- | --- | --- |
| 1 | **Security** | Tenant-filter `/api/providers/health|sites` (+ MCP); fail-closed missing secrets; disable OAuth redirects (JSON body leak); no raw vendor/token bodies in health/logs; byte/time bounds; task supervision |
| 2 | **Durable ingest** | Per-device hourly jobs, checkpoints, catch-up, late reconciliation, honest coverage — not fixed 65m lookback |
| 3 | **Model** | Source-neutral committed revision; SPARQL-derived plans; connection+external series; driver owns routes/auth; no arbitrary URL/POST in RDF |
| 4 | **Data correctness** | Per-equipment type (not first-in-envelope); preserve source ts precision; units/quality/provenance; real persist counts |
| 5 | **Scaling** | No K8s prerequisite. Postgres queue + leases/fencing + per-portal budgets first; worker replicas ≠ API; optional capped autoscaler only after multiworker proof. Today's every-replica-starts-all-pollers amplifies load |
| 6 | **Archive** | Real `archive/ot-edge/<freeze>/` with full Docker contexts + all fieldbus targets + digest prune protection; extract shared semantic code before moving `edge/`; remove OT from normal 4.0 default recipes/publish/tools |
| 7 | **Frontend** | Ops→Providers/Sites/AFDD; NF-only discovery; typed bindings + request preview; window/gap ledger; calm draft/save; source-neutral analytics; honest Admin/MCP |

## N0–N13 dependency order (merge into M0–M14)

Per mega prompt. Preserve completed M0/M2/M9 evidence; do not restart blindly.

1. **N0 / Foundations:** 4.0 boundary (central+web+Timescale; optional MCP/worker). Matrix labels.
2. **N1 + M1:** Verified OT freeze or **unqualified snapshot** with missing evidence listed. Protect digests from prune. Isolated restore lane.
3. **N2:** Security boundaries **before** growing ingest (tenant, secrets, redirects, bounds).
4. **N3 + M5/M7:** Committed model + SPARQL plans.
5. **N4 + M3/M4:** Provider capability/`fetch_history` contract; Ace NotImplemented.
6. **N5–N7:** Durable jobs, storage integrity, explicit gap guarantees.
7. **N8:** Multiworker then optional autoscaler (see autoscaling guide).
8. **N9:** Open-Meteo + contractor fixture.
9. **N10 + M14:** API/MCP + Grok tip retirement.
10. **N11 + M6/M8:** Full SPA migration (Providers panel is only a start).
11. **N12:** Fixture matrix → bounded read-only NF SoftOPEN pilot → published-SPA regression.
12. **N13 + M10–M13:** Publish/pilot/Grok/ACME with truthful status.

## Scaling (N8) — short form

No Kubernetes required. Stages: (1) durable jobs + one scheduler owner + one bounded worker; (2) 2–4 workers with shared leases/fencing; (3) optional queue-driven replica controller with caps/cooldown/audit/dry-run after chaos/load proof. Railway vertical ≠ automatic horizontal. Metrics: oldest-ready-job age, completion lag, 429s, DB/writer pressure — not CPU alone. Formulae and gap tests: autoscaling guide.

## Gap guarantee (N7) — short form

Separate: transport probe, requested window completeness, durable commit, source freshness/cadence, late reconciliation, unrecoverable retention expiry. The ledger is built from N5 hourly jobs, receipts, checkpoints, and gaps. It cannot advance from one latest sample. Without update-log permission, the guarantee is **bounded** time-range plus recent reconciliation. `GET /api/v1/point/updates/data` returned HTTP 403 on the lab key and is not called. Range polling is not gapless. The Providers panel shows that summary. A full per-device window browser stays with N11.

## Exit evidence (N12)

Exact source→DB sets; scoped REST/MCP; units/timestamps/quality; partial history; crash boundaries; long outages; late backloads; 2–4 worker fencing; throttling; DB recovery; bounded memory; controlled autoscaler sim. Isolated fixtures first; then bounded real read-only NF SoftOPEN.

Record implemented / tested / deployed / remaining separately.

## GHCR / Grok (after durable integrity, not before)

Do not build stack images on the low-RAM desktop. PR → GHCR → pin with `./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web`. Railway: central then web; fieldbus off cloud. Grok API proof upgrades from rows/no-duplicates to committed coverage, restart/late-data truth, scoped endpoints, and real-source comparison.

Legacy OT Grok tips are **stale** for this wave (M14).

---

## TODOs — live checklist (Wave-NF)

Update this section **and** the YAML frontmatter after every merge. Prefix unfinished leftovers with `SoftOPEN defer —`.

### Wave-A — now (one PR)
- [x] **wave-a-n2-n6** — N2 security + N6 storage correctness
  - Tenant-filter `/api/providers/health|sites` (+ MCP parity)
  - Fail-closed missing secrets; no OAuth redirects; connect/read/total deadlines + byte bounds
  - Typed safe errors; no raw vendor/token bodies in health/logs
  - Per-equipment type routing (not first-in-envelope); source ts/units/quality; truthful persist counts; DB reconnect
  - Base-branch blockers included: `nf.rs` delimiter, `scripts/nf` display-name audit, security inventory for the two provider GETs
- [x] **n2-security** / **n6-storage** — same Wave-A PR (keep in sync)

### Wave-B — parallel after Wave-A merges
- [x] **wave-b-n1-archive** / **n1-archive-real** — N1 `archive/ot-edge/unqualified-cdaa4f15/` + prune dry-run keep. No 3.6.18 tag. Merged #1294 `e0df8bc7`.
- [x] **n1-restore-boot** — `--replay` renders `evidence/oci-pin.json` digests; prune file lists them; `--boot` exits 2 (no containers). Merged #1300 `75d86af5`.
- [x] **n1-workspace-remove** — `services/fieldbus` excluded from the default workspace, publish workflows, and fieldbus recipes. Split gate compiles `archive/ot-edge/unqualified-cdaa4f15/source`. Merged #1300 `75d86af5`.
- [x] **wave-b-n5-hourly** — N5 durable hourly jobs/receipts/checkpoints/catch-up (**GET history only**; fixture-tested). Merged #1292 `7c311101`.
- [x] **wave-b-n3-model** / **n3-model** — committed model + scoped SPARQL plans (resolver each tick). Merged #1293 `b2575575`.
- [ ] SoftOPEN defer — **n3-replica-store** cross-replica invalidation, durable multi-process store, in-flight SPARQL cancel
- [x] **wave-b-n11-spa** — N11 Providers/Sites/Model/ledger SPA hooks (live rows, backfill submit, and server preview stay deferred). Merged #1289 `018741d6`.

### Wave-C — after Wave-B
- [x] **wave-c-n8-leases** — N8 Postgres queue/leases/fencing (stages 1–2). API role does not start pollers. Merged #1291 `698f8c52`.
- [x] **wave-c-n10-mcp** — scoped REST/MCP jobs/receipts/gaps; OT discovery retired unless `OPENFDD_OT_TOOLS=1`; provider health/sites stay. Merged #1291 `698f8c52`.
- [x] **m14-grok-tools** — legacy OT Grok tips flagged retired; MCP OT wire/driver discovery is not in default `tools/list`. Merged #1300 `75d86af5`.

### Wave-D — publish
- [x] **wave-d-m10-ghcr** / **m10-ghcr** — VERSION 4.0.0. Master `#1302` `fe7e06b6` published `ghcr.io/bbartling/openfdd-central:sha-fe7e06b` (`sha256:3ae2c2baaf49d9a8bc0c3c4a7f9dfc799d6e2c0c48ebf9b1d8c773b8c1a82b61`) and `ghcr.io/bbartling/openfdd-web:sha-fe7e06b` (`sha256:5cf2b0f5bf261480ea4443a6faebaba2edae41275be4e32f540473c14b7ccc61`). No fieldbus image. No PyPI publish. Run https://github.com/bbartling/open-fdd/actions/runs/39357186292
- [x] **actions-ot-gate** — Optional BACnet workflow ([run 39362164673](https://github.com/bbartling/open-fdd/actions/runs/39362164673)) no longer pulls `openfdd-mqtt` / `openfdd-fieldbus` at the portal `sha-<head>`. The Monday schedule is removed. Wave C isolated suites skip on pull request when that mqtt tag is absent. The archive pin is not booted (`--boot` stays refused; `--replay` and the protocol-connector split gate stay the isolated lane).

### This round
- [x] **n0-boundary** — 4.0 boundary and requirements matrix in `docs/architecture/wave-nf-4.0-product-boundary.md` (no row qualified). Merged #1296 `de042f70`.
- [x] **n9-meteo** — Open-Meteo read-only adapter + offline contractor fixture. Ace stays NotImplemented. Merged #1296 `de042f70`.

### SoftOPEN defer / later
- [ ] SoftOPEN defer — **n8-scale** stage 3 live replica controller (dry-run preview only; no Kubernetes)
- [ ] SoftOPEN defer — **m13-acme-later** ACME NF retrofit after bosspi SoftOPEN pilot
- [x] **n4-contract** — provider registry (`latest`, `fetch_history` GET with a bounded window, `update_log` NotImplemented). Ace stays visibly NotImplemented. Conformance tests reject an unbounded NF window before any request. Merged #1301 `5c38e4c1`. #1297 and #1299 closed as superseded.
- [x] **n7-gaps** — coverage ledger over N5 jobs/receipts/checkpoints/gaps. Axes stay separate. Memory receipts are not a durable commit. Update-log HTTP 403 is stated. Range polling is not gapless. A latest sample does not advance the ledger. Merged #1301 `5c38e4c1`.
- [ ] SoftOPEN defer — **n7-device-hour-route** tenant-scoped `GET /api/providers/gaps` and the #1299 device-hour ledger. Not ported: they collide with the #1301 `CoverageLedger` (six-axis summary, Postgres-receipt durable commit).
- [ ] SoftOPEN defer — server-published per-device window rows (`GET /api/providers/windows`), backfill submit, and binding preview. The Providers panel shows the N7 six-axis summary from poll health beside the N11 window table.
- [ ] SoftOPEN defer — N5 historian sample upsert and job receipt are separate writes (one transaction stays with N6)
- [ ] SoftOPEN defer — **n11-frontend** live window rows, backfill submit, and server-issued binding preview
- [ ] SoftOPEN defer — **n12-evidence** bounded read-only NF SoftOPEN pilot and published-SPA regression (offline fixture matrix is in CI; no portal flood)
- [x] **n13-release** phased gates (`docs/operations/WAVE_NF_DELIVERY_GATES.md`) + `wave_nf_status.json` (nothing deployed or qualified). Merged #1298 `3d081622`.
- [ ] SoftOPEN defer — **n2-dns-pin** DNS-at-connect rebinding pin (literal public-mode checks only)
- [ ] SoftOPEN defer — **n2-hot-secrets** hot credential reload without process restart
- [ ] SoftOPEN defer — **m10-railway-repin** Railway re-pin to `sha-fe7e06b` (not done in this merge)

### Already done (do not reopen)
- [x] m0-milestones, m1-freeze-ot (snapshot only; boot stays **n1-restore-boot**), m2-adr, m3-trait (prototype), m5-map, m6-fe-blast, m8-ops-ui, m9-stub-ace

### Prototype still open (do not claim complete)
- [~] m4-nf-driver, m11-prove

### Cloud agents launched 2026-10-19 (Grok Bot)
- Wave-A N2+N6: bc-8669bd28 — merged #1290 `608ee177`
- Wave-B N1 archive: bc-09497442
- Wave-B N5 hourly: bc-81ff01ac
- Wave-B N3 model: bc-9c23a08d
- Wave-B N11 SPA: bc-7fe03caf
- Wave-C N8+N10: bc-d24c1c2e
- Wave-D GHCR: merged #1302 `fe7e06b6`. Images `sha-fe7e06b`. Railway re-pin stays **m10-railway-repin**.

### Merge log (into `wave-nf/4.0.0-portal-ingest`)
- #1290 Wave-A `608ee177`
- #1294 N1 archive `e0df8bc7`
- #1292 N5 `7c311101`
- #1293 N3 `b2575575`
- #1289 N11 `018741d6`
- #1291 Wave-C `698f8c52`
- #1296 N0+N9 `de042f70`
- #1301 N4+N7 `5c38e4c1` (supersedes #1297 and #1299; device-hour gaps route stays **n7-device-hour-route**)
- #1298 N12 fixtures + N13 `3d081622`
- #1300 N1 leftovers + M14 `75d86af5`
