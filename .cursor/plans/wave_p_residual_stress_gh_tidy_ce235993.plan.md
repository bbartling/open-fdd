---
name: Wave P Residual Stress GH Tidy
overview: "Wave P owns Wave O Soft residuals. Local docs/SPA/O2c Mint DONE on branch. Soft: tenant migrate, audit volume assert, synth59, ACME HW expands, Stage C, final stress, GH tidy. No Railway re-pin while Kali owns hub. ≤3 GHCR after unlock."
todos:
  - id: p0-finish-o12b
    content: "#934 MERGED 3.5.20; GHCR hub publishing; fieldbus Docker Hub 500 re-run; Railway re-pin DEFERRED (Kali)"
    status: completed
  - id: p0-hygiene-baseline
    content: "Inventory/delete stale origin wave-o* tip remotes; cancel superseded fails; record in BUG_REPORT_WAVE_P"
    status: completed
  - id: p1-seed-bug-report
    content: "Seed BUG_REPORT_WAVE_P.md + Wave O Soft pointer + SESSION_LOG"
    status: completed
  - id: p2-audit-gate-assert
    content: "Soft: wire security_audit.jsonl volume assert into gate 31/33 (HTTP ACL already green #932)"
    status: pending
  - id: p2b-kali-zap-disposition
    content: "Mint harden for Kali findings DONE (V1–V3+matrix); live ZAP disposition = Kali Soft"
    status: completed
  - id: p2c-tenants-auth
    content: "Kali V1 tenants JWT"
    status: completed
  - id: p2c-public-apis
    content: "Kali V2 topology JWT"
    status: completed
  - id: p2c-web-headers
    content: "Kali V3 CSP/HSTS/security.txt"
    status: completed
  - id: p2c-mt-isolation-matrix
    content: "MT IDOR+admin/agent tests green; MQTT staging proof Soft (Kali)"
    status: completed
  - id: p8i-agent-skill-plot-poll
    content: "openfdd-rcx-fdd-plot-poll skill"
    status: completed
  - id: p8j-fdd-weather-plot-parity
    content: "FDD weather/OAT-METEO overlay"
    status: completed
  - id: p8l-fdd-econ-oa-damper
    content: "FDD econ oa_damper overlay"
    status: completed
  - id: p8m-sidebar-scroll-contain
    content: "Sidebar scroll contain"
    status: completed
  - id: p8n-fdd-plots-no-debug-chrome
    content: "FDD Plots no debug chrome"
    status: completed
  - id: p8k-rcx-vav-health-viz
    content: "RCx vav_health matrix viz"
    status: completed
  - id: p8e-datamodel-ui-all-points
    content: "Data Model all points"
    status: completed
  - id: p8f-datamodel-fdd-rule-annotate
    content: "Data Model FDD annotate"
    status: completed
  - id: p8g-datamodel-export-layout
    content: "Data Model export layout"
    status: completed
  - id: p-docs-gh-pages
    content: "GH Pages docs wave"
    status: completed
  - id: p-docs-ops-blast
    content: "Operations nav_exclude blast"
    status: completed
  - id: p-docs-quickstart-bootstrap
    content: "Quick Start local+Railway"
    status: completed
  - id: p3-tenant-path-inventory
    content: "Soft: inventory hub-root vs tenants/* (needs Railway volume; Kali lock)"
    status: pending
  - id: p3-tenant-path-migrate
    content: "Soft: backup-first tenants/{tid}/ migrate"
    status: pending
  - id: p3-tenant-path-proof
    content: "Soft: ACL+FDD parity after migrate"
    status: pending
  - id: p4-mint-m5-kit
    content: "Soft: MQTT edge kit / skip-kit path"
    status: pending
  - id: p4-mint-m5-synth59
    content: "Soft: synth59 handoff zip missing"
    status: pending
  - id: p5-final-hub-stress
    content: "Blocked until Kali unlock + last tip pin + synth59 honesty"
    status: pending
  - id: p6-ghcr-refresh-policy
    content: "Standing ≤3 tips / Mint compile before push / newest-by-created"
    status: completed
  - id: p6-ui-no-agent-chrome
    content: "SPA batch follows no agent chrome"
    status: completed
  - id: p6-fdd-parity-on-layout
    content: "Soft: run when P3 migrate lands"
    status: pending
  - id: p7-clippy-analytics-hygiene
    content: "Optional clippy analytics"
    status: pending
  - id: p8-hw-plant-soft
    content: "ACME HW/boiler Soft→HARD after Kali unlock + Mint scrape"
    status: pending
  - id: p8c-acme-weather-oat-meteo
    content: "ACME weather Soft after unlock"
    status: pending
  - id: p8d-acme-rtu-health-roles
    content: "ACME rtu_01 health roles Soft after unlock"
    status: pending
  - id: p8h-vav-rcx-fdd-roles
    content: "ACME VAV poll expand Soft after unlock"
    status: pending
  - id: p8b-metric-mstp-soak
    content: "Cite Trane/JCI/MSTP in WAVE_P after tip stress"
    status: pending
  - id: p5-stage-c-park
    content: "Stage C IdP/MFA/SKU Soft-OPEN"
    status: pending
  - id: p-park-edge-telemetry-ui
    content: "PARKED Wave Q"
    status: cancelled
  - id: p9-gh-tidy-closeout
    content: "EXIT: 0 open PRs; stale remotes gone; OPS PINNED + fully_qualified cited"
    status: pending
isProject: false


# Wave P — Residual known bugs + final stress + GH tidy

