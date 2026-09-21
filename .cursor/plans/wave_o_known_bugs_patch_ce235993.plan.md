> **SUPERSEDED by Wave U** — do not play. Active master: [`docs/operations/WAVE_U_MASTER.md`](../../docs/operations/WAVE_U_MASTER.md) · [`.cursor/plans/wave_u_security_hardening_master.plan.md`](wave_u_security_hardening_master.plan.md). Retained as historical/child detail only.

---
name: Wave O Known Bugs Patch
overview: "Wave O product bake CLOSED on master through 3.5.20 (#934). Soft residuals + final stress/GH tidy owned by Wave P. Kali owns live hub — Mint does not Railway re-pin. O2c Kali V1–V3 + MT matrix land on Wave P tip branch."
todos:
  - id: o0-bootstrap
    content: "O0: Seed BUG_REPORT_WAVE_O + pointer from Wave N/OT reports; sync ops pin; agent_spec SESSION_LOG Wave O kickoff"
    status: completed
  - id: o0-local-bacnet-bench
    content: "Optional: Mint local BACnet Who-Is + MQTTS pipeline smoke"
    status: completed
  - id: o0-hygiene-gate
    content: "O0: delete stale wave-o* remotes; tip Actions green; 0 open PRs after tip merge — residual GH tidy = Wave P p9"
    status: completed
  - id: o0-reboot-hold
    content: "HOLD lifted — continuous bake"
    status: completed
  - id: o1-tenant-historian
    content: "O1 write ACL CLOSED 3.5.16; Soft path migrate tenants/{tid}/ → Wave P p3-*"
    status: completed
  - id: o2-audit-zap
    content: "O2a gates 31/33/34 MERGED #932/#933; Soft volume security_audit.jsonl assert → Wave P p2-audit-gate-assert; ZAP=Kali"
    status: completed
  - id: o2-kali-mt-shared-db
    content: "O2b/O2c Mint product harden (V1–V3 + IDOR matrix + admin/agent) on Wave P tip; Kali ZAP/MQTT staging Soft"
    status: completed
  - id: o2c-preauth-tenants
    content: "O2c V1 tenants JWT + tests"
    status: completed
  - id: o2c-preauth-topology
    content: "O2c V2 topology JWT"
    status: completed
  - id: o2c-web-headers
    content: "O2c V3 CSP Fonts + HSTS + security.txt"
    status: completed
  - id: o2c-mt-isolation-matrix
    content: "O2c MT select/datapath/admin/agent tests green; MQTT broker proof Soft→Wave P/Kali"
    status: completed
  - id: o3-acme-metric-mstp
    content: "O3 metric/MSTP CLOSED ops (Trane °C vs JCI °F)"
    status: completed
  - id: o4-mint-m5
    content: "O4 Mint M5 Soft (synth59/kit) → Wave P p4-*"
    status: completed
  - id: o5-stage-c-park
    content: "O5 PARKED Soft-OPEN IdP/MFA/SKU → Wave P p5-stage-c-park"
    status: completed
  - id: o6-historian-perf-parity
    content: "O6 historian limits + FDD clamp CLOSED #931 / 3.5.17; Soft Hive migrate with O1→Wave P"
    status: completed
  - id: o6-admin-data-limits
    content: "O6 admin retain/size API/UI CLOSED #931"
    status: completed
  - id: o7-overview-site-cache
    content: "O7 Overview site cache CLOSED #926"
    status: completed
  - id: o8-hub-admin-console
    content: "O8 hub admin CLOSED #925"
    status: completed
  - id: o8-sell-week-gate
    content: "O8 sell-week gate CLOSED"
    status: completed
  - id: o9-site-datamodel-export-acl
    content: "O9 site export ACL CLOSED #925"
    status: completed
  - id: o10-acme-full-hvac-mqtt
    content: "O10 full HVAC @300s CLOSED 3.5.15 (hw_plant Soft BIP)"
    status: completed
  - id: o-hold-build
    content: "HOLD lifted"
    status: completed
  - id: o-mint-before-ghcr
    content: "Standing process — Wave P p6-ghcr-refresh-policy"
    status: completed
  - id: o-rusty-tip-pins
    content: "rusty-* tips confirmed for O10 fieldbus train"
    status: completed
  - id: o-cycle-template
    content: "Standing tip cycle — Wave P owns next tips"
    status: completed
  - id: o-local-compile-gate
    content: "Standing Mint local compile/test before push"
    status: completed
  - id: o-full-stress-pins
    content: "Full hub stress residual → Wave P p5-final-hub-stress (Kali hub lock)"
    status: completed
  - id: o-fdd-parity-gate
    content: "Standing FDD parity on layout change → Wave P p6-fdd-parity-on-layout"
    status: completed
  - id: o-ui-no-agent-chrome
    content: "Hard rule enforced; Wave P SPA batch follows"
    status: completed
  - id: o-closeout
    content: "Wave O product bake CLOSED; exit OPS PINNED + GH tidy = Wave P p9 (not this plan)"
    status: completed
  - id: o11-pypi-agent-pages
    content: "O11 PyPI Pages CLOSED #927"
    status: completed
  - id: o12-plotly-download-stems
    content: "O12a Plotly stems CLOSED #927"
    status: completed
  - id: o12-creekside-meter-map
    content: "O12b Creekside meter CLOSED #934 / 3.5.20"
    status: completed
  - id: o13-health-post-repin-honesty
    content: "O13 health honesty CLOSED #928 / 3.5.14"
    status: completed
