# Wave O — Known bugs / patch train tracker

**Ops pin (Wave N, until O8/O9 tip):** `sha-9072e0b` / **3.5.10** · `multi_tenant=true`  
**O8+O9 tip:** master `764bb17e` / **3.5.11** — GHCR Publish in flight (2026-09-14)  
**O7 open:** PR [#926](https://github.com/bbartling/open-fdd/pull/926) · **3.5.12** Overview site cache

Parent plan: `.cursor/plans/wave_o_known_bugs_patch_ce235993.plan.md`  
Prior Soft-OPEN: [`BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md`](BUG_REPORT_WAVE_N_MULTI_TENANT_SECURITY.md)

## Bake order

O8 → O9 → O10 → O7 → O3 → O1 → O6 → O2 → O4 · **O5 Soft-OPEN only** (IdP/MFA)

**O2 expanded:** Kali/Railway multi-user shared-DB harden (permission matrix + server ACL + headers + tests) — see plan § O2 / [`wave_o2_…`](../../.cursor/plans/wave_o2_audit_zap_ce235993.plan.md). **HOLD** until Mint reboot resume.

| Step | Status | Evidence |
|------|--------|----------|
| O8 hub admin | **MERGED** #925 | `/admin` + `/api/admin/*` · gate 33 |
| O9 site data-model ACL | **MERGED** #925 | site export + session `building_id` ACL |
| O10 full HVAC @300s | NEXT after 3.5.11 pin | private catalog ~38 devices; rusty tip gate MS/TP |
| O7 Overview cache | **PR #926** | silent per-`buildingId` cache |
| O2a audit + ZAP disposition | queued | **this agent:** audit asserts · **Kali agent:** ZAP/AF (cite only) |
| O2b MT shared-DB harden | **IN PLAN** (HOLD) | product ACL/headers + **beefed CI/stress tests** (no Kali here) |
| O3–O4 | queued | after O10 streams |
| O11 PyPI Pages | IN PROGRESS | `docs/ecm/` section + Drivers CSV nav dedupe |
| O12a Plotly PNG stems | IN PROGRESS | RCx/FDD never `newplot.png`; type-based stems |
| O12b Creekside meter map | OPEN | BAS BACnet electricity meter in dataset; data model lacks metering roles |

## Hygiene

- 0 open PRs after each merge (except the active tip PR)
- Delete feature branches; tip Actions green before Railway re-pin
- Product OT = `openfdd-fieldbus` + rusty-bacnet; bacpypes3 diagnose-only

## Open defects (Wave O additions)

| ID | Status | Summary |
|----|--------|---------|
| **wave-o-plotly-newplot** | Patching | RCx (and any host without stem) download `newplot.png`; fix PlotlyHost + RCx/FDD type stems |
| **wave-o-creekside-meter-map** | OPEN | `LAKESIDE_ES` / Creekside: integrated BAS BACnet electricity meter present in data; package map omits metering → empty Metering UI |