> **For agentic workers:** Follow **§ Ordered execution (locked)** top-to-bottom. Do **not** scramble tips or re-pin Railway mid-batch. **Owns all unfinished Wave O todos** (ported below). Parent: [`wave_o_known_bugs_patch_ce235993.plan.md`](wave_o_known_bugs_patch_ce235993.plan.md).
>
> **Exit rule:** Wave P is not done until **P5 final Railway hub stress** is cited on the **last** tip `sha-*` **and** **P9 GH tidy** is true (0 open PRs, no stale tip branches, no hanging failed Actions on tip).

**Goal:** Close Soft-OPEN with **≤3 GHCR Publishes**, one **final** Railway+ACME stress toward `fully_qualified=true`, then GH tidy.

**Architecture:** Mint local compile/test → PR → CI → squash → GHCR `sha-*` (newest-by-created) → Railway hub re-pin → ACME fieldbus refresh (when fieldbus moved) → spot gates → next phase. **Never** stress until the last product tip is pinned.

**Tech stack:** `openfdd-central` / `openfdd-web` / `openfdd-mqtt` / `openfdd-fieldbus` GHCR; Railway hub; on-prem ACME; gates `31`/`32`/`33`/`34`; `scripts/nightly-ot-bench/run_railway_hub_stress.sh`; `scripts/openfdd_railway_release.sh`; `scripts/ghcr_newest_by_created.py`.

**Pin in:** Railway `sha-f25ffcc` / **3.5.19** · `multi_tenant=true`  
**Pin out:** newest-by-created after **GHCR #3** (or #2 if SPA rode an earlier tip) + **P5 stress cited**

---

## Ported from Wave O (nothing left behind)