isProject: false


# Wave O — Known bugs patch train (master)

> **For agentic workers:** Continuous Wave O bake — **no deferrals** except **O5** Stage C (commercial). Sub-plans O1–O4 + O6–O10 all close this train. **SPA:** no agent explainer chrome.
>
> **Rule:** Mint scrape → GHCR → Railway → ACME are **ordered steps of the same tip cycle**, not “do later / Soft-OPEN.” Never skip Mint before fieldbus GHCR; never park O10 behind polish.

**Status (2026-09-15):** Wave O **product bake CLOSED** on master through **3.5.20** (`aea817fd` / #934 O12b). Soft residuals (tenant path migrate, audit volume assert, synth59, Stage C, final stress, GH tidy, Kali MQTT) live in **Wave P** — [`.cursor/plans/wave_p_residual_stress_gh_tidy_ce235993.plan.md`](wave_p_residual_stress_gh_tidy_ce235993.plan.md) · [`BUG_REPORT_WAVE_P.md`](../../docs/operations/BUG_REPORT_WAVE_P.md). **No Railway re-pin while Kali owns hub.**

**Agent one-liner:**
`Wave O CLOSED → Wave P tip (docs/SPA/O2c) → wait Kali unlock → GHCR re-pin → ONE hub stress → P9 GH tidy`

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

> **Source brief:** Security agent on **Kali** (2026-09-14 map + **2026-09-15 verified pre-auth findings**). Folded into Wave O **and** Wave P Phase 3 tip (`p2c-*`). Sub-plan: [`wave_o2_audit_zap_ce235993.plan.md`](wave_o2_audit_zap_ce235993.plan.md).
>
> **Division of labor (locked):**
> - **External Kali agent** — live AF / ZAP / exploratory Railway pen-test. Cite findings; do **not** ActiveScan from Mint.
> - **This agent (Mint + CI)** — product fixes + automated tests proving ACL/IDOR/headers forever.

### O2c — Kali verified pre-auth disclosures (2026-09-15) — HARD

| # | Finding | Fix | Status (local 2026-09-15) |
|---|---------|-----|---------------------------|
| **V1** | `GET /api/tenants` unauth → Admin via `dev_anonymous()` → full tenant/building roster | JWT-protected; never Admin anonymous for listing; A/B/admin scoped tests | **DONE** — `preauth_disclosure` |
| **V2** | Unauth `capabilities` / `health/stack` / `building/snapshot` / `dashboard/summary` leak MCP, protocols, paths, flags | Protected router (401 when auth ON); `/api/health` stays lean public | **DONE** |
| **V3** | CSP Fonts / HSTS / `security.txt` | nginx Fonts allowlist + HSTS on HTTPS; `security.txt` not SPA HTML | **DONE** (gate 34 hub live / Kali) |

**Critical follow-on:** Tenant A/B/admin IDOR matrix (select + mapping + FDD + analytics **green** in `mt_isolation_matrix_select_and_datapath`); expand jobs/exports/agent mint; same `building_id` two tenants Parquet namespace; MQTT mTLS+ACL on staging (**Kali**). Railway: only web public. **No Railway re-pin while Kali owns hub.**

**Tests:** `services/central/tests/preauth_disclosure.rs` · gate 31 · gate 34. Skill: `openfdd_agent_spec/skills/openfdd-mt-security`.

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
