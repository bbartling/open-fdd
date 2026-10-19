---
name: Wave-NF portal ingest mega 4.0
overview: "Wave-NF 4.0 portal ingest. Order: Wave-A N2+N6 → Wave-B parallel N1/N5/N3/N11 → Wave-C N8+N10 → Wave-D M10 GHCR. ACME later. SoftOPEN pilot ≠ full qualification."
todos:
  - id: wave-a-n2-n6
    content: "Wave-A PR1 — N2 security + N6 storage correctness (tenant filter, fail-closed secrets, no OAuth redirects, bounds, typed errors; per-equip routing, source ts/units/quality, truthful persist counts)"
    status: completed
  - id: wave-b-n1-archive
    content: "Wave-B parallel — N1 real archive/ot-edge freeze + digest prune protection + isolated restore"
    status: pending
  - id: wave-b-n5-hourly
    content: "Wave-B parallel — N5 durable per-device hourly jobs, receipts, checkpoints, catch-up (un-cancel; GET history only)"
    status: pending
  - id: wave-b-n3-model
    content: "Wave-B parallel — N3 source-neutral committed model + scoped SPARQL ingest plans"
    status: pending
  - id: wave-b-n11-spa
    content: "Wave-B parallel — N11 Providers/Sites/Model/ledger SPA + source-neutral analytics"
    status: pending
  - id: wave-c-n8-leases
    content: "Wave-C — N8 shared Postgres queue/leases before replicas"
    status: pending
  - id: wave-c-n10-mcp
    content: "Wave-C — N10 scoped REST/MCP jobs/receipts/gaps; retire OT tool discovery from normal 4.0"
    status: pending
  - id: wave-d-m10-ghcr
    content: "Wave-D — M10 VERSION 4.0.0, GHCR central+web newest-by-created, Railway re-pin, no fieldbus image"
    status: pending
  - id: m0-milestones
    content: M0 MILESTONES Wave-NF; defer the 3620 ART sweep
    status: completed
  - id: m1-freeze-ot
    content: M1 OT archive tag + ARCHIVE_OT_EDGE; product compose central+web+Timescale (N1 full archive/restore still open → Wave-B)
    status: in_progress
  - id: m2-adr
    content: M2 ADR-011 DataProvider + Timescale + RDF
    status: completed
  - id: m3-trait
    content: M3 DataProvider trait and Timescale writer (prototype; N4 capability/history contract still open)
    status: completed
  - id: m4-nf-driver
    content: M4 NF OAuth + point/query latest + GET point/data hour window (connectivity prototype; harden in Wave-A/B)
    status: in_progress
  - id: m5-map
    content: M5 Roles from explicit provider_point_id or SPARQL bindings only (N3 typed committed model → Wave-B)
    status: in_progress
  - id: m6-fe-blast
    content: M6 SPA Providers default; MQTT chrome archived (N11 full Ops ledger → Wave-B)
    status: in_progress
  - id: m7-fe-haystack
    content: M7 Model/SPARQL for provider-mapped buildings (N3/N11 → Wave-B)
    status: pending
  - id: m8-ops-ui
    content: M8 Ops panel shows provider poll health (basic); window/gap ledger pending N5 Wave-B
    status: in_progress
  - id: m9-stub-ace
    content: M9 Ace IoT driver stub (visibly NotImplemented)
    status: completed
  - id: m10-ghcr
    content: M10 VERSION 4.0.0, GHCR central+web, Railway re-pin, no fieldbus image (Wave-D)
    status: pending
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
    content: M14 Flag or replace legacy OT Grok tips for slimmer hub (with Wave-C/D)
    status: pending
  - id: n0-boundary
    content: N0 Define 4.0 product boundary + requirements-to-test matrix labels
    status: pending
  - id: n1-archive-real
    content: SoftOPEN defer — N1 Real archive/ot-edge freeze (owned by Wave-B parallel PR)
    status: pending
  - id: n2-security
    content: N2 Tenant filter health/sites; fail-closed secrets; no OAuth redirects; bounds; typed safe errors (Wave-A)
    status: completed
  - id: n3-model
    content: SoftOPEN defer — N3 Source-neutral committed model (owned by Wave-B parallel PR)
    status: pending
  - id: n4-contract
    content: N4 Provider registry with fetch_history capabilities; Ace stays NotImplemented
    status: pending
  - id: n5-durable
    content: SoftOPEN defer — N5 Durable per-device hourly jobs (owned by Wave-B; was wrongly cancelled)
    status: pending
  - id: n6-storage
    content: N6 Per-equipment type routing; source ts/units/quality; truthful persist counts; DB reconnect (Wave-A)
    status: completed
  - id: n7-gaps
    content: SoftOPEN defer — N7 Coverage ledger; bounded reconciliation; NF update-log 403 limitation stated
    status: pending
  - id: n8-scale
    content: SoftOPEN defer — N8 Shared Postgres queue/leases (Wave-C)
    status: pending
  - id: n9-meteo
    content: SoftOPEN defer — N9 Open-Meteo weather adapter + contractor conformance fixture
    status: pending
  - id: n10-api-mcp
    content: SoftOPEN defer — N10 Scoped REST/MCP (Wave-C)
    status: pending
  - id: n11-frontend
    content: SoftOPEN defer — N11 Full Providers/Sites/Model/ledger UI (Wave-B)
    status: pending
  - id: n12-evidence
    content: SoftOPEN defer — N12 Full acceptance matrix (fixtures then bounded NF SoftOPEN pilot); no portal flooding
    status: pending
  - id: n13-release
    content: SoftOPEN defer — N13 Phased delivery gates; truthful implemented/tested/deployed/remaining status
    status: pending
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
- Ops SPA default view → **Providers** (MQTT retained behind archived tab).
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