| Wave O todo id | Was | Wave P owner |
|----------------|-----|--------------|
| `o12-creekside-meter-map` | in_progress (#934) | **p0-finish-o12b** |
| `o0-hygiene-gate` | in_progress | **p0-hygiene-baseline** + **p9-gh-tidy-closeout** |
| `o4-mint-m5` | pending | **p4-mint-m5-kit** + **p4-mint-m5-synth59** + **p5-final-hub-stress** |
| `o5-stage-c-park` | pending | **p5-stage-c-park** |
| `o-closeout` | pending | **p5-final-hub-stress** + **p9-gh-tidy-closeout** |
| Soft residual **wave-o1-tenant-path-migrate** (ACL shipped; path Soft) | Soft-OPEN | **p3-tenant-path-*** |
| Soft residual **wave-o2a-audit-volume-assert** (HTTP ACL shipped; volume assert Soft) | Soft-OPEN | **p2-audit-gate-assert** |
| Soft residual **wave-o4-synth59-handoff** | Soft-OPEN | **p4-mint-m5-synth59** |
| `o-cycle-template` / `o-local-compile-gate` / `o-mint-before-ghcr` (standing rules) | completed as process | **p6-ghcr-refresh-policy** (re-locked) |
| `o-ui-no-agent-chrome` | completed as rule | **p6-ui-no-agent-chrome** |
| `o-fdd-parity-gate` | completed as rule | **p6-fdd-parity-on-layout** (re-apply on P3) |
| O10 **hw_plant Soft** | Soft → P8 HARD if scrape proves | **p8** |
| Wave N Soft metric/MSTP notes | Soft | **p8b-metric-mstp-soak** |
| O2 Kali ZAP disposition | Soft/parked (Kali box owns scans) | **p2b** — react only to their bug reports |
| Railway ACME inspect 2026-09-15 (WEATHER/PLANT=0, thin RTU, Mapping UI) | NEW patch | **p8c–p8g** |

Wave O parent YAML leftovers are marked **cancelled → moved to Wave P** so agents do not double-execute.

---

## Global constraints

- **Local first:** every product tip — `cargo fmt --check`, `cargo check` touched crates, focused `cargo test` / `clippy -D warnings` on touched packages, web `npm test` if SPA touched — **before** push.
- **GHCR thrift (hard):** **≤3 Publishes** total — see ordered schedule. Never `docker pull :nightly` as tip.
- **No secrets / kits / synth59 zip in git.** Operator paths only.
- **Kali owns ZAP/PEN** (separate machine). Mint: **no** ActiveScan, no ZAP thrash in stress closeout; only **bugfix tips** when Kali hands findings. `p2b` is parked unless findings arrive.
- **Never** delete Parquet / `workspace/` / `docker compose down -v` / invent ZN-T or meter points.
- **SPA:** no agent explainer chrome.
- **O5 Stage C** stays Soft-OPEN (commercial) — not a Wave P close blocker.
- **Hygiene every tip:** after merge — delete remote tip branch; `gh pr list` empty (except active); cancel superseded failed Actions; local on `master` ff-only.

---

## Inventory (honest Soft-OPEN entering Wave P)

| ID | Kind | Close how |
|----|------|-----------|
| **O12b / wave-o-creekside-meter-map** | Product tip in flight #934 / 3.5.20 | P0 |
| **wave-o2a-audit-volume-assert** | Product harness | P2 |
| **wave-o1-tenant-path-migrate** | Ops + proof | P3 |
| **wave-o4-synth59-handoff** / **wave-m-m5-mint-bench** | Ops | P4 → P5 |
| **wave-o5 / stage-c-idp-mfa-sku** | Commercial | Parked |
| **hw_plant Soft** | OT → Wave P patch | **p8** |
| **ACME WEATHER=0 / no Madison meteo** | OT + weather config | **p8c** |
| **ACME rtu_01 thin roles** (oa_t only) | Fieldbus catalog + map | **p8d** |
| **ACME VAV missing airflow/damper/SP** | Fieldbus catalog | **p8h** |
| **TEC + Modbus boiler gateway in poll** | Strip from catalog | **p8 / p8h** |
| **RCx/FDD plot→poll agent skill** | Docs skill | **p8i** |
| **Data Model UI: not all points shown** | Product SPA (+ API if truncating) | **p8e** |
| **Data Model FDD rule annotate** | Bonus SPA | **p8f** |
| **Data Model Export above + view-as-text** | SPA | **p8g** |
| **FDD weather plot local-only (no web overlay)** | SPA FDD Plots | **p8j** |
| **FDD econ plots missing OA damper %** | SPA / series roles | **p8l** |
| **Left sidebar scroll hijacks main plot** | SPA AppShell UX | **p8m** |
| **FDD Plots last_axis=/domain0= debug under chart** | SPA ReportsPage | **p8n** (fixed locally; ship web tip) |
| **GH Pages docs (Haystack map, Rule Cookbook, RCx gallery, ECM, agent merge)** | Docs | **p-docs-gh-pages** |
| **Operations section on GH Pages** | Remove from online nav | **p-docs-ops-blast** |
| **Quick Start missing Railway bootstrap** | Docs | **p-docs-quickstart-bootstrap** |
| **RCx VAV health ranking blank (B100)** | SPA + analytics shape | **p8k** |
| **wave-n-metric-fdd / mstp** | Docs/soak Soft | P8b |
| **wave-n-zap-mt-af** | Kali box owns; Mint react-only | P2b parked |
| **Stale GH tip remotes** | Hygiene | P0 + P9 |
| **clippy::question_mark analytics** | Optional polish | P7 |

---

## Ordered execution (locked) — do this sequence

```text
PHASE 0 — Land in-flight tip + hygiene          GHCR #1 (hub)
  p0-finish-o12b  (#934 → 3.5.20)
  → Publish SUCCESS → newest-by-created pin
  → Railway central→mqtt→web + ACME refresh
  → prove Metering / gates 31/33/34
  p0-hygiene-baseline (stale remotes / cancel fails)
  p1-seed-bug-report (docs only, parallel OK after merge)

PHASE 1 — Docs only (parallel with Phase 2 scrape)  NO GHCR
  p-docs-gh-pages + p-docs-ops-blast + p-docs-quickstart-bootstrap
  p8i agent skill draft (docs)
  → docs-pages Actions only; never block OT scrape

PHASE 2 — ACME OT catalog (Mint scrape first)       GHCR #2 (fieldbus)
  p8i checklist → drive private field_devices
  p8 / p8c / p8d / p8h  (weather Madison, boiler 1002, RTU, VAV; strip TEC+gateway)
  → Mint BACnet scrape PASS → fieldbus PR → GHCR fieldbus
  → ACME refresh same day → ≥1×300s → gate 32 smoke
  → Railway hub pin only if central/web also moved; else fieldbus-only ACME

PHASE 3 — Product SPA + central + **P2c Kali security**   GHCR #3 (hub web±central)
  Batch ONE tip (~3.5.21+):
    p8e p8f p8g  Data Model UI          [LOCAL DONE — ship]
    p8j p8l p8n  FDD Plots               [LOCAL DONE — ship]
    p8k p8m      RCx VAV + sidebar       [LOCAL DONE — ship]
    **p2c-tenants-auth / p2c-public-apis / p2c-web-headers**  [Kali verified — HARD]
    **p2c-mt-isolation-matrix** (tests + minimal route ACL fixes)
    p2 audit volume assert (if code)
    p7 optional clippy ride-along
  → Mint fmt/test → PR → CI → squash → GHCR
  → Railway central→mqtt→web re-pin **only after Kali handoff / operator OK** (newest-by-created)
  → ACME only if fieldbus digest also new this tip (else skip)
  → spot gates 31/33/34 (+32 if ACME touched)

PHASE 4 — Ops / Soft (no product GHCR unless FAIL-NEW)
  p3-tenant-path-*   backup-first migrate + FDD parity
  p4-mint-m5-kit / p4-mint-m5-synth59
  p8b-metric-mstp-soak (cite after stress)
  p2b disposition closes when p2c* green on tip

PHASE 5 — FINAL Railway hub stress (exactly once on tip)   NO new tip
  p5-final-hub-stress
  → pin MUST be newest-by-created after last Publish
  → FULL run_railway_hub_stress.sh
  → gates 31/32/33/34 · ACME ≥2×300s · cite artifact + fully_qualified
  → FAIL-NEW only: tiny hotfix → GHCR #4 emergency → re-pin → re-stress once

PHASE 6 — GH tidy
  p9-gh-tidy-closeout
  p5-stage-c-park stays Soft (not a blocker)
```

### GHCR budget (do not exceed)

| # | When | Images | Railway? | ACME? |
|---|------|--------|----------|-------|
| **1** | After O12b merge | central + web + mqtt | **Yes** | refresh if fieldbus unchanged OK |
| **2** | After ACME catalog tip | **fieldbus** (hub only if forced) | hub only if digest shared | **Yes** same day |
| **3** | After SPA+central batch tip | central + web (± mqtt) | **Yes** | only if fieldbus also in tip |
| **4** | FAIL-NEW hotfix only | as needed | Yes | if fieldbus |

**Docs PR:** 0 GHCR. **P3 migrate / P4 kit / synth59:** 0 GHCR unless product code slipped (then it belongs in #3, not a fourth).

### Anti-patterns

- One GHCR per Soft-OPEN row or per UI nit  
- Railway re-pin before Publish SUCCESS / not newest-by-created  
- Full stress on **3.5.19** after a newer tip exists  
- Stress between Phase 2 and Phase 3 (wait for last hub tip)  
- Leave tip branches after squash · Mint ZAP/ActiveScan · invent OT points · claim WEATHER/PLANT when Devices-by-type still 0  

---

## Detail sections (same IDs — execute only in phase order above)

**Ported:** `o12-creekside-meter-map` · `o0-hygiene-gate` (baseline)

- [ ] Wait CI green on [#934](https://github.com/bbartling/open-fdd/pull/934) (`local-container` + Rust Stack)
- [ ] Squash-merge; delete remote `fix/wave-o-o12b-creekside-meter`
- [ ] Wait GHCR Publish SUCCESS; `./scripts/ghcr_newest_by_created.py openfdd-central openfdd-web openfdd-mqtt`
- [ ] Backup → Railway re-pin central→mqtt→web → ACME fieldbus refresh
- [ ] Prove: `/api/fuel/campus` has `LAKESIDE_ES`; FDD `CS_ELEC_METER` type **METER**; RCx `meter_elec_cdd` non-empty; gates **31/33/34**
- [ ] Delete already-merged stale remotes (2026-09-15 inventory):
  - `origin/fix/wave-o-o13-health-post-repin-3.5.14`
  - `origin/wave-o1-import-write-acl`
  - `origin/wave-o14-mqtt-packet-chunk`
  - `origin/wave-o2-authz-tests`
  - `origin/wave-o2-nginx-headers-hotfix`
  - `origin/wave-o6-historian-limits`
- [ ] Cancel superseded failed Actions on those branches

---

## P1 — Seed BUG_REPORT_WAVE_P

- [ ] Create [`docs/operations/BUG_REPORT_WAVE_P.md`](../../docs/operations/BUG_REPORT_WAVE_P.md)
- [ ] Pointer from Wave O report → Wave P
- [ ] Short `openfdd_agent_spec/SESSION_LOG.md` note

---

## P2 — Audit volume assert tip (~3.5.21)

**Ported:** Soft residual of `o2-audit-zap` (HTTP ACL shipped in 3.5.18/19; volume event assert Soft-OPEN)

- [ ] After ACL deny probes, assert ≥1 `tenant_building_denied` / select-deny / import-deny in `security_audit.jsonl` **or** admin API
- [ ] Fail-closed if MT ON and zero events after forced denies
- [ ] Local `cargo fmt` + focused tests before push → CI → merge → GHCR → Railway+ACME → gate 31/33
- [ ] Batch with P3 same tip when ready

### P2b — Kali ZAP/PEN (parked — other machine)

**Ported:** O2 ZAP Soft — **do not run from Mint.** Separate Kali box owns all ZAP/PEN. Wave P only:

- [ ] When Kali delivers findings → disposition Medium+ in BUG_REPORT_WAVE_P → product bugfix tip if needed
- [ ] No Mint ActiveScan; no ZAP watchers; stress may `SKIP_ZAP=1` without blocking Wave P close

---

## P3 — Tenant historian path migrate (backup-first)

**Ported:** Soft residual of `o1-tenant-historian` (import write ACL CLOSED 3.5.16; path migrate Soft) · sub-plan [`wave_o1_tenant_historian`](wave_o1_tenant_historian_ce235993.plan.md)

- [ ] Inventory hub-root `building=*` vs any `tenants/*` (p3-tenant-path-inventory)
- [ ] Backup Railway workspace first
- [ ] Additive copy (not delete): `BUILDING_100` → `tenants/building_100/…`; `LAKESIDE_ES` → `tenants/lakeside_sd/…`
- [ ] Prove owned JWT FDD + foreign 403 + admin all three
- [ ] **FDD parity** same window before/after (p6-fdd-parity-on-layout)
- [ ] Document `historian_prefix` proof in BUG_REPORT_WAVE_P
- [ ] Ship with P2 tip if code touched; else ops-only + stress proof

---

## P4 — Mint M5 / synth59 ops restore

**Ported:** `o4-mint-m5` · Soft `wave-o4-synth59-handoff` · sub-plan [`wave_o4_mint_m5`](wave_o4_mint_m5_ce235993.plan.md)

- [ ] MQTT edge / fieldbus kit or explicit skip-kit path (p4-mint-m5-kit)
- [ ] docker.sock usable for gates that need it
- [ ] Operator synth59 handoff zip → stage via `synthetic_59_*.py` (not in git)
- [ ] Prefer restore over greenwash; if absent, leave Soft-OPEN and say so at P5

---

## P5 — Final Railway+ACME hub stress

**When:** Only after **Phase 3** hub tip is pinned (newest-by-created). Do **not** run full stress after O12b alone or after fieldbus-only if SPA tip is still pending.

**Ported:** `o-closeout` stress half · `o-full-stress-pins` at O4 step

- [ ] Tip = newest-by-created after **last** product Publish (GHCR #3, or #2 if no SPA tip shipped)
- [ ] ACME continuity ≥2×300 s during ACL stress
- [ ] Full `./scripts/nightly-ot-bench/run_railway_hub_stress.sh` per [`STRESS_CLOSEOUT.md`](../../docs/operations/STRESS_CLOSEOUT.md)
- [ ] Gates **31/32/33/34**
- [ ] Cite artifact dir + `fully_qualified` in BUG_REPORT_WAVE_P
- [ ] FAIL-NEW → tiny hotfix tip → re-pin → re-stress **once** green (emergency GHCR #4 only)

---

## P6 — Standing process locks (ported Wave O rules)

- [ ] **p6-ghcr-refresh-policy:** Mint compile → PR → CI → squash → GHCR → Railway → ACME → gates → BUG_REPORT; ≤2 product Publishes
- [ ] **p6-ui-no-agent-chrome:** no SPA agent sermons
- [ ] **p6-fdd-parity-on-layout:** required when P3 mutates historian roots

---

## P7 — Optional clippy analytics hygiene

- [ ] Fix `clippy::question_mark` in central analytics so local `-D warnings` needs no `-A`
- [ ] Prefer same tip as P2

---

---

## P8 — ACME OT + Data Model patch (Railway inspect 2026-09-15)

**Human evidence (ACME on Railway):** Overview Devices by type → `AHU=1`, `VAV=30`, **`PLANT=0`**, **`WEATHER=0`**, `GENERAL=4`. Data Model `rtu_01` shows only column `oa_t` → role `oa_t` despite richer BACnet RTU. Site has boiler + shared OA; Madison WI Open-Meteo expected.

Also: **p8b-metric-mstp-soak** — cite Trane °C / JCI °F + MSTP honesty after stress; never invent ZN-T.

### Poll policy (locked)

| Include | Exclude (remove from ACME poll) |
|---------|----------------------------------|
| RTU health roles (p8d) | **All TEC** BACnet zone controllers — ignore / strip from `field_devices` |
| JCI/Trane **VAV** health roles for RCx/FDD (p8h) | **Modbus↔BACnet integrator** boiler gateway devices — do not poll object trees |
| Boiler controller **~device 1002** (temps + pumps) whitelist only (p8) | eGauge flood / full object dumps |
| Madison Open-Meteo weather equip (p8c) | Invented ZN-T / CFM / setpoints |

### P8i — Agent skill: RCx + FDD plot → poll checklist

**Intent:** reusable skill under `openfdd_agent_spec/skills/` (e.g. `openfdd-rcx-fdd-plot-poll`) so agents:

1. Walk `REQUIRED_RCX_PRESET_IDS` (`zone_temps`, `vav_flows`, `hw_reset_scatter`, `fan_speeds`, …) + FDD cookbook required∪optional roles
2. Emit a **site poll matrix**: role → equip family → BACnet point (only if scrape-proven)
3. Diff vs live ACME `field_devices` / Data Model gaps
4. Drive catalog edits — **never** invent; **never** add TEC / Modbus gateway

- [ ] Draft skill SKILL.md + checklist template (cite `rcxCatalog.ts`, PACKAGE_AUTHORING VAV/plant tables, ROLE_MAPPING_PARITY)
- [ ] Run once against ACME → update private catalog gaps for p8/p8d/p8h
- [ ] Feed Mapping UI FDD-consumer annotate (p8f) from same role→rule table when practical

### P8 / p8c — Weather + plant (HARD for sell bar)

- [ ] **Local OA:** keep/map RTU `oa_t` → cookbook `oa_t` / outside-air-temp (shared BAS OA OK — do not invent a second sensor)
- [ ] **Web weather:** configure Open-Meteo for **Madison, WI** → `{building}/weather/` with `web-outside-air-temp` / `wx_oa_t`; Devices by type **WEATHER ≥ 1**
- [ ] Prove **BAS vs web OAT** fault / OAT-METEO path works (Overview weather health + RCx / FDD that need web OAT)
- [ ] **Boiler whitelist ONLY** (from controller **~1002**, not Modbus gateway) — **that is the full HW set:**

| Point | Cookbook intent |
|-------|-----------------|
| Pump differential pressure | `hw` ΔP process |
| Pump ΔP setpoint | ΔP SP |
| Pump speed(s) | VFD % / pump cmd |
| Hot water supply temp | `hw_supply_t` |
| Hot water return temp | `hw_return_t` |

- [ ] Stamp `equipType` boiler/plant → Devices by type **PLANT ≥ 1**
- [ ] Remove Modbus↔BACnet boiler integrator + all TEC from poll catalog

### P8d — RTU health roles (fieldbus catalog @300s)

Mint BACnet scrape **before** GHCR. Add health-only points to `rtu_01`:

| Need | Intent |
|------|--------|
| Fan VFD speed | motor / fan % (`fan_speeds`) |
| Duct static pressure + SP | `duct_static_*` RCx |
| Discharge / DAT + SP / PID | SAT/DAT control |
| Cool / compressor status + cmd | mech OAT bins / compressor |
| ERV / energy recovery wheel cmd | ERV |

### P8h — VAV roles for RCx / FDD (`vav_flows`, zone comfort, terminal rules)

Human belief (verify on scrape):

| Status | Point / role |
|--------|----------------|
| **Have (keep)** | Reheat valve cmd · zone air temp · VAV leave / DAT |
| **Missing (add @300s)** | Actual airflow (CFM) · airflow setpoint · damper command · zone temp setpoint |

- [ ] Expand JCI VMA + Trane VAV health poll for the four missing roles (actual CFM ≠ airflow SP — PACKAGE_AUTHORING)
- [ ] Prove RCx `vav_flows` + `zone_temps` / comfort plots non-empty where points exist
- [ ] **No TEC** devices in poll — strip if present

### P8j — FDD weather plot = RCx BAS vs web + fault bool

**Symptom:** FDD Charts for weather / `OAT-METEO` show **local sensor only**; web Open-Meteo OAT is not overlaid.

**Wanted:** Same figure as RCx **`bas_vs_web_oat`** (BAS `oa_t` + Web OAT together, ±err band if already there) **plus** the standard FDD boolean fault strip below (like other rules).

- [ ] Reuse RCx overlay builder / `POST /api/analytics/bas-vs-web-oat` (or shared chart helper) for FDD Plots when rule is weather / `OAT-METEO`
- [ ] Stack bool `fault` series underneath (confirm window / series overlay contract unchanged for other rules)
- [ ] Vitest: FDD weather figure has ≥2 OAT traces (BAS + web) + fault trace
- [ ] Ship on same **web** tip as p8e–g

### P8l — FDD economizer series: always plot OA damper %

**Wanted:** Where applicable (ECON-1…ECON-7, especially **ECON-4 — Low estimated OA fraction**), FDD Plots timeseries must include **`oa_damper_pct`** (OA damper command/position) alongside temps / OA fraction — **dual y-axis** (°F vs %), same pattern as RCx economizer overlays; bool fault strip stays below.

- [ ] Series roles for economizer rules = required∪optional and **always include `oa_damper_pct`** when historian has the column (do not drop as “optional unused”)
- [ ] Plotly: damper on secondary axis; never plot % on the temperature axis
- [ ] Vitest: ECON-4 figure has `oa_damper_pct` trace + fault when fixture has damper
- [ ] Ship on same **web** tip as p8j / p8k

### P8m — Sidebar scroll containment (leave plot fixed)

**Wanted:** While watching a plot in the main/middle pane, hover the **left** Oracle sidebar (tune / upload / rule list) and use the mouse wheel to scroll **only that left pane** — main content must stay put (same scroll position / plot framing).

- [ ] `.app-sidebar` / `.app-sidebar__scroll`: `overflow-y: auto` + height constrained to viewport; `overscroll-behavior: contain`
- [ ] Wheel over sidebar never bubbles to `document` / main scroll (CSS first; `wheel` listener only if needed)
- [ ] Wheel over main pane still scrolls main only
- [ ] Manual check: FDD Plots + Lab/tune sidebar — plot y-scroll unchanged while hunting rules
- [ ] Ship on same **web** tip as p8e–g / p8j / p8l / p8k

### P8n — Remove FDD Plots debug chrome under chart

**Symptom:** Under FDD plot pane: `last_axis=fault last_trace=confirmed_fault domain0=0.0599…` — developer assert leftover, looks wonky.

- [x] Delete `plots-fault-lane` paragraph + helpers from `ReportsPage.tsx` (local 2026-09-15)
- [x] Vitest: assert debug strings absent; lane layout covered in `vibeCharts` tests
- [ ] Ship on same **web** tip as p8m / p8j / p8l / p8k

### P8k — RCx `vav_health_matrix` blank plot (BUILDING_100)

**Symptom (Railway):** Family Zones / VAV → preset *Zones — VAV health (broken / comfort / rogue) [ranking]* → `No points — preset returned empty` · `engine=datafusion · vav-health-v1 · points=0`. Overview VAV health **table** can still look fine (uses `rows`).

**Root cause (likely):** Preset is tagged `chart: "ranking"` so RCxPage only builds `rankingBars(points)`. `vav-health-v1` fills **matrix `rows`** (broken / poor_comfort / rogue flags), not ranking `points` with fail %. Also SQL may filter `equipment_id LIKE 'VAV%'` — opaque B100 ids with `equipType: vav` get dropped.

**Better viz (preferred — not a fake timeseries):**

1. **Donut / pie** — counts of boxes in broken / comfort-fail / rogue / ok (same spirit as zone comfort donut)
2. **Horizontal bar** — worst N VAVs by `comfort_fail_h` or broken fault hours (same pattern as `zone_comfort_rank` ranking bars)
3. Keep the existing matrix **table** under the chart (already useful)

- [ ] New chart kind `vav_health` (or detect `schema_version=vav_health_matrix_v1`) — do **not** force through empty `ranking` points path
- [ ] SPA: pie/donut + worst-box bars from `rows`; caption when FDD broken flags are null (no registry run yet)
- [ ] Central: select VAVs by stamped `equipType` / inventory, not only `LIKE 'VAV%'`
- [ ] Vitest + BUILDING_100 proof on Railway: points/rows non-empty → figure renders
- [ ] Ship on same **web** tip as p8e–g / p8j (central filter fix can ride same tip if needed)

### P8e — BUG: Data Model not listing all points

**Symptom:** Mapping tab for `rtu_01` only shows `oa_t` mapped; other historian columns missing from the table.

- [ ] Inventory API must return **all** Parquet/MQTT columns for the equip (`columns` + `unmapped_columns`)
- [ ] UI table lists every column; blank role = unmapped (still visible); “Show gaps only” filters, does not hide the full set by default
- [ ] Vitest: multi-column MQTT inventory renders N rows

### P8f — Bonus: FDD rule consumers on Mapping

- [ ] For each assigned role, show which FDD rule id(s) consume it (cookbook / registry)
- [ ] Visually differentiate columns/roles with **no** FDD consumer (mapped-for-analytics-only vs FDD-used)

### P8g — Export layout + view-as-text

- [ ] Move **Export site data model** **above** Building / Equipment selects (site-level action, not edit chrome)
- [ ] Assert export always from full-site inventory (`siteInventory` / unfiltered GET) — **never** equipment-filtered payload (code already aims at this; add UI caption + test)
- [ ] **View as text** button: open new browser tab with pretty-printed plain-text data model (`text/plain` blob URL or `document.write`) for human read

**Ship:** One **fieldbus** tip (p8/p8c/p8d/p8h + TEC/gateway strip) + one **web** tip (p8e–g + **p8j** weather + **p8l** econ damper + **p8k** VAV health + **p8m** sidebar scroll + **p8n** kill debug chrome) + **docs-only PR** for P-docs (no GHCR required) + skill draft. ACME same cycle as fieldbus Publish.

---

## P-docs — GH Pages / online docs (2026-09-15 inspect)

**Do not leave this as chat-only.** Ship as docs PR (can be separate from product tips). Prior work already started locally — finish + publish via `docs-pages` Actions.

### Capture (already started / must finish)

| Item | Wanted | Notes |
|------|--------|-------|
| Modeling | Subsection **all SQL rules → Haystack tags / SQL roles** | `docs/modeling/sql-rules-haystack-map.md` generated from `sql_rules/registry.yaml` + `haystack_point_to_role`; link from [modeling/](https://bbartling.github.io/open-fdd/modeling/) |
| Menu | `/rules/` label = **Rule Cookbook** (not “DataFusion SQL Rules”) | Permalink `/rules/` + `/rules/cookbook/` stay stable — README badges must keep working |
| RCx page | Move under **Web App**; old `/RCX_PLOTS_BY_HVAC.html` redirect stub forever | [RCX_PLOTS_BY_HVAC](https://bbartling.github.io/open-fdd/RCX_PLOTS_BY_HVAC.html) → `/web-app/rcx-plots-by-hvac.html` |
| Plot gallery | Upload `/home/ben/Downloads/RCxPlots` → `docs/assets/plot-examples/`; render RCx + **FDD** (FC1, ECON-4) examples on that page | Assets already copied locally |
| ECM calcs | Expand [Engineering calcs](https://bbartling.github.io/open-fdd/operations/ECM_ENGINEERING_MATH.html) — **all** `list_ecm_modules()` + `list_calculators()` + finance/EUI globals; leave no module unlisted | Draft expanded locally; move permalink under `/ecm/` when Operations blasted |
| PyPI agent tools | Drop [PYPI_RELEASE_CHECKLIST](https://bbartling.github.io/open-fdd/ecm/PYPI_RELEASE_CHECKLIST.html); merge Agents / Handoff / Upsell into one professional **AI agents & skills** page (what Open-FDD agents do for humans + linked `openfdd_agent_spec/skills/*/SKILL.md`) | |
| README | Badge/menu links only to **stable permalinks** (`/rules/cookbook/`, `/quick-start/`, `/modeling/`, `/web-app/…`) | Never point at removed Operations hub |

### P-docs-ops-blast — remove Operations from online docs

**Human ask:** get rid of [Operations](https://bbartling.github.io/open-fdd/operations/) from the public site.

- [ ] `nav_exclude: true` (or Jekyll `exclude`) so **Operations does not appear** in just-the-docs left nav / TOC
- [ ] Keep `docs/operations/**` in **git** for agents / BUG_REPORT / patch trains (not “delete the folder”)
- [ ] Public bootstrap that lived under Ops → **Quick Start** only:
  - Local Compose / firewall hub (`LOCAL_DEPLOYMENT` gist)
  - Railway cloud hub (`RAILWAY_DEPLOYMENT` + checklist gist) — user “render” = **Railway** hub path in this product
  - GHCR / docker already under Quick Start — extend, don’t orphan
- [ ] Move or re-parent: Engineering calcs → `/ecm/…`; Security public page stays under existing **Security** section if needed; github-pages preview note → Quick Start or README
- [ ] Stub `/operations/` (+ key old HTML names) with “moved → Quick Start / ECM / Security” + meta refresh so bookmarks never 404
- [ ] Grep docs + README for `/operations/` nav links; rewrite to new homes
- [ ] Prove after Pages deploy: Operations **absent** from menu; Quick Start shows Local + Railway; old Operations URL redirects

### P-docs-quickstart-bootstrap

- [ ] Quick Start index table: **Local stack** · **Railway hub** · Docker/GHCR · Pi · Site lifecycle
- [ ] Local page: `openfdd_stack_up.sh`, ports, JWT login, `--local-web` demo gate honesty
- [ ] Railway page: secrets, volume `/workspace`, deploy order central→mqtt→web, newest-by-created pin — condensed from current RAILWAY_DEPLOYMENT (no Stage C oversell)

**Ship:** docs-only PR OK (no GHCR). Can land before or after O12b tip.

---

## P2c — Kali security handoff (2026-09-15) — HARD before shared-data

**Source:** Kali box AI security review (verified). Mint implements product fixes + automated tests; **do not ActiveScan OT from Mint**. Next pentest uses staging accounts for live cross-tenant + MQTT ACL denial.

**Ship on GHCR #3** with SPA/central tip (or earlier hotfix if shared-data launch blocked). Railway re-pin only when Kali/operator OK.

### Verified issue matrix (endpoint → authz)

| Endpoint | Unauthenticated (auth ON) | Tenant A | Tenant B | Hub admin |
|----------|---------------------------|----------|----------|-----------|
| `GET /api/health` | 200 generic readiness only | same | same | same |
| `GET /api/auth/status` | 200 (`auth_required`, no secrets) | same | same | same |
| `GET /api/auth/login` | POST only | — | — | — |
| `GET /api/tenants` | **401** (no Admin via `dev_anonymous`) | own tenants + buildings only | own only | all tenants/buildings |
| `POST /api/tenants/select` | **401** | membership only; remint cannot mint foreign tenant | deny foreign | any |
| `GET /api/tenants/budgets` | **401** | scoped | scoped | all |
| `GET /api/capabilities` | **401** or `{ok,ready}` only — **no** feature inventory | full | full | full |
| `GET /api/health/stack` | **401** / generic — **no** MCP/protocol/bind | detailed OK | detailed OK | detailed OK |
| `GET /api/building/snapshot` | **401** / generic | scoped | scoped | hub |
| `GET /api/dashboard/summary` | **401** / generic — **no** paths/sites/DM | scoped | scoped | hub |
| Protected `/api/edges|commands|csv|fdd|analytics|jobs|export|…` | **401** | **403/404** on B ids | **403/404** on A ids | cross-tenant OK |
| Agent JWT | n/a | least-privilege, short TTL, tenant-scoped; no admin tools | same | mint only via admin |
| MQTT edge cert A | n/a | pub telemetry/status A; sub commands A only | **deny** B topics + wildcards | ops |

**Root cause V1:** `list_tenants` falls back to `AuthUser::dev_anonymous()` → **Admin** → full plane visibility when JWT missing.

**Root cause V2:** `/api/capabilities`, `/api/health/stack`, `/api/building/snapshot`, `/api/dashboard/summary` registered on **public** router with full topology/MCP/flags/paths.

**Root cause V3:** CSP missing Google Fonts hosts; HSTS absent; confirm `security.txt` + SPA fallback (gate 34).

### Implementation checklist

#### V1 — tenants (`p2c-tenants-auth`)
- [ ] When `auth.required()`, `GET /api/tenants` **requires** Bearer JWT (401 else) — never Admin anonymous for listing
- [ ] Open/loopback mode (no JWT secret): keep local-bench behavior OR Viewer-equivalent empty list — **never** leak production plane
- [ ] Membership filter: Tenant A/B see only `tenant_ids` claim; hub Admin (`role=admin` + empty tenant_ids) sees all
- [ ] Tests: anonymous / A / B / admin response shapes

#### V2 — public APIs (`p2c-public-apis`)
- [ ] Move detailed `capabilities` / `health/stack` / `building/snapshot` / `dashboard/summary` onto **protected** router (JWT middleware)
- [ ] Optional public stub returns only `{ok:true, ready:true}` (or 401) — no services[], MCP, protocols, paths, feature flags
- [ ] Unauth regression: assert absent keys (`services`, `mcp`, `bacnet_bind`, `data_management`, `portfolio`, historian paths, …)

#### V3 — web headers (`p2c-web-headers`)
- [ ] nginx CSP: allow `fonts.googleapis.com` / `fonts.gstatic.com`; keep Plotly same-origin/`blob:`
- [ ] HSTS when HTTPS / `X-Forwarded-Proto=https`
- [ ] Keep nosniff, Referrer-Policy, X-Frame-Options / frame-ancestors
- [ ] `/.well-known/security.txt` 200 text/plain, not SPA HTML (already location=; verify file in image)
- [ ] Extend gate 34 assertions as needed

#### Critical MT isolation (`p2c-mt-isolation-matrix`)
- [ ] Integration tests Tenant A / B / hub admin for: edges, commands, CSV sessions/imports, FDD results/series/session config, analytics, jobs, reports/exports, data management, MQTT edge kits/monitoring, agent tools
- [ ] Foreign IDs → **403/404 and empty body** (not empty-200 with data)
- [ ] Same `building_id` string under two tenants → namespace (`tenants/{tid}/…`) isolates
- [ ] Select cannot mint membership outside JWT claims
- [ ] Agent tokens: short-lived, non-admin, tenant-scoped; never in browser bundles/logs/repo
- [ ] MQTT: document ACL mount path + mTLS deny matrix; broker-side proof on staging (Kali next pentest)
- [ ] Railway: only web public; central/MCP/mqtt private

**Return order (Kali):** concise matrix (above) → **failing tests first** → minimal fixes → all green.

---

## Stage C park

**Ported:** `o5-stage-c-park` — IdP / MFA / SKU Soft-OPEN. Not a Wave P exit gate.

---

## Parked — Wave Q edge telemetry pause/resume UI

**Decision 2026-09-15:** Option **A** only (pause/resume streaming, **not** stop the fieldbus container). Backend mostly exists (`edge:telemetry` suspend/resume via MQTT / `POST /api/commands`; Ops can already issue). Later wave: tenant-scoped MQTT dashboard switch (client = own edges; admin = all) + audit. **Out of Wave P** — do not tip for this here.

---

## P9 — GH tidy closeout (required exit)

**Ported:** `o0-hygiene-gate` + `o-closeout` GH half

Wave P **CLOSED** only when:

- [ ] `gh pr list --state open` → **0**
- [ ] No stale `wave-o*` / `wave-p*` / `fix/wave-o*` remote tip branches
- [ ] Local on `master`, ff with `origin/master`
- [ ] Tip Actions success; superseded fails cancelled
- [ ] BUG_REPORT_WAVE_P: **OPS PINNED** + stress artifact + `fully_qualified`
- [ ] Soft-OPEN remaining ≤ **O5 Stage C** (+ honest synth59 ops Soft if still missing); Wave Q edge telemetry UI stays parked
- [ ] ACME Devices by type: **WEATHER ≥ 1** and **PLANT ≥ 1** (or honest Soft if scrape proves absent) + Data Model lists all RTU columns

**Agent one-liner:**
`0 O12b GHCR#1+Railway → 1 Docs(no GHCR) → 2 ACME fieldbus GHCR#2 → 3 SPA+central GHCR#3+Railway → 4 P3/P4 ops → 5 ONE full hub stress → 6 GH tidy`

---

## Never

- Refresh GHCR more than the batched tip schedule without FAIL-NEW
- Stress on a pin that is not newest-by-created after a Publish
- Leave merged tip branches on origin
- Claim Wave P / Wave O closed with open PRs or red tip Actions
- ActiveScan production OT from Mint
- Park P5 stress or P9 tidy behind polish
- Re-open Wave O parent todos that were moved here
- Invent weather / plant / RTU / VAV points when BACnet scrape does not prove them
- Poll **TEC** devices or **Modbus↔BACnet boiler gateway** object trees
- Claim site export when payload is equipment-filtered
- Map airflow **setpoint** into the actual CFM role (`zone-airflow`)
