---
name: Wave O Known Bugs Patch
overview: "Wave O continuous bake (no deferrals except O5 Stage C): O8→O9→O10→O7→O3→O1→O6→O2→O4. O2b = beefed automated authz tests (Kali agent owns live AF). Railway hub pinned sha-764bb17 / 3.5.11. Mint scrape → GHCR → Railway → ACME = same tip cycle."
todos:
  - id: o0-bootstrap
    content: "O0: Seed BUG_REPORT_WAVE_O + pointer from Wave N/OT reports; sync ops pin sha-9072e0b / 3.5.10; agent_spec SESSION_LOG Wave O kickoff"
    status: completed
  - id: o0-local-bacnet-bench
    content: "Optional: Mint local BACnet Who-Is + MQTTS pipeline smoke (192.168.204.11) via scripts/ops/local_bacnet_ot_bench.sh — docs LOCAL_BACNET_BACPYPE3_BENCH.md"
    status: completed
  - id: o0-hygiene-gate
    content: "O0 every cycle: 0 open PRs; master only; tip Actions green; cancel superseded fails; no stale local branches"
    status: in_progress
  - id: o0-reboot-hold
    content: "HOLD (human): Mint reboot before next product/security implementation turn — plan LOCKED 2026-09-14; resume after reboot for tip-pin → #926 → O10… → O2b beefed tests (no Kali here)"
    status: completed
  - id: o1-tenant-historian
    content: "O1 sub-plan: migrate/re-import BUILDING_100 + LAKESIDE_ES under tenants/{tid}/; harden package import write ACL; gate 31+historian path proof"
    status: completed
  - id: o2-audit-zap
    content: "O2a: stress asserts security_audit events on deny/select/import; ZAP AF owned by external Kali agent (disposition only here) — this agent expands automated authz/header/redirect/rate-limit tests, not Kali"
    status: completed
  - id: o2-kali-mt-shared-db
    content: "O2b (Kali agent owns live AF): map authz+routes+admin+export/upload+Railway; permission matrix; fix IDOR/BOLA/mass-assign; cookies/CSRF/rate-limit/CORS; CSP+headers; security.txt. THIS agent: beefed automated ACL/IDOR/admin/redirect/header/CORS tests + gate 31/33 — do NOT run Kali/ZAP ActiveScan here"
    status: completed
  - id: o3-acme-metric-mstp
    content: "O3: metric Trane VAV FDD + MSTP addressing — next step immediately after O10 streams healthy; never invent ZN-T"
    status: completed
  - id: o4-mint-m5
    content: "O4 sub-plan: Wave M mint residual — fieldbus kit or skip-kit path; docker.sock; synth59 stage; re-run hub stress toward fully_qualified"
    status: pending
  - id: o5-stage-c-park
    content: "O5 PARKED Soft-OPEN: Stage C IdP/MFA/SKU — track only; no product claim until commercial train"
    status: pending
  - id: o6-historian-perf-parity
    content: "O6: CSV→Hive/tenant layout + import admission; admin data limits (default 1y OR GiB cap); concurrent CSV+MQTT stress; identical DataFusion FDD parity; H10 where useful"
    status: completed
  - id: o6-admin-data-limits
    content: "O6 product: hub-admin settable historian retain window + size cap (defaults: 365d OR ~1–5 GiB/tenant-building — whichever binds first); reject import+MQTT beyond policy (no silent FDD truncate); UI or API for admin"
    status: completed
  - id: o7-overview-site-cache
    content: "O7: Per-buildingId Overview+health client cache; stop double DF fan-out on site switch; invalidate only RULES_UPDATED/explicit refresh/ingest — under-hood only, ZERO new explanatory UI chrome"
    status: completed
  - id: o8-hub-admin-console
    content: "ASAP SELL WEEK: Hub-admin React console + REST CRUD users/tenants/data; quiet django-like UI; extend gate 31 ACL stress; tip pin before demo"
    status: completed
  - id: o8-sell-week-gate
    content: "After #925 tip pin: admin CRUD on Railway; acme-ops 403 /api/admin/*; gate 33; then continue O10 same bake"
    status: completed
  - id: o9-site-datamodel-export-acl
    content: "O9 (PR #925): site-wide data-model export + session ACL; close when tip + gate 33 PASS"
    status: completed
  - id: o10-acme-full-hvac-mqtt
    content: "O10 NEXT tip after #925: free 47808 → Mint scrape → rusty tip + full HVAC catalog → GHCR fieldbus → ACME refresh → all-HVAC healthy (same week, not deferred)"
    status: completed
  - id: o-hold-build
    content: "HOLD lifted — continuous bake; nothing deferred except O5 Stage C"
    status: completed
  - id: o-mint-before-ghcr
    content: "Every fieldbus tip: Mint cargo + BACnet scrape (free 47808) then immediately PR→GHCR→Railway→ACME (ordered steps, same cycle)"
    status: completed
  - id: o-rusty-tip-pins
    content: "Confirm/bump rusty-bacnet tip (v0.11.0 if MS/TP OK), rusty-haystack v0.8.1, rusty-modbus v0.1.1 before fieldbus GHCR"
    status: completed
  - id: o-cycle-template
    content: "Each step: Mint compile(+BACnet scrape if fieldbus) → PR → CI → squash → GHCR → Railway → ACME same cycle → gates → BUG_REPORT → next step"
    status: completed
  - id: o-local-compile-gate
    content: "Per product PR on Mint: cargo check/test touched crates + local web --build/--no-pull before push; free UDP 47808 before fieldbus; catch breaks before Actions"
    status: completed
  - id: o-full-stress-pins
    content: "Full Railway+ACME stress at O8/O9, O10, O1, O2, O6, O4 steps; tip sha-* only; O10 proves ALL HVAC @300s"
    status: completed
  - id: o-fdd-parity-gate
    content: "Wherever historian layout/import changes: capture baseline FDD (rule_id×equip fault counts/series digests) → mutate → re-run same window → assert same results; no greenwash"
    status: completed
  - id: o-ui-no-agent-chrome
    content: "Hard rule all Wave O SPA work: no agent/AI explanatory banners, status sermons, or ‘we optimized’ copy — silent under-hood behavior only; notes in openfdd_agent_spec"
    status: completed
  - id: o-closeout
    content: "Wave O closeout: steps 1–9 CLOSED; only O5 Soft-OPEN; OPS PINNED; full stress + FDD parity + all-HVAC cited; 0 open PRs"
    status: pending
  - id: o11-pypi-agent-pages
    content: "O11 docs (parallel): human-readable GH Pages 'PyPI agent tools' — purpose Excel+E+, calcs, agent→xlsx; fix Drivers duplicate CSV; MORE ITEMS TBD while human inspects — do not close early"
    status: completed
  - id: o12-plotly-download-stems
    content: "O12a: RCx+FDD Plotly PNG downloads never newplot.png — generic type stems (rcx_{family}_{preset}, fdd_{ruleId}_series); PlotlyHost always sets toImageButtonOptions; e2e assert"
    status: completed
  - id: o12-creekside-meter-map
    content: "O12b: LAKESIDE_ES/Creekside package data model OFF — no metering roles mapped but dataset has integrated BAS BACnet electricity meter; remap equipType meter + kwh/electric_kw (or elec_power) so Metering/UTIL/SV see it; do not invent points"
    status: in_progress
  - id: o13-health-post-repin-honesty
    content: "O13: Post-re-pin 'wonky' health — /api/health ingest_ok+edges are since-boot and reset to 0 on container restart while /workspace Parquet survives; add started_at/uptime + last_ingest_at (and optional historian presence) so ops/UI don't read 0 as data loss; stress grace after tip pin; docs one-liner in backup-update-restore"
    status: completed