**Current poller (known insufficient for N5):** `poll_secs: 3600`, fixed `now−65min` lookback, history errors can become empty success (false green). Replace with durable per-device completed-hour jobs + receipts before broad rollout.

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

Separate: transport probe, requested window completeness, durable commit, source freshness/cadence, late reconciliation, unrecoverable retention expiry. Coverage ledger cannot advance from one latest sample. Without update-log permission, state the **bounded** time-range + recent reconciliation guarantee and its blind spots.

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
- [ ] **wave-b-n1-archive** — N1 real `archive/ot-edge/<freeze>/` + prune protection + isolated restore
- [ ] **wave-b-n5-hourly** — N5 durable hourly jobs/receipts/checkpoints/catch-up (**GET history only**)
- [ ] **wave-b-n3-model** — N3 committed model + scoped SPARQL plans
- [ ] **wave-b-n11-spa** — N11 Providers/Sites/Model/ledger SPA

### Wave-C — after Wave-B
- [ ] **wave-c-n8-leases** — N8 Postgres queue/leases before replicas
- [ ] **wave-c-n10-mcp** — N10 scoped REST/MCP; retire OT discovery from normal 4.0

### Wave-D — publish
- [ ] **wave-d-m10-ghcr** — VERSION 4.0.0, GHCR central+web newest-by-created, Railway re-pin, no fieldbus

### SoftOPEN defer / later
- [ ] SoftOPEN defer — **m13-acme-later** ACME NF retrofit after bosspi SoftOPEN pilot
- [ ] SoftOPEN defer — **n7-gaps** coverage ledger / update-log 403 stated
- [ ] SoftOPEN defer — **n9-meteo** Open-Meteo + contractor fixture
- [ ] SoftOPEN defer — **n12-evidence** full acceptance matrix (no portal flood)
- [ ] SoftOPEN defer — **n13-release** phased gates + truthful remaining status
- [ ] SoftOPEN defer — **n2-dns-pin** DNS-at-connect rebinding pin (literal public-mode checks only)
- [ ] SoftOPEN defer — **n2-hot-secrets** hot credential reload without process restart

### Already done (do not reopen)
- [x] m0-milestones, m2-adr, m3-trait (prototype), m9-stub-ace

### Prototype still open (do not claim complete)
- [~] m1-freeze-ot, m4-nf-driver, m5-map, m6-fe-blast, m8-ops-ui, m11-prove