isProject: false
---

# Wave O — Known bugs patch train (master)

> **For agentic workers:** Continuous Wave O bake — **no deferrals** except **O5** Stage C (commercial). Sub-plans O1–O4 + O6–O10 all close this train. **SPA:** no agent explainer chrome.
>
> **Rule:** Mint scrape → GHCR → Railway → ACME are **ordered steps of the same tip cycle**, not “do later / Soft-OPEN.” Never skip Mint before fieldbus GHCR; never park O10 behind polish.

**Status (2026-09-15):** Railway hub **OPS tip `sha-f25ffcc` / 3.5.19**. O8–O10–O7–O11–O12a–O13–O1–O3–O6–O2 MERGED. **O12b tip 3.5.20** in flight (meter type + utilities→fuel + Data Model historian merge). Remaining Soft-OPEN: **O4** (synth59 zip) · **O5** Stage C.

**Agent one-liner (continuous):**
`after reboot → GHCR+Railway pin 3.5.11 → #926 → O10 HVAC → O3 → O1/O6 → O2a ZAP + O2b Kali MT shared-DB harden → O4 closeout`

**Honest sell path:** Finish this ordered bake before demo — admin UI, site export ACL, full HVAC MQTT, **and** multi-user shared-DB authz bar (O2b) in-scope this train.


**SoT:** [`BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md`](../../docs/operations/BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md) Soft-OPEN · OT BUG_REPORT · [`PATCH_CYCLE.md`](../../docs/operations/PATCH_CYCLE.md) · prior [`wave_n_acme_mt_security_7f2a9c01.plan.md`](wave_n_acme_mt_security_7f2a9c01.plan.md)

---

## Locked decisions

| Decision | Choice |
|----------|--------|
| Ops pin in | `sha-9072e0b` / **3.5.10** · MT ON |
| Patch size | Tiny VERSION per ship (`3.5.11`…) |
| Fieldbus | ACME on-prem only; poll **300 s**; never Railway; **health-roles only** (few sensors, most outputs, key setpoints) |
| ACME HVAC coverage | **O10** — ALL HVAC boxes from site_scan (not eGauge flood); JCI °F + Trane °C |
| rusty-* tips | bacnet tip ([v0.11.0](https://github.com/jscott3201/rusty-bacnet/releases) if MS/TP OK); haystack [v0.8.1](https://github.com/jscott3201/rusty-haystack/releases); modbus [v0.1.1](https://github.com/jscott3201/rusty-modbus) |
| Local compile | **Mint** pre-CI **required**; + BACnet Who-Is/read scrape before any fieldbus GHCR |
| Ship order | Continuous: Mint PASS → PR/GHCR → Railway hub → ACME (same cycle) |
| Spot gates | **31+32** (+33 admin ACL) after every hub+ACME refresh |
| Full stress | After each of O8/O9 tip, O10, O1, O2, O6, O4/closeout |
| Deferrals | **None** for O1–O4/O6–O10 — only **O5** Stage C parked |
| FDD parity | Required when historian layout / import / tenant root changes — same window, same rules → same faults |
| SPA UX | **O7** under-hood cache; **never** add agent “explainer” banners |
| Hub admin console | **O8** — users/tenants/data CRUD; hub_admin only; quiet django-like |
| Data Model export | **O9** — **entire active site** only; no device/point export picker; server ACL |
| Tenant data visibility | Non-admin: own buildings only for mapping, data-model JSON, session/fault configs, FDD/analytics |
| Stage C IdP/MFA | **Parked** (O5) — O8 is file-CP admin UI, not OIDC |
| Secrets | No ACME kits/IPs/passwords in git or public chat |
| Continuous bake | One ordered sequence; parallelize Mint prep while CI runs |
| Docs / PyPI agents | **O11** parallel docs track — GH Pages section **PyPI agent tools** (`docs/ecm/`); not on product tip critical path |
| Local vs Railway validation | **Local Compose (`react` / `react-ot`) is a real product path** — some operators run Open-FDD on the edge/LAN; Mint local compile + stack smoke must prove a **working product**, not a toy. **Majority stress / sell-week bar stays Railway hub** (ACME MQTTS, MT, full stress, gates 31–33). Never claim Railway PASS from local-only; never skip local product smoke before GHCR tip |

---

## Local product validation vs Railway stress (locked)

| Tier | Where | What “PASS” means |
|------|--------|-------------------|
| **Product smoke (required every tip)** | Mint local — `cargo check/test` touched crates · `npm` web build/test · `./scripts/openfdd_stack_up.sh react` or `react-ot` (+ demo gate when UI dirty) | Stack boots, auth, Overview/FDD/RCx/Inspect basic paths, health honest — **edge/LAN deployable product** |
| **OT bench scrape** | Mint BACnet Who-Is/read before fieldbus GHCR | Wire path works before ACME |
| **Stress / sell bar (majority)** | **Railway hub** + on-prem ACME fieldbus → MQTTS | Gates 31–33, continuity, ACL, full HVAC @300s, hub stress closeout |

**Anti-patterns:** Greenwash Railway from local `react-ot` · Skip local stack smoke because “Railway is SoT” · Treat local as agent-only playground · Replace Railway stress with laptop soak.

---

## O11 — GitHub Pages: PyPI agent tools (parallel)

**Goal:** First-class, **human-readable** GH Pages section for ECM engineering: **calcs**, how an **AI agent puts inputs into Excel**, and how that workbook **compares to EnergyPlus** (honesty / FITTED / BALLPARK / NO_EP). Not buried under Operations; not excluded `README.md`.

**Live after merge+Pages deploy:** https://bbartling.github.io/open-fdd/ecm/

| Page | Path | Role |
|------|------|------|
| Section hub | `docs/ecm/index.md` | What it's for + nav |
| **Purpose: Excel + EnergyPlus** | `docs/ecm/purpose-excel-energyplus.md` | Story: agent → xlsx → twin compare |
| Engineering calcs | `docs/operations/ECM_ENGINEERING_MATH.md` | Formulas agents encode |
| Install & overview | `docs/ecm/overview.md` | `pip` / `ECMJob` / CLI |
| Agent rules | `docs/ecm/AGENTS_ECM_ENGINEERING.md` | Provenance guardrails |
| Handoff / golden workbook | `docs/ecm/OPENFDD_AGENT_ECM_HANDOFF.md` | Liberty dual-AHU |
| Upsell brief | `docs/ecm/ENGINEER_UPSELL_BRIEF.md` | Sales / freeze |
| Release checklist | `docs/ecm/PYPI_RELEASE_CHECKLIST.md` | Trusted Publishing |

**Docs hygiene bundled with O11:**
- [x] Fix duplicate **CSV batch import** under Drivers nav (`csv.md` stub + `csv-batch.md` both had `parent: Drivers`) — stub `nav_exclude: true`, index links `csv-batch.html`

**Boundary (must stay explicit on every page):** PyPI wheel ≠ product FDD. Product FDD = DataFusion on GHCR. Wheel = ECM workbooks + pandas oracle for external agents/engineers.

**Ship:** docs-only PR → merge master → confirm Pages Action green → spot-check `/ecm/`, purpose page, Drivers (one CSV). No VERSION bump required unless bundled with a product tip.

**MORE ITEMS TBD (human still inspecting):** Append rows when dumped. Do **not** close O11 until human confirms backlog empty or parked.

Possible follow-ons (placeholders only):
- [ ] More ECM module math pages (boiler, SAT/DAT, schedules, …) — expand as human requests
- [ ] ROI / walkthrough cookbooks (human)
- [ ] Cross-links from root `AGENTS.md` / mcp README to Pages URLs
- [ ] Any other PyPI extras / CLI pages the human adds
- [ ] Other nav duplicates found during human Pages inspection

**Not O11:** Product SPA chrome, embedding ECM in central/web images, claiming wheel as FDD runtime.

---

## O12 — Known product bugs (human-reported 2026-09-14)

### O12a — RCx / FDD Plotly PNG downloads = `newplot.png`

**Symptom:** Mode-bar camera download lost named stems; files save as `newplot.png`. FDD may have had equipment-prefixed names inconsistently; RCx hosts omitted `downloadFilename` entirely.

**Fix (this bake, web tip):**
- `PlotlyHost` **always** sets `toImageButtonOptions.filename` (fallback = sanitized widget `id`) — never rely on Plotly default.
- **RCx:** `rcx_{family}_{presetId}`, plus `rcx_comfort_donut` / `rcx_worst_zones` — **plot-type stems, no equipment label**.
- **FDD Plots:** `fdd_{ruleId}_series` (rule type only; drop equipment from stem).
- Vitest + e2e assert stem present and ≠ `newplot`.

**Not:** equipment-specific download names (Inspect may keep `{equip}_inspect`).

### O12b — Creekside / `LAKESIDE_ES` data model missing metering

**Symptom:** Metering UI / UTIL / SV paths show **no meter** for Creekside, but the package/dataset **does** include an integrated **BAS BACnet electricity meter**. Map is incomplete — not “no meter in the building.”

**Fix:** Package remap (not product hard-code campus): stamp `equipType: meter` (or equivalent) and map roles `kwh` / `electric_kw` (historian also knows `elec_power`) per [`docs/agent/PACKAGE_AUTHORING.md`](../../docs/agent/PACKAGE_AUTHORING.md) · skill `data-modeling`. Re-import / O1 tenant path when ready. **Never invent ZN-T or fake meter points.**

**Close when:** Metering page + optional UTIL-MONTHLY/INTERVAL see the BAS meter on `LAKESIDE_ES`; BUG_REPORT cites before/after map evidence.

**Parallel OK:** O12a web PR while GHCR 3.5.12 Publish runs; O12b package work can ride O1/Creekside re-import.

---

## O13 — Post–re-pin health honesty (felt “wonky”, data OK)

**Context (2026-09-14 Railway tip pin):** Professional path is correct — **image tag only**, same `/workspace` volume; local `railway_central_workspace_backup.sh` is insurance, **not** restore-on-every-patch. Historian Parquet stays on disk.

**What felt wonky:** After central/mqtt restart, public `/api/health` showed `edges: 0` / `ingest_ok: 0` even though packages + Parquet were intact. Operators (and agents) read that as “data gone / hub broken.”

**Root cause:** `ingest_ok` / live `edges` are **process-lifetime** counters in central memory — they reset on every container start. MQTT edges reconnect on the next session / ~**300 s** poll. That is expected; it is **not** volume wipe.

**Fix (product + ops — this train, small tip OK):**

| Change | Why |
|--------|-----|
| `/api/health`: add `started_at` (or `uptime_secs`) + `last_ingest_at` (ISO/unix of last successful MQTT/CSV write this process, nullable after boot) | Separates “just restarted” from “never ingesting” |
| Optional: `historian_reachable` / cheap parquet root present flag (no full DF scan) | Proves durable store without waiting for edges |
| Docs: one paragraph in [`backup-update-restore.md`](../../docs/operations/backup-update-restore.md) + Railway skill — **ingest_ok≠0 is not restore proof**; gate 18 / datasets are |
| Stress / mid-wave gates: **grace window** after re-pin (e.g. allow edges/ingest 0 for ≤1× poll interval) before FAIL continuity | Stop false FAIL-NEW right after tip |
| SPA: if health panel shows edges/ingest, label as **since boot** (quiet — no agent sermon chrome) | Matches O7/O8 “no explainer banners” rule |

**Not O13:** Pushing local backup tarballs back to Railway on every tip · rewriting historian layout · faster than 300 s OT poll.

**Close when:** After a tip re-pin, health clearly shows fresh boot + durable store still OK; stress does not fail solely on post-restart `ingest_ok: 0`; BUG_REPORT cites one Railway tip with evidence.

**Bake order:** Parallel with O10 reconnect wait — cheap honesty win for sell-week demos.

---

## Parallelism (save wall-clock)

| Overlap OK | Do not overlap |
|------------|----------------|
| Mint `cargo check` while drafting PR | Full stress during another re-pin |
| O3 **ops-only** ACME diag while O1 CI runs | Two Railway/ACME refreshes at once |
| Docs draft during GHCR Publish wait | Claiming tip stress from local `react-ot` |
| Hub-only docs PR while fieldbus Publish lags | Skipping 31+32 |

**Collapse:** If O1+O2 land same tip week → one Railway+ACME refresh → one full stress covering both (still prefer one VERSION bump per product merge).

---

## Mint local compile + BACnet scrape (pre-CI / pre-GHCR)

**Required before any fieldbus or OT-affecting GH push:**

| Touch | Fast gate | Avoid |
|-------|-----------|-------|
| Rust | `cargo check -p openfdd-fieldbus` (+ central/web as touched) + focused tests | Docker-build stack images on low-RAM hosts |
| rusty-* | Confirm tip pins (bacnet/haystack/modbus) compile on Mint | Blind crates.io bump without MS/TP scrape |
| Web | `npm --prefix frontend/web run build` or `stack_up react --no-pull --build` | Claiming GHCR web for dirty tree |
| OT scrape | `preflight_free_47808.sh` → `local_bacnet_ot_bench.sh` whois/read/sensor on **192.168.204.11** bench | Skipping scrape and jumping to ACME |
| MQTT kits | `openfdd-provision` → `deploy/mqtt/` (gitignored) | Committing kits / ACME site_scan |

Docs: [`LOCAL_BACNET_BACPYPE3_BENCH.md`](../../docs/operations/LOCAL_BACNET_BACPYPE3_BENCH.md) · [`BACNET_OT_POLICY.md`](../../docs/operations/BACNET_OT_POLICY.md) · skill `openfdd-bacnet-ot-debug`

---

## Bake sequence (execution order — do not reorder)

| Step | Cycle | Work | Exit |
|------|-------|------|------|
| 1 | **O8** | Hub admin REST + `/admin` UI | #925 tip + gate 33 admin ACL |
| 2 | **O9** | Site-wide data-model export + session/config ACL | Same tip as O8 (#925) |
| 3 | **O10** | rusty-* tip + full HVAC health catalog @300s + ACME→Railway healthy | Mint scrape → fieldbus GHCR → ACME ≥1×300s + gate 32 |
| 4 | **O7** | Overview site-switch cache (under-hood) | Same or immediate next web tip |
| 5 | **O3** | Metric Trane FDD + MSTP addressing | On live O10 streams |
| 6 | **O1** | CSV `tenants/{tid}/` + import write ACL | Tip + gate 31 + historian proof |
| 7 | **O6** | Historian perf + admin data limits + FDD parity | Full stress + parity artifacts |
| 8 | **O2** | **O2a** audit asserts + Kali ZAP disposition · **O2b** shared-DB harden + **beefed CI/stress authz tests** (no Kali here) | Full stress + IDOR/admin/header proofs |
| 9 | **O4** | Mint M5 residual → fully_qualified | Closeout stress |
| — | **O5** | Stage C IdP/MFA | **Only Soft-OPEN** (commercial) |
| ∥ | **O11** | GH Pages **PyPI agent tools** section (`docs/ecm/`) | Docs PR + Pages green; expand when human dumps more |
| ∥ | **O12a** | Plotly PNG stems (RCx/FDD ≠ `newplot.png`) | Web tip + vitest/e2e |
| ∥ | **O12b** | Creekside meter data-model map | Package remap + Metering proof on `LAKESIDE_ES` |
| ∥ | **O13** | Post–re-pin health honesty (`ingest_ok`/`edges` since-boot) | Health fields + stress grace + docs |

**Parallelism (save wall-clock, still no deferral):** After reboot resume → GHCR+Railway pin → while #926 CI → O10 Mint prep. O2b mapping can draft offline during O10 GHCR wait; **do not** ship O2b product until after O1 tenant paths are in place (shared-DB ACL depends on tenant building scope). **O11** docs can ship in parallel anytime (docs-only).

Sub-plans: [`wave_o8_…`](wave_o8_hub_admin_console_ce235993.plan.md) · [`wave_o9_…`](wave_o9_site_datamodel_export_acl_ce235993.plan.md) · [`wave_o10_…`](wave_o10_acme_full_hvac_health_mqtt_ce235993.plan.md) · [`wave_o7_…`](wave_o7_overview_site_cache_ce235993.plan.md) · [`wave_o3_…`](wave_o3_acme_metric_mstp_ce235993.plan.md) · [`wave_o1_…`](wave_o1_tenant_historian_ce235993.plan.md) · [`wave_o6_…`](wave_o6_historian_perf_fdd_parity_ce235993.plan.md) · [`wave_o2_…`](wave_o2_audit_zap_ce235993.plan.md) · [`wave_o4_…`](wave_o4_mint_m5_ce235993.plan.md)

---

## Sell week — continuous train (nothing deferred)

```text
HOLD: Mint reboot → resume agent
THEN: GHCR tip 3.5.11 → Railway backup+pin → gate 31+33
THEN: merge #926 (O7) → free 47808 → Mint scrape → O10 rusty+catalog → GHCR fieldbus → ACME
THEN: O3 metric/MSTP → O1 → O6 → O2a ZAP + O2b Kali shared-DB harden → O4 closeout
DEMO: admin CRUD + site export ACL + full HVAC @5min + multi-user authz bar on Railway
```

## O0 hygiene

- [ ] Wave O BUG_REPORT SoT + link Wave N Soft-OPEN
- [ ] SESSION_LOG kickoff
- [x] **HOLD until Mint reboot** (human) — no product/security implementation until resume
- [ ] Every PR: Mint compile → Every merge: GH tidy → Every re-pin: ACME + **31+32** (+ O8 admin ACL when shipping O8)

```text
Mint check → PR → CI → squash+delete → GHCR tip → GH tidy
  → Railway backup → re-pin central→mqtt→web
  → private ACME fieldbus sha-* → health + edges + ingest_ok
  → gates 31+32
  → full stress at O8/O9, O10, O1, O2, O6, O4 steps
  → BUG_REPORT + agent_spec
```

| Checkpoint | Refresh | Full stress? |
|------------|---------|--------------|
| Mid-PR | Mint only | No |
| Every product merge | Railway + ACME | 31+32 only |
| O1 / O2 / **O6** / **O8** / **O9** / **O10** ship | same | **Yes** (+ FDD parity O1/O6; ACL O8/O9; **all-HVAC @300s** on O10) |
| O3 (step 5) | ACME live | soak+31+32 |
| O7 (step 4) | tip web | Mint A↔B + prefer shared tip |
| O4 (step 9) | tip hub+ACME | **Yes** closeout |

```bash
./scripts/check_ghcr_tip_stack.sh sha-<7>
./scripts/railway_central_workspace_backup.sh
# re-pin central→mqtt→web; private ACME fieldbus refresh; gates 31+32
./scripts/nightly-ot-bench/run_railway_hub_stress.sh   # ship pins / closeout only
# O1/O6: FDD parity artifacts under reports/… (baseline vs after)
```

Skills: `openfdd-railway-cli` · `openfdd-stress-closeout` · [`STRESS_CLOSEOUT.md`](../../docs/operations/STRESS_CLOSEOUT.md) · [`AFDD_MODES.md`](../../docs/operations/AFDD_MODES.md) · [`HISTORIAN_SCALE_QUALIFICATION.md`](../../docs/operations/HISTORIAN_SCALE_QUALIFICATION.md)

**Validated tip** = Railway central/mqtt/web **and** ACME fieldbus on same `sha-*` family. Live OT = **ACME→Railway**; bensbench x86 = stress-kit path — do not mix evidence rows.

---

## O6 — Historian perf (mass CSV + MQTT) + FDD result parity

Stay on **DataFusion + Parquet**. Optimize governance/layout — do not swap engines.

| Workstream | Intent | Product vs ops |
|------------|--------|----------------|
| **Unify write layout** | CSV package ingest → canonical Hive `history/building_id=…/part-*.parquet` (same as MQTT); retire dual legacy sidecar hot path | Product (after O1 tenant roots) |
| **Import admission** | Queue / per-tenant concurrency / backpressure beyond zip MB cap for mass uploads | Product |
| **Admin data limits** | Hub **admin** sets retain window + size budget; **defaults bind first**: **365 days** OR **GiB cap** (start **1–5 GiB**/tenant-or-building — pick one default in PR, document). Import/MQTT/query reject or trim past policy | Product + Ops UI/API |
| **Query budgets** | Extend beyond L5 FDD/job counters: analytics/import respect data limits; keep `OPENFDD_QUERY_MEMORY_MB` / spill | Product + ops |
| **Compaction** | Keep H4 **offline-only**; never compact under live DF scans; schedule after soak | Ops (runtime coordinator = later Soft-OPEN) |
| **Concurrent CSV+MQTT** | Stress: package import(s) on building A while MQTT/AFDD on building B (and same-building only if layout unified) | Stress |

### Admin data limits (defaults)

Today: zip uncompressed cap (~512 MB) + optional FDD/job rate budgets — **no** hub-admin retention/size SoT for historian mass data.

**Ship in O6:**

| Knob | Default | Who sets | Effect |
|------|---------|----------|--------|
| Retain window | **365 days** | Hub admin (API/UI); env bootstrap OK | Historian reads/writes/FDD windows clamp to `[now-retain, now)`; older Parquet eligible for offline GC |
| Size budget | **~1–5 GiB** per tenant (MT) or per building (single-hub) — finalize number in PR + docs | Hub admin | New CSV import / MQTT part publish **403/429** or spill-reject when over; never silent truncate mid-FDD |
| Whichever binds first | Both active | — | Shorter of time-or-bytes wins |
| Override | Admin only | Hub admin / `hub_admin` | Raise for demos; audit log change |

Stress: import oversize package → deny; FDD on in-window data → **same parity** as baseline within limit; MQTT continues under cap without poisoning FDD math.

### FDD parity stress (required on O1 migrate + O6 ship)

**Pass = same DataFusion FDD outcomes** for a fixed window — not “looks similar.”

```text
1. Baseline (tip pin, before mutate):
   - Pick fixture building(s): synth59 and/or BUILDING_100 / known package
   - Run registry FDD (same rule_ids, same start_utc/end_utc, unit_system)
   - Snapshot: per rule_id × equipment → fault_count (and series digest if available)
2. Apply change (tenant migrate / Hive CSV write / import queue / data limits / concurrent MQTT)
3. Re-run identical FDD window on same tip family (window must fit inside retain default)
4. Assert snapshots equal (or document intentional contract change — never silent drift)
5. Concurrent soak: while MQTT ingest_ok advances, re-run FDD on CSV building → parity still holds
6. Data-limit soak: fill near GiB/day cap → further import denied; in-window FDD still matches baseline
```

Artifacts: `reports/wave_o_fdd_parity_<UTC>/` (`baseline.json`, `after.json`, `diff.txt`, pin sha). Cite in BUG_REPORT. Synth59 **59/59** remains the honest matrix bar when that fixture is in scope.

Mint pre-CI: `cargo check` on `fdd_store` / `fdd_sql` / central ingest; optional H10 light workload — not a substitute for Railway tip-pin parity.

---

## O7 — Overview site-switch cache (under-hood only)

**Problem:** Changing `?site=` clears Overview and re-fires a DataFusion analytics fan-out (charts + ~10 health matrices), often **twice**, plus again on tab focus. FDD **results** are already durable (`GET /api/fdd/results`); the wonky feel is redundant **live** analytics, not a Rust-vs-React packaging issue.

**Do not:** embed SPA in Rust central, rewrite Overview as Streamlit, or add UI text like “Cached”, “Optimized”, “AI refreshed”, “Loading analytics for…” sermons, or agent tip banners about this change.

**Do (invisible):**

| Fix | Touch |
|-----|--------|
| Per-`buildingId` in-memory (or React Query) cache of Overview + health envelopes — show last site **instantly** | `OverviewPopulated.tsx`, `centralOverview.ts`, health sections |
| Stop double fetch — no `vavHealthToken` bump on overview success; drop unstable `equipment` from refresh deps | `OverviewPopulated.tsx` |
| Invalidate / hard refetch only on `RULES_UPDATED`, explicit refresh control that **already exists**, or proven ingest invalidation — not every site switch / `visibilitychange` | same |
| Prefer durable FDD for matrix flags; optional later one-shot `overview-health` API | `plant_health.rs` / frontend (only if needed) |
| Mint: `npm run build` + local web smoke A↔B site switch feels instant | demo gate |

**Acceptance:** Switch BUILDING_100 ↔ LAKESIDE_ES (or ACME ↔ CSV) without blanking tables into a long DF storm; network panel shows **cached hit or single soft refresh**, not N× plant-health POSTs twice. Existing chrome unchanged — **less** text, not more.

Agent notes: [`openfdd-react-spa`](../../openfdd_agent_spec/skills/openfdd-react-spa/SKILL.md) · [`AGENTS.md`](../../openfdd_agent_spec/AGENTS.md) UI copy rule.

---

## O8 — Hub admin console (sell MQTTS+CSV accounts)

**Have today (Wave N):** Shared Railway workspace · `multi_tenant=true` · three tenants (ACME / B100 / Lakeside) · file `users.json` logins · building ACL · gate **31** (non-admin deny foreign mapping/series; hub `admin` lists all) · ACME MQTTS streaming tested.

**Missing (why you don’t see it):** No `/admin` React console; no `/api/users` CRUD — provisioning is still **edit control-plane JSON + Railway secrets**. Sites can delete a dataset; that is **not** tenant/user admin.

**Ship O8:**

| Capability | Spec |
|------------|------|
| Who | JWT `hub_admin` / role admin only — 403 for tenant ops/agent |
| Users | List / create / disable / reset password / assign `tenant_ids` + roles |
| Tenants | List / create / edit `building_ids` map (tie MQTT site_id + CSV building) |
| Data | Purge tenant or building historian under policy (confirm); respect O6 data limits |
| UI | Quiet **django-admin-like**: plain tables, forms, confirm dialogs — **no** AI tip chrome |
| API | Persist to `control_plane/users.json` + `tenants.json` (atomic write); audit every change |
| Stress | Extend gate 31: tenant user cannot list/CRUD users or see foreign buildings; hub admin sees all tenants + can open any building; after delete user, login fails |

**Not O8:** OIDC IdP / MFA / SKU billing (remain **O5** Soft-OPEN). O8 = product admin over the file CP you already sell with.

---

## O9 — Site-wide data-model export + ACL (sell week)

**Problem:** Export on Data Model feels like device/point selection. Buyers need **one export = whole active site**. Auth must prove non-admin cannot pull another tenant’s model or configs.

**Ship O9:** See [`wave_o9_site_datamodel_export_acl_ce235993.plan.md`](wave_o9_site_datamodel_export_acl_ce235993.plan.md).

| Capability | Spec |
|------------|------|
| Export scope | **Active site only** — full equipment/roles/columns/validation JSON |
| Kill | Device-only / point-only / multi-select export UX |
| Edit UX | Equipment picker remains for **mapping edits** only — not for export |
| Auth | Building ACL on mapping + data-model download + session/fault config GET/PUT |
| Stress | Pairwise tenant JWT: own site **200** (full equip list); foreign **403**; admin all |

Prefer **same tip** as O8.

---

## O2 — Audit / ZAP + multi-user shared-DB security (Railway)

> **Source brief:** Security agent on **Kali** testing Railway multi-user shared-database rollout (2026-09-14). Folded into Wave O — **not Soft-OPEN**. Sub-plan: [`wave_o2_audit_zap_ce235993.plan.md`](wave_o2_audit_zap_ce235993.plan.md).
>
> **Division of labor (locked):**
> - **External Kali agent** — live AF / ZAP / exploratory Railway pen-test. Cite their findings in BUG_REPORT; do **not** run Kali or ActiveScan from this Mint/Cursor agent.
> - **This agent (Mint + CI)** — product fixes + **beefed automated tests** (unit/integration/stress gates) that prove ACL/IDOR/admin/redirect/headers forever. Prefer fail-closed CI over one-off pen-test.
>
> **Do not start implementation until after Mint reboot resume** (`o0-reboot-hold`).

### O2a — Audit asserts + ZAP disposition (ZAP run = Kali agent)

- Assert `security_audit` events on deny / select / import under hub stress (this agent)
- **ZAP AF / ActiveScan:** external Kali agent only — Medium+ disposition notes land in `BUG_REPORT_WAVE_O`
- Never ActiveScan production OT MQTT path from Mint

### O2b — Multi-user shared-DB harden + **beefed test bar** (this agent)

**Phase A — Map (read-only first):** Authn/authz, API routes, data models, admin functions, invitations/sharing, exports, uploads, Railway deploy config. Produce a **concise permission matrix** for every resource/endpoint. Flag where authz is **absent**, **client-side only**, or vulnerable to **IDOR/BOLA** / **mass assignment**.

**Phase B — Minimal safe fixes (server-side):**

| Area | Requirement |
|------|-------------|
| Ownership / tenant | Enforce server-side checks on **every** read/write/delete/export (building + tenant scope; hub_admin exception only) |
| Mass assignment | Explicit **allowlists** for writable fields on user/tenant/session/config/import bodies |
| Admin | Protect hub-admin-only actions (`/api/admin/*` and equivalents) — 403 for tenant ops/agent |
| Post-login `from` | Validate redirects as **same-origin relative paths** only |
| Cookies / CSRF | Secure cookie flags; CSRF where cookie auth is used |
| Auth abuse | Rate limit login / recovery / agent-token endpoints |
| CORS | Restrictive production CORS |
| Errors | Production-safe error handling (no stack/secret leakage) |
| Browser headers | Tested **CSP** compatible with Google Fonts + Plotly; **HSTS** only if HTTPS-only; `X-Content-Type-Options: nosniff`; `Referrer-Policy: strict-origin-when-cross-origin`; `CSP frame-ancestors` or `X-Frame-Options` |
| `security.txt` | Serve `/.well-known/security.txt`; SPA fallback must **not** return HTML for it |

**Phase C — Beefed automated tests (this agent — required, not optional):**

Expand beyond “happy path.” Prefer **table-driven** pairwise JWT tests wired into CI and/or `scripts/nightly-ot-bench/33_*` (+ new `34_wave_o_security_*` if needed).

| Suite | Must prove |
|-------|------------|
| **IDOR/BOLA matrix** | User A JWT × foreign `building_id` / tenant / equipment / mapping / session-config / data-model export / FDD results / analytics / historian path → **403** (not empty 200) |
| **Admin surface** | Tenant ops + agent JWT → **403** on every `/api/admin/*` (list/upsert/delete users & tenants, disable) |
| **Mass assignment** | PUT/POST with extra fields (`role=Admin`, foreign `tenant_ids`, `disabled=false` self-heal, arbitrary config keys) → ignored or **400**; store unchanged |
| **Redirect** | Login / auth `from=` with `//evil`, `https://evil`, `\evil`, absolute foreign → rejected; only `/…` relative same-origin accepted |
| **Headers** | Response assertions: CSP (Fonts+Plotly allowlist), nosniff, Referrer-Policy, frame-ancestors/XFO; HSTS only when HTTPS profile |
| **`security.txt`** | `GET /.well-known/security.txt` → **200 text/plain** (or documented type); **not** `text/html` SPA shell |
| **CORS** | Disallowed Origin → no `Access-Control-Allow-Origin` reflect; allowed origin explicit |
| **Rate limit** | Burst login / agent-token → **429** (or documented throttle) without lockout DoS of hub_admin recovery path |
| **Audit** | Each deny above emits named `security_audit` event (gate assert) |
| **Negative empty** | Foreign resource never returns **200 + empty body** as soft leak |
| **Secrets hygiene** | Grep/CI: no passwords/JWTs/Railway tokens in fixtures, snapshots, or client bundles |

**Exit:** Matrix in BUG_REPORT/docs · product tip green · gates **31+33** (+ new 34 if added) PASS · Kali agent ZAP disposition cited (external) · Railway tip pin after merge.

**Not O2b:** Stage C IdP/MFA/SKU (remain **O5**). This agent does **not** operate Kali.

---

## O10 — ACME ALL HVAC health MQTT @ 300 s (+ rusty tip)

**Problem:** ACME is **not** set up for whole-HVAC MQTT FDD. Exported data model showed only `rtu_01`/`oa_t`. Site scan lists full plant (JCI VMA imperial, Trane VAV metric, RTU, HW, TECs, Tracer). Catalog must cover **all HVAC** with **minimal health points** so fault equations can run without flooding MS/TP.

**Ship O10:** See [`wave_o10_acme_full_hvac_health_mqtt_ce235993.plan.md`](wave_o10_acme_full_hvac_health_mqtt_ce235993.plan.md).

| Rule | Spec |
|------|------|
| Interval | **300 s** fixed poll + MQTT publish |
| Points | Health/FDD roles only — few sensors, most outputs, some setpoints (~30% ethos) |
| Devices | **All** HVAC from site_scan (every JCI VMA + Trane VAV + RTU + HW + needed TEC/Tracer); **not** full eGauge trees |
| Units | JCI → °F/imperial; Trane VAV → °C/metric (honest FDD; ties O3) |
| Crates | Tip [rusty-bacnet](https://github.com/jscott3201/rusty-bacnet/releases) / [rusty-haystack](https://github.com/jscott3201/rusty-haystack/releases) / [rusty-modbus](https://github.com/jscott3201/rusty-modbus) after Mint scrape proves MS/TP |
| Gate | Immediate next tip after #925: Mint scrape → GHCR → ACME refresh → all-HVAC healthy + gate 32 |

---

## Never

- Fieldbus on Railway · ActiveScan live OT · Stage C “done” · failed tip Actions / open PRs · ACME secrets / site_scan dumps in git · greenwash · invent MSTP values · claim Railway PASS from local `react-ot` · claim FDD parity without baseline/after artifacts · reintroduce Feather SoT · runtime compaction overlapping DF scans · **agent/explanatory UI chrome** · claim “admin UI exists” when only Sites delete + file CP · expose user CRUD to non–hub_admin · ship **per-device/point** data-model export · claim config ACL without gate proof · **GHCR/ACME before Mint BACnet scrape PASS** · **park O10/O7/O1 as Soft-OPEN** · poll faster than **300 s** · flood eGauge/full object trees as “HVAC health” · claim ALL HVAC streaming when data model is still `rtu_01`/`oa_t` only

---

## Closeout

- [ ] Steps **1–9** CLOSED in bake order (O8→O9→O10→O7→O3→O1→O6→O2→O4) · only **O5** Soft-OPEN
- [ ] OPS PINNED tip · MT ON · Railway+ACME same sha-* family · full stress cited
- [ ] **FDD parity** artifacts for O1/O6
- [ ] **O7** snappy site switch (no new UI copy)
- [ ] **O8/O9** tip + gates 31+33 PASS
- [ ] **O10** all-HVAC @300s healthy + gate 32 (same week as #925 tip — not Soft-OPEN)
- [ ] **O2a** audit+ZAP disposition · **O2b** Kali multi-user shared-DB matrix + ACL/headers/`security.txt` + IDOR/admin/redirect/header tests
- [ ] rusty-* tip pins cited
- [ ] 0 open PRs · `master` only · tip Actions green
